# Design: Batch Pipeline Deployment

**Status:** Finalized
**ID:** batch-deployment
**Created:** 2026-05-14
**Updated:** 2026-05-14
**Feature:** [batch-deployment](../features/batch-deployment.md)
**Implementation Plan:** [`design/batch-deployment-plan.md`](./batch-deployment-plan.md)

---

## Context

`ddt deploy` provisions a batch pipeline as a scheduled, containerized job. The pipeline's `deploy:` block declares the schedule; the project's `catalog` setting determines the deployment target (`local` or `gcp`). The design centers on two Docker apps as primary artifacts:

1. **Pipeline container** — runs `ddt run <pipeline>` on demand; one per pipeline; built and destroyed per pipeline deploy/undeploy
2. **Airflow container** — schedules and triggers pipeline runs; shared across all deployed pipelines; built once on first deploy; not rebuilt when pipelines are added or removed

Both apps are defined declaratively in Terraform modules and follow the same build-and-deploy pattern regardless of target. `ddt deploy` = `terraform apply` + write DAG file. `ddt undeploy` = `terraform destroy` + delete DAG file.

DAGs are **not baked into the Airflow image**. They are written as Python files to a directory that Airflow mounts and polls. This means adding or removing a pipeline does not require rebuilding or restarting Airflow.

Cloud Composer is not used.

---

## Architecture Overview

**Local (`catalog: local`):**

```
ddt deploy [<name>]           reads catalog=local from project.yml
    │
    ├── For each pipeline:
    │     │
    │     ├── Python: assemble pipeline build context → /tmp/ddt-pipeline-<name>/
    │     │
    │     ├── terraform apply  [batch_pipeline_local/]
    │     │     ├── local_file.dockerfile → Dockerfile (batch_pipeline.Dockerfile.tftpl)
    │     │     └── null_resource.build  → docker build -t ddt-local/<name>:latest
    │     │
    │     └── Python: write DAG file → ~/.ddt/airflow/dags/<name>.py
    │                                   (DockerOperator — runs ddt-local/<name>:latest)
    │
    └── terraform apply  [airflow_local/]    ← only on first deploy; idempotent thereafter
          ├── local_file.dockerfile   → Dockerfile (airflow.Dockerfile.tftpl)
          ├── null_resource.build     → docker build -t ddt-airflow:latest
          ├── local_file.compose      → ~/.ddt/airflow/docker-compose.yml
          └── null_resource.up        → docker compose up -d

                    ~/.ddt/airflow/dags/        (host directory)
                           │  mounted as volume
                           ▼
                    Airflow scheduler           (polls dags/ every 30s)
                           │
                      DockerOperator
                           │
                    docker run --rm \
                      -e PIPELINE_NAME=<name> \
                      -v <project>/warehouse:/app/warehouse \
                      ddt-local/<name>:latest
```

**Deployed (`catalog: gcp`):**

```
ddt deploy [<name>]           reads catalog=gcp from project.yml
    │
    ├── For each pipeline:
    │     │
    │     ├── Python: assemble pipeline build context → /tmp/ddt-pipeline-<name>/
    │     │
    │     ├── terraform apply  [batch_pipeline/]
    │     │     ├── local_file.dockerfile → Dockerfile (batch_pipeline.Dockerfile.tftpl)
    │     │     ├── null_resource.build  → gcloud builds submit → Artifact Registry
    │     │     └── google_cloud_run_v2_job → ddt-job-<name>
    │     │
    │     └── Python: write DAG file → gs://<warehouse-bucket>/airflow/dags/<name>.py
    │                                   (CloudRunExecuteJobOperator — triggers ddt-job-<name>)
    │
    └── terraform apply  [airflow/]          ← only on first deploy; idempotent thereafter
          ├── local_file.dockerfile       → Dockerfile (airflow.Dockerfile.tftpl)
          ├── null_resource.build         → gcloud builds submit → Artifact Registry
          ├── google_sql_database_instance → Cloud SQL PostgreSQL (ddt-airflow-db)
          ├── google_sql_database         → airflow
          ├── google_sql_user             → airflow
          └── google_cloud_run_v2_service → ddt-airflow
                (min-instances=1, GCS bucket mounted at /opt/airflow/dags/)

                    gs://<warehouse-bucket>/airflow/dags/    (GCS prefix)
                           │  GCS FUSE mount (Cloud Run gen2)
                           ▼
                    Airflow scheduler           (polls dags/ every 30s)
                           │
                    CloudRunExecuteJobOperator
                           │
                    Cloud Run job: ddt-job-<name>
                           │
                    ddt run <name>  →  GCS warehouse
```

