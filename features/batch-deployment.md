# Feature: Batch Collector Deployment

**Status:** Draft
**ID:** batch-deployment
**Feature Set:** collector-deployment
**Created:** 2026-05-11
**Updated:** 2026-05-11

## Summary

dcf collectors currently run only when a developer manually executes `dcf run`. This feature adds `dcf deploy`, a CLI command that provisions a production-grade scheduled batch job on GCP with a single command. Deployment configuration — schedule, resource overrides, and other options — lives in the collector's YAML file alongside the collector definition itself, so collector logic and deployment intent are always co-located. The deployed job runs on that schedule using Cloud Composer (managed Apache Airflow) for orchestration and Cloud Run for execution, writing results to the GCS warehouse. Infrastructure is defined in dcf's own Terraform modules — users never write Terraform directly.

## Problem

A collector that only runs manually is a development tool, not a data product. Today, making a dcf collector run automatically requires a developer to: set up a Composer environment by hand, author a DAG file, configure environment variables and credentials in GCP, wire up the Cloud Run job or Dataproc cluster, and maintain all of this independently of dcf. There is no connection between the collector definition (`collectors/my_collector.yml`) and where or how it runs in production. Teams either skip scheduling entirely (collectors stay manual) or reinvent orchestration infrastructure for each project.

## User Story

As a developer who has built and validated a dcf collector, I want to deploy it as a scheduled job with one command, so that my data lake stays current without manual intervention and I don't have to manage orchestration infrastructure separately from my collectors.

## Requirements

### Must Have

- Deployment configuration is declared in the collector YAML under a `deployment:` block (schedule, and any infrastructure overrides)
- `dcf deploy <collector-name>` reads the `deployment:` block from the collector YAML and provisions the job on GCP
- `dcf deploy` errors clearly if the collector YAML has no `deployment:` block
- The deployed job runs `dcf run <collector-name>` on the schedule declared in the collector YAML
- Infrastructure is provisioned via dcf's own Terraform modules — the user never writes Terraform
- Scheduling is handled by Cloud Composer (managed Apache Airflow); execution runs in a Cloud Run job
- The deployed job writes to the same GCS warehouse bucket configured in `project.yml`
- `dcf undeploy <collector-name>` removes the DAG and Cloud Run job without touching warehouse data
- Running `dcf deploy` on an already-deployed collector is idempotent — re-reads the collector YAML and updates the deployment to match
- Deployment state is recorded in `project.yml` under a `deployments:` key
- Requires `catalog: gcp` and a completed `dcf gcp setup` — error clearly if not

### Nice to Have

- `dcf deploy status <collector-name>` shows current deployment state and last run outcome
- `dcf deploy status` (no arg) lists all deployed collectors and their schedules
- Infrastructure overrides in the `deployment:` block (Composer environment size, Cloud Run CPU/memory, region, or execution target like Dataproc)
- `paused: true` in the `deployment:` block to provision a DAG without activating it
- Failure notifications (email or webhook) configurable in the `deployment:` block

## Acceptance Criteria

- [ ] `collectors/github_repos.yml` with a `deployment: { schedule: "0 8 * * *" }` block is accepted by `dcf validate github_repos` without error
- [ ] `dcf deploy github_repos` completes without error on a project with `catalog: gcp` and completed GCP setup
- [ ] A Cloud Composer DAG named `github_repos` is visible in the Composer UI after deploy
- [ ] The DAG triggers on the cron schedule declared in the collector YAML and runs to completion
- [ ] The collector run inside the Cloud Run job writes rows to `gs://<warehouse-bucket>/github_repos/github_repos/data/`
- [ ] `dcf undeploy github_repos` removes the DAG from Composer and the Cloud Run job; warehouse data is untouched
- [ ] Running `dcf deploy github_repos` a second time does not create a second DAG — it updates the existing one to match the current collector YAML
- [ ] `dcf deploy github_repos` on a collector YAML with no `deployment:` block exits with a clear error message
- [ ] `dcf deploy github_repos` without `catalog: gcp` in `project.yml` exits with a clear error message
- [ ] Deployment state (`schedule`, `dag_id`, `cloud_run_job`) is written to `project.yml` under `deployments.github_repos`

## Out of Scope

