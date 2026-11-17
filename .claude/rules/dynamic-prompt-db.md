---
paths:
  - "dynamic_prompt/src/dynamic_prompt/repo/**"
  - "dynamic_prompt/src/dynamic_prompt/database.py"
  - "dynamic_prompt/src/dynamic_prompt/migrate_to_firestore.py"
---

## dynamic_prompt — リポジトリ層 / DB

データアクセスは `repo/` で backend 非依存に抽象化されている。呼び出し側は `get_repo()` でシングルトン `RepoBundle` (`vocab`/`quiz`/`topic`) を取得する。バックエンドは `DATA_BACKEND` 環境変数 (既定 `sqlite`、`firestore` も可) で切替。詳細なテーブル定義・マイグレーション手順・Firestore の設計判断は [docs/SCHEMA.md](../../dynamic_prompt/docs/SCHEMA.md) を参照。

- 新しいバックエンドを追加する場合は `repo/base.py` の Protocol を実装し、SQLite 実装 (`repo/sqlite_repo/`) と戻り値の形 (タイムスタンプ ISO 8601 文字列、ID は整数) を一致させること。
- `database.py` は旧 API の後方互換 shim。新規コードは `get_repo()` を使う。
- SQLite → Firestore の本番移行は `migrate_to_firestore.py`。
