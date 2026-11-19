# dynamic_prompt Repository Layer & Schema

Covers `mcps/dynamic_prompt/src/dynamic_prompt/repo/`, `database.py`, `migrate_to_firestore.py`.

## Repository abstraction

Data access is abstracted behind `repo/` (introduced in Phase 1). Callers (`tools.py`, `quiz_server.py`, `main.py`) get the singleton `RepoBundle` (`vocab` / `quiz` / `topic`) via `get_repo()` and never depend on the concrete backend. `main.py` calls `init_repo(DATA_BACKEND)` at module level at startup.

| Module                    | Responsibility                                                                                                                                                                                                                                                                                                                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `repo/base.py`            | `VocabRepo` / `QuizRepo` / `TopicRepo` Protocols + `RepoBundle` dataclass — the backend-agnostic interface                                                                                                                                                                                                                                                                                 |
| `repo/sqlite_repo/`       | SQLite implementation, split by responsibility: `connection.py` (`DB_PATH`, `_connect_db`), `schema.py` (table defs + `_MIGRATIONS`/`init_db`), `vocab.py` (word status transitions + `SqliteVocabRepo`), `quiz.py` (MC + free quiz + `SqliteQuizRepo`), `topic.py` (`SqliteTopicRepo`). Module-level functions are the sole source of SQL; the `Sqlite*Repo` classes are thin OO wrappers |
| `repo/firestore_repo.py`  | Firestore implementation. Return shapes match SQLite exactly (timestamps as ISO 8601 strings, integer ids). `session_id`/`topic_id` are minted via a transactional `counters/{name}` document (no auto-id strings). Avoids composite indexes — filters/sorts/samples in Python (personal-scale data). Uses the sync `firestore.Client` (not `AsyncClient`)                                 |
| `repo/__init__.py`        | `init_repo(backend)` / `get_repo()`. Backend selected by `DATA_BACKEND` env (default `sqlite`)                                                                                                                                                                                                                                                                                             |
| `migrate_to_firestore.py` | SQLite → Firestore migration (`python -m dynamic_prompt.migrate_to_firestore --source <db> --project <id> [--dry-run]`). 500-row batches, preserves original integer ids as document ids, sets counters to the max, verifies row counts post-write (exits 1 on mismatch)                                                                                                                   |
| `database.py`             | Backward-compat shim re-exporting the old `repo/sqlite_repo.py` API. Scheduled for removal; new code uses `get_repo()`                                                                                                                                                                                                                                                                     |

**Firestore backend**: enable with `DATA_BACKEND=firestore`. Local verification: start `gcloud beta emulators firestore start --host-port=127.0.0.1:8085` (needs Java), set `FIRESTORE_EMULATOR_HOST`/`GOOGLE_CLOUD_PROJECT`, run `pytest src/dynamic_prompt/tests/test_repo_contract.py`.

## SQLite specifics

WAL journaling (`vocab.db`). `DB_PATH` overridable via env (default `src/dynamic_prompt/vocab.db`). `init_db()` (= `vocab.init()`) runs schema creation + migrations once at server startup. Each tool call gets a fresh connection for thread safety (`_connect_db`).

**Migration system**: `schema_version` table tracks the applied version. `_MIGRATIONS` is a list of `(version, description, func)`; `_migrate()` applies only unapplied versions in order (idempotent). To add one: define `_migration_NNN(db)` and append it to `_MIGRATIONS` with the next sequential version.

## Tables

**`unknown_words`**: `id` PK, `lang`, `word` (lowercase, UNIQUE with lang), `context`, `status` (`unlearned`/`wrong`/`memory_test`, default `unlearned`), `reviewed_at`, `created_at`.

**`quiz_sessions`**: `id` PK, `lang`, `title`, `created_at`, `submitted_at` (NULL = pending), `scored_at` (NULL = unscored free-answer or MC-only).

**`quiz_questions`**: `id` PK, `session_id` FK, `question_index` (UNIQUE with session_id), `question_text`, `choices` (JSON array, `'[]'` for free), `correct_index` (0 for free), `user_answer`, `is_correct`, `question_type` (`mc`/`free`), `model_answer`, `user_answer_text`.

**`story_topics`**: `id` PK, `lang`, `topic`, `summary` (default `''`), `created_at`.

**`schema_version`**: `version` PK, `description`, `applied_at`.

## Word status levels

```
save → [unlearned]
         ├─ correct → DELETE
         └─ wrong   → [wrong]
                       ├─ correct → [memory_test] (hidden for configured period)
                       └─ wrong   → stays [wrong]
                                     ├─ correct (after period) → DELETE
                                     └─ wrong (after period)   → [wrong]
```

`memory_test_period_hours` in `user_config.yaml` controls the hide duration (default 24h).
