"""Firestore 実装のリポジトリ層。

``DATA_BACKEND=firestore`` で使う。``base.py`` の ``VocabRepo`` / ``QuizRepo`` /
``TopicRepo`` Protocol を実装し、戻り値の形は SQLite 実装 (``sqlite_repo``) と完全に
一致させる (タイムスタンプは ISO 8601 文字列、ID は整数)。呼び出し側 (tools /
quiz_server) はバックエンドの違いを意識しない。

設計メモ:

- **整数ID**: 既存インタフェースは session_id / topic_id を ``int`` で返し、MCP ツール
  ``score_free_answers(session_id: int)`` やブラウザがそのまま往復させる。Firestore の
  auto-id (文字列) では契約を破るため、``counters/{name}`` ドキュメントをトランザクションで
  インクリメントして整数IDを採番し、それを文字列化したものをドキュメントIDに使う。
- **タイムスタンプ**: 書き込みは ``SERVER_TIMESTAMP``。読み出し時に ISO 8601 文字列へ
  変換して返す (SQLite の ``datetime('now')`` 文字列と揃える)。
- **クエリ**: 個人利用規模のため、複合インデックスが要るクエリは避け、単一の等価フィルタ
  またはコレクション走査 + Python 側でのフィルタ/ソート/サンプリングで実装する。

非同期版 ``AsyncClient`` は使わない (既存コードベースが同期前提)。
"""

import logging
import random
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

from dynamic_prompt.repo.sqlite_repo.vocab import (
    STATUS_MEMORY_TEST,
    STATUS_UNLEARNED,
    STATUS_WRONG,
)

logger = logging.getLogger(__name__)

# コレクション名
_WORDS = "unknown_words"
_SESSIONS = "quiz_sessions"
_QUESTIONS = "questions"  # quiz_sessions/{id} のサブコレクション
_TOPICS = "story_topics"
_COUNTERS = "counters"


# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------


def _word_doc_id(lang: str, word: str) -> str:
    """``unknown_words`` の自然ID。"""
    return f"{lang}__{word}"


