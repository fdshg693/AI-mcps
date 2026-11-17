"""SQLite -> Firestore 移行スクリプト。

使い方::

    uv run python -m dynamic_prompt.migrate_to_firestore \\
        --source /path/to/vocab.db \\
        --project dynamic-prompt-mcp \\
        [--dry-run]

``FIRESTORE_EMULATOR_HOST`` がセットされていればエミュレータへ書き込む
(ローカル検証用)。Phase 2 ではローカル SQLite -> ローカルエミュレータで動作確認し、
Phase 5 で本番 Firestore に対して使う。

処理の流れ:
  1. SQLite の各テーブルの件数をログ
  2. 各テーブルを Firestore に書き込み (500件バッチ)
     - ``unknown_words``  -> 自然ID ``{lang}__{word}`` に upsert (merge=False)
     - ``quiz_sessions``  -> 元の整数IDをドキュメントIDに保持し、``questions`` を
       サブコレクション ``quiz_sessions/{id}/questions/{question_index}`` へ
     - ``story_topics``   -> 元の整数IDをドキュメントIDに保持
  3. ``--dry-run`` の場合は書き込みをスキップし、書き込み予定件数だけレポート
  4. 書き込み後、Firestore 側の件数を集約クエリで取得し SQLite 側と突き合わせ
  5. 差分があれば exit code 1

備考: 実行時の ``FirestoreQuizRepo`` / ``FirestoreTopicRepo`` は ``counters/{name}``
ドキュメントで整数IDを採番する。移行では元のIDを保持しつつ、カウンタを最大IDに
セットして以降の採番が衝突しないようにする。
"""

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from itertools import islice

from dynamic_prompt.repo.firestore_repo import (
    _COUNTERS,
    _QUESTIONS,
    _SESSIONS,
    _TOPICS,
    _WORDS,
    _word_doc_id,
)

logger = logging.getLogger("migrate_to_firestore")

_BATCH_SIZE = 500


