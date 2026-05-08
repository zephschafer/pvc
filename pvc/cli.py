from __future__ import annotations

import traceback
from pathlib import Path

import typer
import yaml

app = typer.Typer(help="pvc", no_args_is_help=True)
gcp_app = typer.Typer(help="GCP lake provisioning", no_args_is_help=True)
mcp_app = typer.Typer(help="MCP server for AI-driven pipeline development", no_args_is_help=True)
app.add_typer(gcp_app, name="gcp")
app.add_typer(mcp_app, name="mcp")

def _project_root() -> Path:
    from .project import find_project_root
    return find_project_root()


def _pipelines_dir() -> Path:
    return _project_root() / "pipelines"


def _load_config() -> dict:
    cfg = _project_root() / "project.yml"
    if not cfg.exists():
        return {}
    return yaml.safe_load(cfg.read_text()) or {}


def _save_config(config: dict) -> None:
    cfg = _project_root() / "project.yml"
    cfg.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))


def _get_catalog() -> str:
    return _load_config().get("catalog", "local")


# ------------------------------------------------------------------ #
# init                                                                 #
# ------------------------------------------------------------------ #

@app.command()
def init(
    api_key: str = typer.Option("", prompt="PortlandMaps API key (leave blank to use default)", show_default=False),
    regions: str = typer.Option("", prompt="Valid regions, comma-separated (blank for all)", show_default=False),
    catalog: str = typer.Option("local", prompt="Catalog type (local or gcp)", show_default=True),
):
    """Create or update project.yml configuration."""
    cfg = _load_config()
    if api_key:
        cfg["portlandmaps_api_key"] = api_key
    cfg["valid_regions"] = [r.strip() for r in regions.split(",") if r.strip()]
    cfg["catalog"] = catalog
    _save_config(cfg)
    typer.echo(f"Config saved to {_project_root() / 'project.yml'}")


# ------------------------------------------------------------------ #
# run                                                                  #
# ------------------------------------------------------------------ #

@app.command()
def run(
    pipeline_name: str = typer.Argument(..., help="Pipeline name (without .yml) or 'all'"),
    start: str | None = typer.Option(None, help="Override backfill start date (YYYY-MM-DD)"),
    end: str | None = typer.Option(None, help="Override backfill end date (YYYY-MM-DD)"),
    limit: int | None = typer.Option(None, help="Run only the first N iterations"),
    param: list[str] = typer.Option([], help="Override a param value: key=value (repeatable)"),
):
    """Run one or all pipelines."""
    from .config import load_pipeline, load_all_pipelines
    from .engine import run_pipeline

    catalog = _get_catalog()
    param_overrides = _parse_params(param)

    pipelines_dir = _pipelines_dir()
    if pipeline_name == "all":
        pipelines = load_all_pipelines(pipelines_dir)
    else:
        path = pipelines_dir / f"{pipeline_name}.yml"
        if not path.exists():
            typer.echo(f"Pipeline not found: {path}", err=True)
            raise typer.Exit(1)
        pipelines = [load_pipeline(path)]

    for pipeline in pipelines:
        if start or end:
            _override_date_range(pipeline, start, end)
        run_pipeline(pipeline, catalog=catalog, limit=limit, param_overrides=param_overrides)


# ------------------------------------------------------------------ #
# validate                                                             #
# ------------------------------------------------------------------ #

@app.command()
def validate(
    pipeline_name: str = typer.Argument(..., help="Pipeline name (without .yml) or 'all'"),
):
    """Parse and validate pipeline YAML without running it."""
    from .config import load_pipeline, load_all_pipelines

    pipelines_dir = _pipelines_dir()
    if pipeline_name == "all":
        pipelines = load_all_pipelines(pipelines_dir, resolve_env=False)
        names = [p.name for p in pipelines]
        typer.echo(f"OK — {len(pipelines)} pipeline(s): {', '.join(names)}")
    else:
        path = pipelines_dir / f"{pipeline_name}.yml"
        if not path.exists():
            typer.echo(f"Pipeline not found: {path}", err=True)
            raise typer.Exit(1)
        pipeline = load_pipeline(path, resolve_env=False)
        typer.echo(f"OK — '{pipeline.name}' ({len(pipeline.source.params)} params, "
                   f"{len(pipeline.source.iterate)} iterate axes, "
                   f"{len(pipeline.schema_.columns)} columns)")


# ------------------------------------------------------------------ #
# gcp                                                                  #
# ------------------------------------------------------------------ #

