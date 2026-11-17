"""リポジトリ層のバックエンド非依存な契約テスト。

``get_repo()`` 経由でのみデータ操作し、SQLite と Firestore の両実装が同じ振る舞いを
することを保証する。

- ``sqlite`` は常に実行する。
- ``firestore`` は ``FIRESTORE_EMULATOR_HOST`` がセットされている時だけ実行する
  (未設定なら自動でスキップ)。CI 高速化のため、デフォルトでは sqlite のみ走る。

エミュレータ起動例:
    gcloud beta emulators firestore start --host-port=127.0.0.1:8085
    $env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8085"
    $env:GOOGLE_CLOUD_PROJECT="dynamic-prompt-mcp-test"
    uv run --project . pytest src/dynamic_prompt/tests/test_repo_contract.py -v
"""

import os

import pytest

from dynamic_prompt.repo import get_repo, init_repo

_BACKENDS = ["sqlite"]
if os.environ.get("FIRESTORE_EMULATOR_HOST"):
    _BACKENDS.append("firestore")


def _clear_firestore() -> None:
    """エミュレータ上の全コレクションを削除する。"""
    from dynamic_prompt.repo import build_firestore_repo
    from dynamic_prompt.repo import firestore_repo as fr

    client = build_firestore_repo().vocab._client
    for coll_name in (fr._WORDS, fr._TOPICS, fr._COUNTERS):
        for doc in client.collection(coll_name).list_documents():
            doc.delete()
    for doc in client.collection(fr._SESSIONS).list_documents():
        for sub in doc.collections():
            for q in sub.list_documents():
                q.delete()
        doc.delete()


@pytest.fixture(params=_BACKENDS)
def repo(request):
    """各バックエンドで初期化済みの RepoBundle を返す。データは事前にクリアする。"""
    backend = request.param
    if backend == "sqlite":
        from dynamic_prompt.repo.sqlite_repo import connection as conn_mod

        bundle = init_repo("sqlite")
        with conn_mod._connect_db() as db:
            for table in ("quiz_questions", "quiz_sessions", "unknown_words", "story_topics"):
                db.execute(f"DELETE FROM {table}")
    else:
        _clear_firestore()
        bundle = init_repo("firestore")
    yield bundle
    # 後続テスト (SQLite 前提の autouse フィクスチャ等) のため既定へ戻す。
    init_repo("sqlite")


# ---------------------------------------------------------------------------
# Vocab
# ---------------------------------------------------------------------------


class TestVocab:
    def test_save_and_review_pool(self, repo):
        saved = repo.vocab.save_words("en", ["  Apple ", "banana", "", "  "])
        assert saved == ["apple", "banana"]
        pool = repo.vocab.get_review_pool("en", limit=10, memory_test_period_hours=24)
        words = {p["word"] for p in pool}
        assert words == {"apple", "banana"}
        assert all(p["status"] == "unlearned" for p in pool)

    def test_save_preserves_status_updates_context(self, repo):
        repo.vocab.save_words("en", ["grape"])
        # grape を wrong にする (incorrect 回答経由)
        repo.vocab.process_answers("en", [], ["grape"])
        repo.vocab.save_words("en", ["grape"], context="new context")
        pool = repo.vocab.get_review_pool("en", limit=10, memory_test_period_hours=24)
        grape = next(p for p in pool if p["word"] == "grape")
        assert grape["status"] == "wrong"
        assert grape["context"] == "new context"

    def test_correct_unlearned_removes(self, repo):
        repo.vocab.save_words("en", ["x"])
        msgs = repo.vocab.process_answers("en", ["x"], [])
        assert "removed" in msgs[0]
        pool = repo.vocab.get_review_pool("en", limit=10, memory_test_period_hours=24)
        assert pool == []

    def test_wrong_then_correct_moves_to_memory_test_hidden(self, repo):
        repo.vocab.save_words("en", ["y"])
        repo.vocab.process_answers("en", [], ["y"])  # -> wrong
        repo.vocab.process_answers("en", ["y"], [])  # -> memory_test (hidden)
        # period 大: まだ隠れている
        pool = repo.vocab.get_review_pool("en", limit=10, memory_test_period_hours=24)
        assert all(p["word"] != "y" for p in pool)
        # period 0: 即復習対象
        pool2 = repo.vocab.get_review_pool("en", limit=10, memory_test_period_hours=0)
        assert any(p["word"] == "y" and p["status"] == "memory_test" for p in pool2)

    def test_process_answer_not_found(self, repo):
        msgs = repo.vocab.process_answers("en", ["ghost"], [])
        assert "not found" in msgs[0]


# ---------------------------------------------------------------------------
# Quiz (MC)
# ---------------------------------------------------------------------------


