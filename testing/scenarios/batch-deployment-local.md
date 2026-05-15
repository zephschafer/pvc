# Scenario: Batch Deployment — Local (Phases 1–3)

## Goal

Test the new Terraform-based local batch deployment lifecycle: the `batch_pipeline_local/`
Terraform module passes validation, `ddt deploy github_repos` with `catalog: local` builds
a pipeline Docker image declaratively via Terraform and writes a DAG file to
`~/.ddt/airflow/dags/`, and the local Airflow Docker Compose stack picks up the DAG and can
execute the pipeline.

**This scenario tests new implementation code.** The `batch_pipeline_local/` Terraform module,
the rewritten `local_deploy.py` Terraform path, and the `airflow_local/` Terraform module do
not exist yet — the first run will surface implementation findings.

**The core questions this scenario answers:**
1. Does the `batch_pipeline_local/` Terraform module pass `terraform validate` and produce a
   valid `terraform plan` without requiring GCP credentials?
2. Does `ddt deploy github_repos` (local) build the pipeline image via Terraform and write
   `~/.ddt/airflow/dags/github_repos.py`?
3. Is the Docker image correctly built from the shared `batch_pipeline.Dockerfile.tftpl`
   template with `java_enabled=true` (includes JVM)?
4. Does `ddt undeploy github_repos` run `terraform destroy` and remove the DAG file, without
   touching warehouse data?
5. Does the local Airflow stack start via `airflow_local/` Terraform module, pick up the DAG,
   and successfully trigger the pipeline container?

## Target Component

This scenario tests ddt's own Terraform modules and CLI provisioning layer:
- `ddt/infra/modules/templates/batch_pipeline.Dockerfile.tftpl`
- `ddt/infra/modules/batch_pipeline_local/` (main.tf, variables.tf, outputs.tf)
- `ddt/infra/modules/templates/airflow.Dockerfile.tftpl`
- `ddt/infra/modules/templates/docker-compose.yml.tftpl`
- `ddt/infra/modules/airflow_local/` (main.tf, variables.tf, outputs.tf)
- `ddt/local_deploy.py` — rewritten deploy/undeploy to call Terraform instead of `docker build` directly
- `ddt/cli.py` — `ddt deploy`, `ddt undeploy`

The pipeline used as the test vehicle is `github_repos` (Apache org, public repos, no auth
required, six columns, append strategy — simplest existing pipeline).

## Test Phases

### Phase 1 — Module Foundation: `terraform validate`

1. Clone quipu and inject `test_config.yml` as `project.yml` (standard test setup).
2. Set `catalog: local` in `project.yml`.
3. Confirm the module files exist:
   ```bash
   ls ddt/infra/modules/templates/
   # Expected: batch_pipeline.Dockerfile.tftpl  airflow.Dockerfile.tftpl  docker-compose.yml.tftpl
   ls ddt/infra/modules/batch_pipeline_local/
   # Expected: main.tf  variables.tf  outputs.tf
   ```
4. Run `terraform validate` in `ddt/infra/modules/batch_pipeline_local/`:
   ```bash
   terraform -chdir=ddt/infra/modules/batch_pipeline_local init -backend=false
   terraform -chdir=ddt/infra/modules/batch_pipeline_local validate
   ```
5. Create a minimal `test.tfvars` and confirm `terraform plan` completes without GCP credentials:
   ```hcl
   pipeline_name = "github_repos"
   build_context = "/tmp/test-build"
   image_tag     = "ddt-local/github_repos:latest"
   content_hash  = "abc123"
   java_enabled  = true
   ```
   ```bash
   terraform -chdir=ddt/infra/modules/batch_pipeline_local plan -var-file=test.tfvars
   ```
6. Verify the plan shows `local_file.dockerfile` and `null_resource.build` will be created —
   **no google provider resources**.
7. Render the Dockerfile template manually to verify conditional Java block:
   ```bash
   # With java_enabled=true: must include openjdk-21-jre-headless
   # With java_enabled=false: must NOT include apt-get / openjdk
   ```

Phase 1 success: `terraform validate` passes; `terraform plan` completes without GCP
credentials; the plan shows exactly two resources (`local_file.dockerfile`, `null_resource.build`);
the Dockerfile template renders differently for `java_enabled=true` vs `false`.

### Phase 2 — Local Pipeline Deploy via Terraform

