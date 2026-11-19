@./README.md

## このフォルダだけを開いたとき

アンブレラ（fdshg693/AI）の `mcps/` として clone されている前提。共通の手順（Junction・フックの作り方、`_umbrella/` の扱い、2 段階コミット）は [repo-layout](../maintenance/docs/repo-layout.md#サブモジュールを単体で開く)。

- `plans/` はアンブレラの `plans/` への Junction。作成・変更したプランはアンブレラに属する。`dynamic_prompt/plans/` はパッケージ内の設計履歴で別物。
- uv はアンブレラの workspace と `.venv` を使う。コマンドはアンブレラのルートで `uv run --package <name> ...`（`--project` は不要）。サブモジュール直下に `pyproject.toml` は置かない。
- MCP サーバーを足したら、アンブレラの `pyproject.toml` の `[tool.uv.workspace] members` に `mcps/<name>` を足す（[TEMPLATES.md](TEMPLATES.md)）。
- `dynamic_prompt` の Docker / Cloud Build のビルドコンテキストはこのフォルダのルート。アップロード対象は `.dockerignore`・`.gcloudignore` で絞っている。

## 規約の入口

MCP サーバー共通の規約は [TEMPLATES.md](TEMPLATES.md)。AI 向けの詳細は [.claude/rules/](.claude/rules/) にある。このフォルダを開いたときは `paths:` に応じて自動で読まれるが、アンブレラから開いたときは読まれないので、触るファイルに応じて次を読む。

| ファイル                                                             | 扱うこと                                                             |
| -------------------------------------------------------------------- | -------------------------------------------------------------------- |
| [architecture.md](.claude/rules/architecture.md)                     | サブモジュール全体の構成、workspace への登録、ドキュメントの置き場所 |
| [mcp-server-conventions.md](.claude/rules/mcp-server-conventions.md) | MCP サーバー共通規約（TEMPLATES.md の要約）                          |
| [dynamic-prompt.md](.claude/rules/dynamic-prompt.md)                 | `dynamic_prompt` のサーバー本体・コマンド・注意点                    |
| [dynamic-prompt-db.md](.claude/rules/dynamic-prompt-db.md)           | `dynamic_prompt` のリポジトリ層・DB・Firestore 移行                  |
| [dynamic-prompt-infra.md](.claude/rules/dynamic-prompt-infra.md)     | `dynamic_prompt/infra/`（Docker・Cloud Build・Terraform）            |
| [memo-server.md](.claude/rules/memo-server.md)                       | `memo` 全体・コマンド・ドキュメントマップ                            |
| [memo-schema.md](.claude/rules/memo-schema.md)                       | `memo` のスキーマ・DB・マイグレーション                              |
| [memo-tools.md](.claude/rules/memo-tools.md)                         | `memo` のレイヤー構成・MCP ツール・管理者ツールの表示切り替え        |
| [memo-features.md](.claude/rules/memo-features.md)                   | `memo` のドメインルール（メモ・ユーザー・カテゴリ）                  |