**Undeploy:**

```
ddt undeploy <name>
    │
    ├── terraform destroy  [batch_pipeline[_local]/]
    │     └── removes Cloud Run job (GCP) or local Docker image
    │
    └── Python: delete DAG file
          └── ~/.ddt/airflow/dags/<name>.py  (local)
              gs://<warehouse-bucket>/airflow/dags/<name>.py  (GCP)

    Airflow picks up the deleted DAG within ~30s. No Airflow restart or rebuild.
    Warehouse data is untouched.
```

---

## Components

### Pipeline Container

| Property | Value |
|----------|-------|
| **Type** | process |
| **Owner** | ddt code |
| **Local behavior** | `docker build` → local image `ddt-local/<name>:latest`; run by Airflow `DockerOperator` on schedule |
| **Deployed behavior** | `gcloud builds submit` → Artifact Registry; run as Cloud Run job by Airflow `CloudRunExecuteJobOperator` |
| **Entrypoint** | `ddt run $PIPELINE_NAME` (baked via `CMD`) |

**Interface:**
- Input: `PIPELINE_NAME` env var; warehouse volume mount (local) or Workload Identity for GCS (GCP)
- Output: Parquet files at `<project>/warehouse/<name>/` (local) or `gs://<bucket>/<name>/` (GCP); exit code

**Dockerfile template:** `ddt/infra/modules/templates/batch_pipeline.Dockerfile.tftpl`

Contents baked into image: `ddt/` source, `pyproject.toml`, `pipelines/<name>.yml`, `connectors/`, minimal `project.yml`

---

### Airflow Container

| Property | Value |
|----------|-------|
| **Type** | service |
| **Owner** | ddt code |
| **Local behavior** | Docker Compose: Airflow scheduler + webserver (port 8080) + PostgreSQL. DAGs read from `~/.ddt/airflow/dags/` (host-mounted volume). `DockerOperator` triggers pipeline containers via Docker socket. |
| **Deployed behavior** | Cloud Run service (min-instances=1, gen2 execution environment). DAGs read from `gs://<warehouse-bucket>/airflow/dags/` via GCS FUSE mount. `CloudRunExecuteJobOperator` triggers Cloud Run pipeline jobs. |
| **Entrypoint** | `airflow standalone` (runs scheduler + webserver in one process) |

**Interface:**
- Input: `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` env var; `AIRFLOW__CORE__FERNET_KEY` env var; `AIRFLOW_ADMIN_PASSWORD` env var (from `project.yml`); DAG directory (mounted)
- Output: triggers pipeline containers on schedule; webserver UI at port 8080 (local) or Cloud Run HTTPS URL (GCP)

**Dockerfile template:** `ddt/infra/modules/templates/airflow.Dockerfile.tftpl`

Based on `apache/airflow:2.9-python3.12`. Providers installed at image build time:
- Local image: `apache-airflow-providers-docker`
- GCP image: `apache-airflow-providers-google`

**Built once on first deploy.** Rebuilt only if the Airflow version or providers change — not when pipelines are added, changed, or removed.

---

### DAG Directory

| Property | Value |
|----------|-------|
| **Type** | config |
| **Owner** | ddt code (Python writes files; Airflow reads them) |
| **Local path** | `~/.ddt/airflow/dags/` (host directory, volume-mounted into Airflow container) |
| **GCP path** | `gs://<warehouse-bucket>/airflow/dags/` (GCS prefix, FUSE-mounted into Cloud Run Airflow service) |

One `.py` file per deployed pipeline. Airflow polls for changes every 30 seconds (`dag_dir_list_interval = 30`).

