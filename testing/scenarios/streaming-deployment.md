# Scenario: Streaming Pipeline Deployment

## Goal

Test the full streaming deployment lifecycle: a pipeline YAML with a Pub/Sub source
and `deploy: type: streaming` block is validated, deployed to GCP via `dcf deploy`,
and a long-running Apache Beam job on Dataflow subscribes to the Pub/Sub topic,
projects each message through the pipeline schema, and writes windowed Parquet files
to the GCS warehouse. Then verify that re-deploying is idempotent and `dcf undeploy`
drains the Dataflow job without touching warehouse data.

**This scenario tests new feature code.** The `deploy: type: streaming`,
`source: type: pubsub`, streaming Terraform module, and Beam runner do not exist yet —
the first run will surface Blocking findings that drive development of the
`streaming-deployment` feature.

**The core questions this scenario answers:**
1. Does `dcf validate` accept a `source: type: pubsub` and `deploy: type: streaming`
   block in the pipeline YAML?
2. Does `dcf deploy` provision a Dataflow streaming job (not a batch job) from the
   pipeline YAML?
3. Do messages published to Pub/Sub appear as Parquet files in the GCS warehouse?
4. Is re-deploying idempotent — no duplicate Dataflow jobs?
5. Does `dcf undeploy` drain the Dataflow job cleanly without touching warehouse data?

## Target Component

This scenario tests dcf's own CLI, GCP provisioning layer, and the new Beam runner —
not an external third-party API. The pipeline used as the test vehicle is
`click_events`: a flat JSON event with five fields, no nesting, no cadence axes,
keeping schema complexity minimal so failures isolate to the streaming infrastructure.

## Target API

**GCP Pub/Sub** — the streaming data source.

Test topic: `dcf-test-clicks`
Test subscription: `dcf-test-clicks-sub`

Provision before Phase 2:
```bash
gcloud pubsub topics create dcf-test-clicks --project <project_id>
gcloud pubsub subscriptions create dcf-test-clicks-sub \
  --topic dcf-test-clicks --project <project_id>
```

Message format (JSON, one per Pub/Sub message):
```json
{
  "event_id": "evt-001",
  "user_id": 42,
  "action": "click",
  "page": "/pricing",
  "timestamp": "2026-05-12T10:00:00Z"
}
```

Publish test messages via:
```bash
gcloud pubsub topics publish dcf-test-clicks \
  --message '{"event_id":"evt-001","user_id":42,"action":"click","page":"/pricing","timestamp":"2026-05-12T10:00:00Z"}' \
  --project <project_id>
```

## Test Phases

### Phase 1 — Pipeline YAML with streaming source and deploy block

1. Write `pipelines/click_events.yml` in the test clone:
   ```yaml
   version: 1
   name: click_events
   description: Clickstream events from the product UI

   source:
     type: pubsub
     subscription: projects/<project_id>/subscriptions/dcf-test-clicks-sub

   schema:
     columns:
       - name: event_id
         path: event_id
         type: string
       - name: user_id
         path: user_id
         type: integer
       - name: action
         path: action
         type: string
       - name: page
         path: page
         type: string
       - name: timestamp
         path: timestamp
         type: timestamp

   build:
     strategy: append

   deploy:
     type: streaming
     window_seconds: 60
   ```
2. Run `dcf validate click_events` — does it accept `source.type: pubsub` and
   `deployment.type: streaming` without error?
3. Verify the schema is checked: remove a required field (e.g. `type:` from a column)
   and confirm validate rejects it, then restore.
4. Run `dcf validate github_repos` (an existing batch pipeline) — confirm no regression.

Phase 1 success: `dcf validate click_events` passes and rejects malformed YAML with a
clear error. Batch pipeline validation is unaffected.

### Phase 2 — Prerequisites and `dcf deploy` provisions Dataflow via Terraform

