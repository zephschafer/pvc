# Test Run: GCP Data Lake (Remote Warehouse Round-Trip)
Date: 2026-05-10 | Tester: Claude Sonnet 4.6 | Scenario: gcp-data-lake

## Outcome: FAILURE (Phase 1 blocked; 3 additional Blocking/Major gaps found via code review)

Phase 1 (`pvc gcp setup`) could not complete because the `quipu-data-generator` GCP
project does not have billing enabled. The run was stopped at the first GCS API call.

However, code review of the GCP implementation surface revealed two additional Blocking
gaps that would prevent the happy path even with billing enabled. All findings documented below.

---

## Success Criteria

### Phase 1 — GCP Setup
- [~] `pvc gcp setup` behavior documented: command exists, credentials check passes, fails on billing
- [ ] `pvc gcp setup` completes without errors — BLOCKED (billing not enabled on quipu-data-generator)
- [ ] GCS bucket created and visible in GCP console — NOT REACHED
- [~] `project.yml` updated with GCP metadata — partial (`setup_status: failed` written)

### Phase 2 — Pipeline Run with GCP Catalog
- [ ] `pvc run` with `catalog: gcp` writes Parquet to GCS — NOT REACHED
- [ ] Incremental upsert works against GCS-backed Iceberg — NOT REACHED

### Phase 3 — Query the GCP Warehouse via MCP
- [ ] MCP `query_warehouse` reads from correct location (GCS or local) — NOT REACHED
  (code review confirms it would fail: `warehouse_reader.py` is local-only)
- [ ] Query returns correct data — NOT REACHED

### Phase 4 — Teardown
- [~] GCP resources cleaned up — partial (no GCS bucket was created; project.yml reset to `catalog: local`)

---

## Phase 1: What Happened

### Prerequisites: PASS

- `terraform`: installed (v1.9.8 at `/opt/homebrew/bin/terraform`) ✓
- `gcloud`: installed, authenticated as `zephyr.schafer@gmail.com` ✓
- `pvc gcp setup --help`: works, shows required `--project-id` and `--region` flags ✓

### `pvc gcp setup` execution: FAIL at first step

Running `pvc gcp setup --project-id quipu-data-generator --region us-central1`:

```
Checking Google credentials...
Credentials OK.
Creating Terraform state bucket...

Setup failed: 403 POST https://storage.googleapis.com/storage/v1/b?project=quipu-data-generator&prettyPrint=false: The billing account for the owning project is disabled in state absent
```

**Root cause:** `quipu-data-generator` GCP project does not have billing enabled.

**Error quality assessment:**
- ✓ "Setup failed:" prefix is clean — not a raw traceback shown to user
- ✗ No actionable guidance: user is not told to go to console.cloud.google.com/billing
- ✗ The full stack trace (2000 chars) IS saved to `project.yml` as `setup_error` — pollutes user's config file
- ✗ `project.yml` now shows `setup_status: failed` with embedded multiline traceback in YAML
  **→ Finding F-014 (Minor / UX)**

---

## Phase 2-3: Code Review Findings (Would Block Even with Billing)

### F-011: Terraform `.tf` files missing from repository (Blocking)

`pvc/gcp/terraform.py` line 10:
```python
_MODULE_DIR = Path(__file__).parent.parent / "infra" / "modules" / "gcp"
```

This resolves to `pvc/pvc/infra/modules/gcp/`. This directory does not exist anywhere in the pvc repository. No `.tf` files exist anywhere in pvc (confirmed via `find`).

`terraform.provision()` copies `*.tf` files from `_MODULE_DIR` to a work directory, then runs `terraform init` and `terraform apply`. With no `.tf` files, Terraform would initialize an empty configuration and `apply` would do nothing — then fail at `terraform output warehouse_bucket` because there is no `warehouse_bucket` output defined.

Even with billing enabled, `pvc gcp setup` would fail at the Terraform step.
**→ Finding F-011 (Blocking / Runtime)**

### F-012: No GCP Spark catalog configured (Blocking)

`spark_session.py` `get_spark()` configures ONLY the `local` catalog:
```python
.config("spark.sql.catalog.local", "org.apache.iceberg.spark.SparkCatalog")
.config("spark.sql.catalog.local.type", "hadoop")
.config("spark.sql.catalog.local.warehouse", str(warehouse_path))
```

No `gcp` catalog is configured. Additionally, no GCS connector JAR is referenced
(required for Spark to write to GCS: `gs://...` paths).

In `iceberg.py`, when `catalog = "gcp"`:
```python
warehouse_root = Path(spark.conf.get(f"spark.sql.catalog.{catalog}.warehouse"))
# → spark.conf.get("spark.sql.catalog.gcp.warehouse") → KeyError or empty string
```

This would crash the write step. Even if setup produced a valid GCS bucket, pipelines
with `catalog: gcp` cannot write to it.
**→ Finding F-012 (Blocking / Runtime)**

### F-013: `warehouse_reader.py` is local-only (Major, MCP)

```python
def _warehouse() -> Path:
    from .project import find_project_root
    return find_project_root() / "warehouse"
```