**Written by:** `ddt deploy` (Python, after Terraform apply)
**Deleted by:** `ddt undeploy` (Python, after Terraform destroy)

Local DAG template uses `DockerOperator`:
```python
DockerOperator(
    task_id="run_<name>",
    image="ddt-local/<name>:latest",
    environment={"PIPELINE_NAME": "<name>"},
    volumes=["<warehouse_path>:/app/warehouse"],
    docker_url="unix:///var/run/docker.sock",
    auto_remove="success",
)
```

GCP DAG template uses `CloudRunExecuteJobOperator`:
```python
CloudRunExecuteJobOperator(
    task_id="run_<name>",
    project_id="<project_id>",
    region="<region>",
    job_name="ddt-job-<name>",
)
```

---

### Terraform Module: `batch_pipeline_local/` (new)

| Property | Value |
|----------|-------|
| **Type** | module |
| **Owner** | ddt code |
| **Manages** | Airflow Dockerfile → local image build |
| **Entrypoint** | `ddt/infra/modules/batch_pipeline_local/` |

**Resources:** `local_file.dockerfile`, `null_resource.build`

**Variables:** `pipeline_name`, `build_context`, `image_tag`, `content_hash`, `java_enabled` (default: `true`)

**Outputs:** `image_tag`

**State:** `~/.ddt/terraform/pipelines/<name>/local/`

---

### Terraform Module: `batch_pipeline/` (GCP, refined)

| Property | Value |
|----------|-------|
| **Type** | module |
| **Owner** | ddt code |
| **Manages** | Pipeline Dockerfile → Cloud Build → Artifact Registry image → Cloud Run job |
| **Entrypoint** | `ddt/infra/modules/gcp/batch_pipeline/` (existing, modified) |

**Removed from current module:**
- `google_storage_bucket_object.dag` — DAGs are now written directly by Python, not uploaded via Terraform
- `dag_bucket`, `dag_blob_name`, `dag_content` variables

**Added to current module:**
- `local_file.dockerfile` — renders Dockerfile from template into build context
- `null_resource.build` — runs `gcloud builds submit` (replaces Python `_build_image()`)
- `build_context`, `content_hash`, `java_enabled` (default: `false`) variables
- Fix: `pvc-job-` → `ddt-job-` in resource name

**Variables:** `pipeline_name`, `build_context`, `image_uri`, `sa_email`, `content_hash`, `java_enabled`, `project_id`, `region`

**Outputs:** `job_name`

**State:** `~/.ddt/terraform/pipelines/<name>/gcp/`

---

### Terraform Module: `airflow_local/` (new)

| Property | Value |
|----------|-------|
| **Type** | module |
| **Owner** | ddt code |
| **Manages** | Airflow Dockerfile → local image build → Docker Compose stack |
| **Entrypoint** | `ddt/infra/modules/airflow_local/` |

**Resources:** `local_file.dockerfile`, `null_resource.build`, `local_file.compose`, `null_resource.up`

**Variables:** `image_tag`, `dag_dir` (`~/.ddt/airflow/dags/`), `warehouse_path`, `docker_socket` (default: `unix:///var/run/docker.sock`), `db_password`, `admin_password`, `fernet_key`

**Outputs:** `webserver_url` (`http://localhost:8080`), `compose_file`

**State:** `~/.ddt/terraform/airflow/local/`

---

### Terraform Module: `airflow/` (GCP, new)

| Property | Value |
|----------|-------|
| **Type** | module |
| **Owner** | ddt code |
| **Manages** | Airflow Dockerfile → Cloud Build → Cloud SQL → Cloud Run service |
| **Entrypoint** | `ddt/infra/modules/gcp/airflow/` |

**Resources:**
- `local_file.dockerfile`
- `null_resource.build` — `gcloud builds submit` for Airflow image
- `google_sql_database_instance.airflow_db` — Cloud SQL PostgreSQL (`db-f1-micro`)
- `google_sql_database.airflow`, `google_sql_user.airflow`
- `google_cloud_run_v2_service.airflow` — min-instances=1, gen2 execution environment, GCS volume mount for DAGs