1. Verify prerequisites:
   - `gcloud auth list` — authenticated
   - `catalog: gcp` in `project.yml`
   - `dcf gcp setup` completed (warehouse bucket exists)
   - Pub/Sub API enabled: `gcloud services list --enabled | grep pubsub`
   - Dataflow API enabled: `gcloud services list --enabled | grep dataflow`
   - Artifact Registry API enabled: `gcloud services list --enabled | grep artifactregistry`
   - Cloud Build API enabled: `gcloud services list --enabled | grep cloudbuild`
   - Create the test topic and subscription (if not already present):
     ```bash
     gcloud pubsub topics create dcf-test-clicks --project <project_id>
     gcloud pubsub subscriptions create dcf-test-clicks-sub \
       --topic dcf-test-clicks --project <project_id>
     ```
2. Run `dcf deploy click_events` — record the full output.
3. Check what was provisioned:
   - Dataflow job: `gcloud dataflow jobs list --region us-central1 --project <project_id>`
   - Confirm the job state is `JOB_STATE_RUNNING` (streaming jobs run continuously)
4. Check `project.yml` — was `deployments.click_events` written with `type`,
   `subscription`, `dataflow_job_id`, and `deployed_at`?
5. **Verify Terraform state** — confirm resources were provisioned via the
   `streaming_pipeline` Terraform module:
   ```bash
   ls ~/.dcf/terraform/pipelines/click_events/
   # Expected: main.tf  outputs.tf  terraform.tfstate  terraform.tfvars.json  variables.tf
   terraform -chdir=~/.dcf/terraform/pipelines/click_events show
   # Expected output contains:
   #   google_dataflow_flex_template_job.pipeline
   ```
6. Confirm `dcf deploy` on a pipeline without `deployment:` block exits with a clear error.
7. Confirm `dcf deploy` without `catalog: gcp` exits with a clear error.

Phase 2 success: `dcf deploy click_events` completes, a Dataflow job is running,
`project.yml` records the deployment state, and Terraform state at
`~/.dcf/terraform/pipelines/click_events/` contains the Dataflow job resource.

### Phase 3 — Message ingestion and data verification

1. Wait 30 seconds after deploy for the Dataflow job to reach `JOB_STATE_RUNNING`
   and for the Pub/Sub subscriber to initialize.
2. Publish 10 test messages across a range of user IDs and actions:
   ```bash
   for i in $(seq 1 10); do
     gcloud pubsub topics publish dcf-test-clicks \
       --message "{\"event_id\":\"evt-$(printf '%03d' $i)\",\"user_id\":$((i % 5 + 1)),\"action\":\"click\",\"page\":\"/page-$i\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"}" \
       --project <project_id>
   done
   ```
3. Wait for the window to close — the pipeline is configured with `window_seconds: 60`,
   so wait at least 70 seconds after publishing.
4. Check GCS for output files:
   ```bash
   gsutil ls "gs://<warehouse-bucket>/click_events/click_events/data/"
   ```
5. Query the warehouse:
   ```bash
   DCF_PROJECT_DIR=$CLONE uv --directory /path/to/dcf run python -c \
     "from dcf.warehouse_reader import query; print(query('SELECT COUNT(*), MIN(event_id), MAX(event_id) FROM click_events.click_events'))"
   ```
6. Verify all 10 messages are present and the `timestamp` field is correctly typed.

Phase 3 success: at least 10 rows appear in the warehouse within 2 minutes of publishing.

### Phase 4 — Idempotency and teardown

1. Run `dcf deploy click_events` a second time — same pipeline YAML, no changes.
2. Confirm no second Dataflow job was created — there should be exactly one
   `JOB_STATE_RUNNING` job:
   ```bash
   gcloud dataflow jobs list --region us-central1 --project <project_id> \
     --filter="name:dcf-job-click-events AND state=JOB_STATE_RUNNING"
   ```
   (Count must be 1.)
3. Confirm the Terraform state directory still exists and shows exactly one managed
   resource: `terraform -chdir=~/.dcf/terraform/pipelines/click_events show`
4. Run `dcf undeploy click_events`.
5. Confirm the Dataflow job was **drained** (not cancelled) — check job history:
   ```bash
   gcloud dataflow jobs list --region us-central1 --project <project_id> \
     --filter="name:dcf-job-click-events"
   # Expected state: JOB_STATE_DRAINED (not JOB_STATE_CANCELLED)
   ```
   Drain flushes in-flight messages to GCS before stopping; cancel discards them.
