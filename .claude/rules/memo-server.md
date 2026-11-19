---
paths:
  - "memo/**"
---

## memo — メモ管理 MCP サーバー

FastMCP ベース。タイトル+概要のメモを SQLite に保存し、CRUD を MCP ツールとして提供。検索はタイトル部分一致 + OpenAI embeddings によるセマンティック検索。マルチユーザー対応 (`user_id` でスコープ)、`is_admin` フラグによる管理者ツールの動的可視性あり。

### Commands (cwd はアンブレラのルート)

```bash
uv run --package memo memo --user alice                         # stdio (Claude Desktop / VS Code)
TRANSPORT=http PORT=8080 uv run --package memo memo              # HTTP: /mcp?user=NAME&client_id=ID
uv run --package memo memo-admin                                 # ユーザー管理 Web UI (別プロセス、127.0.0.1:8090)
uv run --package memo memo-migrate [/path/to/memo.db]            # スキーマを最新に移行 (idempotent)
uv run --package memo pytest mcps/memo/src/memo/tests/ -v
```

### ドキュメントマップ

詳細は [claude/](../../memo/claude/) 配下 (トピック別、英語):

- [CONVENTIONS.md](../../memo/claude/CONVENTIONS.md) — FastMCP は必ず公式ドキュメント確認、レイヤー分離、環境変数規約、README/CLAUDE 分割
- スキーマ・DB・移行 → [memo-schema](memo-schema.md)
- レイヤー構成・MCP/Web エッジ → [memo-tools](memo-tools.md)
- メモ/ユーザー/カテゴリのドメインルール → [memo-features](memo-features.md)

### 非自明な注意点

- FastMCP の API は絶対に記憶で使わない。[CONVENTIONS.md](../../memo/claude/CONVENTIONS.md) の通り必ず https://gofastmcp.com を確認する。
- 環境変数は env 優先 + `mcps/memo/.env` フォールバック (既存の env は上書きしない)。