**Variables:** `image_uri`, `content_hash`, `project_id`, `region`, `sa_email`, `warehouse_bucket`, `db_password`, `admin_password`, `fernet_key`

**Outputs:** `webserver_url`, `service_name`

**State:** `~/.ddt/terraform/airflow/gcp/`

---

## Local vs. Deployed Parity

| Concern | Local | Deployed | Notes |
|---------|-------|----------|-------|
| Deploy command | `ddt deploy` → `terraform apply` + write DAG file | `ddt deploy` → `terraform apply` + write DAG file | Identical |
| Undeploy command | `ddt undeploy` → `terraform destroy` + delete DAG file | `ddt undeploy` → `terraform destroy` + delete DAG file | Identical |
| Pipeline image build | `docker build` via `null_resource` | `gcloud builds submit` via `null_resource` | Same Dockerfile template; different builder |
| Pipeline image storage | Local Docker daemon | Artifact Registry | |
| Pipeline execution | Airflow `DockerOperator` → `docker run` | Airflow `CloudRunExecuteJobOperator` → Cloud Run job | Different operator; same pipeline `CMD` |
| Airflow image build | `docker build` via `null_resource` | `gcloud builds submit` via `null_resource` | Same Airflow Dockerfile template |
| Airflow host | Docker Compose (scheduler + webserver + Postgres) | Cloud Run service min-instances=1 (gen2) | |
| Airflow DB | PostgreSQL container (in Docker Compose) | Cloud SQL PostgreSQL | |
| DAG storage | `~/.ddt/airflow/dags/` (host dir, volume-mounted) | `gs://<warehouse-bucket>/airflow/dags/` (GCS FUSE mount) | |
| DAG pickup latency | ~30s (Airflow polls mounted dir) | ~30s (Airflow polls GCS FUSE mount) | |
| Airflow UI | `http://localhost:8080` | Cloud Run HTTPS URL | |
| Airflow credentials | From `project.yml` (`airflow_admin_password`) | From `project.yml` (`airflow_admin_password`) | Deferred: move to Secret Manager |
| Pipeline storage | Volume-mounted `<project>/warehouse/` | GCS warehouse bucket | |
| Java in pipeline image | Yes — `java_enabled: true`; Spark used for local Iceberg writes | No — `java_enabled: false`; PyArrow + GCS direct write bypasses Spark | Determined by catalog in image |
| Airflow rebuild needed for pipeline changes | No | No | Only the DAG file changes; Airflow container is unaffected |
| Terraform state: pipelines | `~/.ddt/terraform/pipelines/<name>/local/` | `~/.ddt/terraform/pipelines/<name>/gcp/` | |
| Terraform state: airflow | `~/.ddt/terraform/airflow/local/` | `~/.ddt/terraform/airflow/gcp/` | |

---

## Interface Contracts

### CLI

```
ddt deploy [<pipeline-name>]
ddt undeploy <pipeline-name>
ddt deploy status [<pipeline-name>]
```

| Command | Behavior |
|---------|----------|
| `ddt deploy` | Deploy all pipelines with a `deploy:` block. Apply Airflow module on first deploy (idempotent thereafter). Write DAG file per pipeline. Exit non-zero if any pipeline fails; print per-pipeline summary. |
| `ddt deploy <name>` | Deploy one pipeline. Same Airflow module apply. Write that pipeline's DAG file. |
| `ddt undeploy <name>` | `terraform destroy` that pipeline's module. Delete its DAG file. Airflow stops scheduling within ~30s. |
| `ddt deploy status` | Print deployment state from `project.yml` for all pipelines. |

Future: `ddt deploy <name1> <name2> ...` to deploy a named subset.

### Config Schema (`project.yml`)

No new pipeline YAML fields. New keys in `project.yml`:

```yaml
airflow_admin_password: "changeme"   # Airflow webserver admin password
airflow_fernet_key: "<base64>"       # Generated by ddt on first deploy if absent
```

`ddt deploy` generates `airflow_fernet_key` automatically on first run if not present and writes it back to `project.yml`. `airflow_admin_password` must be set by the user before first deploy.

