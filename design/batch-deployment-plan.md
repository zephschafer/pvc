# Implementation Plan: Batch Collector Deployment

**Design:** [`design/batch-deployment.md`](./batch-deployment.md)
**Feature:** [`features/batch-deployment.md`](../features/batch-deployment.md)
**Created:** 2026-05-14
**Phases:** 5
**Status:** Draft

---

## Overview

This plan replaces two Python-only deploy implementations (`local_deploy._build_batch_image()` and `batch_deploy._build_image()` + `_find_or_create_composer_env()`) with declarative Terraform modules that manage the full lifecycle — container build, deployment, and Airflow orchestration — for both local and GCP targets. DAGs are written as files to a mounted directory rather than baked into an image, so adding or removing collectors does not require restarting Airflow. The test vehicle throughout is the `github_repos` collector (HTTP, bearer auth, append strategy, six columns — the simplest existing collector).

Phases 1–3 are local-only and require no GCP credentials. Phases 4–5 require a live GCP project. The primary risks are Terraform `null_resource` trigger behavior (ensure content_hash actually causes a re-run), Cloud SQL provisioning time (~5–10 minutes on first deploy), and the Docker socket mount on Mac (verify the path is correct for Docker Desktop).

---

## Phase 1: Module Foundations

**Goal:** The shared Dockerfile template and `batch_collector_local/` Terraform module exist and pass `terraform validate`.

**Testable without completing later phases:** Yes — `terraform validate` and `terraform plan` are sufficient.

### Files

| File | Action | What to implement |
|------|--------|-------------------|
| `dcf/infra/modules/templates/batch_collector.Dockerfile.tftpl` | Create | Terraform template. Base image `python:3.12-slim`. Conditional Java block using `%{ if java_enabled ~}...%{ endif ~}` that installs `openjdk-21-jre-headless` when true. Then: `WORKDIR /app`, `COPY pyproject.toml .`, `COPY dcf/ ./dcf/`, `RUN pip install --no-cache-dir -e .`, `COPY collectors/ ./collectors/`, `COPY connectors/ ./connectors/`, `COPY project.yml .`, `ENV PIPELINE_NAME=""`, `CMD ["sh", "-c", "dcf run $PIPELINE_NAME"]` |
| `dcf/infra/modules/batch_collector_local/variables.tf` | Create | Five variables: `collector_name` (string), `build_context` (string — absolute path to the stable build dir), `image_tag` (string, e.g. `dcf-local/github_repos:latest`), `content_hash` (string — SHA256 trigger), `java_enabled` (bool, default `true`) |
| `dcf/infra/modules/batch_collector_local/main.tf` | Create | Two resources: (1) `local_file.dockerfile` — uses `templatefile("${path.module}/../../templates/batch_collector.Dockerfile.tftpl", { java_enabled = var.java_enabled })`, writes to `"${var.build_context}/Dockerfile"`. (2) `null_resource.build` — `depends_on = [local_file.dockerfile]`, `triggers = { content_hash = var.content_hash }`, `provisioner "local-exec"` running `docker build -t ${var.image_tag} ${var.build_context}`. Requires only `hashicorp/null` and `hashicorp/local` providers (no google provider). |
| `dcf/infra/modules/batch_collector_local/outputs.tf` | Create | Single output `image_tag` with value `var.image_tag` |

### Implementation Notes

**Template syntax:** Terraform template files use `${ }` for variable interpolation and `%{ if condition ~}...%{ endif ~}` for conditionals. The `~}` strips trailing whitespace. The `java_enabled` variable must match the Terraform bool type exactly — pass it as a bool in `templatefile()`, not a string.

**Provider requirements:** `batch_collector_local/` must NOT declare the `google` provider. Declare only `required_providers { null = { source = "hashicorp/null" }, local = { source = "hashicorp/local" } }`. This is critical — the google provider initialization requires GCP credentials and would break the local-only target.

**Template path:** `"${path.module}/../../templates/batch_collector.Dockerfile.tftpl"` — `path.module` resolves to the directory containing the `.tf` file being evaluated, so from `batch_collector_local/main.tf` this resolves to `dcf/infra/modules/templates/`.

**null_resource trigger:** The `content_hash` trigger causes `null_resource.build` to re-run when the hash changes. Without a trigger, Terraform would only run the provisioner on first `apply`. The hash must be passed consistently — if Python changes the hash computation, it causes a rebuild regardless of actual file changes.

### Done When

