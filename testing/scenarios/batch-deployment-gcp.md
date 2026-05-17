# Scenario: Batch Deployment — GCP (Phases 4–5)

## Goal

Test the new Terraform-based GCP batch deployment lifecycle: `dcf deploy github_repos` with
`catalog: gcp` builds the pipeline container via `gcloud builds submit` (not Cloud Composer),
creates a Cloud Run job, and writes the DAG file to `gs://<warehouse-bucket>/airflow/dags/`.
Then verify the GCP Airflow stack (Cloud Run service + Cloud SQL) picks up the DAG and
executes the pipeline on schedule.

**This scenario tests new implementation code.** The Terraform-based `batch_pipeline/` GCP
module rewrite, the `gcp/airflow/` Terraform module, and the rewritten `batch_deploy.py`
(no Composer) do not exist yet. Cloud Composer is not used — it has been replaced by a custom
Airflow Docker app deployed as a Cloud Run service.

**The core questions this scenario answers:**
1. Does `dcf deploy github_repos` (GCP) build the pipeline container via Terraform
   (`gcloud builds submit`) and create a Cloud Run job named `dcf-job-github-repos`?
2. Is the DAG file written to `gs://<bucket>/airflow/dags/github_repos.py` using
   `CloudRunExecuteJobOperator` (not Composer/DAG bucket)?
3. Does `dcf deploy` (GCP) also provision a Cloud Run Airflow service + Cloud SQL on first
   deploy? Does second deploy skip reprovisioning (idempotent)?
4. Does the Airflow UI pick up the DAG via GCS FUSE mount and execute it?
5. Does `dcf undeploy github_repos` remove the Cloud Run job, DAG file, and — when it is
   the last pipeline — the Airflow Cloud Run service and Cloud SQL instance?

## Target Component

This scenario tests dcf's GCP provisioning layer:
- `dcf/infra/modules/gcp/batch_pipeline/` — rewritten to use Terraform + `gcloud builds submit`
- `dcf/infra/modules/gcp/airflow/` — new module: Cloud Run Airflow + Cloud SQL + GCS FUSE
- `dcf/infra/modules/templates/batch_pipeline.Dockerfile.tftpl` — shared template (`java_enabled=false` for GCP)
- `dcf/infra/modules/templates/airflow.Dockerfile.tftpl` — Airflow image with google provider
- `dcf/gcp/batch_deploy.py` — rewritten: no Composer calls; uses `_write_dag_gcs()` and `_tf_apply_airflow_gcp()`
- `dcf/cli.py` — `dcf deploy`, `dcf undeploy`

The pipeline used as the test vehicle is `github_repos` (Apache org, public repos, no auth
required, six columns, append strategy — simplest existing pipeline).

## Test Phases

### Phase 1 — GCP Pipeline Container via Terraform

1. Confirm GCP prerequisites:
   ```bash
   gcloud auth list                                       # authenticated
   gcloud services list --enabled | grep -E "run|build|artifactregistry"
   # Expected: run.googleapis.com, cloudbuild.googleapis.com, artifactregistry.googleapis.com
   ```
   If any API is missing: `gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com`
2. Confirm `project.yml` has `catalog: gcp` and `dcf gcp setup` has been completed:
   - `gcp.project_id`, `gcp.region`, `gcp.warehouse_bucket`, `gcp.sa_email` all set
3. Write the `github_repos.yml` pipeline to `$CLONE/pipelines/` with a `deployment:` block:
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
4. Run `dcf deploy github_repos`:
   ```bash
   DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run dcf deploy github_repos
   ```
   Note: This will trigger `gcloud builds submit` which takes 2–5 minutes on first run.
5. Confirm the Cloud Run job was created with the correct name:
   ```bash
   gcloud run jobs list --region <region> --project <project_id>
   # Expected: dcf-job-github-repos  (NOT pvc-job-github-repos)
   ```