Pipeline `deploy:` block is unchanged:
```yaml
deploy:
  schedule: "0 8 * * *"
  paused: false
```

### Terraform Variable Summary

| Module | Key variables |
|--------|--------------|
| `batch_pipeline_local/` | `pipeline_name`, `build_context`, `image_tag`, `content_hash`, `java_enabled` |
| `batch_pipeline/` (GCP) | `pipeline_name`, `build_context`, `image_uri`, `sa_email`, `content_hash`, `java_enabled`, `project_id`, `region` |
| `airflow_local/` | `image_tag`, `dag_dir`, `warehouse_path`, `docker_socket`, `db_password`, `admin_password`, `fernet_key` |
| `airflow/` (GCP) | `image_uri`, `content_hash`, `project_id`, `region`, `sa_email`, `warehouse_bucket`, `db_password`, `admin_password`, `fernet_key` |

### Inter-Service Protocols

| From | To | Protocol | Payload |
|------|----|----------|---------|
| Airflow scheduler (local) | Pipeline container | Docker socket — `DockerOperator` | Image tag, env vars, volume mounts |
| Airflow scheduler (GCP) | Cloud Run job | Cloud Run Execute Job API (gRPC) | Job name; pipeline name is baked into image as `ENV PIPELINE_NAME` |
| Cloud Run pipeline job | GCS | GCS object write (HTTPS) | Parquet files |
| Cloud Run Airflow service | Cloud SQL | PostgreSQL wire protocol (TCP 5432) | Airflow metadata (task states, DAG runs) |
| `ddt deploy` (GCP) | GCS DAG prefix | GCS object write (HTTPS) | DAG `.py` file |
| Cloud Run Airflow service | GCS DAG prefix | GCS FUSE (read-only, filesystem API) | DAG `.py` files (polled every 30s) |

---

## Technology Choices

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Airflow hosting (cloud) | Cloud Run service (min-instances=1, gen2) | Cloud Composer; Compute Engine VM; GKE | Composer is the problem being solved. Compute Engine is always-on + VM management. GKE is heavy. Cloud Run fits the app-centric Terraform pattern and is consistent with pipeline container deployment. |
| Airflow hosting (local) | Docker Compose (scheduler + webserver + Postgres) | Single `airflow standalone` container | Docker Compose is the natural multi-container local pattern. Postgres in Compose matches the cloud DB. |
| Airflow DB | PostgreSQL everywhere (Docker Compose locally; Cloud SQL on GCP) | SQLite; AlloyDB | SQLite corrupts under Airflow's concurrent scheduler + worker writes. AlloyDB is oversized. PostgreSQL is correct; Docker Compose makes the local case simple. |
| DAG distribution | Files written to a mounted directory (host dir locally; GCS FUSE on GCP) | Baked into Airflow image; K8s ConfigMap | Image baking requires rebuilding Airflow on every pipeline change — makes undeploy slow and complex. Mounted directory lets Airflow pick up changes within 30s with no container restart. Consistent with how Airflow is typically operated. |
| Airflow process model | `airflow standalone` (single process per container) | Separate scheduler + webserver services | `airflow standalone` is simpler to Terraform-manage for a single-project tool. Two Cloud Run services doubles cost and complexity. Known limitation: not recommended for high-scale; acceptable for a personal data lake. |
| Dockerfile location | Terraform template (`*.Dockerfile.tftpl`) in shared `templates/` dir | Inline Python string; per-module templates | Single source of truth. Shared path (`${path.module}/../../templates/`) avoids duplication between local and GCP modules. |
| Build trigger | `content_hash` tfvar (SHA256 of build context files) | `timestamp()` (always rebuild) | `timestamp()` wastes Cloud Build minutes. Hash rebuilds only when source actually changes. |
| `ddt undeploy` semantics | `terraform destroy` + delete DAG file | Pause DAG only; keep infrastructure | `terraform destroy` gives a clean, complete teardown matching the declarative model. Pausing leaves Cloud Run jobs and images consuming quota. |
| GCS DAG path | Prefix in existing warehouse bucket (`airflow/dags/`) | Separate dedicated bucket | One less GCS bucket to manage. Warehouse bucket already exists from `ddt gcp setup`. |
| Docker socket (local) | Mount `/var/run/docker.sock` into Airflow container | Airflow `LocalExecutor` running `ddt run` as subprocess | Socket mount is standard for tools that need to start sibling containers (CI systems, etc.). Subprocess inside Airflow shares the scheduler's process — a failing pipeline can crash the scheduler. |
| Airflow credentials | Read from `project.yml` for now | Secret Manager; environment-provided | Simple for a personal tool. `project.yml` is gitignored. Deferred to a future security hardening pass. |
| `java_enabled` per target | `true` for local, `false` for GCP | Same image for both | Local Iceberg path uses Spark (requires JVM). GCP path uses PyArrow + GCS direct write, bypassing Spark entirely (`runner.py:19`, `iceberg.py:63`). |