- [ ] `terraform validate` succeeds in `dcf/infra/modules/batch_collector_local/`
- [ ] `terraform plan` with a test tfvars file shows `local_file.dockerfile` and `null_resource.build` would be created
- [ ] The `templates/` directory exists and `batch_collector.Dockerfile.tftpl` renders correctly with `java_enabled=true` (includes the apt-get Java install line) and `java_enabled=false` (no apt-get line)

### Test Scenario

`testing/scenarios/batch-deployment-local.md` — Phase 1

---

## Phase 2: Local Collector Deploy via Terraform

**Goal:** `dcf deploy github_repos` with `catalog: local` builds the collector Docker image via the new Terraform module and writes a DAG file to `~/.dcf/airflow/dags/`. `dcf undeploy github_repos` runs `terraform destroy` and deletes the DAG file. Hard cutover — `_build_batch_image()` is deleted.

**Testable without completing later phases:** Yes — the image builds and the DAG file is written even before Airflow exists.

### Files

| File | Action | What to implement |
|------|--------|-------------------|
| `dcf/local_deploy.py` | Modify | Delete `_build_batch_image()`. Rewrite `_deploy_batch()`: (1) call `_sync_build_context(project_root, collector_name)` to create a stable dir at `~/.dcf/build/local/<name>/` with dcf source + pyproject.toml + collectors/<name>.yml + connectors/ + minimal `project.yml` stub (`catalog: local\n`); (2) compute `content_hash` over synced files; (3) call `_tf_apply_local_collector(collector_name, build_context, image_tag, content_hash)`; (4) call `_write_local_dag(collector_name, schedule, paused, image_tag, warehouse_path)` to write DAG file to `~/.dcf/airflow/dags/<name>.py`. Rewrite `_undeploy_batch()`: call `_tf_destroy_local_collector(collector_name)` then delete `~/.dcf/airflow/dags/<name>.py` if it exists. |
| `dcf/local_deploy.py` | Modify | Add `_sync_build_context(project_root, collector_name) -> Path`: creates `~/.dcf/build/local/<collector_name>/`, uses `shutil.copytree` with `dirs_exist_ok=True` for `dcf/` source and subdirs, copies `pyproject.toml`, writes minimal `project.yml`. Returns the Path. |
| `dcf/local_deploy.py` | Modify | Add `_content_hash(build_context: Path) -> str`: iterates `sorted(build_context.rglob("*"))`, skips `Dockerfile` (written by Terraform, not by Python), reads each file's bytes, accumulates into `hashlib.sha256()`, returns hexdigest. |
| `dcf/local_deploy.py` | Modify | Add `_tf_apply_local_collector(collector_name, build_context, image_tag, content_hash)`: mirrors `batch_deploy._terraform_apply_collector()` — creates work dir at `~/.dcf/terraform/collectors/<name>/local/`, copies `.tf` files from `dcf/infra/modules/batch_collector_local/`, writes `terraform.tfvars.json`, runs `terraform init` then `terraform apply -auto-approve`. Uses the same `_tf_env()` pattern (TF_INPUT=0, plugin cache). |
| `dcf/local_deploy.py` | Modify | Add `_tf_destroy_local_collector(collector_name)`: creates same work dir, copies same `.tf` files, runs `terraform init` then `terraform destroy -auto-approve`. After destroy, call `shutil.rmtree(work_dir)` to remove state. |
| `dcf/local_deploy.py` | Modify | Add `_local_dag_content(collector_name, schedule, paused, image_tag, warehouse_path) -> str`: returns a Python string that is a valid Airflow DAG using `DockerOperator`. Import: `from airflow.providers.docker.operators.docker import DockerOperator`. DAG uses `schedule_interval=schedule`, `is_paused_upon_creation=paused`, task uses `image=image_tag`, `environment={"PIPELINE_NAME": collector_name}`, `volumes=[f"{warehouse_path}:/app/warehouse"]`, `docker_url="unix:///var/run/docker.sock"`, `auto_remove="success"`. |
| `dcf/local_deploy.py` | Modify | Add `_write_local_dag(collector_name, schedule, paused, image_tag, warehouse_path)`: creates `~/.dcf/airflow/dags/` if needed, writes `_local_dag_content(...)` to `~/.dcf/airflow/dags/<collector_name>.py`. |
| `dcf/cli.py` | Modify | Update `deploy()`: support no-arg call — if `collector_name` is `None`, scan `collectors/` dir for all YAMLs with a `deploy:` block, deploy each independently (continue on failure, collect errors), print per-collector summary, exit non-zero if any failed. Make `collector_name` an `Optional[str]` arg with `typer.Argument(default=None)`. |
| `dcf/cli.py` | Modify | Update `undeploy()`: change confirmation text from Composer-specific wording to `"Remove collector '{name}' deployment and stop its scheduling?"`. Update routing: local batch uses new `local_deploy.undeploy()` which calls `_tf_destroy_local_collector` + DAG delete. Remove any stale Composer-specific messaging. |
| `tests/test_deploy_cli.py` | Modify | Update `test_deploy_requires_gcp_catalog`: `catalog: local` is now VALID for `dcf deploy`. Change this test to verify that `catalog: local` routes to local deploy (mock `local_deploy.deploy` and assert it is called). Add a new test `test_deploy_no_args_deploys_all` that creates two collectors with `deploy:` blocks and asserts both are deployed when `dcf deploy` is called with no args. |