def _to_iso(value) -> str | None:
    """Firestore の Timestamp (tz-aware datetime) を ISO 8601 文字列へ変換する。

    ``None`` はそのまま ``None`` を返す。SQLite の ``datetime('now')`` 形式
    (``"YYYY-MM-DD HH:MM:SS"``) に近づけるため、UTC の秒精度・スペース区切りにする。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _next_id(client: firestore.Client, name: str) -> int:
    """``counters/{name}`` をトランザクションで +1 し、新しい整数値を返す。

    SQLite の AUTOINCREMENT を模倣する。1 始まり。
    """
    ref = client.collection(_COUNTERS).document(name)
    transaction = client.transaction()

    @firestore.transactional
    def _incr(txn) -> int:
        snap = ref.get(transaction=txn)
        current = snap.to_dict().get("value", 0) if snap.exists else 0
        new_value = current + 1
        txn.set(ref, {"value": new_value})
        return new_value

    return _incr(transaction)


# ---------------------------------------------------------------------------
# Vocab
# ---------------------------------------------------------------------------


class FirestoreVocabRepo:
    """単語・復習プールの Firestore リポジトリ。"""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def init(self) -> None:
        # Firestore はスキーマレス。接続確認のみ。
        logger.info("Firestore backend initialized (project=%s)", self._client.project)

    def save_words(self, lang: str, words: list[str], context: str = "") -> list[str]:
        """単語を保存し、保存された (正規化済み) 単語のリストを返す。

        既存の単語はコンテキストのみ更新し、ステータス・created_at は保持する。
        SQLite の ``ON CONFLICT(lang, word) DO UPDATE SET context = COALESCE(...)``
        と同じ挙動。
        """
        ctx = context.strip()
        saved: list[str] = []
        for word in words:
            w = word.strip().lower()
            if not w:
                continue
            ref = self._client.collection(_WORDS).document(_word_doc_id(lang, w))
            snap = ref.get()
            if snap.exists:
                # 既存: コンテキストが与えられた時だけ更新。status は保持。
                if ctx:
                    ref.update({"context": ctx})
            else:
                ref.set(
                    {
                        "lang": lang,
                        "word": w,
                        "context": ctx or None,
                        "status": STATUS_UNLEARNED,
                        "reviewed_at": None,
                        "created_at": firestore.SERVER_TIMESTAMP,
                    }
                )
            saved.append(w)
        return saved

    def get_review_pool(self, lang: str, limit: int, memory_test_period_hours: int) -> list[dict]:
        """復習対象の単語をランダムに返す。

        ``unlearned`` / ``wrong`` は常に対象。``memory_test`` は ``reviewed_at`` から
        ``memory_test_period_hours`` 時間経過したものだけ含める。各要素は
        ``word`` / ``context`` / ``status``。
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=memory_test_period_hours)
        query = self._client.collection(_WORDS).where(
            filter=firestore.FieldFilter("lang", "==", lang)
        )
        pool: list[dict] = []
        for snap in query.stream():
            d = snap.to_dict()
            status = d.get("status")
            if status in (STATUS_UNLEARNED, STATUS_WRONG):
                pass
            elif status == STATUS_MEMORY_TEST:
                reviewed_at = d.get("reviewed_at")
                if reviewed_at is None or reviewed_at > cutoff:
                    continue
            else:
                continue
            pool.append({"word": d.get("word"), "context": d.get("context"), "status": status})
        if len(pool) > limit:
            pool = random.sample(pool, limit)
        return pool

    def process_answers(self, lang: str, correct: list[str], incorrect: list[str]) -> list[str]:
        """正答・誤答にステータス遷移を適用し、結果メッセージのリストを返す。"""
        results: list[str] = []
        for w in correct:
            results.append(self._process_answer(lang, w, True))
        for w in incorrect:
            results.append(self._process_answer(lang, w, False))
        return results

    def _process_answer(self, lang: str, word: str, is_correct: bool) -> str:
        w = word.strip().lower()
        label = word.strip()
        ref = self._client.collection(_WORDS).document(_word_doc_id(lang, w))
        snap = ref.get()
        if not snap.exists:
            return f"'{label}': not found"
        status = snap.to_dict().get("status")

        if is_correct:
            if status == STATUS_UNLEARNED:
                ref.delete()
                return f"'{label}': correct, removed"
            if status == STATUS_WRONG:
                ref.update(
                    {
                        "status": STATUS_MEMORY_TEST,
                        "reviewed_at": firestore.SERVER_TIMESTAMP,
                    }
                )
                return f"'{label}': correct, moved to review"
            # memory_test
            ref.delete()
            return f"'{label}': correct, fully learned"

        # incorrect
        if status == STATUS_UNLEARNED:
            ref.update({"status": STATUS_WRONG})
            return f"'{label}': incorrect, marked difficult"
        if status == STATUS_WRONG:
            return f"'{label}': incorrect, stays difficult"
        # memory_test
        ref.update({"status": STATUS_WRONG, "reviewed_at": None})
        return f"'{label}': incorrect, back to difficult"


# ---------------------------------------------------------------------------
# Quiz
# ---------------------------------------------------------------------------


