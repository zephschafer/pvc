# pvc Feature Registry

Last updated: 2026-05-11 | Total: 1 | Active: 0 | Complete: 0 | Draft: 1

## Status Definitions

| Status | Meaning |
|--------|---------|
| **Draft** | Requirements being gathered; not yet approved for development |
| **Active** | In development or recently shipped; acceptance criteria not yet all passing |
| **Complete** | Implemented, tested, and all acceptance criteria verified |

---

## Features

## Feature Sets

| Feature Set | Features |
|-------------|---------|
| pipeline-deployment | batch-deployment, streaming-deployment (planned) |

---

## Features

| ID | Name | Status | Summary | Scenarios |
|----|------|--------|---------|-----------|
| batch-deployment | Batch Pipeline Deployment | Draft | Deploy any pvc pipeline as a scheduled GCP batch job with one CLI command (Composer + Cloud Run) | batch-deployment |

---

## Adding a Feature

Run `/new-feature` in Claude Code. The skill guides you through requirements gathering and writes the feature file.

To add a feature manually, create `features/<slug>.md` following the template structure described in `features/README.md`, then add a row to the table above.
