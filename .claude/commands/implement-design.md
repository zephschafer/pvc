You are helping the user plan the implementation of a ddt technical design and produce test scenarios to validate it. Your job is to read the design thoroughly, ask enough questions to phase the work correctly, and produce two artifacts: a precise implementation plan and one or more test scenarios compatible with the `/test-feature` skill.

Do not write implementation code. Your outputs are the plan and the scenarios — not the code itself.

---

## Arguments

The design slug is passed as an argument (e.g. `/implement-design batch-deployment`). If no argument is given, list the files in `design/` and ask the user which design to plan.

---

## Step 1: Read all context

Read the following before doing anything else:

1. **`design/<slug>.md`** — the technical design. This is your primary input. Pay particular attention to: Architecture Overview (ASCII diagrams), Local vs. Deployed Parity table, Interface Contracts, Technology Choices, and Open Questions.
2. **`features/<slug>.md`** — the feature file, if it exists. The Acceptance Criteria define what "done" means; the Requirements define non-negotiables.
3. **`testing/scenarios/`** — list existing scenarios. Identify any that already cover this design area. Do not produce a scenario that duplicates an existing one — flag it and ask if the user wants to extend the existing scenario instead.
4. **`testing/FINDINGS.md`** — check for existing findings in this area. Known gaps should appear in the scenarios as Known Expected Findings.
5. **`design/DESIGNS.md`** — confirm the design's current status. If the design has unresolved Open Questions, surface them before planning.

**If the design has unresolved Open Questions:** list them for the user before proceeding. Ask which are resolved (and what the resolution was) and which can be treated as deferred decisions. Do not plan implementation around unresolved questions — the plan will be wrong. Update the design doc's Open Questions section with any resolutions the user provides.

---

## Step 2: Probe the codebase

Before drafting the plan, read the files the design names as targets. Verify they exist and understand their current structure. Key locations:

- `ddt/config/models.py` — existing Pydantic schema; identify where new fields slot in
- `ddt/cli.py` — existing CLI commands; identify where new commands attach
- `ddt/engine/runner.py` — pipeline execution loop
- `ddt/gcp/` — GCP provisioning; identify existing patterns to reuse or extend
- `ddt/infra/modules/gcp/` — Terraform modules; identify existing module structure
- `tests/` — existing test patterns; understand what test infrastructure is available

Note:
- Which files will be **created** vs. **modified**
- Which existing patterns the implementation can reuse directly
- Which parts of the design require entirely new code with no existing pattern to follow
- Any implementation constraints not already noted in the design

---

## Step 3: Requirements gathering (interactive — do not skip)

Based on what you've read, identify what is still unknown about the implementation plan. Ask 3–5 targeted questions and **wait for responses before proceeding to Step 4**.

Do not ask questions already answered in the design or feature file. The goal is to fill in these planning unknowns:

- **How should the work be phased?** Which components must be built first? Are there any parts that can be built and tested independently before the rest is ready?
- **What is the minimum viable first phase?** What is the smallest slice that produces observable, testable behavior? (e.g. "validate accepts the deploy: block" is testable before deploy itself works)
- **What is the local-first test vehicle?** Which existing pipeline or component should be used to test the implementation — something simple (no auth, flat JSON) that isolates failures to the new code, not the data source.
- **Are there constraints on GCP resource creation?** If the design involves provisioning GCP resources, is there an existing project and service account set up? Can the test create real resources, or should Phase 1 be local-only?
- **What already exists?** Is any part of this design already partially implemented? Are there branches, PRs, or prior run artifacts that should inform the plan?

---

## Step 4: Draft the implementation plan

Write `design/<slug>-plan.md` using this structure:

```markdown
# Implementation Plan: <Name>

**Design:** [`design/<slug>.md`](.<slug>.md)
**Feature:** [`features/<slug>.md`](../features/<slug>.md) <!-- omit if no feature file -->
**Created:** YYYY-MM-DD
**Phases:** N
**Status:** Draft

---

## Overview

[2–3 sentences. What is being built, in what order, and what the key risk areas are.
Mention the test vehicle (the existing pipeline used to drive testing).]

---

## Phase <N>: <Name>

**Goal:** [One sentence — what capability exists after this phase that did not exist before.]

**Testable without completing later phases:** Yes / No

### Files

| File | Action | What to implement |
|------|--------|-------------------|
| `path/to/file.py` | Create / Modify | [Specific class, function, or config change] |
| ... | | |

### Implementation Notes

[Specific guidance for each file: which existing patterns to follow, which class to subclass,
which function signature to match, which Pydantic fields to add. Be concrete enough that an
implementation agent does not need to re-read the design doc to understand what to do.
Reference design doc sections by heading when relevant.]

### Done When

- [ ] [Specific, observable condition — a CLI command succeeds, a test passes, a file is written]
- [ ] ...

### Test Scenario

[Name of the scenario this phase maps to — see Step 5. Format: `testing/scenarios/<slug>-phase-N.md` or `testing/scenarios/<slug>.md` if a single scenario covers all phases.]

---

## Resolved Design Decisions

[If any Open Questions from the design doc were resolved during planning, record them here with the resolution. This supplements the design doc's Decision Log.]

| Question | Resolution | Date |
|----------|------------|------|
| | | |

---

## Implementation Order Rationale

[Why the phases are ordered this way. What unblocks what. Which phases could be parallelized if multiple engineers are working.]

---

## Known Risks

| Risk | Phase | Mitigation |
|------|-------|------------|
| [Technical risk — e.g. "GCP API behavior differs from docs"] | Phase N | [How to detect and handle] |
| ... | | |
```

