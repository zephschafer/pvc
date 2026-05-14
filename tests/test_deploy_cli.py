"""Tests for ddt deploy / undeploy CLI error paths (F-031)."""

import pytest
import yaml
from pathlib import Path
from typer.testing import CliRunner

from ddt.cli import app

runner = CliRunner()


def _make_project(tmp_path: Path, catalog: str = "local", gcp: dict | None = None) -> Path:
    config = {"catalog": catalog}
    if gcp:
        config["gcp"] = gcp
    (tmp_path / "project.yml").write_text(yaml.dump(config))
    (tmp_path / "pipelines").mkdir()
    return tmp_path


def _make_pipeline(project: Path, name: str, with_deploy: bool = True) -> None:
    deploy_block = 'deploy:\n  schedule: "0 8 * * *"\n' if with_deploy else ""
    (project / "pipelines" / f"{name}.yml").write_text(
        f"version: 1\n"
        f"name: {name}\n"
        f"source:\n  type: http\n  url: https://example.com\n"
        f"schema:\n  columns:\n    - name: id\n      path: id\n      type: integer\n"
        f"build:\n  strategy: incremental\n  primary_key: id\n"
        f"{deploy_block}"
    )


def test_deploy_missing_pipeline(tmp_path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))
    result = runner.invoke(app, ["deploy", "nonexistent"])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_deploy_no_deploy_block(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    _make_pipeline(project, "my_pipeline", with_deploy=False)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))
    result = runner.invoke(app, ["deploy", "my_pipeline"])
    assert result.exit_code == 1
    assert "no 'deploy:' block" in result.output


def test_deploy_local_catalog_routes_to_local_deploy(tmp_path, monkeypatch):
    project = _make_project(tmp_path, catalog="local")
    _make_pipeline(project, "my_pipeline", with_deploy=True)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))

    called = {}

    def mock_deploy(pipeline_name, deployment, project_root, subscription=None):
        called["pipeline_name"] = pipeline_name
        return {
            "type": "batch",
            "image_tag": f"ddt-local/{pipeline_name}:latest",
            "warehouse_path": str(project_root / "warehouse"),
            "airflow_url": "http://localhost:8080",
            "schedule": "0 8 * * *",
            "deployed_at": "2026-05-14T00:00:00+00:00",
        }

    monkeypatch.setattr("ddt.local_deploy.deploy", mock_deploy)
    monkeypatch.setattr("ddt.local_deploy._check_docker", lambda: None)
    result = runner.invoke(app, ["deploy", "my_pipeline"])
    assert result.exit_code == 0, result.output
    assert called.get("pipeline_name") == "my_pipeline"


def test_deploy_no_args_deploys_all(tmp_path, monkeypatch):
    project = _make_project(tmp_path, catalog="local")
    _make_pipeline(project, "pipeline_a", with_deploy=True)
    _make_pipeline(project, "pipeline_b", with_deploy=True)
    _make_pipeline(project, "no_deploy", with_deploy=False)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))

    deployed = []

    def mock_deploy(pipeline_name, deployment, project_root, subscription=None):
        deployed.append(pipeline_name)
        return {
            "type": "batch",
            "image_tag": f"ddt-local/{pipeline_name}:latest",
            "warehouse_path": str(project_root / "warehouse"),
            "airflow_url": "http://localhost:8080",
            "schedule": "0 8 * * *",
            "deployed_at": "2026-05-14T00:00:00+00:00",
        }

    monkeypatch.setattr("ddt.local_deploy.deploy", mock_deploy)
    monkeypatch.setattr("ddt.local_deploy._check_docker", lambda: None)
    result = runner.invoke(app, ["deploy"])
    assert result.exit_code == 0, result.output
    assert "pipeline_a" in deployed
    assert "pipeline_b" in deployed
    assert "no_deploy" not in deployed


def test_deploy_requires_gcp_setup_complete(tmp_path, monkeypatch):
    project = _make_project(tmp_path, catalog="gcp", gcp={"setup_status": "failed"})
    _make_pipeline(project, "my_pipeline", with_deploy=True)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))
    result = runner.invoke(app, ["deploy", "my_pipeline"])
    assert result.exit_code == 1
    assert "GCP setup is not complete" in result.output


def test_undeploy_not_deployed(tmp_path, monkeypatch):
    project = _make_project(tmp_path, catalog="gcp", gcp={"setup_status": "complete"})
    _make_pipeline(project, "my_pipeline", with_deploy=True)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))
    result = runner.invoke(app, ["undeploy", "my_pipeline"])
    assert result.exit_code == 1
    assert "not in project.yml deployments" in result.output


def test_deploy_status_none(tmp_path, monkeypatch):
    _make_project(tmp_path)
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))
    result = runner.invoke(app, ["deploy-status"])
    assert result.exit_code == 0
    assert "No pipelines are currently deployed" in result.output


def test_deploy_status_shows_deployments(tmp_path, monkeypatch):
    project = _make_project(tmp_path)
    config = yaml.safe_load((project / "project.yml").read_text())
    config["deployments"] = {
        "my_pipeline": {
            "schedule": "0 8 * * *",
            "dag_id": "my_pipeline",
            "cloud_run_job": "ddt-job-my-pipeline",
            "airflow_url": "https://ddt-airflow-abc123-uc.a.run.app",
            "deployed_at": "2026-05-11T08:00:00+00:00",
        }
    }
    (project / "project.yml").write_text(yaml.dump(config))
    monkeypatch.setenv("DDT_PROJECT_DIR", str(tmp_path))
    result = runner.invoke(app, ["deploy-status"])
    assert result.exit_code == 0
    assert "my_pipeline" in result.output
    assert "0 8 * * *" in result.output
    assert "ddt-job-my-pipeline" in result.output