6. Confirm Terraform state exists and contains the Cloud Run job — NOT a DAG bucket object:
   ```bash
   ls ~/.dcf/terraform/pipelines/github_repos/gcp/
   # Expected: main.tf  outputs.tf  terraform.tfstate  terraform.tfvars.json  variables.tf
   terraform -chdir=~/.dcf/terraform/pipelines/github_repos/gcp show
   # Expected: google_cloud_run_v2_job.pipeline
   # NOT expected: google_storage_bucket_object.dag
   ```
7. Confirm the DAG file was written to GCS (not via Terraform — via `_write_dag_gcs()`):
   ```bash
   gsutil ls gs://<warehouse-bucket>/airflow/dags/
   # Expected: gs://<warehouse-bucket>/airflow/dags/github_repos.py
   gsutil cat gs://<warehouse-bucket>/airflow/dags/github_repos.py
   # Expected: contains CloudRunExecuteJobOperator, not CloudRunJobOperator
   ```
8. Confirm no Cloud Composer environment was created or referenced:
   ```bash
   gcloud composer environments list --locations <region>
   # Expected: empty (or pre-existing unrelated environments)
   ```
9. Manually trigger the Cloud Run job to verify it executes correctly:
   ```bash
   gcloud run jobs execute dcf-job-github-repos --region <region> --wait
   ```
10. After the job completes, verify data in GCS warehouse:
    ```bash
    gsutil ls gs://<warehouse-bucket>/github_repos/github_repos/data/
    ```
11. Test undeploy:
    ```bash
    DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run dcf undeploy github_repos
    gcloud run jobs list --region <region>           # dcf-job-github-repos gone
    gsutil ls gs://<bucket>/airflow/dags/            # github_repos.py gone
    ls ~/.dcf/terraform/pipelines/github_repos/gcp/  # No such file or directory
    gsutil ls gs://<bucket>/github_repos/            # warehouse data still present
    ```

Phase 1 success: `dcf deploy github_repos` (GCP) builds the image via `gcloud builds submit`,
creates `dcf-job-github-repos` Cloud Run job, writes `airflow/dags/github_repos.py` to GCS,
and exits 0 without any Composer references. `dcf undeploy` removes the job and DAG file
without touching warehouse data.

### Phase 2 — Idempotency and Content Hash

1. Re-deploy `github_repos`:
   ```bash
   DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run dcf deploy github_repos
   ```
2. Confirm `gcloud builds submit` was NOT re-triggered (content_hash unchanged — no file
   modifications since last deploy). Watch for "No changes" or "0 to add, 0 to change" in
   Terraform output.
3. Modify `pipelines/github_repos.yml` (add a comment or change `per_page`), then re-deploy:
   - Content hash should change → `gcloud builds submit` should run again
   - A new image ID should appear in Artifact Registry
4. Confirm the `dcf-job-github-repos` Cloud Run job is updated to use the new image — not
   duplicated (still one job after second deploy).
5. Confirm the DAG file in GCS is updated (content matches current schedule).

Phase 2 success: second deploy with unchanged files skips Cloud Build; a file change triggers
a rebuild; the Cloud Run job is updated in-place, not duplicated.

### Phase 3 — GCP Airflow Stack

**Prerequisites:**
- `airflow_admin_password` must be set in `project.yml` before this phase.
- Cloud SQL Admin API must be enabled: `gcloud services enable sqladmin.googleapis.com`
- Cloud Run must have permission to connect to Cloud SQL (granted via Terraform in the module)

1. Deploy `github_repos` — this time, the `airflow_gcp/` Terraform module also runs:
   ```bash
   DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run dcf deploy github_repos
   ```
   Note: Cloud SQL provisioning takes 5–10 minutes on first deploy. This is expected.
2. Confirm Cloud SQL instance was created:
   ```bash
   gcloud sql instances list --project <project_id>
   # Expected: dcf-airflow-db  RUNNABLE  POSTGRES_15
   ```
3. Confirm Cloud Run Airflow service was created:
   ```bash
   gcloud run services list --region <region> --project <project_id>
   # Expected: dcf-airflow  running  min-instances=1
   ```