class FirestoreQuizRepo:
    """クイズの Firestore リポジトリ (MC + 自由回答)。"""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def _session_ref(self, session_id: int):
        return self._client.collection(_SESSIONS).document(str(session_id))

    def _questions(self, session_id: int) -> list[dict]:
        """セッションの問題を question_index 昇順で返す (生ドキュメント dict)。"""
        snaps = (
            self._session_ref(session_id).collection(_QUESTIONS).order_by("question_index").stream()
        )
        return [s.to_dict() for s in snaps]

    def create_session(self, lang: str, title: str, questions: list[dict]) -> int:
        """クイズセッション (MC / free 混在可) を保存し、セッションIDを返す。"""
        session_id = _next_id(self._client, _SESSIONS)
        session_ref = self._session_ref(session_id)
        batch = self._client.batch()
        batch.set(
            session_ref,
            {
                "id": session_id,
                "lang": lang,
                "title": title,
                "created_at": firestore.SERVER_TIMESTAMP,
                "submitted_at": None,
                "scored_at": None,
            },
        )
        for i, q in enumerate(questions):
            qtype = q.get("question_type", "mc")
            qref = session_ref.collection(_QUESTIONS).document(str(i))
            if qtype == "free":
                batch.set(
                    qref,
                    {
                        "question_index": i,
                        "question_text": q["question"],
                        "question_type": "free",
                        "model_answer": q.get("model_answer", ""),
                        "choices": [],
                        "correct_index": 0,
                        "user_answer": None,
                        "is_correct": None,
                        "user_answer_text": None,
                    },
                )
            else:
                batch.set(
                    qref,
                    {
                        "question_index": i,
                        "question_text": q["question"],
                        "question_type": "mc",
                        "choices": list(q["choices"]),
                        "correct_index": q["correct_index"],
                        "user_answer": None,
                        "is_correct": None,
                        "model_answer": None,
                        "user_answer_text": None,
                    },
                )
        batch.commit()
        return session_id

    def submit_answers(self, session_id: int, answers: list) -> dict:
        """回答を保存・採点し、結果 dict を返す。

        MC は即時採点、free はテキストを保存して未採点のまま残す。
        ``answers`` の各要素は MC なら int、free なら str。
        """
        session_ref = self._session_ref(session_id)
        question_snaps = list(
            session_ref.collection(_QUESTIONS).order_by("question_index").stream()
        )

        correct_count = 0
        mc_total = 0
        has_free = False
        details = []
        batch = self._client.batch()
        for snap, user_ans in zip(question_snaps, answers):
            q = snap.to_dict()
            if q.get("question_type") == "free":
                has_free = True
                batch.update(snap.reference, {"user_answer_text": str(user_ans)})
                details.append(
                    {
                        "question_index": q["question_index"],
                        "question_text": q["question_text"],
                        "question_type": "free",
                        "user_answer_text": str(user_ans),
                        "model_answer": q.get("model_answer") or "",
                        "is_correct": None,
                    }
                )
            else:
                mc_total += 1
                user_ans_int = int(user_ans)
                is_correct = 1 if user_ans_int == q["correct_index"] else 0
                correct_count += is_correct
                batch.update(
                    snap.reference,
                    {"user_answer": user_ans_int, "is_correct": bool(is_correct)},
                )
                details.append(
                    {
                        "question_index": q["question_index"],
                        "question_text": q["question_text"],
                        "question_type": "mc",
                        "choices": list(q["choices"]),
                        "correct_index": q["correct_index"],
                        "user_answer": user_ans_int,
                        "is_correct": bool(is_correct),
                    }
                )

        batch.update(session_ref, {"submitted_at": firestore.SERVER_TIMESTAMP})
        batch.commit()

        return {
            "session_id": session_id,
            "correct_count": correct_count,
            "total_count": len(question_snaps),
            "mc_total": mc_total,
            "has_free": has_free,
            "details": details,
        }

    def get_pending(self) -> dict | None:
        """未回答の最新クイズを返す。なければ None。"""
        query = self._client.collection(_SESSIONS).where(
            filter=firestore.FieldFilter("submitted_at", "==", None)
        )
        pending = [s.to_dict() for s in query.stream()]
        if not pending:
            return None
        # created_at 降順で最新を選ぶ (None は最古扱い)。
        pending.sort(key=lambda d: (d.get("created_at") is not None, d.get("created_at")))
        latest = pending[-1]
        sid = latest["id"]

        result_questions = []
        for q in self._questions(sid):
            qtype = q.get("question_type") or "mc"
            if qtype == "free":
                result_questions.append({"question": q["question_text"], "question_type": "free"})
            else:
                result_questions.append(
                    {
                        "question": q["question_text"],
                        "question_type": "mc",
                        "choices": list(q["choices"]),
                        "correct_index": q["correct_index"],
                    }
                )
        return {
            "session_id": sid,
            "lang": latest["lang"],
            "title": latest["title"],
            "questions": result_questions,
        }

    def get_recent_results(self, lang: str, limit: int = 5) -> list[dict]:
        """直近の完了済みクイズ結果を返す。"""
        query = self._client.collection(_SESSIONS).where(
            filter=firestore.FieldFilter("lang", "==", lang)
        )
        sessions = [
            d for d in (s.to_dict() for s in query.stream()) if d.get("submitted_at") is not None
        ]
        sessions.sort(key=lambda d: d["submitted_at"], reverse=True)
        sessions = sessions[:limit]

        results = []
        for s in sessions:
            questions = self._questions(s["id"])
            correct_count = sum(1 for q in questions if q.get("is_correct"))
            q_details = []
            for q in questions:
                qtype = q.get("question_type") or "mc"
                is_correct = q.get("is_correct")
                if qtype == "free":
                    q_details.append(
                        {
                            "index": q["question_index"],
                            "question_text": q["question_text"],
                            "question_type": "free",
                            "model_answer": q.get("model_answer") or "",
                            "user_answer_text": q.get("user_answer_text") or "",
                            "is_correct": bool(is_correct) if is_correct is not None else None,
                        }
                    )
                else:
                    choices = list(q["choices"])
                    user_answer = q.get("user_answer")
                    q_details.append(
                        {
                            "index": q["question_index"],
                            "question_text": q["question_text"],
                            "question_type": "mc",
                            "correct_choice": choices[q["correct_index"]],
                            "user_choice": (
                                choices[user_answer] if user_answer is not None else "(未回答)"
                            ),
                            "is_correct": bool(is_correct),
                        }
                    )
            results.append(
                {
                    "session_id": s["id"],
                    "title": s["title"],
                    "submitted_at": _to_iso(s.get("submitted_at")),
                    "scored_at": _to_iso(s.get("scored_at")),
                    "correct_count": correct_count,
                    "total_count": len(questions),
                    "questions": q_details,
                }
            )
        return results

    def get_unscored(self, lang: str, limit: int = 5) -> list[dict]:
        """提出済みだが未採点の自由回答クイズを返す。"""
        query = self._client.collection(_SESSIONS).where(
            filter=firestore.FieldFilter("lang", "==", lang)
        )
        candidates = [
            d
            for d in (s.to_dict() for s in query.stream())
            if d.get("submitted_at") is not None and d.get("scored_at") is None
        ]
        candidates.sort(key=lambda d: d["submitted_at"], reverse=True)

        results = []
        for s in candidates:
            free_questions = [
                q
                for q in self._questions(s["id"])
                if (q.get("question_type") or "mc") == "free"
                and q.get("user_answer_text") is not None
            ]
            if not free_questions:
                continue
            results.append(
                {
                    "session_id": s["id"],
                    "title": s["title"],
                    "submitted_at": _to_iso(s.get("submitted_at")),
                    "questions": [
                        {
                            "question_index": q["question_index"],
                            "question_text": q["question_text"],
                            "model_answer": q.get("model_answer") or "",
                            "user_answer_text": q.get("user_answer_text") or "",
                            "is_correct": bool(q["is_correct"])
                            if q.get("is_correct") is not None
                            else None,
                        }
                        for q in free_questions
                    ],
                }
            )
            if len(results) >= limit:
                break
        return results

    def score_free_answers(self, session_id: int, scores: list[dict]) -> dict:
        """自由回答の採点結果を保存する。

        ``scores`` は ``[{"question_index": 0, "is_correct": True}, ...]`` 形式。
        """
        session_ref = self._session_ref(session_id)
        correct_count = 0
        batch = self._client.batch()
        for s in scores:
            is_correct = bool(s["is_correct"])
            correct_count += 1 if is_correct else 0
            qref = session_ref.collection(_QUESTIONS).document(str(s["question_index"]))
            batch.update(qref, {"is_correct": is_correct})
        batch.update(session_ref, {"scored_at": firestore.SERVER_TIMESTAMP})
        batch.commit()
        return {
            "session_id": session_id,
            "scored_count": len(scores),
            "correct_count": correct_count,
        }


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------


class FirestoreTopicRepo:
    """物語の話題の Firestore リポジトリ。"""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def save_topic(self, lang: str, topic: str, summary: str = "") -> int:
        """話題を保存し、IDを返す。"""
        topic_id = _next_id(self._client, _TOPICS)
        self._client.collection(_TOPICS).document(str(topic_id)).set(
            {
                "id": topic_id,
                "lang": lang,
                "topic": topic,
                "summary": summary,
                "created_at": firestore.SERVER_TIMESTAMP,
            }
        )
        return topic_id

    def list_recent(self, lang: str, limit: int = 20) -> list[dict]:
        """直近の話題を新しい順 (id 降順) に返す。"""
        query = self._client.collection(_TOPICS).where(
            filter=firestore.FieldFilter("lang", "==", lang)
        )
        topics = [s.to_dict() for s in query.stream()]
        topics.sort(key=lambda d: d["id"], reverse=True)
        topics = topics[:limit]
        return [
            {
                "id": t["id"],
                "topic": t["topic"],
                "summary": t.get("summary", ""),
                "created_at": _to_iso(t.get("created_at")),
            }
            for t in topics
        ]