---

## Open Questions

None blocking implementation. All architectural decisions are resolved.

The following are deferred by design:

- **Airflow credentials security.** Admin password and fernet key in `project.yml` are acceptable for now. Future: move to Secret Manager, with ddt reading from there instead.
- **`airflow standalone` scale limit.** Single-process Airflow is not recommended for high-scale production. Acceptable for a personal data lake. Future: migrate to Celery executor + separate scheduler/webserver services if pipeline count grows.
- **`ddt deploy` subset targeting.** Currently all-or-nothing (no args) or single pipeline. Future: `ddt deploy <name1> <name2> ...` to deploy a named subset.

---

## Design Decision Log

| Date | Decision | Rationale | Revisit If |
|------|----------|-----------|------------|
| 2026-05-14 | Container spec lives in Terraform template, not Python | Eliminates dual-definition bug (local vs GCP Dockerfiles); single source of truth | A future non-Terraform deployment path is added |
| 2026-05-14 | Two separate Terraform modules per tier (local + GCP) for both pipeline and Airflow | Single module initializes the google provider even for local targets — breaks users with no GCP account | A Terraform multi-provider pattern emerges that handles conditional provider initialization |
| 2026-05-14 | Replace Cloud Composer with custom Airflow Docker app | Composer is outside Terraform's control (imperative gcloud). Custom Docker app is declarative, version-controlled, and follows the same local/cloud pattern as pipeline containers | Airflow operational complexity becomes too burdensome |
| 2026-05-14 | DAGs mounted from directory; not baked into Airflow image | Image baking requires Airflow rebuild on every pipeline change. Mounted directory lets ddt write/delete DAG files and Airflow picks up changes in ~30s with no restart. Keeps undeploy = terraform destroy + delete file. | DAG count or size grows large enough to make GCS FUSE latency a problem |
| 2026-05-14 | `ddt undeploy` = `terraform destroy` + delete DAG file | Clean, complete teardown matching the declarative model. Leaves no orphaned Cloud Run jobs or images. Warehouse data is not managed by Terraform and is untouched. | N/A |
| 2026-05-14 | Cloud SQL provisioned by Terraform as part of `ddt deploy` | Terraform handles dependency ordering naturally (Cloud Run service depends on Cloud SQL). Acceptable if first deploy is slow. | N/A |
| 2026-05-14 | GCS DAG prefix inside warehouse bucket (`airflow/dags/`) | One less bucket to manage. Warehouse bucket already provisioned by `ddt gcp setup`. | DAG files need different access controls than warehouse data |
| 2026-05-14 | `java_enabled: true` for local, `false` for GCP | Local catalog uses Spark (requires JVM). GCP catalog uses PyArrow + GCS direct write, bypassing Spark (`runner.py:19`, `iceberg.py:63`). | A GCP pipeline type is added that requires Java |
| 2026-05-14 | Airflow admin password and fernet key from `project.yml` | Simple for a personal tool. Deferred security improvement. | Multi-user access or sharing of `project.yml` is needed |
| 2026-05-14 | `ddt deploy` (no args) deploys all pipelines independently; exits non-zero if any fail | Independent deploys allow partial success. All-or-nothing would abort healthy pipelines on one failure. | N/A |
