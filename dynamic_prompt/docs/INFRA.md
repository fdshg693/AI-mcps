# dynamic_prompt Infra

Covers `dynamic_prompt/infra/` (paths are relative to the `mcps` submodule root) — Docker / Cloud Build / Terraform for GCP Cloud Run deployment.

## Commands (`justfile`)

All commands run from `dynamic_prompt/infra/` via [just](https://github.com/casey/just).

```bash
cd dynamic_prompt/infra

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

GCP project ID: recipes that call GCP read `GCP_PROJECT_ID`, else `project_id` in `terraform/terraform.tfvars`, and stop if neither is set. No project ID is hard-coded.

Windows: `justfile` sets `windows-shell` to Git Bash (`C:/Program Files/Git/usr/bin/bash.exe`) to avoid mojibake.

## Layout

| Path                             | Content                                                                                                                               |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `Dockerfile`                     | Python 3.13-slim + uv. Build context is the **`mcps` submodule root** (not the umbrella root) — pass `-f` to point at this Dockerfile |
| `firestore-emulator.compose.yml` | Official Cloud SDK emulator image (bundles Java, no host JDK needed). Port 8085 with healthcheck                                      |
| `cloudbuild.yaml`                | Cloud Build definition; `_IMAGE` substitution var sets the registry path                                                              |
| `terraform/`                     | Cloud Run, Artifact Registry, GCS, IAM                                                                                                |

**Dockerfile**: separates dependency install from code copy for cache efficiency. Default env: `TRANSPORT=http`, `HOST=0.0.0.0`, `PORT=8080`, `DB_PATH=/data/vocab.db`. Cloud Run YAML source: `PROMPTS_URI=gs://${project_id}-dp-data/prompts`, `CONFIG_TTL_SECONDS=60` — sync YAML via `just upload-prompts`, apply immediately by calling the `reload_config` MCP tool.

## Terraform

| File               | Content                                                                                                          |
| ------------------ | ---------------------------------------------------------------------------------------------------------------- |
| `main.tf`          | Provider, API enablement                                                                                         |
| `variables.tf`     | `project_id`, `region`, `image_tag`, `google_client_id`, `google_client_secret`, `service_url`, `allowed_emails` |
| `terraform.tfvars` | Actual values (gitignored)                                                                                       |
| `registry.tf`      | Artifact Registry (Docker)                                                                                       |
| `storage.tf`       | GCS bucket (`prevent_destroy`) — SQLite persistence                                                              |
| `cloud_run.tf`     | Cloud Run v2, `max_instance_count = 1`, GCS volume mount                                                         |
| `iam.tf`           | `allUsers` → `roles/run.invoker`                                                                                 |
| `outputs.tf`       | `service_url`, `mcp_endpoint`, `image_repo`                                                                      |

## GCP environment

- Project: `project_id` in `terraform.tfvars` / Region: `asia-northeast1` (`region` variable default)
- Cloud Run URL: `just tf-output` → `service_url` (MCP endpoint: `/mcp`)
- Artifact Registry: `asia-northeast1-docker.pkg.dev/<project_id>/dynamic-prompt/server`
- Upload filters: `.dockerignore` (local `docker build`) and `.gcloudignore` (`gcloud builds submit`) at the submodule root keep `.env`, `*.db`, tfstate/tfvars and the umbrella Junctions out of the build
- Single instance only (SQLite single-writer constraint); persistence via a GCS bucket mounted at `/data`
- Health check: `GET /health`

## First deployment to a new project

`just deploy` only works once the project already has the Artifact Registry repo and the prompts in GCS. On a brand-new project, follow this order (verified 2026-11):

1. Create the project and link billing (`gcloud projects create <id>` / `gcloud billing projects link <id> --billing-account=<account>`). Terraform authenticates with ADC: `gcloud auth application-default login`.
2. Compute `service_url` up front — Cloud Run's deterministic URL is `https://dynamic-prompt-<PROJECT_NUMBER>.<region>.run.app` (`gcloud projects describe <id> --format='value(projectNumber)'`). No placeholder apply is needed. The `service_url` Terraform output shows the legacy `*.a.run.app` URL instead; both serve the same service.
3. In the Console (Google Auth Platform): consent screen (External, Testing; add yourself as a test user), then a "Web application" OAuth client with redirect URI `{service_url}/auth/callback`. The client secret is shown in full only once.
4. Write `terraform/terraform.tfvars` (from `terraform.tfvars.example`), then `just tf-init`.
5. Create the APIs and the registry first, because `cloud-build` pushes into a repo Terraform creates:
   `terraform -chdir=terraform apply -target=google_project_service.apis -target=google_artifact_registry_repository.repo`
6. `just cloud-build`. Right after project creation it may fail with `PERMISSION_DENIED ... serviceusage.services.use` even for the owner — IAM propagation; retry after a minute.
7. Create the bucket and upload the prompts **before** Cloud Run starts — the server reads `prompts/user_config.yaml` from GCS at startup and exits(1) if it is missing:
   `terraform -chdir=terraform apply -target=google_storage_bucket.data` → `just upload-prompts`
8. `just tf-apply`, then `just cloud-health` / `just cloud-info`.

If the Cloud Run service is created but its first revision fails, Terraform marks it tainted and cannot replace it: google provider v6 keeps `deletion_protection = true` on `google_cloud_run_v2_service` by default. Untainting does not help either (no template diff → no new revision). Delete the empty service with `gcloud run services delete dynamic-prompt`, `terraform state rm google_cloud_run_v2_service.app`, and apply again. For the same reason `just tf-destroy` fails on the service unless `deletion_protection = false` is applied first.

## Known behavior

- `terraform plan` always shows an in-place change on the service-level `scaling` block (`min_instance_count = 0 -> null`). It is a provider quirk and harmless.
- The Dockerfile runs `uv sync` per package without a lock file (the umbrella `uv.lock` is outside the build context), so dependency versions can differ from the local environment.
- `uv run` in `CMD` syncs the dev dependency group at container start (a few extra packages), which slows cold starts slightly.

## Auth

FastMCP `GoogleProvider` (OAuth 2.1), protecting only `/mcp` (`/health` and the quiz UI are open). Cloud Run IAM grants `allUsers` → `roles/run.invoker` (auth is app-level, not IAM-level). Configured via `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`SERVICE_URL`/`ALLOWED_EMAILS` env vars on the container. `allowed_emails` (terraform var) restricts to specific Google accounts; unset = allow all. Requires a pre-created OAuth consent screen + credentials in GCP Console, with redirect URI `{SERVICE_URL}/auth/callback`.

## Notes

- `terraform.tfvars` and `terraform.tfstate*` must stay gitignored.
- `max_instance_count = 1` on Cloud Run must not change (would allow concurrent SQLite writers).
- The GCS bucket has `prevent_destroy` — survives `terraform destroy`.