1. Write the `github_repos.yml` pipeline to `$CLONE/pipelines/` with a `deployment:` block:
   ```yaml
   version: 1
   name: github_repos
   source:
     type: http
     url: https://api.github.com/orgs/apache/repos
     params:
       per_page: 100
   schema:
     columns:
       - {name: id, path: id, type: integer}
       - {name: name, path: name, type: string}
       - {name: full_name, path: full_name, type: string}
       - {name: private, path: private, type: boolean}
       - {name: stargazers_count, path: stargazers_count, type: integer}
       - {name: updated_at, path: updated_at, type: timestamp}
   build:
     strategy: append
   deploy:
     schedule: "0 8 * * *"
   ```
2. Run `ddt validate github_repos` — confirm the `deployment:` block is accepted without error.
3. Run `ddt deploy github_repos`:
   ```bash
   DDT_PROJECT_DIR=$CLONE uv --directory /path/to/ddt run ddt deploy github_repos
   ```
4. Verify Terraform state was created:
   ```bash
   ls ~/.ddt/terraform/pipelines/github_repos/local/
   # Expected: main.tf  outputs.tf  terraform.tfstate  terraform.tfvars.json  variables.tf
   ```
5. Verify the Docker image was built:
   ```bash
   docker images | grep ddt-local/github_repos
   # Expected: ddt-local/github_repos  latest  <image-id>  <time>  <size>
   ```
6. Verify the build context was created at the stable path:
   ```bash
   ls ~/.ddt/build/local/github_repos/
   # Expected: ddt/  pyproject.toml  pipelines/  connectors/  project.yml  (Dockerfile written by TF)
   ```
7. Verify the DAG file was written:
   ```bash
   cat ~/.ddt/airflow/dags/github_repos.py
   # Expected: valid Python Airflow DAG using DockerOperator
   ```
   Confirm the DAG file contains: `DockerOperator`, `image="ddt-local/github_repos:latest"`,
   `environment={"PIPELINE_NAME": "github_repos"}`, volume mount for the warehouse path.
8. Run `ddt validate github_repos` with `schedule: "not a cron"` — confirm rejection with
   clear error message. Then restore the valid schedule.
9. Test the no-deploy-block error path:
   - Remove the `deployment:` block from `github_repos.yml`
   - Run `ddt deploy github_repos` — confirm it exits with a clear error (not a traceback)
   - Restore the `deployment:` block
10. Test `ddt deploy` with no args (if two pipelines with `deployment:` blocks exist):
    - Create a second pipeline YAML (e.g., copy `github_repos.yml` as `github_repos_2.yml`)
    - Run `ddt deploy` (no pipeline name) — confirm both are deployed

Phase 2 success: `ddt deploy github_repos` builds `ddt-local/github_repos:latest` via
Terraform, writes `~/.ddt/airflow/dags/github_repos.py` containing a `DockerOperator` DAG,
creates Terraform state at `~/.ddt/terraform/pipelines/github_repos/local/terraform.tfstate`,
and exits 0.

### Phase 3 — Idempotency and Undeploy (pre-Airflow)

1. Run `ddt deploy github_repos` a second time — confirm it is idempotent:
   - Terraform should detect the image is current (content_hash unchanged) and skip `docker build`
   - DAG file should be refreshed (overwritten with same content)
   - Command exits 0 without error
2. Modify a pipeline file (e.g., add a comment to `pipelines/github_repos.yml`) and re-deploy:
   - Content hash should change → Terraform should rebuild the Docker image
   - Confirm a new image ID appears in `docker images`
3. Run `ddt undeploy github_repos`:
   ```bash
   DDT_PROJECT_DIR=$CLONE uv --directory /path/to/ddt run ddt undeploy github_repos
   ```
4. Confirm the Docker image is removed:
   ```bash
   docker images | grep ddt-local/github_repos
   # Expected: no output
   ```
5. Confirm the DAG file is deleted:
   ```bash
   ls ~/.ddt/airflow/dags/github_repos.py
   # Expected: No such file or directory
   ```
6. Confirm Terraform state directory is removed:
   ```bash
   ls ~/.ddt/terraform/pipelines/github_repos/local/
   # Expected: No such file or directory
   ```
7. Confirm warehouse data is untouched — if any Parquet files exist from a prior run, verify
   they are still present.

Phase 3 success: second deploy is idempotent; a file change triggers a rebuild (content_hash
works); undeploy removes the image, DAG file, and Terraform state without touching warehouse data.

### Phase 4 — Local Airflow Stack

**Prerequisites:** `airflow_admin_password` must be set in `project.yml` before this phase.
Add it manually: `airflow_admin_password: "testpassword123"`.

1. Confirm the Airflow module files exist:
   ```bash
   ls ddt/infra/modules/airflow_local/
   # Expected: main.tf  variables.tf  outputs.tf
   ```
