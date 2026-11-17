# dynamic_prompt Infra

Covers `mcps/dynamic_prompt/infra/` — Docker / Cloud Build / Terraform for GCP Cloud Run deployment.

## Commands (`justfile`)

All commands run from `mcps/dynamic_prompt/infra/` via [just](https://github.com/casey/just).

```bash
cd mcps/dynamic_prompt/infra

just                # list recipes (default)

# Docker
just build / run / stop / health / logs

# Firestore emulator (local test / Docker)
just emulator-up / emulator-down       # 8085, --wait for healthy
just test-firestore                    # emulator up + contract tests (sqlite + firestore)
just migrate-firestore                 # SQLite -> emulator migration script

# GCP
just cloud-build                       # Cloud Build -> Artifact Registry
just tf-init / tf-plan / tf-apply / tf-output / tf-destroy
just cloud-info / cloud-health         # gcloud service info / unauthenticated health check

just deploy                            # cloud-build -> tf-apply
```

Windows: `justfile` sets `windows-shell` to Git Bash (`C:/Program Files/Git/usr/bin/bash.exe`) to avoid mojibake.

## Layout

| Path | Content |
|------|---------|
| `Dockerfile` | Python 3.13-slim + uv. Build context is the **repo root** (`my_ai_tools/`) — pass `-f` to point at this Dockerfile |
| `firestore-emulator.compose.yml` | Official Cloud SDK emulator image (bundles Java, no host JDK needed). Port 8085 with healthcheck |
| `cloudbuild.yaml` | Cloud Build definition; `_IMAGE` substitution var sets the registry path |
| `terraform/` | Cloud Run, Artifact Registry, GCS, IAM |

**Dockerfile**: separates dependency install from code copy for cache efficiency. Default env: `TRANSPORT=http`, `HOST=0.0.0.0`, `PORT=8080`, `DB_PATH=/data/vocab.db`. Cloud Run YAML source: `PROMPTS_URI=gs://${project_id}-dp-data/prompts`, `CONFIG_TTL_SECONDS=60` — sync YAML via `just upload-prompts`, apply immediately by calling the `reload_config` MCP tool.

## Terraform

| File | Content |
|------|---------|
| `main.tf` | Provider, API enablement |
| `variables.tf` | `project_id`, `region`, `image_tag`, `google_client_id`, `google_client_secret`, `service_url`, `allowed_emails` |
| `terraform.tfvars` | Actual values (gitignored) |
| `registry.tf` | Artifact Registry (Docker) |
| `storage.tf` | GCS bucket (`prevent_destroy`) — SQLite persistence |
| `cloud_run.tf` | Cloud Run v2, `max_instance_count = 1`, GCS volume mount |
| `iam.tf` | `allUsers` → `roles/run.invoker` |
| `outputs.tf` | `service_url`, `mcp_endpoint`, `image_repo` |

## GCP environment

- Project: `dynamic-prompt-mcp` / Region: `asia-northeast1`
- Cloud Run URL: `https://dynamic-prompt-m2py3twbha-an.a.run.app` (MCP endpoint: `/mcp`)
- Artifact Registry: `asia-northeast1-docker.pkg.dev/dynamic-prompt-mcp/dynamic-prompt/server`
- Single instance only (SQLite single-writer constraint); persistence via a GCS bucket mounted at `/data`
- Health check: `GET /health`

## Auth

FastMCP `GoogleProvider` (OAuth 2.1), protecting only `/mcp` (`/health` and the quiz UI are open). Cloud Run IAM grants `allUsers` → `roles/run.invoker` (auth is app-level, not IAM-level). Configured via `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`SERVICE_URL`/`ALLOWED_EMAILS` env vars on the container. `allowed_emails` (terraform var) restricts to specific Google accounts; unset = allow all. Requires a pre-created OAuth consent screen + credentials in GCP Console, with redirect URI `{SERVICE_URL}/auth/callback`.

## Notes

- `terraform.tfvars` and `terraform.tfstate*` must stay gitignored.
- `max_instance_count = 1` on Cloud Run must not change (would allow concurrent SQLite writers).
- The GCS bucket has `prevent_destroy` — survives `terraform destroy`.