4. Get the Airflow Cloud Run service URL from the deploy output or:
   ```bash
   gcloud run services describe dcf-airflow --region <region> --format="value(status.url)"
   ```
5. Open the Airflow URL in a browser — confirm the UI loads (login: admin /
   `airflow_admin_password` from `project.yml`).
   Note: First load may take 30–60 seconds as Airflow initializes its DB on startup.
6. Confirm the `github_repos` DAG appears in the Airflow UI (GCS FUSE mounts
   `gs://<bucket>/airflow/dags/` at `/opt/airflow/dags` inside the container — DAG should
   appear within ~30s of the scheduler polling cycle).
7. Manually trigger the `github_repos` DAG via the Airflow UI.
8. Monitor the DAG run until it completes. If it fails, check Cloud Run job logs:
   ```bash
   gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=dcf-job-github-repos" \
     --limit=50 --format=text
   ```
9. After successful DAG run, verify data in GCS:
   ```bash
   gsutil ls gs://<warehouse-bucket>/github_repos/github_repos/data/
   ```
10. Confirm deployment state is written to `project.yml` under `deployments.github_repos`:
    - `schedule`, `dag_id`, `cloud_run_job`, `airflow_url`, `deployed_at`
11. Run `dcf deploy github_repos` a second time — Airflow stack should NOT be reprovisioned:
    ```bash
    # Terraform should show 0 changes for airflow module resources
    # Cloud SQL instance should still show the same instance name (not recreated)
    ```

Phase 3 success: Cloud SQL + Cloud Run Airflow provisioned on first deploy; Airflow UI
accessible at Cloud Run URL; `github_repos` DAG appears in UI; manual DAG trigger executes
`dcf-job-github-repos` and writes data to GCS; second deploy leaves Airflow stack unchanged.

### Phase 4 — GCP Undeploy and Airflow Teardown

1. Run `dcf undeploy github_repos`:
   ```bash
   DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run dcf undeploy github_repos
   ```
2. Confirm the Cloud Run pipeline job is removed:
   ```bash
   gcloud run jobs list --region <region>
   # Expected: dcf-job-github-repos absent
   ```
3. Confirm the DAG file is removed from GCS:
   ```bash
   gsutil ls gs://<bucket>/airflow/dags/
   # Expected: empty (or CommandException: One or more URLs matched no objects)
   ```
4. Since `github_repos` was the only deployed pipeline, confirm the Airflow Cloud Run service
   and Cloud SQL instance are also destroyed:
   ```bash
   gcloud run services list --region <region>
   # Expected: dcf-airflow absent
   gcloud sql instances list --project <project_id>
   # Expected: dcf-airflow-db absent (or DELETING)
   ```
5. Confirm Terraform state directories are removed:
   ```bash
   ls ~/.dcf/terraform/pipelines/github_repos/gcp/
   # Expected: No such file or directory
   ls ~/.dcf/terraform/airflow/gcp/
   # Expected: No such file or directory
   ```
6. Confirm GCS warehouse data is untouched:
   ```bash
   gsutil ls gs://<warehouse-bucket>/github_repos/github_repos/data/
   # Expected: Parquet files from Phase 3 DAG run still present
   ```