6. **Verify Terraform state directory was removed** by `dcf undeploy`:
   ```bash
   ls ~/.dcf/terraform/pipelines/click_events/
   # Expected: No such file or directory
   ```
7. Confirm warehouse data is NOT deleted — GCS Parquet files remain:
   ```bash
   gsutil ls "gs://<warehouse-bucket>/click_events/click_events/data/"
   ```
8. Confirm `deployments.click_events` is removed from `project.yml`.
9. Clean up the test Pub/Sub resources:
   ```bash
   gcloud pubsub subscriptions delete dcf-test-clicks-sub --project <project_id>
   gcloud pubsub topics delete dcf-test-clicks --project <project_id>
   ```

Phase 4 success: second deploy is idempotent (Terraform applies a diff, not a
duplicate); undeploy drains the Dataflow job and removes the state dir without
touching warehouse data.

## Success Criteria

- [ ] Phase 1: `dcf validate click_events` accepts `source.type: pubsub` and `deployment.type: streaming`
- [ ] Phase 1: `dcf validate` rejects malformed YAML with a clear error message
- [ ] Phase 1: `dcf validate` on an existing batch pipeline is unaffected (no regression)
- [ ] Phase 2: `dcf deploy click_events` completes without error
- [ ] Phase 2: Dataflow job state is `JOB_STATE_RUNNING` after deploy
- [ ] Phase 2: `project.yml` records `deployments.click_events` with type, subscription, dataflow_job_id
- [ ] Phase 2: `dcf deploy` on a pipeline with no `deployment:` block exits with a clear error
- [ ] Phase 2: `dcf deploy` without `catalog: gcp` exits with a clear error
- [ ] Phase 2: Terraform state exists at `~/.dcf/terraform/pipelines/click_events/terraform.tfstate`
- [ ] Phase 2: `terraform show` lists `google_dataflow_flex_template_job.pipeline`
- [ ] Phase 3: All 10 published messages appear in the warehouse within 2 minutes
- [ ] Phase 3: Parquet files appear in `gs://<warehouse-bucket>/click_events/click_events/data/`
- [ ] Phase 3: `timestamp` column is correctly typed (not stored as string)
- [ ] Phase 4: Second `dcf deploy` produces exactly one running Dataflow job (idempotent)
- [ ] Phase 4: `dcf undeploy click_events` drains the job (state: `JOB_STATE_DRAINED`)
- [ ] Phase 4: Terraform state directory is removed after `dcf undeploy`
- [ ] Phase 4: GCS data files are untouched after `dcf undeploy`

## Known Complexity

- **Dataflow Flex Template build:** Streaming Dataflow jobs use Flex Templates — the Beam
  pipeline is packaged as a container image and launched from a template spec. This
  requires Cloud Build + Artifact Registry (same as batch) plus generating a Flex
  Template JSON spec and uploading it to GCS. More moving parts than the batch Cloud Run
  job approach.
- **Beam Python SDK in the container:** The container image must include `apache-beam[gcp]`
  which is ~300 MB. Cloud Build will download it on every image build unless layer caching
  is configured. First deploy will be slow (5–10 minutes).
- **Dataflow job startup time:** After `dcf deploy` completes, the Dataflow job takes
  2–4 minutes to reach `JOB_STATE_RUNNING`. The deploy command should poll and print
  progress, similar to how `_find_or_create_composer_env()` polls in the batch path.
- **Windowing:** Beam's fixed-time windows determine how often messages are flushed to GCS.
  A 60-second window means messages published at T+0 first appear in GCS at T+60 (after
  the window closes and the trigger fires). The test must wait for the full window to close
  before checking GCS.
- **Pub/Sub message ordering:** Pub/Sub does not guarantee ordering by default.
  The `event_id` field can be used to verify all messages arrived, but order in GCS
  files may differ from publish order.
- **Drain vs cancel:** Streaming Dataflow jobs must be drained (not cancelled) for clean
  shutdown — drain flushes buffered messages in the in-flight window to GCS first.
  Drain takes 1–5 minutes. `dcf undeploy` must call drain and poll until the job reaches
  `JOB_STATE_DRAINED` before removing Terraform state.
- **Schema projection in streaming:** dcf's current `projector.py` is designed to operate
  on a list of dicts from an HTTP response batch. In streaming, it must operate on
  individual Pub/Sub messages decoded as JSON. This requires a streaming-aware projection
  layer in the Beam pipeline code.