@gcp_app.command("setup")
def gcp_setup(
    project_id: str = typer.Option(..., "--project-id", "-p", help="GCP project ID"),
    region: str = typer.Option(..., "--region", "-r", help="GCP region (e.g. us-central1)"),
):
    """Provision a GCP data lake."""
    from .gcp import bootstrap, terraform
    from .gcp.gcloud import get_credentials

    cfg = _load_config()
    gcp = cfg.get("gcp", {})

    if gcp.get("setup_status") in ("running", "complete"):
        typer.echo(f"GCP setup already '{gcp['setup_status']}'. Use --force to re-run.", err=True)
        raise typer.Exit(1)

    typer.echo("Checking Google credentials...")
    try:
        credentials = get_credentials()
    except RuntimeError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1)
    typer.echo("Credentials OK.")

    gcp.update({"project_id": project_id, "region": region, "setup_status": "running"})
    cfg["gcp"] = gcp
    _save_config(cfg)

    try:
        typer.echo("Creating Terraform state bucket...")
        tf_state_bucket = bootstrap.create_state_bucket(project_id, region, credentials)

        typer.echo("Creating service account...")
        sa_email = bootstrap.create_service_account(project_id, credentials)

        typer.echo("Creating service account key...")
        key_data = bootstrap.create_service_account_key(project_id, sa_email, credentials)

        typer.echo("Storing key in Secret Manager...")
        secret_name = bootstrap.store_key_in_secret_manager(project_id, key_data, credentials)

        typer.echo("Provisioning lake infrastructure (terraform apply)...")
        warehouse_bucket = terraform.provision(
            project_id=project_id,
            region=region,
            sa_email=sa_email,
            tf_state_bucket=tf_state_bucket,
        )

        gcp.update({
            "sa_email": sa_email,
            "secret_name": secret_name,
            "tf_state_bucket": tf_state_bucket,
            "warehouse_bucket": warehouse_bucket,
            "setup_status": "complete",
            "setup_error": None,
        })
        cfg["gcp"] = gcp
        _save_config(cfg)

        typer.echo(f"\nGCP lake provisioned successfully!")
        typer.echo(f"  Warehouse bucket: {warehouse_bucket}")
        typer.echo(f"  Service account:  {sa_email}")

    except Exception as e:
        gcp.update({"setup_status": "failed", "setup_error": traceback.format_exc()[-2000:]})
        cfg["gcp"] = gcp
        _save_config(cfg)
        typer.echo(f"\nSetup failed: {e}", err=True)
        raise typer.Exit(1)


@gcp_app.command("status")
def gcp_status():
    """Show GCP lake setup status."""
    cfg = _load_config()
    gcp = cfg.get("gcp")

    if not gcp:
        typer.echo("No GCP configuration found. Run: pvc gcp setup --project-id X --region Y")
        return

    typer.echo(f"Status:           {gcp.get('setup_status', 'unknown')}")
    typer.echo(f"Project ID:       {gcp.get('project_id', '-')}")
    typer.echo(f"Region:           {gcp.get('region', '-')}")
    typer.echo(f"Warehouse bucket: {gcp.get('warehouse_bucket', '-')}")
    typer.echo(f"Service account:  {gcp.get('sa_email', '-')}")
    if gcp.get("setup_error"):
        typer.echo(f"\nLast error:\n{gcp['setup_error']}", err=True)


# ------------------------------------------------------------------ #
# mcp                                                                  #
# ------------------------------------------------------------------ #

@mcp_app.command("serve")
def mcp_serve():
    """Start the pvc MCP server (stdio transport for Claude Desktop)."""
    from .mcp_server import serve
    serve()


@mcp_app.command("setup-desktop")
def mcp_setup_desktop():
    """Register pvc as an MCP server in Claude Desktop's config."""
    import json
    import shutil

    claude_config = Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if not claude_config.exists():
        typer.echo(f"Claude Desktop config not found at {claude_config}", err=True)
        typer.echo("Is Claude Desktop installed?", err=True)
        raise typer.Exit(1)

    project_dir = str(_project_root())
    uv_path = shutil.which("uv") or "uv"

    cfg = json.loads(claude_config.read_text()) if claude_config.stat().st_size else {}
    cfg.setdefault("mcpServers", {})
    cfg["mcpServers"]["pvc"] = {
        "command": uv_path,
        "args": ["--directory", project_dir, "run", "pvc", "mcp", "serve"],
    }
    claude_config.write_text(json.dumps(cfg, indent=2))
    typer.echo(f"Registered pvc MCP server in {claude_config}")
    typer.echo("Restart Claude Desktop to pick up the change.")


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _parse_params(raw: list[str]) -> dict:
    result = {}
    for item in raw:
        if "=" not in item:
            typer.echo(f"Invalid --param format (expected key=value): '{item}'", err=True)
            raise typer.Exit(1)
        k, v = item.split("=", 1)
        for cast in (int, float):
            try:
                v = cast(v)
                break
            except ValueError:
                pass
        result[k.strip()] = v
    return result


def _override_date_range(pipeline, start: str | None, end: str | None) -> None:
    from .config.models import DateRangeIterate
    for spec in pipeline.source.iterate:
        if isinstance(spec, DateRangeIterate):
            if start:
                spec.start = start
            if end:
                spec.end = end
