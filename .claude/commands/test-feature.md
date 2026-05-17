You are running a dcf feature test for a specific scenario. Your job is to act as a disciplined QA engineer who executes scenario phases precisely, records every failure, friction point, and gap, and — for data pipeline scenarios — also acts as a first-time dcf user attempting to build a real pipeline.

## What You Are Testing

dcf is a YAML-driven data ingestion framework and Claude plugin (CLI + skills + MCP server). Scenarios fall into two types:

- **Pipeline scenarios** — test whether a user can build and run a working data pipeline against a real external API (e.g. `github-repos`, `stripe-payments`). The core question is whether dcf's YAML schema is expressive enough and the pipeline runs correctly end-to-end.
- **Feature scenarios** — test whether a new dcf feature (CLI command, infrastructure provisioning, config schema) works as designed (e.g. `batch-deployment`, `streaming-deployment`). The core question is whether the implemented feature meets its acceptance criteria.

Determine the scenario type in Step 1. Steps 2 and 3 differ by type.

## Arguments

The scenario name is passed as an argument (e.g., `/test-feature github-repos`). If no argument is given, ask the user which scenario to run.

---

## Step 0: Set up the clean test environment

Before reading the scenario, create an isolated project directory for this run. Every test starts from a fresh clone of quipu so that warehouse data, pipelines, and config from previous runs do not carry over.

**a. Check for test_config.yml**

Look for `testing/test_config.yml` in the dcf repository. If it does not exist, stop and tell the user:

> `testing/test_config.yml` is missing. Copy `testing/test_config.yml.example` to `testing/test_config.yml` and fill in the credentials needed for this scenario. The file is gitignored and will not be committed.

Do not proceed until the user confirms the file exists.

**b. Determine the run directory**

```
testing/runs/YYYY-MM-DD-<scenario-name>/
```

Use today's date. If a `quipu/` subdirectory already exists in that run directory (from a prior attempt), remove it before cloning:

```bash
rm -rf testing/runs/YYYY-MM-DD-<scenario>/quipu
```

**c. Clone quipu**

```bash
git clone https://github.com/zephschafer/quipu.git \
  testing/runs/YYYY-MM-DD-<scenario>/quipu
```

The clone will have no `project.yml` (quipu gitignores it) and no warehouse data — a clean slate.

**d. Inject credentials**

Copy `testing/test_config.yml` into the clone as `project.yml`:

```bash
cp testing/test_config.yml \
  testing/runs/YYYY-MM-DD-<scenario>/quipu/project.yml
```

**e. Record the clone path**

Set `CLONE` to the absolute path of the cloned quipu (e.g. `/Users/zephschafer/Documents/GitHub/dcf/testing/runs/2026-05-10-github-repos/quipu`). All subsequent dcf commands target this path via the `DCF_PROJECT_DIR` environment variable.

Shorthand for all CLI commands from this point forward:

```bash
DCF_PROJECT_DIR=$CLONE uv --directory /Users/zephschafer/Documents/GitHub/dcf run dcf <command>
```

---

## Step 1: Read the Scenario

Read the scenario file at `testing/scenarios/<scenario-name>.md`. This defines:
- The goal and core question
- Test phases with numbered steps and success conditions
- Success criteria (checklist)
- Known complexity and expected findings
- Credentials required

**Determine the scenario type** from the "Target API" or "Target Component" section:
- If it names an **external API** (GitHub, Stripe, Jira, etc.) → **Pipeline scenario** — follow Steps 2 and 3 as written for pipeline scenarios.
- If it names a **dcf CLI command, module, or infrastructure component** → **Feature scenario** — skip Step 2 (API probing) and follow the feature scenario path in Step 3.