- **`append` strategy only:** Streaming pipelines cannot use `incremental` (upsert)
  strategy — there is no batch to deduplicate within. The pipeline YAML must use
  `cadence.strategy: append`. `dcf validate` should reject `strategy: incremental` on a
  streaming pipeline with a clear error.

## Known Expected Findings (Pre-identified)

All of the following are expected Blocking findings on the first run, because streaming
is entirely unimplemented. Document them and stop — do not attempt to work around
missing CLI commands by writing custom Python.

- **Blocking:** `source.type: pubsub` is not a valid source type — `models.py` only
  knows `http` and `python`. `dcf validate` will reject the pipeline YAML.
- **Blocking:** `deployment.type` is not a field in the `Deploy` model — `models.py` only
  has `schedule` and `paused`. Validate will reject `type: streaming`.
- **Blocking:** `dcf deploy` has no streaming code path — it always provisions via the
  batch path (Cloud Build + Cloud Run + Terraform `batch_pipeline` module).
- **Blocking:** No `streaming_pipeline` Terraform module exists at
  `dcf/infra/modules/gcp/streaming_pipeline/`. The batch module provisions
  `google_cloud_run_v2_job`; the streaming module must provision
  `google_dataflow_flex_template_job`.
- **Blocking:** No Beam runner code exists in dcf — there is no Beam pipeline that reads
  from Pub/Sub, applies schema projection, and writes windowed Parquet to GCS.
- **Major:** `dcf undeploy` uses `terraform destroy`, which for a Dataflow job will call
  cancel (not drain). A dedicated drain + poll sequence is needed before `terraform destroy`.

## Credentials Required

No new credential keys beyond what `gcp-data-lake` already uses:

- `catalog: gcp` — set in `testing/test_config.yml`
- `gcp.project_id` and `gcp.region` — set in `testing/test_config.yml`
- GCP authenticated via `gcloud auth application-default login`
- `gcp.warehouse_bucket` — set after `dcf gcp setup` completes

**Additional GCP APIs that must be enabled before this scenario runs:**
```bash
gcloud services enable dataflow.googleapis.com
gcloud services enable pubsub.googleapis.com
gcloud services enable artifactregistry.googleapis.com
gcloud services enable cloudbuild.googleapis.com
```

Note these in `test_config.yml.example` as GCP prerequisite comments (same pattern
as the batch-deployment scenario comment block), not as new keys.

## By Design Decisions from Prior Runs

(None yet — first run of this scenario)

## Notes for Agent

- This scenario tests **entirely unimplemented feature code**. Every Phase 1 and Phase 2
  step will produce Blocking findings. Document them precisely and stop — do not
  work around missing schema fields or CLI commands by writing custom Python.
- Use `click_events` as the test pipeline — flat JSON, no nesting, no cadence axes.
  Isolates all failures to the streaming infrastructure layer.
- The CLONE for this scenario should have `catalog: gcp`, a valid `gcp.warehouse_bucket`,
  and `gcp.setup_status: complete` in `project.yml` — same config as `gcp-data-lake`
  and `batch-deployment`.
- When Phase 2 produces Blocking findings, record the exact error message for each.
  The findings together define the implementation roadmap for the streaming-deployment
  feature.
- For Phase 3 timing: publish messages, then wait at least `window_seconds + 10` seconds
  (70s for the default 60s window) before querying GCS. Dataflow windows close on wall
  clock time, not message count.
- Dataflow drain (Phase 4) takes 1–5 minutes. Poll `gcloud dataflow jobs describe
  <job_id> --format "value(currentState)"` until it reaches `JOB_STATE_DRAINED`.
- The Pub/Sub subscription `dcf-test-clicks-sub` should be cleaned up after the test
  run (Phase 4 step 9) — it is a test artifact.
- If `dcf undeploy` calls Terraform destroy directly on a Dataflow job, Terraform will
  call the GCP delete API which maps to cancel, not drain. This is a pre-identified
  finding (Major severity) — record it if observed and note the drain command:
  `gcloud dataflow jobs drain <job_id> --region us-central1 --project <project_id>`