7. To test the "partial undeploy" case (Airflow stays up when other pipelines remain):
   - Deploy a second pipeline (e.g., copy `github_repos.yml` as `github_repos_2.yml`)
   - `dcf deploy github_repos_2`
   - `dcf undeploy github_repos` (not the second pipeline)
   - Confirm Airflow Cloud Run and Cloud SQL remain running (second pipeline's DAG still in GCS)
   - `dcf undeploy github_repos_2`
   - Confirm Airflow Cloud Run and Cloud SQL are now destroyed (no DAG files remain)

Phase 4 success: undeploy removes the Cloud Run job, DAG file, Terraform state, and — when
the last pipeline is undeployed — the Airflow Cloud Run service and Cloud SQL instance. GCS
warehouse data is never touched. Partial undeploy leaves Airflow running.

## Success Criteria

- [ ] Phase 1: `dcf deploy github_repos` (GCP) exits 0; no Composer references in output
- [ ] Phase 1: `gcloud run jobs list` shows `dcf-job-github-repos` (NOT `pvc-job-github-repos`)
- [ ] Phase 1: `gsutil ls gs://<bucket>/airflow/dags/` shows `github_repos.py`
- [ ] Phase 1: `gsutil cat gs://<bucket>/airflow/dags/github_repos.py` contains `CloudRunExecuteJobOperator`
- [ ] Phase 1: `terraform show` at pipeline state dir shows `google_cloud_run_v2_job.pipeline`; no `google_storage_bucket_object.dag`
- [ ] Phase 1: Manual `gcloud run jobs execute dcf-job-github-repos` runs to completion
- [ ] Phase 1: Parquet files written to `gs://<bucket>/github_repos/github_repos/data/` after manual job execution
- [ ] Phase 1: `dcf undeploy github_repos` removes Cloud Run job and GCS DAG file; warehouse data untouched
- [ ] Phase 2: Second `dcf deploy github_repos` with unchanged files does NOT trigger `gcloud builds submit`
- [ ] Phase 2: Modifying a pipeline file triggers a Cloud Build rebuild on next deploy
- [ ] Phase 2: Cloud Run job is updated in-place after rebuild (one job, not two)
- [ ] Phase 3: Cloud SQL instance `dcf-airflow-db` created on first GCP deploy
- [ ] Phase 3: Cloud Run Airflow service `dcf-airflow` created with min-instances=1, gen2 execution environment
- [ ] Phase 3: Airflow UI accessible at Cloud Run HTTPS URL
- [ ] Phase 3: `github_repos` DAG appears in Airflow UI within ~30s of deploy
- [ ] Phase 3: Manually triggering DAG executes `dcf-job-github-repos`; data written to GCS warehouse
- [ ] Phase 3: Second `dcf deploy` does not reprovision Cloud SQL or Cloud Run Airflow service
- [ ] Phase 4: `dcf undeploy github_repos` (last pipeline): Cloud Run Airflow + Cloud SQL destroyed
- [ ] Phase 4: Airflow state directory removed (`~/.dcf/terraform/airflow/gcp/` gone)
- [ ] Phase 4: GCS warehouse data untouched after full undeploy
- [ ] Phase 4: Partial undeploy (one of two pipelines) leaves Airflow running

## Known Complexity

- **Cloud SQL provisioning time:** First `terraform apply` for the `gcp/airflow/` module will
  take 5–10 minutes waiting for Cloud SQL to become RUNNABLE. This is normal GCP behavior.
  Print a progress message before Terraform runs. Do not treat timeout or long wait as a bug.

- **GCS FUSE mount + Cloud Run gen2:** Cloud Run gen2 is required for GCS volume mounts.
  The Terraform resource may require `launch_stage = "BETA"` depending on the google provider
  version. If Terraform rejects the GCS volume mount config, add `launch_stage = "BETA"` as
  a known finding.

- **IAM propagation delay:** After Terraform grants `roles/cloudsql.client` to the Cloud Run
  SA, there may be a 30–60 second propagation window before Cloud Run can connect to Cloud SQL.
  Airflow will retry DB connections on startup; if the Airflow service fails immediately, wait
  60 seconds and check again before diagnosing.

- **`pvc-job-` → `dcf-job-` rename:** If a previous Terraform state at
  `~/.dcf/terraform/pipelines/github_repos/gcp/` references a resource named `pvc-job-...`,
  Terraform will plan to destroy the old job and create a new `dcf-job-...` one. This is
  correct behavior. If `_import_existing_cloud_run_job()` tries to import using the old name,
  it will need updating. Note this as a Migration finding, not a bug.

- **Cloud SQL deletion protection:** The `google_sql_database_instance` resource has
  `deletion_protection = false` in the design. If the GCP project has org-level deletion
  protection policies, `terraform destroy` may fail. Note this as an environment-specific
  finding.

- **Artifact Registry repo creation:** `_ensure_artifact_registry_repo()` must run before
  `gcloud builds submit`. If this Python call is removed or skipped in the refactor, Cloud
  Build will fail to push the image. Watch for this in Phase 1.

- **Cloud SQL Auth Proxy vs. direct VPC:** The `dcf-airflow` Cloud Run service connects to
  Cloud SQL via socket path (`/cloudsql/<instance-connection-name>`). This requires the
  Cloud Run service to declare the Cloud SQL instance in its config. If the connection string
  uses a TCP host instead, the connection will fail with a "connection refused" error.

## Known Expected Findings (Pre-identified)

- **Blocking (expected):** `dcf/infra/modules/gcp/batch_pipeline/main.tf` currently has a
  `google_storage_bucket_object.dag` resource (old Composer-based design). The new design
  removes this resource. Until the module is rewritten, `dcf deploy` (GCP) will still try to
  create a DAG object in the Composer bucket. Document as Blocking finding.

- **Blocking (expected):** `gcp/batch_deploy.py` currently calls
  `_find_or_create_composer_env()` — this function will be removed in the rewrite. Until
  removed, `dcf deploy` (GCP) will fail trying to find/create a Composer environment. Document
  as Blocking finding.

- **Major (expected):** Cloud Run job may still be named `pvc-job-github-repos` if the
  `"pvc-job-${var.pipeline_name}"` string in `batch_pipeline/main.tf` is not updated to
  `"dcf-job-${var.pipeline_name}"`. This will fail Phase 1 success criterion. Document as
  Major finding and stop.

- **Minor (possible):** `dag_bucket`, `dag_blob_name`, and `dag_content` variables may still
  exist in `batch_pipeline/variables.tf` from the old design. If not removed, Terraform will
  error when the Python caller doesn't pass them. Document as Minor finding.

- **Enhancement (likely):** GCS FUSE DAG propagation to Airflow scheduler may be slower than
  30 seconds if the GCS FUSE mount has a different cache TTL than the local filesystem.
  If DAGs take >60s to appear, note the observed latency as an Enhancement finding.

## Credentials Required

- `catalog: gcp` in `project.yml`
- `gcp.project_id`, `gcp.region`, `gcp.warehouse_bucket`, `gcp.sa_email` in `project.yml`
- GCP authenticated via `gcloud auth application-default login`
- `airflow_admin_password` set manually in `project.yml` before Phase 3

**Additional GCP APIs required:**
```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  servicenetworking.googleapis.com
```

## By Design Decisions from Prior Runs

(None yet — first run of this scenario)

## Notes for Agent

- This scenario tests **unimplemented feature code**. Expect Phase 1 to surface Blocking
  findings about the stale Composer references in `batch_deploy.py` and `batch_pipeline/main.tf`.
  Document them and stop — do not attempt to work around missing Terraform resources by running
  manual `gcloud` commands.
- Full command prefix: `DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run dcf <command>`
- Use the `github_repos` pipeline pointed at `https://api.github.com/orgs/apache/repos` — no
  auth required, keeps data fetching simple and isolates failures to the deployment layer.
- Record the exact Cloud Run job name returned by `gcloud run jobs list` in your findings.
  If it shows `pvc-job-...` rather than `dcf-job-...`, that is a pre-identified Major finding.
- For Phase 3, add `airflow_admin_password: "testpassword123"` to `project.yml` before
  deploying. The fernet key and DB password should be auto-generated and written back — verify
  they appear in `project.yml` after the first deploy.
- Cloud SQL provisioning in Phase 3 takes 5–10 minutes. If the deploy command appears to hang
  after printing "Provisioning Cloud SQL...", wait up to 10 minutes before diagnosing.
- For Phase 3 DAG execution, prefer triggering manually from the Airflow UI over waiting for
  the `0 8 * * *` schedule.
- If Phase 4's Airflow teardown fails because Cloud SQL deletion is protected by org policy,
  note the GCP project's org constraints in your findings.
- Check Cloud Run logs for the pipeline job if Phase 3 DAG execution fails:
  ```bash
  gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=dcf-job-github-repos" \
    --limit=50 --project <project_id> --format=text
  ```