def _parse_ts(value) -> datetime | None:
    """SQLite の ISO 8601 文字列 (``"YYYY-MM-DD HH:MM:SS"``) を UTC datetime に変換。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _chunked(iterable, size):
    it = iter(iterable)
    while batch := list(islice(it, size)):
        yield batch


def _read_sqlite(source: str) -> dict:
    """SQLite から全テーブルを読み出し、Firestore 書き込み用の中間表現を返す。"""
    db = sqlite3.connect(source)
    db.row_factory = sqlite3.Row
    try:
        words = [dict(r) for r in db.execute("SELECT * FROM unknown_words").fetchall()]
        sessions = [dict(r) for r in db.execute("SELECT * FROM quiz_sessions").fetchall()]
        questions = [
            dict(r) for r in db.execute("SELECT * FROM quiz_questions").fetchall()
        ]
        topics = [dict(r) for r in db.execute("SELECT * FROM story_topics").fetchall()]
    finally:
        db.close()
    return {
        "words": words,
        "sessions": sessions,
        "questions": questions,
        "topics": topics,
    }


def _word_payload(row: dict) -> dict:
    return {
        "lang": row["lang"],
        "word": row["word"],
        "context": row.get("context"),
        "status": row.get("status") or "unlearned",
        "reviewed_at": _parse_ts(row.get("reviewed_at")),
        "created_at": _parse_ts(row.get("created_at")),
    }


def _session_payload(row: dict) -> dict:
    return {
        "id": row["id"],
        "lang": row["lang"],
        "title": row["title"],
        "created_at": _parse_ts(row.get("created_at")),
        "submitted_at": _parse_ts(row.get("submitted_at")),
        "scored_at": _parse_ts(row.get("scored_at")),
    }


def _question_payload(row: dict) -> dict:
    import json

    qtype = row.get("question_type") or "mc"
    choices_raw = row.get("choices") or "[]"
    try:
        choices = json.loads(choices_raw)
    except (TypeError, ValueError):
        choices = []
    is_correct = row.get("is_correct")
    return {
        "question_index": row["question_index"],
        "question_text": row["question_text"],
        "question_type": qtype,
        "choices": choices,
        "correct_index": row.get("correct_index") or 0,
        "user_answer": row.get("user_answer"),
        "is_correct": bool(is_correct) if is_correct is not None else None,
        "model_answer": row.get("model_answer"),
        "user_answer_text": row.get("user_answer_text"),
    }


def _write_firestore(client, data: dict) -> None:
    """中間表現を Firestore に書き込む (バッチ)。"""
    from google.cloud import firestore

    # --- unknown_words ---
    for chunk in _chunked(data["words"], _BATCH_SIZE):
        batch = client.batch()
        for row in chunk:
            ref = client.collection(_WORDS).document(
                _word_doc_id(row["lang"], row["word"])
            )
            batch.set(ref, _word_payload(row))  # merge=False (上書き)
        batch.commit()

    # --- quiz_sessions (questions サブコレクションを束ねて書く) ---
    questions_by_session: dict[int, list[dict]] = {}
    for q in data["questions"]:
        questions_by_session.setdefault(q["session_id"], []).append(q)

    # session doc + その questions をまとめてバッチに積む (500 op 上限を尊重)
    ops: list = []
    for s in data["sessions"]:
        session_ref = client.collection(_SESSIONS).document(str(s["id"]))
        ops.append((session_ref, _session_payload(s)))
        for q in questions_by_session.get(s["id"], []):
            qref = session_ref.collection(_QUESTIONS).document(str(q["question_index"]))
            ops.append((qref, _question_payload(q)))
    for chunk in _chunked(ops, _BATCH_SIZE):
        batch = client.batch()
        for ref, payload in chunk:
            batch.set(ref, payload)
        batch.commit()

    # --- story_topics ---
    for chunk in _chunked(data["topics"], _BATCH_SIZE):
        batch = client.batch()
        for row in chunk:
            ref = client.collection(_TOPICS).document(str(row["id"]))
            batch.set(
                ref,
                {
                    "id": row["id"],
                    "lang": row["lang"],
                    "topic": row["topic"],
                    "summary": row.get("summary") or "",
                    "created_at": _parse_ts(row.get("created_at")),
                },
            )
        batch.commit()

    # --- counters: 以降の採番が既存IDと衝突しないよう最大値にセット ---
    max_session = max((s["id"] for s in data["sessions"]), default=0)
    max_topic = max((t["id"] for t in data["topics"]), default=0)
    client.collection(_COUNTERS).document(_SESSIONS).set({"value": max_session})
    client.collection(_COUNTERS).document(_TOPICS).set({"value": max_topic})


def _count_firestore(client) -> dict:
    """Firestore 側の件数を集約クエリで取得する。"""

    def _count(query) -> int:
        result = query.count().get()
        return int(result[0][0].value)

    return {
        "words": _count(client.collection(_WORDS)),
        "sessions": _count(client.collection(_SESSIONS)),
        "questions": _count(client.collection_group(_QUESTIONS)),
        "topics": _count(client.collection(_TOPICS)),
    }


def migrate(source: str, project: str | None, dry_run: bool) -> int:
    """移行を実行し、終了コードを返す (0=成功, 1=件数不一致)。"""
    data = _read_sqlite(source)
    sqlite_counts = {
        "words": len(data["words"]),
        "sessions": len(data["sessions"]),
        "questions": len(data["questions"]),
        "topics": len(data["topics"]),
    }
    logger.info("SQLite counts: %s", sqlite_counts)

    if dry_run:
        logger.info("[dry-run] 書き込みをスキップします。書き込み予定件数:")
        logger.info("  unknown_words : %d", sqlite_counts["words"])
        logger.info("  quiz_sessions : %d", sqlite_counts["sessions"])
        logger.info("  quiz_questions: %d", sqlite_counts["questions"])
        logger.info("  story_topics  : %d", sqlite_counts["topics"])
        return 0

    from google.cloud import firestore

    client = firestore.Client(project=project)
    logger.info("Firestore project=%s に書き込みます ...", client.project)
    _write_firestore(client, data)

    fs_counts = _count_firestore(client)
    logger.info("Firestore counts: %s", fs_counts)

    mismatched = {
        k: (sqlite_counts[k], fs_counts[k])
        for k in sqlite_counts
        if sqlite_counts[k] != fs_counts[k]
    }
    if mismatched:
        logger.error("件数不一致 (sqlite, firestore): %s", mismatched)
        return 1
    logger.info("全件数一致。移行成功。")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="SQLite -> Firestore 移行")
    parser.add_argument("--source", required=True, help="SQLite DB ファイルパス")
    parser.add_argument(
        "--project",
        default=None,
        help="GCP プロジェクトID (省略時は環境変数 / エミュレータ既定)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="実書き込みせず件数のみレポート",
    )
    args = parser.parse_args(argv)
    return migrate(args.source, args.project, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
