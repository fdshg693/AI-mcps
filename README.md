# mcps

[FastMCP](https://gofastmcp.com) で作った MCP サーバーをまとめるリポジトリ。アンブレラ [fdshg693/AI](https://github.com/fdshg693/AI) の `mcps/` にサブモジュールとして入っている。

各サーバーは `<name>/` 配下の独立した Python パッケージで、アンブレラの uv workspace のメンバー。コマンドはアンブレラのルートで `uv run --package <name> ...` として実行する。

## 構成

| パス                                                       | 内容                                                                 |
| ---------------------------------------------------------- | -------------------------------------------------------------------- |
| [dynamic_prompt/](dynamic_prompt/)                         | 外国語学習用 MCP サーバー（後述）                                    |
| [memo/](memo/)                                             | メモ管理 MCP サーバー（後述）                                        |
| [TEMPLATES.md](TEMPLATES.md)                               | MCP サーバーを足すときの共通規約                                     |
| [claude_desktop_config.jsonc](claude_desktop_config.jsonc) | Claude Desktop から接続する設定例                                    |
| [.claude/rules/](.claude/rules/)                           | AI 向けの実装規約（英語・日本語混在。索引は [AGENTS.md](AGENTS.md)） |

## MCP サーバー

### dynamic_prompt

AI に外国語学習を伴走させるための MCP サーバー。

- 会話で出てきた未知語を SQLite（または Firestore）に蓄積し、`unlearned → wrong → memory_test` のステータス遷移で忘却対策の再出題を AI に行わせる
- 同じプロセスで Starlette + SSE のクイズ Web UI を立ち上げ、AI が出題したクイズをローカルのブラウザへリアルタイムに送る（選択式・自由回答の両対応）
- 言語ごとの教え方やユーザーの母語などは YAML で宣言的に管理し、`get_instruction` ツール経由で AI に渡す
- stdio（Claude Desktop）と HTTP + Google OAuth（Cloud Run）の両モードで動く

使い方・ツール一覧は [dynamic_prompt/README.md](dynamic_prompt/README.md)、Cloud Run へのデプロイは [dynamic_prompt/docs/INFRA.md](dynamic_prompt/docs/INFRA.md)。

### memo

タイトルと概要を持つメモを管理する MCP サーバー。

- SQLite にメモを保存し、CRUD を MCP ツールとして提供する
- 検索はタイトルの部分一致と、OpenAI embeddings による概要のセマンティック検索
- ユーザーごとにメモを分離し、管理者ツールはセッションごとに表示を切り替える

使い方・ツール一覧は [memo/README.md](memo/README.md)。

## Claude Desktop から接続する

[claude_desktop_config.jsonc](claude_desktop_config.jsonc) を Claude Desktop の設定にコピーし、`your/path/to/AI` をアンブレラの clone 先に書き換える。`uv run --directory <アンブレラ> --package <name> <name>` の形で起動する。

## ライセンス

[MIT License](LICENSE)