### Implementation Notes

**`_sync_build_context` sync strategy:** Use `shutil.copytree(src, dst, dirs_exist_ok=True)` for directories. For individual files (`pyproject.toml`), use `shutil.copy2`. This overwrites stale files but does not delete files that have been removed from source. For correctness, wipe and recreate the stable dir on each deploy: `shutil.rmtree(build_context, ignore_errors=True)` then `build_context.mkdir(parents=True)`.

**Stable build context path:** `Path.home() / ".dcf" / "build" / "local" / collector_name`. This persists across deploys so Terraform can track the Dockerfile it wrote previously.

**`_content_hash` skips Dockerfile:** The Dockerfile is written by Terraform's `local_file.dockerfile`. If Python's hash included it, the hash would be stale before Terraform writes it. Hash only the files Python controls: dcf source, pyproject.toml, collector YAMLs, connectors, project.yml stub.

**`image_tag` format:** `f"dcf-local/{collector_name}:latest"` — matches the existing convention in `local_deploy.py`.

**`warehouse_path` for DAG:** Use `str(project_root / "warehouse")` — the absolute host path that Docker will volume-mount into the collector container. The DockerOperator runs on the host's Docker daemon, so this must be an absolute host path.

**Terraform work dir vs. module dir:** The Terraform module lives in `dcf/infra/modules/batch_collector_local/`. The work dir (where state is kept) lives at `~/.dcf/terraform/collectors/<name>/local/`. The Python function copies `.tf` files from module dir to work dir (same pattern as `batch_deploy._terraform_apply_collector()`). This keeps state in `~/.dcf/` and keeps the source module clean.

**Stale test fix:** `test_deploy_requires_gcp_catalog` (line 51 of `test_deploy_cli.py`) currently asserts exit code 1 and `"catalog is not 'gcp'"` — this is the old behavior. Mock `local_deploy.deploy` to return a dummy state dict and assert it is called. The new test for no-args should create two collector YAMLs and mock `local_deploy.deploy` to assert it is called twice.

### Done When

- [ ] `dcf deploy github_repos` with `catalog: local` in project.yml runs `terraform apply`, builds `dcf-local/github_repos:latest`, exits 0
- [ ] `docker images | grep dcf-local/github_repos` shows the image after deploy
- [ ] `~/.dcf/airflow/dags/github_repos.py` exists after deploy and contains a `DockerOperator` DAG
- [ ] `~/.dcf/terraform/collectors/github_repos/local/terraform.tfstate` exists
- [ ] `dcf undeploy github_repos` runs `terraform destroy`, removes `~/.dcf/airflow/dags/github_repos.py`, exits 0
- [ ] `docker images | grep dcf-local/github_repos` returns empty after undeploy
- [ ] `~/.dcf/terraform/collectors/github_repos/local/` directory is removed after undeploy
- [ ] `dcf deploy` (no args, two collectors with `deploy:` blocks) deploys both; exits non-zero if either fails
- [ ] `pytest tests/test_deploy_cli.py` passes (with updated tests)

### Test Scenario

`testing/scenarios/batch-deployment-local.md` — Phases 1–2

---

## Phase 3: Local Airflow Stack

**Goal:** `dcf deploy github_repos` with `catalog: local` also starts a local Airflow Docker Compose stack. The Airflow scheduler reads DAGs from `~/.dcf/airflow/dags/`. The `github_repos` DAG appears in the Airflow UI and can be triggered to run the collector container.

**Testable without completing later phases:** Yes — requires only local Docker and the `github_repos` image from Phase 2.

### Files

