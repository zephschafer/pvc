# dcf Core Limitations Tracker

Last updated: 2026-05-14 | Total findings: 59 | Open: 5 | Fixed: 54

## Severity Definitions

| Level | Definition |
|-------|-----------|
| **Blocking** | This type of collector cannot be built at all with dcf in its current form |
| **Major** | Collector can be built but produces wrong, incomplete, or unreliable output |
| **Minor** | Collector works correctly but the experience is rough (errors, confusion, extra steps) |
| **Enhancement** | Works, but a feature addition would make it significantly better |

## Category Definitions

| Category | Definition |
|----------|-----------|
| **Schema** | The YAML schema cannot express what's needed (new model fields needed) |
| **Runtime** | The engine fails, produces wrong output, or behaves unexpectedly at execution time |
| **Skill** | The `new-collector` Claude skill gives wrong guidance, misses a step, or is unclear |
| **MCP** | An MCP tool fails, returns wrong data, or lacks a needed capability |
| **UX** | Error messages are unhelpful, CLI output is confusing, docs are wrong |
| **Performance** | Correct behavior but unacceptably slow or resource-intensive |

---

## Open Findings

| ID | Severity | Category | Summary | Scenario |
|----|----------|----------|---------|----------|
| F-046 | Minor | UX | No actionable guidance when `ZONE_RESOURCE_POOL_EXHAUSTED` — raw Terraform error surfaced with no suggestion to retry in another zone | streaming-deployment |
| F-047 | Minor | UX | `features/batch-deployment.md` line 55 and scenario criterion "dcf deploy without catalog: gcp exits with clear error" are stale — behavior changed in commit `08faf16` when `catalog: local` was routed to local Docker deployment instead of erroring | batch-deployment |
| F-048 | Minor | UX | Local Docker deployment (`local_deploy.py`, commit `08faf16`) has no feature file in `features/`; `FEATURES.md` registry is incomplete and requirements/acceptance criteria are undocumented | batch-deployment |
| F-049 | Minor | UX | `sa_email` is required by `_require_gcp_config()` for `dcf deploy` (GCP path) but is not listed in the batch-deployment scenario notes as a required project.yml field; tester must manually discover and populate it | batch-deployment |
| F-059 | Minor | UX | `dcf undeploy` (local) does not tear down the Airflow stack when no DAGs remain — user must manually run `docker compose down` after the last undeploy. GCP path correctly destroys Airflow when no DAG files exist in GCS; local path has no equivalent check. | batch-deployment-local |

---

## Fixed Findings

