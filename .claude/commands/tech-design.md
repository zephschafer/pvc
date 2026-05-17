You are helping the user produce a technical design document for a dcf feature. Your job is to ask enough targeted questions to produce a precise, decision-grade design — not to write from the first sentence. Architecture discussion comes before writing.

---

## Step 1: Orient to existing context

**Check for an existing feature:**
Read `features/FEATURES.md`. If the user named a feature slug (e.g. `batch-deployment`), or if their description clearly matches a row in that table, read `features/<slug>.md` to extract the problem statement, requirements, and any existing Design Notes. This is your starting context — do not ask questions already answered there.

**Check for an existing design:**
Read `design/DESIGNS.md` if it exists. If a design doc already exists for this slug, tell the user and ask whether they want to revise it or start a new version.

**If no feature and no design exists:** proceed with what the user has told you. You will not have a feature file to anchor to.

---

## Step 2: Requirements gathering (interactive — do not skip)

Based on what you've read and what the user has told you, identify what is still unknown. Ask 3–6 targeted questions and **wait for responses before proceeding to Step 3**.

Do not ask questions already answered in the feature file or by the user. Adapt to what you know. The goal is to fill in these architectural unknowns:

- **What is the runtime boundary?** Where does dcf's code end and an external service (GCP, Beam, Airflow, etc.) begin? What process owns each step?
- **What is the local dev story?** How does a developer run this end-to-end on their laptop — same binary, a docker-compose, a simulator, or something else?
- **What is the deployed topology?** Which managed services are used, and how do they connect? What triggers what?
- **What are the seams?** Where are the interface boundaries — CLI flags, config schema fields, environment variables, inter-service protocols?
- **What are the live technology choices?** Are there alternatives that were seriously considered? Why was each choice made?
- **What changes between local and deployed?** Enumerate the differences explicitly — same code path or different? Same storage or different? Same credentials or different?

Keep questions focused on architecture, not product requirements. If a question can be answered by reading the codebase (Step 3), do that instead of asking.

---

## Step 3: Probe the codebase

Before drafting, read the relevant source files to understand existing patterns and constraints. Key locations for dcf:

- `dcf/config/models.py` — YAML schema (Collector, Source, Auth, Build, Deploy, Column types)
- `dcf/cli.py` — CLI commands and flags
- `dcf/engine/runner.py` — collector execution loop
- `dcf/engine/fetcher.py` — fetch logic
- `dcf/writer/iceberg.py` — write strategies
- `dcf/warehouse_reader.py` — query path (local and GCS)
- `dcf/gcp/` — GCP provisioning modules
- `dcf/mcp_server.py` — MCP tool surface
- `testing/scenarios/` — existing test scenarios

Note which patterns the design would reuse, which would change, and which new modules or config fields are needed.

---

## Step 4: Draft the design document

Choose a slug: short, lowercase, hyphenated. Reuse the feature slug if one exists. Examples: `batch-deployment`, `streaming-deployment`, `local-dev-runtime`.

Write `design/<slug>.md` using this structure:

```markdown
# Design: <Name>

**Status:** Draft
**ID:** <slug>
**Created:** YYYY-MM-DD
**Updated:** YYYY-MM-DD
**Feature:** [<slug>](../features/<slug>.md) <!-- omit if no feature file exists -->

---

## Context

[One paragraph. What is being designed and why. Reference the feature problem statement if a feature file exists.]

---

## Architecture Overview

[ASCII diagram showing the major components and their connections. Label each arrow with the protocol or data format (e.g. HTTP, Pub/Sub, GCS path, subprocess). Use two diagrams if local and deployed topologies differ significantly.]

**Local:**
```
[ASCII diagram]
```

**Deployed:**
```
[ASCII diagram]
```

---

## Components

For each major component (process, service, or module), describe:

### <Component Name>

| Property | Value |
|----------|-------|
| **Type** | process / service / module / config |
| **Owner** | dcf code / GCP managed / user-provided |
| **Local behavior** | [what runs locally] |
| **Deployed behavior** | [what runs in production] |
| **Entrypoint** | [CLI command, file path, or service endpoint] |

**Interface:**
- Input: [what it receives — config fields, env vars, stdin, topic message, etc.]
- Output: [what it produces — file path, GCS object, Pub/Sub message, exit code, etc.]

---

## Local vs. Deployed Parity

| Concern | Local | Deployed | Notes |
|---------|-------|----------|-------|
| Trigger | [e.g. `dcf run` CLI] | [e.g. Cloud Composer DAG] | |
| Execution | [e.g. local Python process] | [e.g. Cloud Run job] | |
| Storage | [e.g. local Iceberg path] | [e.g. GCS bucket] | |
| Credentials | [e.g. ADC via gcloud] | [e.g. Workload Identity] | |
| Config | [e.g. `collector.yml` local path] | [e.g. bundled in container] | |
| Observability | [e.g. stdout logs] | [e.g. Cloud Logging] | |

---

## Interface Contracts

### CLI

```
dcf <command> [flags]
```

| Flag / Arg | Type | Required | Description |
|------------|------|----------|-------------|
| | | | |

### Config Schema

New or changed fields in `dcf/config/models.py`:

```yaml
# Example YAML showing new fields in context
collector:
  <new-field>: <type>  # description
