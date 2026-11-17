# dynamic_prompt Architecture

Covers `mcps/dynamic_prompt/src/dynamic_prompt/` excluding the repository/DB layer (see [SCHEMA.md](SCHEMA.md)). Tool call semantics and call order are in [../TOOLS.md](../TOOLS.md); this file covers module wiring and request flow.

## Module structure

| Module                              | Responsibility                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`                         | Dataclasses (`Language`, `UserConfig`, `AppConfig`, `Instruction`) — all `frozen=True`                                                             |
| `config_source.py`                  | `ConfigSource` abstraction (`LocalConfigSource` / `GCSConfigSource`) + factory, switched by `PROMPTS_URI`                                          |
| `config.py`                         | YAML loading, path constants, TTL-cached `ConfigStore` (`config_store` singleton). Checks TTL on every access and auto-refreshes                   |
| `session.py`                        | `_Session` class + singleton — holds the current target language                                                                                   |
| `tools.py`                          | Variable resolvers, template rendering, vocab/quiz/story tools, and the 13 `@mcp.tool` functions. DB access via `get_repo()`                       |
| `main.py`                           | `mcp` FastMCP instance + entry point (`main()`), transport switch (`TRANSPORT` env), `/health`, OAuth (HTTP mode), starts quiz server (stdio only) |
| `quiz_server.py`                    | Starlette + uvicorn quiz web server (SSE, REST, word-save API). Runs in a daemon thread                                                            |
| `static/quiz.html` / `.css` / `.js` | Quiz UI (SSE connect, answer submit, word save)                                                                                                    |
| `validate.py`                       | YAML configuration consistency checker                                                                                                             |

`main.py` creates the `mcp` instance; `tools.py` imports it via side-effect import to register tools. `init_db()` runs at module level so DB init happens on every startup path.

## Transport modes

- **stdio** (default, Claude Desktop): `main()` starts the quiz web server on a daemon thread (port pool 8765–8767).
- **HTTP** (`TRANSPORT=http`): `mcp.http_app(path="/mcp")` is combined with the quiz UI routes into one Starlette app under uvicorn. `combined_lifespan` initializes both the MCP session manager and the quiz `asyncio.Queue`. Single port serves `/` (quiz UI), `/mcp`, `/health`, `/events` (SSE), `/api/*`, `/static/`.

**OAuth (HTTP only)**: set via `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` → FastMCP `GoogleProvider` protects `/mcp` (not `/health` or the quiz UI). `SERVICE_URL` sets the OAuth `base_url` (default `http://localhost:8080`). Unset envs = no auth (local dev).

**Email allowlist**: `ALLOWED_EMAILS` (comma-separated) makes `main.py`'s `EmailAllowlistGoogleTokenVerifier` reject Google accounts not on the list (adds `userinfo.email` to required scopes). Unset = warn + allow all (backward compatible).

**Quiz server port management**: `start_quiz_server()` tries the port pool in order; if occupied, kills the stale process via `netstat`+`taskkill` (Windows) / `lsof`+`kill` (Unix) and retries. Graceful shutdown via `atexit` + `uvicorn.Server.should_exit`. Active port via `get_active_port()`.

**Gotcha**: `fastmcp run <file>` double-instantiates `mcp` (tools become 0). Always launch via `uv run dynamic_prompt` (the entry point). See `memo/CLAUDE_DESKTOPでの使い方.md` at the repo root.

## Quiz Web UI

**Multiple choice**: `send_quiz` → DB save + SSE push → browser radio-button UI → user submits → web server scores immediately → `get_quiz_results` → feeds `answer_words`.

**Free answer** (two-phase — AI grades afterward): `send_free_quiz` → DB save + SSE push → browser textarea UI → saved unscored → `get_unscored_quizzes` → AI compares to `model_answer` → `score_free_answers` → `get_quiz_results` → feeds `answer_words`.

- Real-time push via SSE; `/api/pending` is the fallback on page load.
- Cross-thread comms: `asyncio.Queue` + `asyncio.run_coroutine_threadsafe()` (sync MCP tool → async SSE).
- Word save: browser form → `POST /api/save_words` → DB directly; picked up by the next `get_words` call (async hand-off).

| Method | Path              | Description                                   |
| ------ | ----------------- | --------------------------------------------- |
| GET    | `/`               | serve quiz.html                               |
| GET    | `/events`         | SSE push                                      |
| GET    | `/api/pending`    | unanswered quizzes                            |
| POST   | `/api/submit`     | submit + score                                |
| POST   | `/api/save_words` | save words from the UI (lang, words, context) |

## Configuration-driven design

Behavior is driven by YAML under `src/dynamic_prompt/prompts/` (or GCS, see below): `user_config.yaml`, `app_config.yaml`, `instructions.yaml` (templates + declared variable scopes), `languages/*.yaml` (+ `_default.yaml` fallback).

**External storage (`PROMPTS_URI`)**: `config_source.py` abstracts local filesystem vs. GCS.

| `PROMPTS_URI`        | Behavior                                                       |
| -------------------- | -------------------------------------------------------------- |
| unset (default)      | `LocalConfigSource` reads `src/dynamic_prompt/prompts/`        |
| `/abs/path`          | `LocalConfigSource` reads that path                            |
| `gs://bucket/prefix` | `GCSConfigSource` (google-cloud-storage SDK) reads that prefix |

Cloud Run sets `PROMPTS_URI=gs://${project_id}-dp-data/prompts`; upload via `just upload-prompts` (`gsutil rsync`). `validate.py` is local-YAML-only, for pre-upload checks.

**TTL cache**: `ConfigStore` checks TTL on every access and reloads in the background when expired (`CONFIG_TTL_SECONDS`, default 60s, `<=0` disables auto-refresh). A failed reload keeps serving the stale cache rather than crashing.

**`ConfigStore` (mutable wrapper over frozen dataclasses)**: the dataclasses stay `frozen=True`; `ConfigStore` exposes `user_config`/`app_config`/`languages`/`instructions` as `@property`, checking TTL on access.

- `config_store.reload()` — force immediate reload, ignoring TTL
- `config_store.update_user_config(**kwargs)` / `update_app_config(**kwargs)` — temporary field overrides, discarded on the next auto-refresh or `reload()`
- `config_store.format_language_codes()` — comma-separated registered language codes

MCP tool `reload_config` triggers `reload()` from the AI side (edit YAML externally → apply immediately). All modules access config only through the `config_store` singleton — no module-level constants.

## Template rendering

Instructions use `str.format_map()` with `{variable}` placeholders. Each instruction declares which variable groups it needs (`user_config`, `language`). `_VAR_RESOLVERS` (`tools.py`) maps group names to functions pulling from `config_store.user_config` or `session.lang`.

## Session state

`_Session` (`session.py`) holds the current target language. Tools like `get_instruction` require a language to be set first via `determine_language`.

## Adding a new language

1. Create `src/dynamic_prompt/prompts/languages/<code>.yaml` following `en.yaml`/`fr.yaml`.
2. Run `validate.py` to confirm fields match expectations.

## Adding a new instruction

1. Add an entry to `instructions.yaml` with `requires_language`, `variables` (group name → field list), and `template`.
2. Ensure every `{placeholder}` maps to a field in the relevant dataclass.
3. Escape literal `{`/`}` as `{{`/`}}` (`str.format_map()` would otherwise treat them as placeholders).
4. Run `validate.py`.
