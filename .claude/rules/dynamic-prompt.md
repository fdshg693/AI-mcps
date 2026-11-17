---
paths:
  - "dynamic_prompt/src/dynamic_prompt/*.py"
  - "dynamic_prompt/src/dynamic_prompt/prompts/**"
  - "dynamic_prompt/src/dynamic_prompt/static/**"
  - "dynamic_prompt/src/dynamic_prompt/tests/**"
  - "dynamic_prompt/pyproject.toml"
---

## dynamic_prompt — 外国語学習 MCP サーバー

FastMCP ベース。会話中の未知語を SQLite/Firestore に蓄積し、`unlearned → wrong → memory_test` の状態遷移で忘却対策の再出題を行う。同プロセスで Starlette + SSE のクイズ Web UI を起動する。詳細は [docs/ARCHITECTURE.md](../../dynamic_prompt/docs/ARCHITECTURE.md)、DB/リポジトリ層は [dynamic-prompt-db](dynamic-prompt-db.md)、ツール一覧・呼び出し順は [TOOLS.md](../../dynamic_prompt/TOOLS.md) を参照。

### Commands (cwd はアンブレラのルート)

```bash
uv run --package dynamic_prompt dynamic_prompt                       # stdio (Claude Desktop 用)。クイズ Web サーバーも自動起動 (既定 http://127.0.0.1:8765)
TRANSPORT=http PORT=8080 uv run --package dynamic_prompt dynamic_prompt  # HTTP (Cloud Run 等)
uv run --package dynamic_prompt python mcps/dynamic_prompt/src/dynamic_prompt/validate.py   # YAML 設定の整合性チェック
uv run --package dynamic_prompt pytest mcps/dynamic_prompt/src/dynamic_prompt/tests/ -v
```

13 個の MCP ツールを公開: `determine_language`, `get_instruction`, `get_words`, `save_words`, `answer_words`, `send_quiz`, `send_free_quiz`, `get_quiz_results`, `get_unscored_quizzes`, `score_free_answers`, `get_past_topics`, `save_story_topic`, `reload_config`.

### 非自明な注意点

- `fastmcp run <file>` は `mcp` インスタンスを二重生成してツールが 0 になる。必ず `uv run --package dynamic_prompt dynamic_prompt` を使うこと。
- YAML 設定はローカル (`prompts/`) または `PROMPTS_URI=gs://...` (GCS) から読む。ConfigStore は TTL キャッシュ付き — 詳細は ARCHITECTURE.md。