| File | Action | What to implement |
|------|--------|-------------------|
| `dcf/infra/modules/templates/airflow.Dockerfile.tftpl` | Create | Based on `apache/airflow:2.9-python3.12`. Two sections: (1) `USER root` block to install the target-specific provider: `%{ if target == "local" ~}RUN pip install apache-airflow-providers-docker%{ else ~}RUN pip install apache-airflow-providers-google%{ endif ~}`. (2) `USER airflow` to restore non-root user. No DAG files are copied in — DAGs are mounted at runtime. |
| `dcf/infra/modules/templates/docker-compose.yml.tftpl` | Create | Four services: `postgres` (image: `postgres:15`, healthcheck: `pg_isready -U airflow`), `airflow-init` (runs `db migrate` then creates admin user via `_AIRFLOW_WWW_USER_*` env vars, `depends_on` postgres healthy), `airflow-scheduler` (depends on init completing, mounts `${dag_dir}:/opt/airflow/dags:ro` and `${docker_socket}:/var/run/docker.sock`, env `AIRFLOW__CORE__EXECUTOR: LocalExecutor`, `AIRFLOW__SCHEDULER__DAG_DIR_LIST_INTERVAL: "30"`), `airflow-webserver` (port 8080, healthcheck: curl `/health`). All services share env vars `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` and `AIRFLOW__CORE__FERNET_KEY`. One named volume `postgres_data`. |
| `dcf/infra/modules/airflow_local/variables.tf` | Create | Variables: `image_tag` (string, e.g. `dcf-airflow:latest`), `dag_dir` (string, absolute path to `~/.dcf/airflow/dags/`), `warehouse_path` (string, absolute path for DockerOperator volume mounts), `docker_socket` (string, default `unix:///var/run/docker.sock`), `db_password` (string, sensitive), `admin_password` (string, sensitive), `fernet_key` (string, sensitive) |
| `dcf/infra/modules/airflow_local/main.tf` | Create | Four resources: (1) `local_file.dockerfile` — renders `airflow.Dockerfile.tftpl` with `target = "local"`, writes to `${var.build_context}/Dockerfile`. Actually simpler: bake `target` into the module as `"local"` literal — no variable needed. (2) `null_resource.build` — triggers on Airflow Dockerfile content hash, runs `docker build -t ${var.image_tag} ${var.build_context}`. (3) `local_file.compose` — renders `docker-compose.yml.tftpl` with all variable values, writes to `~/.dcf/airflow/docker-compose.yml`. (4) `null_resource.up` — `depends_on = [local_file.compose, null_resource.build]`, runs `docker compose -f ${path to compose file} up -d --wait`. No google provider. |
| `dcf/infra/modules/airflow_local/outputs.tf` | Create | `webserver_url` = `"http://localhost:8080"`, `compose_file` = path to generated docker-compose.yml |
| `dcf/local_deploy.py` | Modify | Add `_airflow_build_context() -> Path`: creates `~/.dcf/build/airflow-local/`, ensures it exists (no files needed — Dockerfile is written by Terraform). Returns the path. |
| `dcf/local_deploy.py` | Modify | Add `_generate_airflow_credentials(project_root: Path) -> dict`: reads `project.yml`, extracts `airflow_admin_password` (raise clear error if absent), extracts `airflow_fernet_key` (auto-generate via `Fernet.generate_key().decode()` if absent, write back to `project.yml`). Returns `{"db_password": "airflow", "admin_password": ..., "fernet_key": ...}`. |
| `dcf/local_deploy.py` | Modify | Add `_tf_apply_airflow_local(dag_dir, warehouse_path, credentials) -> dict`: creates work dir at `~/.dcf/terraform/airflow/local/`, copies TF files from `dcf/infra/modules/airflow_local/`, writes tfvars.json, runs `terraform init` + `terraform apply`. Returns Terraform outputs as dict. |
| `dcf/local_deploy.py` | Modify | Update `_deploy_batch()`: after calling `_write_local_dag()`, call `_generate_airflow_credentials()` then `_tf_apply_airflow_local()`. Print the webserver URL from outputs. Update `project.yml` `airflow` key with `{"url": "http://localhost:8080", "deployed_at": ...}`. |
| `dcf/cli.py` | Modify | Update `deploy()` success output for local batch to print the Airflow URL: `"  Airflow UI: http://localhost:8080"` |

### Implementation Notes

**Airflow build context for local module:** The `airflow_local/` module needs a build context directory (for `docker build`). Since the Airflow image has no user-specific files (no DAGs baked in), the build context can be a small stable directory at `~/.dcf/build/airflow-local/` that only contains the Dockerfile written by Terraform. The `content_hash` for the Airflow null_resource trigger should be based on the Dockerfile template content — if the template changes, rebuild; if it doesn't, skip.

**`docker compose up -d --wait`:** The `--wait` flag blocks until all services are healthy. This ensures Airflow is ready before `dcf deploy` returns. If `--wait` is not supported (older Docker Compose versions), use `--wait` with a timeout or poll the health endpoint. Note this as a Known Complexity in the scenario.