2. Run `ddt deploy github_repos` — should now also start the Airflow Docker Compose stack:
   ```bash
   DDT_PROJECT_DIR=$CLONE uv --directory /path/to/ddt run ddt deploy github_repos
   ```
3. Confirm the Airflow stack is running:
   ```bash
   docker compose -f ~/.ddt/airflow/docker-compose.yml ps
   # Expected: postgres, airflow-init (exited 0), airflow-scheduler, airflow-webserver all present
   ```
4. Confirm `airflow-scheduler` and `airflow-webserver` are healthy.
5. Open `http://localhost:8080` — confirm Airflow UI loads. Login with admin /
   `airflow_admin_password` from `project.yml`.
6. Confirm `github_repos` DAG appears in the Airflow UI (may take up to 30 seconds for
   scheduler to pick it up).
7. Manually trigger the `github_repos` DAG via the Airflow UI.
8. Monitor the DAG run until it completes. If it fails, check logs:
   ```bash
   docker logs <airflow-scheduler-container>
   ```
9. After a successful DAG run, confirm Parquet files were written to the warehouse:
   ```bash
   ls $CLONE/warehouse/github_repos/github_repos/data/
   ```
10. Run a warehouse query to verify data:
    ```bash
    DDT_PROJECT_DIR=$CLONE uv --directory /path/to/ddt run ddt query \
      "SELECT COUNT(*), MAX(name) FROM github_repos.github_repos"
    ```
11. Run `ddt undeploy github_repos` — confirm the DAG file is removed; wait 30 seconds
    and confirm the DAG disappears from the Airflow UI (without Airflow restarting).
12. Run `ddt deploy github_repos` a second time — confirm the Airflow Docker Compose stack
    does NOT restart (Terraform detects no changes needed); only the DAG file is added back.

Phase 4 success: Airflow UI is accessible at `http://localhost:8080`; `github_repos` DAG
appears within 30s; manual DAG trigger executes the pipeline container and writes Parquet to
the warehouse; undeploy removes the DAG file without restarting Airflow; second deploy is
idempotent for the Airflow stack.

## Success Criteria

- [ ] Phase 1: `terraform validate` passes in `ddt/infra/modules/batch_pipeline_local/` without GCP credentials
- [ ] Phase 1: `terraform plan` shows exactly `local_file.dockerfile` and `null_resource.build` — no google provider resources
- [ ] Phase 1: `batch_pipeline.Dockerfile.tftpl` renders with JVM install when `java_enabled=true`, without it when `false`
- [ ] Phase 2: `ddt validate github_repos` accepts the `deploy: { schedule: "0 8 * * *" }` block without error
- [ ] Phase 2: `ddt validate` rejects an invalid cron expression with a clear error message
- [ ] Phase 2: `ddt deploy github_repos` (local) exits 0 and builds `ddt-local/github_repos:latest`
- [ ] Phase 2: `~/.ddt/terraform/pipelines/github_repos/local/terraform.tfstate` exists after deploy
- [ ] Phase 2: `~/.ddt/airflow/dags/github_repos.py` exists and contains `DockerOperator`
- [ ] Phase 2: `ddt deploy github_repos` on a pipeline with no `deployment:` block exits with a clear error (not a traceback)
- [ ] Phase 3: Second `ddt deploy github_repos` is idempotent — no new image built when content unchanged
- [ ] Phase 3: Modifying a pipeline file changes the content_hash and triggers an image rebuild
- [ ] Phase 3: `ddt undeploy github_repos` removes the Docker image, DAG file, and Terraform state dir
- [ ] Phase 3: Warehouse data files are untouched after undeploy
- [ ] Phase 4: `ddt deploy github_repos` starts the local Airflow Docker Compose stack
- [ ] Phase 4: Airflow UI is accessible at `http://localhost:8080`
- [ ] Phase 4: `github_repos` DAG appears in Airflow UI within 30s of deploy
- [ ] Phase 4: Manually triggering the DAG runs the pipeline container and writes Parquet to the warehouse
- [ ] Phase 4: `ddt undeploy github_repos` removes the DAG file; Airflow no longer shows the DAG within ~30s (without restart)
- [ ] Phase 4: Second `ddt deploy github_repos` does not restart the Airflow stack (only DAG file refreshed)
- [ ] Throughout: No GCP credentials used or required in Phases 1–4

## Known Complexity