This always reads from the local `warehouse/` directory. There is no code path that
reads from GCS. The MCP `query_warehouse` tool uses this reader, so it cannot query
GCS-backed data regardless of `catalog` setting in `project.yml`.

To support GCS, `warehouse_reader.py` would need to:
1. Read `catalog` from `project.yml`
2. When `catalog: gcp`, build `gs://bucket/.../*.parquet` paths
3. Configure DuckDB with GCS credentials before calling `read_parquet()`
**→ Finding F-013 (Major / MCP)**

### F-015: No `pvc gcp teardown` command (Minor)

The CLI has `gcp setup` and `gcp status` but no `gcp teardown` or `gcp destroy`.
Users have no automated way to clean up GCP resources. They must manually:
- Delete the GCS warehouse bucket via `gsutil`
- Delete the Terraform state bucket
- Delete the service account via IAM console
- Delete the Secret Manager secret

The scenario expected a teardown command. There is none.
**→ Finding F-015 (Minor / UX)**

### F-016: README does not document Terraform prerequisite (Minor)

The README's GCP section:
```bash
gcloud auth application-default login
uv run pvc gcp setup --project-id my-project --region us-central1
uv run pvc gcp status
```

Missing from the docs:
- `terraform` must be installed (v1.x)
- GCP project must have billing enabled
- Required GCP APIs must be enabled (Storage, IAM, Secret Manager)

While Terraform IS installed in this test environment, the docs don't mention it as a prerequisite. A user following the README verbatim would not install Terraform before running `gcp setup`.
**→ Finding F-016 (Minor / UX)**

### F-017: `bootstrap.py` hardcodes `quipu-lake` service account name (Minor)

```python
_SA_ACCOUNT_ID = "quipu-lake"
_SECRET_ID     = "quipu-lake-sa-key"
```

These names are hardcoded to "quipu" — the former internal project name for pvc.
If two pvc user projects share the same GCP project, both would try to create and
modify the same service account and secret, causing conflicts. The service account
name should be derived from the pvc project name or configurable.
**→ Finding F-017 (Minor / UX)**

---

## `new-pipeline` Skill Review

The skill makes no mention of `catalog: gcp`, `pvc gcp setup`, or when to switch
to cloud mode. A user building for production has no guidance that the GCP path exists
or how to activate it. This extends existing finding F-006 (skill has no credential
guidance) to also cover the cloud deployment lifecycle.

---

## Phase 4: Teardown

No GCS bucket was created (setup failed before the Terraform step). Cleaned up
`project.yml` by removing the `gcp:` block and resetting `catalog: local`.

---

## Confirmed Findings Summary

| Finding | Expected? | Status |
|---------|-----------|--------|
| F-011: Terraform `.tf` files missing from repo | Unexpected | New (Blocking) |
| F-012: No GCP Spark catalog configured in `spark_session.py` | Expected | Confirmed (Blocking) |
| F-013: `warehouse_reader.py` reads local-only, no GCS awareness | Expected | Confirmed (Major) |
| F-014: Billing error has no actionable guidance; stack trace in project.yml | Expected | Confirmed (Minor) |
| F-015: No `pvc gcp teardown` command | Unexpected | New (Minor) |
| F-016: README doesn't mention Terraform as prerequisite | Unexpected | New (Minor) |
| F-017: `bootstrap.py` hardcodes `quipu-lake` service account name | Unexpected | New (Minor) |

---

## Proposed Fixes

1. **F-011 (Blocking):** Create the Terraform infrastructure module at `pvc/infra/modules/gcp/`
   with `main.tf` defining: GCS warehouse bucket, IAM bindings, Iceberg catalog config.
   Without this, `pvc gcp setup` cannot complete.

2. **F-012 (Blocking):** Update `spark_session.py` to accept a `catalog` param. When
   `catalog = "gcp"`, fetch GCS bucket from `project.yml` and configure:
   - `spark.sql.catalog.gcp` with GCS-backed Iceberg catalog type
   - `spark.jars.packages` must include the GCS connector JAR
   - Service account credentials injected via Hadoop config

3. **F-013 (Major):** Update `warehouse_reader.py` to read `catalog` from `project.yml`.
   When `catalog: gcp`, build `gs://bucket/{namespace}/{table}/data/*.parquet` glob paths
   and configure DuckDB with GCS credentials before `read_parquet()`.

4. **F-014 (Minor):** In `gcp/bootstrap.py`, catch `Forbidden` errors in `create_state_bucket`
   and raise a `RuntimeError` with actionable message:
   `"Billing is not enabled for project '{project_id}'. Enable it at: console.cloud.google.com/billing"`
   Also: don't save the full traceback to `project.yml` — store only the exception message.

5. **F-015 (Minor):** Add `pvc gcp teardown` command that runs `terraform destroy` and
   removes the GCS buckets and service account.

6. **F-016 (Minor):** Update README GCP section to list prerequisites:
   `terraform` (v1.x), billing enabled, APIs enabled (storage, iam, secretmanager).

7. **F-017 (Minor):** Make service account ID and secret name configurable
   (derive from project name, or accept as `--sa-name` flag).