**`airflow-init` vs. `airflow standalone`:** The design calls for `airflow standalone`, but Docker Compose works better with explicit service separation. `airflow standalone` runs everything in one process, while the Compose file runs separate containers. This is an improvement over `airflow standalone` for local — better failure isolation. If we use `airflow standalone`, it can be a single service: `command: standalone`. Both approaches work; the Compose multi-service approach is more robust. Decide during implementation.

**Fernet key generation:** Requires `cryptography` package (already a transitive dependency of Airflow). Generate with: `from cryptography.fernet import Fernet; key = Fernet.generate_key().decode()`.

**`airflow_admin_password` missing:** If not in `project.yml`, raise a `RuntimeError` with a clear message: `"airflow_admin_password is missing from project.yml. Add it before running dcf deploy."` — do not auto-generate it (users need to know their Airflow password).

**`db_password`:** Use a fixed value `"airflow"` for the local Postgres container — this is a local dev-only DB not exposed to the network, so security is not a concern. No need to read from `project.yml`.

### Done When

- [ ] `dcf deploy github_repos` (local) exits 0 and prints `"Airflow UI: http://localhost:8080"`
- [ ] `docker compose -f ~/.dcf/airflow/docker-compose.yml ps` shows all services running
- [ ] `http://localhost:8080` returns the Airflow UI (login: admin / project.yml password)
- [ ] The `github_repos` DAG is visible in the Airflow UI
- [ ] Manually triggering the DAG via the UI runs the collector container and writes Parquet to `./warehouse/`
- [ ] `dcf undeploy github_repos` removes the DAG file; Airflow no longer shows the DAG after ~30s (without restarting Airflow)
- [ ] Second `dcf deploy github_repos` is idempotent — Airflow stack does not restart; only the DAG file is refreshed

### Test Scenario

`testing/scenarios/batch-deployment-local.md` — Phases 3–5

---

## Phase 4: GCP Collector Container via Terraform

**Goal:** `dcf deploy github_repos` with `catalog: gcp` builds the collector container via Terraform (`null_resource` + `gcloud builds submit`), creates the Cloud Run job, and writes the DAG file to `gs://<warehouse-bucket>/airflow/dags/github_repos.py`. Cloud Composer is not used. No Airflow stack yet.

**Testable without completing later phases:** Yes — the Cloud Run job exists and can be triggered manually; the DAG file is in GCS.

### Files