| ID | Summary | Fixed In | Notes |
|----|---------|----------|-------|
| F-058 | Airflow REST API auth backend not configured in docker-compose — all `/api/v1/` calls returned 401 | `dcf/infra/modules/templates/docker-compose.yml.tftpl` — added `AIRFLOW__API__AUTH_BACKENDS: airflow.api.auth.backend.basic_auth` to shared env block | batch-deployment-local |
| F-057 | `DockerOperator` `volumes` parameter removed in `apache-airflow-providers-docker` 3.x — DAG import failed with `Invalid arguments: volumes` | `dcf/local_deploy.py` — `_local_dag_content()` switched to `mounts=[Mount(...)]` with `from docker.types import Mount` | batch-deployment-local |
| F-056 | Airflow webserver hard-coded to port 8080 — conflicts with other services (e.g., spark-iceberg) | `airflow_local/variables.tf` — new `webserver_port` variable (default 8090); `airflow_local/outputs.tf` and `docker-compose.yml.tftpl` use the variable | batch-deployment-local |
| F-055 | docker-compose `command: version` + `entrypoint: >` YAML conflict — bash received flags as positional args, causing `command not found` errors | `dcf/infra/modules/templates/docker-compose.yml.tftpl` — `airflow-init` switched to list-form entrypoint with `>-` folded scalar; `command:` removed | batch-deployment-local |
| F-054 | Airflow 2.10+ base image blocks `pip install` when run as root — build failed with `You are running pip as root` | `dcf/infra/modules/templates/airflow.Dockerfile.tftpl` — removed `USER root` / `USER airflow` wrapper; pip runs as default `airflow` user | batch-deployment-local |
| F-053 | Airflow base image tag `2.9-python3.12` does not exist on Docker Hub — short `major.minor-pythonX.Y` tags are not published | `dcf/infra/modules/templates/airflow.Dockerfile.tftpl` — updated to `apache/airflow:2.10.4-python3.12` | batch-deployment-local |
| F-052 | Terraform `path.module` resolves to `.` in copied work dirs — `templatefile()` calls failed with "no file exists at ./../templates/..." | `dcf/local_deploy.py` and `dcf/gcp/batch_deploy.py` — added `_copy_templates_to_work_dir(work_dir)` helper; called in all 4 TF apply functions; all module paths changed to `${path.module}/templates/` | batch-deployment-local |
| F-051 | `tests/test_deploy_cli.py` `test_deploy_requires_gcp_catalog` asserted `catalog: local` errors — behavior changed when local deploy was added | `tests/test_deploy_cli.py` — replaced stale test with `test_deploy_local_catalog_routes_to_local_deploy` and `test_deploy_no_args_deploys_all` | batch-deployment-local |
| F-050 | `gcp/batch_collector/main.tf` named Cloud Run job `"pvc-job-${var.collector_name}"` — stale prefix from before project rename | `dcf/infra/modules/gcp/batch_collector/main.tf` — renamed to `"dcf-job-${var.collector_name}"` | batch-deployment-gcp |
| F-045 | `dcf gcp setup` did not grant `roles/dataflow.worker` — workers failed with cryptic IAM error on job startup | `dcf/infra/modules/gcp/main.tf` — added `google_project_iam_member` resource granting `roles/dataflow.worker` to the SA | |
| F-044 | Wrong Dockerfile base image for Flex Template — `python:3.12-slim` has no `/opt/google/dataflow/python_template_launcher`; job fails at startup | `gcp/streaming_deploy.py` — changed to `gcr.io/dataflow-templates-base/python312-template-launcher-base` with `ENV FLEX_TEMPLATE_PYTHON_PY_FILE` instead of `ENTRYPOINT` | |
| F-043 | `google_dataflow_flex_template_job` not in GA Terraform provider — `hashicorp/google` does not support this resource type | `dcf/infra/modules/gcp/streaming_collector/main.tf` — switched `required_providers` to `hashicorp/google-beta ~> 5.0`; added `provider = google-beta` on the resource | |
| F-042 | `dcf undeploy` would call `terraform destroy` (cancel) not drain on a Dataflow job | `infra/modules/gcp/streaming_collector/main.tf` — `on_delete = "drain"` on the `google_dataflow_flex_template_job` resource; Terraform handles the drain automatically | |
| F-041 | No Beam runner code in dcf — no collector to read from Pub/Sub, project, and write windowed Parquet to GCS | New `dcf/gcp/beam_runner.py` — `ReadFromPubSub → project_message → FixedWindows → WriteToParquet` Beam collector; runs as Dataflow Flex Template entrypoint | |
| F-040 | No `streaming_collector` Terraform module — batch module only provisions `google_cloud_run_v2_job` | New `dcf/infra/modules/gcp/streaming_collector/` — `google_dataflow_flex_template_job` with `on_delete = "drain"` | |
| F-039 | `dcf deploy` could not load or route streaming collectors | `dcf/cli.py` — `deploy` and `undeploy` commands route by `collector.deployment.type`; `deploy-status` and confirm messages are streaming-aware | |
| F-038 | `Deploy` model required `schedule` (cron); no `type` or `window_seconds` fields | `dcf/config/models.py` — `Deploy.type: Literal["batch","streaming"] = "batch"`, `schedule` optional (required only for batch), `window_seconds: int = 60` added | |
| F-037 | `source.type: pubsub` not recognized — `Source` union only accepted `http` and `python` | `dcf/config/models.py` — new `PubSubSource` model with `subscription: str`; added to `Source` union; Collector validator enforces `strategy: append` for streaming | |
| F-035 | Generated DAG used `CloudRunJobOperator` which doesn't exist in `apache-airflow-providers-google` for Composer 3 / Airflow 2.11; correct name is `CloudRunExecuteJobOperator` | `gcp/batch_deploy.py` — `_dag_content()` updated to import and use `CloudRunExecuteJobOperator` | |
| F-033 | `dcf deploy` failed with "No Cloud Composer environments found" when no environment pre-existed | `gcp/batch_deploy.py` — `_find_or_create_composer_env()` auto-provisions `dcf-composer` with `--async` + polls every 30s until RUNNING; `undeploy` uses new `_describe_composer_dag_bucket()` helper | |
| F-034 | Cloud Run container exited immediately (`JAVA_GATEWAY_EXITED`) because `runner.py` unconditionally started Spark even when `catalog=gcp`; `python:3.12-slim` has no JVM | `engine/runner.py` — GCS path skips Spark init; `spark.stop()` guarded by `if spark is not None` | `0685e72` |
| F-001 | Spark startup WARN noise obscured dcf output | `spark_session.py` — fd-level stderr redirect + `spark.driver.host=127.0.0.1` | |
| F-002 | No `namespace` field; namespace always equalled collector name | `models.py` + `writer/iceberg.py` — optional `namespace` field with fallback to `collector.name` | |
| F-003 | Array-valued fields (e.g. `topics`) could not be projected | `models.py` + `transforms.py` — new `array_join` transform | 7 unit tests in `tests/test_transforms.py` |
| F-004 | `records_path` on top-level array silently returned 0 rows | `engine/fetcher.py` — raises `ValueError` with actionable message | 3 unit tests in `tests/test_fetcher.py` |
| F-005 | No warehouse path printed after successful run | `engine/runner.py` — appended `→ <path>` to completion line | |
| F-006 | `new-collector` skill had no guidance on credential creation, token scopes, or storage | Added credential section to `new-collector.md` — covers env vars, project.yml storage, auth type selection | |
| F-007 | `dcf init` hardcoded to Portland Maps — no general credential collection | `cli.py` — removed Portland Maps/regions prompts; init now only sets catalog, prints key storage instructions | |
| F-008 | `dcf validate` passed silently when `{{ env.VAR }}` was unset | `cli.py` — validate now scans YAML for env refs and warns on any that are missing | |
| F-009 | HTTP 401/403 gave raw `requests.HTTPError` with no guidance | `engine/fetcher.py` — 401/403/404/429 now surface with human-readable message + actionable hint | |
| F-010 | Bearer auth required a `key` field that the fetcher never used | `config/models.py` — `Auth.key` is now optional for bearer; required only for query_param/header | |
| F-011 | Terraform `.tf` files missing from dcf repository | `dcf/infra/modules/gcp/main.tf` + `variables.tf` created | |
| F-012 | `append` and `full_refresh` with `catalog: gcp` used unconfigured Spark GCS catalog | `writer/iceberg.py` — all three strategies now route through `_append_gcs`/`_overwrite_gcs`/`_upsert_gcs`; Spark bypassed entirely for GCS | |
| F-013 | `warehouse_reader.py` read only local warehouse — GCS not supported | `warehouse_reader.py` rewritten: GCS blobs downloaded via `google-cloud-storage`, registered as Arrow tables via `conn.register()` | DuckDB 1.5.2 has no GCS extension; approach avoids it entirely |
| F-014 | Billing-not-enabled 403 had no actionable guidance; traceback saved to project.yml | `gcp/bootstrap.py` + `cli.py` — billing error now raises with billing console URL; project.yml stores `str(e)` not traceback | |
| F-015 | No `dcf gcp teardown` command | `cli.py` — added `dcf gcp teardown`; `terraform.py` — added `destroy()`; `bootstrap.py` — added `delete_secret` + `delete_service_account` | |
| F-016 | README GCP section missing Terraform, billing, and API prerequisites | `README.md` — added GCP prerequisites section with required APIs and setup commands | |
| F-017 | `bootstrap.py` hardcoded `quipu-lake` as SA ID and secret name | `gcp/bootstrap.py` — renamed to `dcf-lake` throughout | |
| F-018 | `list_warehouse_tables` only shows GCS tables when `catalog: gcp` | `warehouse_reader.py` — _iter_local_tables() helper; list_tables() now shows both GCS (location='gcs') and local-only (location='local') | `2f5d057` |
| F-019 | `query_warehouse` auto-LIMIT wrapping broke COPY/DDL with cryptic parse error | `warehouse_reader.py` — _is_write_statement() detects write prefixes; DDL bypasses wrapping | `2f5d057` |
| F-020 | No `materialize_model` MCP tool — model persistence required workarounds | `warehouse_reader.py` + `mcp_server.py` — new materialize_model() writes result Parquet locally and uploads to GCS when catalog=gcp | `2f5d057` |
| F-021 | Querying local-only table in GCP mode gave cryptic DuckDB CatalogException | `warehouse_reader.py` — _resolve_table_refs() now falls back to local read_parquet() for tables not in GCS | `2f5d057` |
| F-022 | MCP `run_collector` ignored `catalog: gcp` — always wrote to local warehouse | `mcp_server.py` — reads `_project_config().get("catalog", "local")` before calling runner | `c8ea972` |
| F-023 | Connector exceptions showed only `fetch error: {e}` — no traceback, no failure summary | `runner.py` — adds exception class, full traceback (indented), and 3-state completion line (complete / complete with errors / FAILED) | `a1041e0` |
| F-024 | `new-collector` skill missing decision guidance on when to use `type: python` vs `type: http` | `new-collector.md` — added decision table with GraphQL, cursor pagination, and HTML scraping as explicit python triggers; quick rule of thumb | `11cdd85` |
| F-025 | `new-collector` skill didn't document auth pattern for Python connectors — `PythonSource` has no `auth` field | `new-collector.md` — added "auth pattern" section under `type: python` showing how to pass key as static param with `{{ env.VAR }}` and read from `dynamic_params` | |
| F-030 | `deployment:` block in collector YAML silently ignored by `dcf validate` — invalid cron expressions passed without error | `config/models.py` — added `Deploy` model with cron validator; `Collector.deploy` optional field; `cli.py` validate now shows clean error on `ValidationError`; also fixed `from_dict` dict-mutation bug | |
| F-031 | `dcf deploy` and `dcf undeploy` CLI commands did not exist | `cli.py` — added `dcf deploy <name>`, `dcf undeploy <name>`, `dcf deploy-status [<name>]`; `gcp/batch_deploy.py` — orchestration: Cloud Build image, Cloud Run job, Composer DAG upload | |
| F-032 | `gcloud builds submit` in batch_deploy.py missing `--project` — used active gcloud config project instead of `gcp.project_id` from project.yml, causing 400 HTTPError | `gcp/batch_deploy.py` — added `"--project", project_id` to `gcloud builds submit` subprocess call | |
| F-026 | `dcf gcp setup` failed on re-run — Terraform 409 when warehouse bucket already exists | `gcp/terraform.py` — `_import_existing_resources()` checks GCS before apply and runs `terraform import` if bucket already exists; idempotent on re-run | |
| F-027 | `dcf gcp teardown` reported "GCP resources destroyed" even when all steps were skipped | `cli.py` — teardown now tracks which resources were actually destroyed and prints accurate summary or "No GCP resources were found to destroy" | |
| F-028 | `setup_error` in project.yml contained raw ANSI terminal escape codes | `cli.py` — added `_ANSI_RE` pattern; strips escape codes from error string before writing to project.yml | |
| F-029 | `new-collector` skill had no mention of `catalog: gcp`, `dcf gcp setup`, or `dcf deploy` | `new-collector.md` — added Step 10 covering GCP prerequisites, required APIs, `deployment:` block syntax, and `dcf deploy`/`dcf undeploy` commands | |

---

## By Design

| ID | Summary | Rationale |
|----|---------|-----------|
| — | No by-design decisions yet | — |
