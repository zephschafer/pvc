# Contributing to dcf

## Dev setup

See the [Developing dcf](README.md#developing-dcf) section of the README for the full setup walkthrough. Quick version:

```bash
git clone https://github.com/zephschafer/dcf
cd dcf
uv sync
uv run dcf --help   # verify install
```

You'll need a separate dcf project to test against. The easiest path is the demo project:

```bash
git clone https://github.com/Data-Dispatch/quipu-data-generator ../quipu-data-generator
cd ../quipu-data-generator
uv sync   # picks up dcf from ../dcf via editable path dep
uv run dcf validate all
```

Or create a minimal scratch project (see README for the boilerplate).

---

## Testing changes

There's no formal test suite yet. Use the manual workflow:

```bash
# Catch config/schema issues without running anything
uv run dcf validate all

# Run a single iteration cheaply
uv run dcf run <collector_name> --limit 1

# Full run
uv run dcf run <collector_name>

# Verify output
uv run dcf query 'SELECT * FROM <namespace>.<table> LIMIT 5'

# Test MCP tools
uv run dcf mcp serve   # then connect via Claude Desktop
```

When writing new logic, keep it in pure functions where possible — that'll make it easy to add a proper pytest suite later.

---

## Code layout

```
dcf/
├── cli.py              CLI entry point (Typer)
├── config/
│   ├── models.py       Pydantic models for collector YAML
│   └── loader.py       YAML loading + env var resolution
├── engine/
│   ├── runner.py       Outer loop (iterate → fetch → project → write)
│   ├── fetcher.py      HTTP and Python source fetchers
│   ├── iterator.py     Cartesian iteration over date ranges and categoricals
│   ├── projector.py    Schema projection (path extraction, transforms)
│   └── transforms.py   Column transforms (crs_reproject, etc.)
├── writer/
│   └── iceberg.py      Iceberg write strategies (incremental / append / full_refresh)
└── gcp/                GCP integration (auth, provisioning, Terraform)
```

See the README's [dcf package structure](README.md#dcf-package-structure) section for the full layout.

---

## Conventions

- **Python 3.12+** — use type hints throughout
- **Pydantic v2** for all config and schema models (`dcf/config/models.py`)
- **Typer** for CLI commands (`dcf/cli.py`)
- **uv** for dependency management — add deps to `pyproject.toml`, then run `uv sync`
- No mutable global state; prefer pure functions so logic is easy to test

---

## Submitting changes

- Open a PR against `main`
- One logical change per PR — keep diffs focused
- Describe what you changed and why in the PR body; include a quick note on how you tested it

---

## Good places to contribute

- **New source types** — beyond `http` and `python` (`dcf/engine/fetcher.py`)
- **New transforms** — beyond `crs_reproject` (`dcf/engine/transforms.py`)
- **New build strategies** — beyond `incremental`, `append`, `full_refresh` (`dcf/writer/iceberg.py`)
- **A test suite** — pytest, targeting the engine and config modules
- **GitHub Actions CI** — lint + validate against the demo project on each PR