| File | Action | What to implement |
|------|--------|-------------------|
| `dcf/infra/modules/gcp/batch_collector/main.tf` | Modify | Remove `google_storage_bucket_object.dag` resource. Add `local_file.dockerfile`: renders `batch_collector.Dockerfile.tftpl` with `java_enabled = var.java_enabled`, writes to `"${var.build_context}/Dockerfile"`. Add `null_resource.build`: `depends_on = [local_file.dockerfile]`, `triggers = { content_hash = var.content_hash }`, `provisioner "local-exec"` runs `gcloud builds submit --project ${var.project_id} --region ${var.region} --tag ${var.image_uri} --timeout 600s ${var.build_context}`. Fix: rename `"pvc-job-${...}"` → `"dcf-job-${...}"` in `google_cloud_run_v2_job.collector`. Add required providers `hashicorp/local` and `hashicorp/null` alongside existing `hashicorp/google`. |
| `dcf/infra/modules/gcp/batch_collector/variables.tf` | Modify | Remove variables: `dag_bucket`, `dag_blob_name`, `dag_content`. Add variables: `build_context` (string), `content_hash` (string), `java_enabled` (bool, default `false`). Keep all existing variables. |
| `dcf/infra/modules/gcp/batch_collector/outputs.tf` | Modify | Remove `dag_blob_name` output. Keep `job_name` output. |
| `dcf/gcp/batch_deploy.py` | Modify | Remove functions: `_build_image()`, `_find_or_create_composer_env()`, `_parse_dag_path()`, `_dag_content()` (replace with standalone DAG writer). |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_sync_build_context(project_root: Path, collector_name: str) -> Path`: same logic as the local equivalent — creates `~/.dcf/build/gcp/<name>/`, syncs dcf source + pyproject.toml + collectors/<name>.yml + connectors/ + minimal GCP `project.yml` stub (`catalog: gcp\ngcp:\n  project_id: ...\n  region: ...\n  warehouse_bucket: ...`). Returns path. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_content_hash(build_context: Path) -> str`: SHA256 of all files in build context (excluding `Dockerfile`), same as local equivalent. |
| `dcf/gcp/batch_deploy.py` | Modify | Rewrite `_terraform_apply_collector()`: remove `dag_bucket`, `dag_blob_name`, `dag_content` from tfvars; add `build_context`, `content_hash`, `java_enabled=False`. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_gcp_dag_content(collector_name, schedule, paused, project_id, region, job_name) -> str`: returns the Airflow DAG Python string using `CloudRunExecuteJobOperator` (same logic as existing `_dag_content()` but renamed and kept as a Python function, not a Terraform variable). |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_write_dag_gcs(dag_content: str, collector_name: str, warehouse_bucket: str)`: uses `google.cloud.storage.Client` to upload `dag_content` as a blob at `airflow/dags/<collector_name>.py` in `warehouse_bucket`. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_delete_dag_gcs(collector_name: str, warehouse_bucket: str)`: deletes `airflow/dags/<collector_name>.py` from `warehouse_bucket` if it exists (no error if absent). |
| `dcf/gcp/batch_deploy.py` | Modify | Rewrite `deploy()`: (1) call `_sync_build_context()`, (2) `_content_hash()`, (3) `_terraform_apply_collector()`, (4) `_gcp_dag_content()`, (5) `_write_dag_gcs()`. Remove all Composer-related calls. |
| `dcf/gcp/batch_deploy.py` | Modify | Rewrite `undeploy()`: call `_terraform_destroy_collector()` then `_delete_dag_gcs()`. |
| `dcf/gcp/_collector_utils.py` | Modify | If any shared helpers (e.g., `_require_gcp_config()`) reference Composer or DAG bucket, remove those references. |

### Implementation Notes

**`pvc-job-` rename:** The existing state at `~/.dcf/terraform/collectors/<name>/gcp/terraform.tfstate` may already reference a Cloud Run job named `pvc-job-...`. Renaming the resource in `main.tf` will cause Terraform to try to destroy the old job and create a new one. This is correct behavior — the old name was wrong. The `_import_existing_cloud_run_job()` function will need to be updated to import with the new name `dcf-job-...`. Add a migration note to the scenario Known Complexity.

**`_ensure_artifact_registry_repo()`:** This function in `batch_deploy.py` ensures the Artifact Registry repo exists before Cloud Build pushes. It should remain as a Python call before `terraform apply`, not move into Terraform, since the repo is a project-level resource (not per-collector). Call it from `deploy()` before the Terraform step.

**GCP minimal `project.yml` stub:** The stub baked into the GCP collector image must include `gcp.warehouse_bucket` so `dcf run` inside the container can write to GCS. The container uses Workload Identity (the Cloud Run SA has Storage permissions) — no credentials file needed in the image.

**GCS DAG write:** Use `from google.cloud import storage; client = storage.Client(project=project_id); bucket = client.bucket(warehouse_bucket); blob = bucket.blob(f"airflow/dags/{collector_name}.py"); blob.upload_from_string(dag_content, content_type="text/plain")`. This requires `google-cloud-storage` which is already a dcf dependency.

**Terraform state migration:** If a developer has existing Terraform state for `batch_collector/` (from the Composer-based implementation), running `terraform apply` with the new module will see `google_storage_bucket_object.dag` in state but not in config — Terraform will plan to destroy it. This is correct behavior. Note it in the scenario.

### Done When

- [ ] `dcf deploy github_repos` (GCP) exits 0; no Composer calls anywhere in output
- [ ] `gcloud run jobs list --region <region>` shows `dcf-job-github-repos` (not `pvc-job-...`)
- [ ] `gsutil ls gs://<bucket>/airflow/dags/` shows `github_repos.py`
- [ ] `gsutil cat gs://<bucket>/airflow/dags/github_repos.py` contains `CloudRunExecuteJobOperator`
- [ ] `~/.dcf/terraform/collectors/github_repos/gcp/terraform.tfstate` shows `google_cloud_run_v2_job.collector`; no `google_storage_bucket_object.dag`
- [ ] `dcf undeploy github_repos` (GCP): Cloud Run job deleted, `gs://<bucket>/airflow/dags/github_repos.py` deleted
- [ ] `terraform show` after undeploy shows no managed resources; state dir removed

### Test Scenario

`testing/scenarios/batch-deployment-gcp.md` — Phases 1–2

---

## Phase 5: GCP Airflow Stack

**Goal:** `dcf deploy github_repos` with `catalog: gcp` also provisions a Cloud Run Airflow service with Cloud SQL PostgreSQL. The `github_repos` DAG appears in the Airflow UI via the GCS FUSE mount, is triggered on schedule by the Airflow scheduler, and executes the collector via `CloudRunExecuteJobOperator`.

