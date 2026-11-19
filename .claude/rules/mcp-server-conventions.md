---
paths:
  - "**"
---

## MCP サーバー共通規約

新しい MCP サーバーを `mcps/<name>/` に追加するときの規約。全文は [TEMPLATES.md](../../TEMPLATES.md) を参照。

- ドキュメントは `README.md` (日本語・人間向け概要) / `.claude/rules/<name>.md` (AI 向け、英語) / `TOOLS.md` (日本語・ツール一覧) / `USECASE.md` (任意・ユースケース) に分離する。`folder/CLAUDE.md` は作らない。
- DB は常に SQLite などの軽量ファイルベース DB を使う。
- 環境変数は「環境変数 → パッケージ内 `.env` フォールバック」の順で読む。
- 責務ごとにサブフォルダ・ファイルを分割してよい (承認不要)。
- 新しいパッケージはアンブレラの `pyproject.toml` の workspace `members` に `mcps/<name>` を追記すること ([architecture](architecture.md) 参照)。