```

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| | | | | |

### Inter-Service Protocols

| From | To | Protocol | Payload |
|------|----|----------|---------|
| | | | |

---

## Technology Choices

| Decision | Choice | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| | | | |

---

## Open Questions

- [ ] [Question that must be resolved before implementation begins]
- [ ] ...

---

## Design Decision Log

Record decisions made during the design conversation — especially ones that could be revisited.

| Date | Decision | Rationale | Revisit If |
|------|----------|-----------|------------|
| YYYY-MM-DD | | | |
```

Fill every section. If a section genuinely does not apply (e.g. no inter-service protocols), write "N/A" and one sentence explaining why.

---

## Step 5: Update or create DESIGNS.md

If `design/DESIGNS.md` does not exist, create it:

```markdown
# dcf Design Registry

Last updated: YYYY-MM-DD | Total: 1 | Draft: 1 | Finalized: 0

## Status Definitions

| Status | Meaning |
|--------|---------|
| **Draft** | Under discussion; not yet approved for implementation |
| **Finalized** | Approved for implementation; open questions resolved |
| **Superseded** | Replaced by a newer design |

---

## Designs

| ID | Name | Status | Feature | Summary |
|----|------|--------|---------|---------|
| <slug> | <Name> | Draft | [<feature-slug>](../features/<feature-slug>.md) | <one-line summary> |

---

## Adding a Design

Run `/tech-design` in Claude Code. The skill guides you through architecture discussion and writes the design file.
```

If `design/DESIGNS.md` already exists, add a row to its table and update the header counts.

---

## Step 6: Cross-link with the feature file

If a feature file exists at `features/<slug>.md`, update its **Design Notes** section to add a reference:

```markdown
Design document: [`design/<slug>.md`](../design/<slug>.md)
```

Do not rewrite the Design Notes — just prepend the link so engineers can navigate between the two documents.

---

## Step 7: Present to the user

Tell the user:
- The design file path (`design/<slug>.md`)
- Any open questions that must be resolved before implementation
- Any interface changes that will require updates to `dcf/config/models.py` or `dcf/cli.py`
- Whether any related test scenarios should be created

Ask: is there anything to revise in the design? Iterate until they are satisfied.

---

## Step 8: Offer next steps

Once the design is finalized, offer the following (pick the ones that apply):

> **Scenario coverage:** Would you like to create a test scenario for the local run path? Run `/new-scenario <slug>` or I can do it inline.

> **Feature alignment:** The design introduced new requirements not in the feature file. Would you like me to update `features/<slug>.md` to reflect them?

> **Implementation handoff:** The design is ready. The next step is implementation. Key files to touch: [list the specific files identified in Step 3].

---

## Rules

**Do not write the design document until you have enough information from Step 2.** A design written from the first sentence will be vague, miss the local/deployed split, and require heavy revision.

**Topology first.** Always draft the ASCII diagrams before filling in the tables. The diagram forces you to name every component and every connection — gaps in the diagram reveal gaps in the design.

**Parity is not optional.** The Local vs. Deployed Parity table must be filled in even if the answer is "identical." That is itself a design decision worth recording.

**Technology choices require alternatives.** Do not record a technology choice without at least one alternative considered and a rationale. "We used X" is not a decision; "We used X instead of Y because Z" is.

**Open questions block finalization.** A design with unresolved open questions has status Draft. Only move to Finalized when all questions are resolved or explicitly deferred with a written reason.

**One design per deployment topology.** If local and deployed are fundamentally different architectures (not just configuration differences), consider whether they need separate design docs and confirm with the user.
