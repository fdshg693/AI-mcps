---
paths:
  - "**"
---

## サブモジュール全体構成

`mcps/` はアンブレラ（fdshg693/AI）のサブモジュールで、FastMCP 製の MCP サーバーをまとめる。各サーバーは `<name>/` 配下の独立した Python パッケージで、アンブレラの uv workspace のメンバー。サブモジュール直下に `pyproject.toml` は置かない。新しい MCP サーバーを追加したら、アンブレラの `pyproject.toml` の `[tool.uv.workspace] members` に `mcps/<name>` を追記すること。

| パス                          | 内容                                                                                                                                                                |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `<name>/`                     | 各 MCP サーバー。独立した Python パッケージ (`pyproject.toml` を持つ workspace member)。共通の作成規約は [mcp-server-conventions](mcp-server-conventions.md) を参照 |
| `TEMPLATES.md`                | MCP サーバー共通の作成規約 (全文)                                                                                                                                   |
| `claude_desktop_config.jsonc` | Claude Desktop から接続する設定例                                                                                                                                   |

コマンドはアンブレラのルートを cwd にして `uv run --package <name> ...` で実行する (`--project` は不要)。

## ドキュメントの置き場所

- 人間向けの概要は各パッケージの `README.md` (日本語)。
- AI 向けのアーキテクチャ・規約知識は `folder/CLAUDE.md` ではなく **`.claude/rules/<topic>.md`** (このサブモジュールの `.claude/rules/`) に置く。長文の詳細はパッケージ内 `docs/` に置き、rule ファイルからポイントする。アンブレラから開いたときの入口は [AGENTS.md](../../AGENTS.md) の索引なので、rule を足したら索引にも 1 行足す。
- 既存の `dynamic_prompt/CLAUDE.md` 的な単一巨大ファイルは段階的に rule + `docs/` へ移行済み。新規に `CLAUDE.md` を作らないこと。
