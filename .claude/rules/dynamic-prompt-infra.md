---
paths:
  - "dynamic_prompt/infra/**"
---

## dynamic_prompt — Infra (Docker / Cloud Build / Terraform)

Cloud Run へのデプロイ基盤。コマンドは `dynamic_prompt/infra/justfile` から (`just` で一覧)。GCP: project は `terraform/terraform.tfvars` の `project_id` (justfile だけは環境変数 `GCP_PROJECT_ID` で上書き可) / region `asia-northeast1`。Cloud Run は `max_instance_count = 1` 固定 (SQLite 単一書き込み制約 — 変更不可)、永続化は GCS バケットを `/data` にマウント。認証は FastMCP `GoogleProvider` (OAuth 2.1、`/mcp` のみ保護)。詳細・コマンド全量・Terraform 構成は [docs/INFRA.md](../../dynamic_prompt/docs/INFRA.md) を参照。

- Dockerfile のビルドコンテキストはこのサブモジュールのルート (`mcps/`)。アンブレラのルートにしない (全サブモジュールがコンテキストに入る)。
- `terraform.tfvars` / `terraform.tfstate*` は必ず gitignore 対象。GCS バケットは `prevent_destroy`。