- **Docker socket mount on Mac:** The `airflow-scheduler` container mounts
  `/var/run/docker.sock` to allow `DockerOperator` to start pipeline containers. Docker
  Desktop on Mac uses a virtual socket at `unix:///var/run/docker.sock` which is exposed to
  containers — but this path may differ on Linux or Windows. The scenario assumes Mac with
  Docker Desktop; note any socket path failure as an environment-specific finding.

- **`docker compose up --wait` version requirement:** The `--wait` flag (blocks until all
  services are healthy) requires Docker Compose v2.1+. If the flag is not supported, ddt may
  need to poll `http://localhost:8080/health` in a loop instead. Note the Docker Compose
  version in your findings.

- **Airflow DAG scan interval:** The scheduler polls `~/.ddt/airflow/dags/` every 30 seconds
  (`DAG_DIR_LIST_INTERVAL: 30`). After `ddt deploy`, the DAG may not appear in the UI for up
  to 30 seconds — this is expected behavior, not a bug.

- **Terraform `null_resource` content_hash trigger:** The `null_resource.build` triggers a
  `docker build` only when `content_hash` changes. If content_hash is computed incorrectly
  (e.g., includes the Dockerfile written by Terraform), the trigger will always fire or never
  fire. Test both paths explicitly.

- **Stable build context wipe:** `_sync_build_context()` wipes and recreates
  `~/.ddt/build/local/<name>/` on each deploy before syncing files. This means Terraform's
  `local_file.dockerfile` (written to that dir) is deleted before each run — that is
  intentional, as Terraform will recreate it. If the wipe happens after Terraform writes the
  Dockerfile but before Terraform reads it, there could be an ordering issue. Watch for this
  in Phase 2.

- **Fernet key auto-generation:** On first deploy with `airflow_admin_password` set but no
  `airflow_fernet_key` in `project.yml`, ddt should auto-generate the fernet key and write
  it back to `project.yml`. Verify this write succeeds and the key persists on second deploy
  (not regenerated).

## Known Expected Findings (Pre-identified)

- **Blocking (expected):** `ddt/local_deploy.py` currently has `_build_batch_image()` which
  calls `docker build` directly (Python subprocess) — not via Terraform. This is the old path
  being replaced. The first run will almost certainly fail because the Terraform module and
  the new Python code don't exist yet. Document this as a Blocking finding and stop.

- **Blocking (expected):** `ddt/infra/modules/batch_pipeline_local/` does not exist yet —
  `terraform validate` will fail in Phase 1 until the module is created. This is an expected
  first finding.

- **Minor (possible):** `ddt deploy` (no args) may not yet support no-arg invocation in
  `cli.py`. If `typer.Argument()` rejects `None`, document as Enhancement finding.

- **Minor (possible):** `airflow_admin_password` missing from `project.yml` may produce an
  unclear error if Phase 4 is reached without setting it. The correct behavior is a clear
  `RuntimeError` with a message like `"airflow_admin_password is missing from project.yml"`.

## Credentials Required

- No GCP credentials required for Phases 1–4
- Docker Desktop must be running on the test machine
- `airflow_admin_password` must be set manually in `project.yml` before Phase 4

## By Design Decisions from Prior Runs

(None yet — first run of this scenario)

## Notes for Agent

- This scenario tests **unimplemented feature code**. Expect Phase 1 to produce Blocking
  findings about missing Terraform modules. Document them and stop — do not attempt to work
  around missing modules by writing custom Terraform.
- Full command prefix: `DDT_PROJECT_DIR=$CLONE uv --directory /path/to/ddt run ddt <command>`
- After injecting `test_config.yml` as `project.yml`, explicitly set `catalog: local`. Do NOT
  use `catalog: gcp` at any point in Phases 1–4.
- Use the `github_repos` pipeline pointed at `https://api.github.com/orgs/apache/repos` — no
  auth required, keeps data fetching simple.
- For Phase 1 `terraform validate`, you will need `terraform` installed. Check with
  `terraform version`. If not installed, document as a prerequisite finding and stop Phase 1.
- For Phase 4, add `airflow_admin_password: "testpassword123"` to `project.yml` before
  running `ddt deploy`. If you forget, the command should raise a clear error — verify the
  error message is actionable.
- If Phase 4's Airflow DAG run fails, check the Airflow task log in the UI first, then check
  Docker logs (`docker logs <scheduler-container>`). A common failure is the DockerOperator
  not finding the pipeline image (`ddt-local/github_repos:latest`) — confirm the image is in
  the local daemon with `docker images`.
- Record the Docker Compose version (`docker compose version`) in your findings — needed to
  evaluate whether `--wait` is supported.