**Testable without completing later phases:** N/A — this is the final phase.

### Files

| File | Action | What to implement |
|------|--------|-------------------|
| `dcf/infra/modules/gcp/airflow/variables.tf` | Create | Variables: `image_uri` (string), `content_hash` (string — hash of Airflow Dockerfile template, triggers rebuild on Airflow version change), `project_id`, `region`, `sa_email`, `warehouse_bucket` (string — GCS bucket where DAGs are stored at `airflow/dags/`), `db_password` (string, sensitive), `admin_password` (string, sensitive), `fernet_key` (string, sensitive) |
| `dcf/infra/modules/gcp/airflow/main.tf` | Create | Resources: (1) `local_file.dockerfile` — renders `airflow.Dockerfile.tftpl` with `target = "gcp"`. (2) `null_resource.build` — `gcloud builds submit --tag ${var.image_uri}` from build context. (3) `google_sql_database_instance.airflow_db` — `database_version = "POSTGRES_15"`, `settings { tier = "db-f1-micro" }`, `deletion_protection = false`. (4) `google_sql_database.airflow` — `name = "airflow"`, `instance = google_sql_database_instance.airflow_db.name`. (5) `google_sql_user.airflow` — `name = "airflow"`, `password = var.db_password`. (6) `google_cloud_run_v2_service.airflow` — `min_instance_count = 1`, execution environment `EXECUTION_ENVIRONMENT_GEN2`, volume mount from `warehouse_bucket` GCS bucket at `/opt/airflow/dags`, env vars for DB connection (`postgresql+psycopg2://airflow:<password>@/<db>?host=/cloudsql/<instance>` via Cloud SQL connector), fernet key, admin password. |
| `dcf/infra/modules/gcp/airflow/outputs.tf` | Create | `webserver_url` (from `google_cloud_run_v2_service.airflow.uri`), `service_name` |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_airflow_build_context(project_id, region) -> Path`: creates `~/.dcf/build/airflow-gcp/`, only needs a small dir (Dockerfile written by Terraform). Returns path. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_airflow_image_uri(project_id, region) -> str`: returns `f"{region}-docker.pkg.dev/{project_id}/dcf-runner/dcf-airflow:latest"`. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_generate_airflow_credentials(project_root: Path) -> dict`: reads `project.yml`, extracts `airflow_admin_password` (raise if absent), auto-generates `airflow_fernet_key` if absent + writes back to `project.yml`. Returns dict with `db_password` (auto-generated random string, written to `project.yml` as `airflow_db_password`), `admin_password`, `fernet_key`. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_tf_apply_airflow_gcp(build_context, image_uri, content_hash, gcp_config, credentials) -> dict`: creates work dir at `~/.dcf/terraform/airflow/gcp/`, copies TF files from `dcf/infra/modules/gcp/airflow/`, writes tfvars.json, runs `terraform init` + `terraform apply`. Returns outputs dict. |
| `dcf/gcp/batch_deploy.py` | Modify | Update `deploy()`: after `_write_dag_gcs()`, call `_generate_airflow_credentials()`, `_ensure_artifact_registry_repo()`, `_airflow_build_context()`, `_tf_apply_airflow_gcp()`. Add Airflow URL to returned state dict and print it. |
| `dcf/gcp/batch_deploy.py` | Modify | Add `_tf_destroy_airflow_gcp()`: mirrors destroy pattern from `_terraform_destroy_collector()` for the Airflow module. Called from `undeploy()` only if all collectors are undeployed (i.e., `airflow/dags/` prefix in GCS is empty after DAG deletion). |

### Implementation Notes

**Cloud SQL connectivity in Cloud Run:** The standard pattern for Cloud Run → Cloud SQL is the Cloud SQL Auth Proxy, or the newer direct VPC connector approach. The simplest for Terraform is to add the Cloud SQL instance connection name to the Cloud Run service as a `cloudsql_instance` in the `volumes` block and use the socket path (`/cloudsql/<connection-name>`). The DB connection string becomes `postgresql+psycopg2://airflow:<password>@/<db>?host=/cloudsql/<connection-name>`. Add this to the `google_cloud_run_v2_service` template.

**GCS FUSE mount in Cloud Run (gen2):** The Cloud Run service resource needs `volumes { name = "dags"; gcs { bucket = var.warehouse_bucket; read_only = true } }` and a corresponding `volume_mounts { name = "dags"; mount_path = "/opt/airflow/dags" }` in the container block. Only Cloud Run gen2 supports GCS FUSE mounts. Set `launch_stage = "BETA"` if required by the provider.