class TestQuizMc:
    def _make(self, repo, lang="en", title="Quiz"):
        return repo.quiz.create_session(
            lang,
            title,
            [
                {"question": "Q1", "choices": ["A", "B"], "correct_index": 0},
                {"question": "Q2", "choices": ["X", "Y"], "correct_index": 1},
            ],
        )

    def test_create_returns_int_id(self, repo):
        sid = self._make(repo)
        assert isinstance(sid, int)

    def test_pending_then_submit(self, repo):
        sid = self._make(repo, title="Pending")
        pending = repo.quiz.get_pending()
        assert pending["session_id"] == sid
        assert pending["title"] == "Pending"
        assert pending["lang"] == "en"
        assert len(pending["questions"]) == 2
        assert pending["questions"][0]["question"] == "Q1"

        result = repo.quiz.submit_answers(sid, [0, 1])
        assert result["session_id"] == sid
        assert result["correct_count"] == 2
        assert result["total_count"] == 2
        assert result["mc_total"] == 2
        assert result["has_free"] is False
        assert all(d["is_correct"] for d in result["details"])
        # 提出後は pending から消える
        assert repo.quiz.get_pending() is None

    def test_mixed_answers(self, repo):
        sid = self._make(repo)
        result = repo.quiz.submit_answers(sid, [0, 0])  # Q1 correct, Q2 wrong
        assert result["correct_count"] == 1

    def test_results_filter_and_limit(self, repo):
        for i in range(3):
            s = self._make(repo, title=f"Q{i}")
            repo.quiz.submit_answers(s, [0, 1])
        self._make(repo, lang="fr", title="French")  # pending, excluded
        en = repo.quiz.get_recent_results("en")
        assert len(en) == 3
        assert all(r["correct_count"] == 2 for r in en)
        assert repo.quiz.get_recent_results("fr") == []
        assert len(repo.quiz.get_recent_results("en", limit=2)) == 2

    def test_results_detail_structure(self, repo):
        sid = self._make(repo, title="Detail")
        repo.quiz.submit_answers(sid, [0, 0])
        res = repo.quiz.get_recent_results("en")[0]
        qs = res["questions"]
        assert qs[0]["question_type"] == "mc"
        assert qs[0]["correct_choice"] == "A"
        assert qs[0]["is_correct"] is True
        assert qs[1]["is_correct"] is False


# ---------------------------------------------------------------------------
# Quiz (free-answer)
# ---------------------------------------------------------------------------


class TestQuizFree:
    def _make_free(self, repo, lang="en"):
        return repo.quiz.create_session(
            lang,
            "Free Quiz",
            [
                {
                    "question": "Describe your day",
                    "question_type": "free",
                    "model_answer": "A good answer",
                },
            ],
        )

    def test_submit_free_stays_unscored(self, repo):
        sid = self._make_free(repo)
        result = repo.quiz.submit_answers(sid, ["my answer"])
        assert result["has_free"] is True
        assert result["mc_total"] == 0
        assert result["details"][0]["is_correct"] is None
        assert result["details"][0]["user_answer_text"] == "my answer"

        unscored = repo.quiz.get_unscored("en")
        assert len(unscored) == 1
        assert unscored[0]["session_id"] == sid
        assert unscored[0]["questions"][0]["user_answer_text"] == "my answer"
        assert unscored[0]["questions"][0]["model_answer"] == "A good answer"

    def test_score_free(self, repo):
        sid = self._make_free(repo)
        repo.quiz.submit_answers(sid, ["my answer"])
        out = repo.quiz.score_free_answers(sid, [{"question_index": 0, "is_correct": True}])
        assert out["scored_count"] == 1
        assert out["correct_count"] == 1
        # 採点後は unscored から消える
        assert repo.quiz.get_unscored("en") == []
        res = repo.quiz.get_recent_results("en")[0]
        assert res["questions"][0]["is_correct"] is True


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------


class TestTopic:
    def test_save_and_list_recent_first(self, repo):
        id1 = repo.topic.save_topic("en", "first", "summary one")
        id2 = repo.topic.save_topic("en", "second", "")
        assert isinstance(id1, int) and id1 != id2
        topics = repo.topic.list_recent("en")
        assert [t["topic"] for t in topics] == ["second", "first"]
        assert topics[1]["summary"] == "summary one"

    def test_filter_by_language_and_limit(self, repo):
        repo.topic.save_topic("en", "english", "")
        repo.topic.save_topic("fr", "french", "")
        assert [t["topic"] for t in repo.topic.list_recent("en")] == ["english"]
        assert [t["topic"] for t in repo.topic.list_recent("fr")] == ["french"]
        for i in range(5):
            repo.topic.save_topic("de", f"t{i}", "")
        assert len(repo.topic.list_recent("de", limit=3)) == 3

    def test_empty(self, repo):
        assert repo.topic.list_recent("en") == []