- Streaming collector deployment (separate feature: `streaming-deployment`)
- Non-GCP deployment targets (AWS MWAA, Azure Data Factory, on-prem Airflow)
- Multi-collector DAGs — one dcf collector maps to exactly one Composer DAG
- dbt or SQL transformation as part of the batch job (separate concern)
- Collector monitoring dashboards or alerting UIs
- Automatic retries on fetch errors (separate feature: `incremental-retry`, if defined)
- Self-hosted Airflow (Cloud Composer only for now)

## Related Scenarios

- [`testing/scenarios/batch-deployment-local.md`](../testing/scenarios/batch-deployment-local.md) — local Terraform module validation, `dcf deploy` local, DAG file writing, local Airflow Docker Compose stack lifecycle
- [`testing/scenarios/batch-deployment-gcp.md`](../testing/scenarios/batch-deployment-gcp.md) — GCP collector container via Terraform, Cloud Run job, GCS DAG write, GCP Airflow (Cloud Run + Cloud SQL) lifecycle

## Design Notes

Design document: [`design/batch-deployment.md`](../design/batch-deployment.md)

### Infrastructure default: Composer + Cloud Run

The opinionated default is:
- **Cloud Composer** (managed Apache Airflow) — orchestrates scheduling; one DAG per deployed collector
- **Cloud Run job** — executes `dcf run <collector>` in a containerized environment; stateless, billed per execution

This keeps costs proportional to collector frequency and avoids always-on cluster costs. Future YAML overrides could target Dataproc (Apache Spark) for collectors requiring cluster-scale processing.

### Terraform module

New module at `dcf/infra/modules/gcp/batch_collector/` defining:
- `google_cloud_run_v2_job` — containerized execution unit running `dcf run <name>`
- `google_composer_environment` — shared Airflow environment (created once, reused across collectors)
- `google_composer_user_workloads_config_map` — DAG config per collector
- DAG file generated by dcf and uploaded to the Composer DAGs GCS bucket

The existing Terraform workflow (`dcf/gcp/terraform.py` — `provision()` / `destroy()`) can be extended or reused. The `_MODULE_DIR` pattern already copies `.tf` files to a work directory and runs `terraform apply`.

### Container image (open question)

The Cloud Run job must run `dcf run <collector>`, which requires the dcf package, the collector YAML, any Python connectors, and project credentials. Options:

1. **User builds image from their project** — dcf generates a `Dockerfile` in the user's project (quipu), the user runs `dcf build` which builds and pushes to Artifact Registry, then `dcf deploy` references that image
2. **dcf packages the user's collectors/connectors at deploy time** — dcf zips `collectors/` and `connectors/`, uploads to GCS, Cloud Run job downloads and executes at runtime
3. **Runtime clone** — Cloud Run job clones the quipu repo from GitHub on each run (requires GitHub credentials in the job)

Option 1 is the cleanest long-term but requires a `dcf build` step. Option 2 avoids a container build but adds runtime complexity. **This is the primary open design question for implementation.**

### Collector YAML: `deployment:` block

The `deployment:` block is added to a collector's YAML alongside `source` and `cadence`. Example:

```yaml
# collectors/github_repos.yml
version: 1
name: github_repos
source: ...
cadence: ...

deployment:
  schedule: "0 8 * * *"   # cron — required
  paused: false            # optional, default false
  # Future overrides:
  # cloud_run:
  #   cpu: 2
  #   memory: 2Gi
  # execution_target: dataproc  # override from default Cloud Run
```

The `deployment:` block requires a `Deployment` model in `dcf/config/models.py` and a `Collector.deployment` optional field. `dcf validate` should check that `schedule` is a valid cron expression when a `deployment:` block is present.

### CLI surface

New commands in `dcf/cli.py` (following the existing typer sub-app pattern — see `gcp_app`):
```
dcf deploy <name>          # reads deploy: block from collector YAML, provisions GCP job
dcf undeploy <name>        # tears down Composer DAG + Cloud Run job
dcf deploy status [<name>] # shows deployment state from project.yml
```

### State in project.yml

```yaml
deployments:
  github_repos:
    schedule: "0 8 * * *"
    dag_id: github_repos
    cloud_run_job: dcf-job-github-repos
    deployed_at: "2026-05-11T08:00:00"
```

### GCP prerequisites

- `catalog: gcp` set in `project.yml`
- `dcf gcp setup` completed (SA, warehouse bucket, Secret Manager key)
- Cloud Composer API enabled (`composer.googleapis.com`)
- Cloud Run API enabled (`run.googleapis.com`)
- Artifact Registry API enabled (`artifactregistry.googleapis.com`) — if using container image approach