**Airflow Cloud Run container command:** The `dcf-airflow` Cloud Run service should run `airflow standalone` (single command that starts scheduler + webserver). The container port is 8080.

**Cloud SQL provisioning time:** First `terraform apply` for the `airflow/` module will take 5–10 minutes waiting for Cloud SQL. Print progress in Python before calling Terraform: `"  Provisioning Cloud SQL (this may take 5–10 minutes on first deploy)..."`. Subsequent applies are fast — Terraform confirms no changes needed.

**`airflow_db_password` auto-generation:** Generate with `secrets.token_urlsafe(16)` and write to `project.yml` as `airflow_db_password`. This is a one-time write — if the key already exists, use it. Do not regenerate on subsequent deploys (that would change the DB password and break the running Airflow).

**IAM for Cloud Run → Cloud SQL:** The Cloud Run SA needs `roles/cloudsql.client`. Add a `google_project_iam_member` resource in `airflow/main.tf`: `member = "serviceAccount:${var.sa_email}"`, `role = "roles/cloudsql.client"`. Also add `roles/storage.objectViewer` on the warehouse bucket for the GCS FUSE DAG mount (if not already granted by `dcf gcp setup`).

**Airflow undeploy timing:** `_tf_destroy_airflow_gcp()` is only called when ALL collectors are undeployed (no DAG files remain in GCS). Check `len(list_gcs_dag_files()) == 0` after `_delete_dag_gcs()`. If DAG files remain, leave Airflow running.

### Done When

- [ ] `dcf deploy github_repos` (GCP) exits 0 and prints the Airflow Cloud Run URL
- [ ] Cloud SQL instance `dcf-airflow-db` exists in GCP
- [ ] Cloud Run service `dcf-airflow` exists with min-instances=1 and gen2 execution environment
- [ ] Airflow UI is accessible at the Cloud Run HTTPS URL (login: admin / `airflow_admin_password` from `project.yml`)
- [ ] `github_repos` DAG appears in the Airflow UI within ~30s of deploy completing
- [ ] Manually triggering the DAG runs `dcf-job-github-repos` Cloud Run job; data appears in GCS warehouse
- [ ] `dcf undeploy github_repos` (last collector): destroys Cloud Run Airflow service + Cloud SQL + DAG file; Cloud Run collector job removed
- [ ] `~/.dcf/terraform/airflow/gcp/` is removed after full undeploy

### Test Scenario

`testing/scenarios/batch-deployment-gcp.md` — Phases 3–5

---

## Resolved Design Decisions

All design open questions were resolved before planning began. No new decisions were made during planning.

---

## Implementation Order Rationale

Phases 1–3 are local-only and can be completed and fully tested without any GCP credentials. Phase 1 (templates + local module) must come before Phase 2 (Python calls Terraform) since Python needs the module to exist. Phase 3 (local Airflow) depends on Phase 2's DAG file writing. Phases 4–5 follow the same dependency structure for GCP. Phase 4 can begin independently of Phase 3 completion — they touch different files.

Phases 2 and 4 could be parallelized by two engineers (different files: `local_deploy.py` vs `batch_deploy.py` + `batch_collector/`). Phase 3 depends on Phase 2. Phase 5 depends on Phase 4. Phase 1 must complete before any other phase.

---

## Known Risks

| Risk | Phase | Mitigation |
|------|-------|------------|
| `null_resource` doesn't re-run when expected | 1, 4 | Verify `content_hash` changes when collector files change; test with a deliberate file edit before second deploy |
| `pvc-job-` → `dcf-job-` rename breaks existing Terraform state | 4 | `_import_existing_cloud_run_job()` must be updated to use new name; may need `terraform state rm` + re-import for machines with existing state |
| Cloud SQL provisioning takes >10 minutes | 5 | Print progress; document expected wait time in scenario Known Complexity |
| GCS FUSE mount requires `BETA` launch stage | 5 | If the google provider rejects the volume mount config, add `launch_stage = "BETA"` to the Cloud Run service resource |
| IAM propagation delay after granting `roles/cloudsql.client` | 5 | Wait 60s after Terraform apply before the Cloud Run service attempts DB connection; Airflow will retry connections automatically |
| Docker socket path differs on non-Mac hosts | 3 | Default `unix:///var/run/docker.sock` works on Linux + Mac with Docker Desktop; document as assumption; make configurable via `airflow_docker_socket` in `project.yml` |
| Airflow `--wait` flag not supported in older Docker Compose | 3 | Check Docker Compose version; if `--wait` unsupported, poll `http://localhost:8080/health` in a loop from Python after `docker compose up -d` |