Also read:
- `README.md` — the full dcf YAML schema reference
- `testing/FINDINGS.md` — existing findings (so you don't re-report known issues)
- Any prior runs for this scenario in `testing/runs/` (to build on prior work)
- For pipeline scenarios: `.claude/commands/new-pipeline.md` — the skill you will simulate

---

## Step 2: Investigate the target

### Pipeline scenarios — Probe the API

Before writing any pipeline, investigate the target API as a real user would:

- Fetch the API documentation (web search or provided URL)
- Make real HTTP requests to representative endpoints to see actual response shapes
- Record: response structure, pagination mechanism, auth mechanism, array/nested fields, date field formats, rate limits
- Note anything that seems hard to express in dcf's current YAML schema

Do NOT skip this step for pipeline scenarios. Understanding the real API response is essential to accurate testing.

### Feature scenarios — Review prerequisites

Before executing any phases, verify the prerequisites listed in the scenario:

- Check that required GCP APIs are enabled (if applicable)
- Verify credentials in `project.yml` match what the scenario requires
- Check for any prior run artifacts (Terraform state, provisioned resources) that could affect a clean run
- Read any implementation plan at `design/<slug>-plan.md` if it exists — understand what was built and in what order

---

## Step 3: Execute the scenario

### Pipeline scenarios — Attempt Pipeline Creation

Proceed through the `new-pipeline` skill steps as if you are a first-time user who just installed dcf:

1. Choose source type: `http` or `python`
2. Design the pipeline YAML (iterate axes, auth, params, schema, build strategy)
3. If Python connector needed: design and write it
4. Write the pipeline YAML
5. Validate

**Write files directly to the clone** — do not use MCP write tools (they target the live quipu):

- Connector: write to `$CLONE/connectors/<name>.py`
- Pipeline YAML: write to `$CLONE/pipelines/<name>.yml`

**Validate using the CLI:**

```bash
DCF_PROJECT_DIR=$CLONE uv --directory /Users/zephschafer/Documents/GitHub/dcf run dcf validate <name>
```

**Critical constraint:** Do NOT work around YAML schema limitations by writing custom Python. If the schema cannot express what the API needs, record it as a finding and note the limitation. The test is whether dcf's YAML is expressive enough — not whether Python can compensate.

### Feature scenarios — Execute scenario phases

Work through each phase defined in the scenario file in order. For each phase:

1. Execute the numbered steps exactly as written
2. Record the actual output of every command — do not paraphrase
3. If a step fails, diagnose and distinguish:
   - **Missing implementation** (feature code not yet written) → record as Blocking finding, do not work around it, proceed to the next phase if possible
   - **User error or misconfiguration** → fix and retry
   - **dcf bug in existing code** → record as finding, attempt workaround only if the scenario explicitly allows it
4. Check the phase success condition — record whether it passed or failed
5. Do not advance to the next phase if the current phase's success condition failed, unless the scenario explicitly says to continue

**Critical constraint for feature scenarios:** Do NOT implement missing feature code to make a test pass. If `dcf deploy` doesn't exist yet, record that as a Blocking finding and stop that phase. The test is whether the implemented feature works — not whether you can implement it inline.

---

## Step 4: Iterative verification

### Pipeline scenarios

Run and iterate until either success or a blocking finding.

**Run with limit:**

```bash
DCF_PROJECT_DIR=$CLONE uv --directory /Users/zephschafer/Documents/GitHub/dcf run dcf run <name> --limit 1
```

If it fails: diagnose the error. Distinguish between:
- **User error** (wrong path, wrong param name) → fix and retry
- **dcf bug or schema gap** → record finding, attempt workaround if possible, continue

**When `--limit 1` succeeds:**

- Verify schema projection: check that all expected columns are present and typed correctly
- Run full pipeline (or a reasonable subset via `--limit`):

```bash
DCF_PROJECT_DIR=$CLONE uv --directory /Users/zephschafer/Documents/GitHub/dcf run dcf run <name>
```

**Query the clone's warehouse** to verify row counts and spot-check data quality. The warehouse lives at `$CLONE/warehouse/`. Query it directly:

```bash
DCF_PROJECT_DIR=$CLONE uv --directory /Users/zephschafer/Documents/GitHub/dcf run python -c \
  "from dcf.warehouse_reader import query; import json; print(query('SELECT * FROM <namespace>.<table> LIMIT 10'))"
```

Or read the Parquet files directly with DuckDB if simpler.

**Mark success criteria checkboxes** if the full run succeeds.

### Feature scenarios

After completing all phases, mark the success criteria checkboxes based on the phase outcomes. For each criterion:
- Check it if the relevant phase step produced the expected output
- Leave it unchecked with a note if the phase failed or was not reached
- Note any partial passes (e.g. "command ran but output format differs from expected")

---

## Step 5: Document findings

### Create the run directory and report

The run directory (`testing/runs/YYYY-MM-DD-<scenario-name>/`) was created in Step 0. Add to it:

**`report.md`** — structured findings report:

```markdown
# Test Run: <Scenario Name>
Date: YYYY-MM-DD | Tester: Claude <model> | Scenario: <scenario-name>

## Outcome: SUCCESS | PARTIAL SUCCESS | FAILURE

## Success Criteria
- [x] <criterion from scenario file>
- [ ] <criterion that failed>
... (copy from scenario file, check off what passed)

## What Worked
- <item>: ✓
...

## What Failed
- <description of failure>
  [→ Finding F-XXX: Severity / Category]

## Friction Points (things that were confusing or took extra steps)
- <description>
  [→ Finding F-XXX: Minor / UX]

## Artifacts Produced
<!-- For pipeline scenarios: -->
See pipeline.yml in this directory. (copy the final YAML here if it worked)
<!-- For feature scenarios: -->
<List GCP resources created, files modified, state written, etc.>

## Proposed Fixes
1. F-XXX: <concise fix proposal>
...
```

**For pipeline scenarios:** copy `$CLONE/pipelines/<name>.yml` as `pipeline.yml` and `$CLONE/connectors/<name>.py` as `connector.py` if one was written.

**For feature scenarios:** note any GCP resources created (environment names, job IDs) so the user can clean them up if needed.

### Update the central tracker

Update `testing/FINDINGS.md`:
- Add new findings to the Open Findings table with the next available F-XXX ID
- Use the severity and category definitions at the top of FINDINGS.md
- Update the header stats (Total, Open counts)
- Do NOT duplicate findings that already exist in the tracker

---

## Step 6: Summary Report

Present a concise summary to the user:

```
## Round Complete: <Scenario Name>

Outcome: <SUCCESS | PARTIAL SUCCESS | FAILURE>

New findings: N
  - F-XXX: <one-line summary> [Blocking/Major/Minor/Enhancement]
  ...

Success criteria: X/Y passed

Proposed next steps:
  1. <fix or decision needed from you>
  ...
```

Wait for the user to review and tell you which findings to fix, mark by-design, or defer.

---

## Rules for Finding Classification

**Never classify a finding as Minor if it prevents the scenario's core goal from being achieved.** When in doubt, classify higher (more severe).

**A finding is Blocking if:** the scenario cannot progress without a dcf code change or missing implementation.

**A finding is a Skill finding if:** a dcf skill (`new-pipeline`, `new-feature`, `tech-design`, `implement-design`) gave wrong or missing guidance that caused the wrong path to be taken.

**A finding is a UX finding if:** an error message was cryptic, a CLI flag was confusing, or reading source code was required to understand what was happening.

**Do not report findings for things that are intentionally out of scope.** Check the README, the feature file's "Out of Scope" section, and existing "By Design" entries in FINDINGS.md before filing.

---

## After Findings Are Reviewed

When the user tells you to fix a finding:

1. Implement the fix in the relevant dcf source file
2. Write a pytest unit test in `tests/` that would have caught this issue (if it's a Runtime finding)
3. Re-run the relevant scenario phase to verify the fix
4. Update `testing/FINDINGS.md`: move the finding to the Fixed table with the git commit hash
5. Update `testing/runs/<run>/report.md` to note the fix

When the user marks a finding "By Design":

1. Move it to the By Design table in `testing/FINDINGS.md` with the rationale the user gave
2. Note it in the scenario file so future rounds don't re-investigate it