Rules for the plan:
- **Every file touched must appear in the Files table** — no loose "and also update X" in prose.
- **Phase boundaries must be testable.** Each phase ends with a condition that can be verified with a CLI command, unit test, or observable output. If you cannot write a "Done When" checklist for a phase, it is not a phase — it is part of the next one.
- **Implementation Notes must be concrete.** "Add a `deploy` field to the Pipeline model" is not enough — specify the Pydantic type, whether it is Optional, its default, and which validators to add. An implementation agent reading this plan should not need to re-read the design doc to understand what to code.
- **One file, one row.** If a file needs multiple changes, add multiple rows or enumerate the changes within the Notes column.

---

## Step 5: Write test scenarios

For each implementation phase (or group of closely related phases), write a test scenario in `testing/scenarios/`. Use the format from `testing/scenarios/python-connector.md` or `testing/scenarios/batch-deployment.md` as a reference.

**Scenario naming:**
- If the design has 1–2 phases, write one scenario: `testing/scenarios/<slug>.md`
- If the design has 3+ phases with meaningfully different test setups, write one scenario per phase: `testing/scenarios/<slug>-phase-1.md`, etc. But first check if an existing scenario already covers the earlier phases.

**Each scenario must include:**

- **Goal:** The core question this scenario answers about the implementation. Not "does the code work" — be specific. E.g. "Does `ddt validate` accept and reject the `deploy:` block correctly before any GCP resources are created?"
- **Target Component:** This scenario tests ddt's own code, not an external API. Name the specific CLI commands, modules, or infrastructure components under test.
- **Test Phases:** Ordered phases with numbered steps and phase success conditions. Phase 1 should always be testable with local resources only (no GCP, no external APIs) — validate the config schema, unit-test the new models, confirm error messages. Later phases can introduce GCP or external dependencies.
- **Success Criteria:** Checkboxes that map directly to the feature's Acceptance Criteria (if a feature file exists). Every acceptance criterion should appear somewhere in a scenario's success criteria.
- **Known Complexity:** Identify the hard parts before they surface. GCP provisioning time, IAM propagation delays, API enablement prerequisites — name them so the test agent doesn't mistake expected behavior for a bug.
- **Known Expected Findings:** List any gaps in the design or codebase that the test agent is likely to hit. These are not bugs to fix — they are findings to document. Pre-identifying them prevents the test agent from spending time diagnosing expected failures.
- **Notes for Agent:** Specific, operational guidance. Which pipeline to use as the test vehicle. Which gcloud commands to run. What to check if Phase N fails. Which findings to document and stop on (don't work around missing functionality).

**Critical rule:** Scenario Phase 1 must always be runnable with the test environment that already exists (clone of quipu + `test_config.yml`). Do not put a GCP resource creation step in Phase 1 if local validation can come first.

---

## Step 6: Update cross-links

After writing the plan and scenarios:

1. **Design doc (`design/<slug>.md`):** Add a reference to the plan in a new "Implementation Plan" line at the top:
   ```
   **Implementation Plan:** [`design/<slug>-plan.md`](./<slug>-plan.md)
   ```
   Update the Status from `Draft` to `Finalized` if all Open Questions are resolved.

2. **Feature file (`features/<slug>.md`):** Add the scenario(s) to the Related Scenarios section:
   ```markdown
   - [`testing/scenarios/<slug>.md`](../testing/scenarios/<slug>.md) — [what aspect it covers]
   ```
   Remove any `TODO:` items that the new scenarios now address.

3. **`testing/FINDINGS.md`:** If the plan surfaces any pre-identified gaps (e.g. "the design requires X but X doesn't exist in the codebase"), add them as Enhancement findings now so they're tracked before the test agent hits them.

---

## Step 7: Present to the user

Tell the user:

- The plan file path (`design/<slug>-plan.md`)
- The scenario file path(s) (`testing/scenarios/<slug>.md` or phase files)
- Any Open Questions from the design that were resolved during planning (so they can verify the resolutions are correct)
- Any pre-identified findings added to `testing/FINDINGS.md`
- The first command to run the first scenario: `/test-feature <slug>` or `/test-feature <slug>-phase-1`

Ask: is there anything to revise in the plan or scenarios?

---

## Rules

**Do not write implementation code.** This skill produces the plan and scenarios only. If you find yourself writing Python or Terraform, stop — that belongs in the implementation step, not here.

**Unresolved Open Questions block finalization.** If the design has unresolved questions that affect what code to write, surface them before writing the plan. A plan built on an unresolved question will send the implementer down the wrong path.

**Scenarios must be compatible with `/test-feature`.** The test-feature skill clones quipu into a fresh directory, injects credentials from `test_config.yml`, and then runs through the scenario phases. All steps in the scenario must work within that environment. Do not reference paths, binaries, or credentials that aren't set up by the test-feature environment setup.

**Phase 1 is always local.** The first test phase must not require real GCP resources, external APIs, or credentials beyond what's already in `testing/test_config.yml`. If the design is entirely GCP-dependent with no local test surface, explain this to the user and discuss what a Phase 1 could look like (e.g. schema validation, unit tests with mocked clients, dry-run mode).

**Acceptance criteria → success criteria.** Every acceptance criterion in the feature file must appear as a success criterion checkbox in at least one scenario. If you find acceptance criteria that no scenario covers, add them — do not silently drop them.

**Test vehicle must be simple.** The pipeline used to drive testing should be the simplest possible one that exercises the implementation. For deployment features, `github_repos` is the standard test vehicle — no auth, flat JSON, one iterate axis. This isolates failures to the new code, not the data source.
