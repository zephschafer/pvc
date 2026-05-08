import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

_MODULE_DIR = Path(__file__).parent.parent / "infra" / "modules" / "gcp"
_WORK_DIR   = Path.home() / ".pvc" / "terraform"


def provision(
    project_id: str,
    region: str,
    sa_email: str,
    tf_state_bucket: str,
) -> str:
    """
    Run terraform init + apply.
    Auth is handled automatically via ADC (gcloud application-default credentials).
    Returns the warehouse_bucket name from terraform output.
    Raises RuntimeError on non-zero exit.
    """
    _WORK_DIR.mkdir(parents=True, exist_ok=True)

    for tf_file in _MODULE_DIR.glob("*.tf"):
        shutil.copy2(tf_file, _WORK_DIR / tf_file.name)

    env = {
        **os.environ,
        "TF_INPUT":            "0",
        "TF_PLUGIN_CACHE_DIR": str(_WORK_DIR / ".plugin-cache"),
    }
    (_WORK_DIR / ".plugin-cache").mkdir(exist_ok=True)

    _run(
        [
            "terraform", "init", "-reconfigure",
            f"-backend-config=bucket={tf_state_bucket}",
            "-backend-config=prefix=terraform/state",
        ],
        _WORK_DIR, env,
    )

    _run(
        [
            "terraform", "apply", "-auto-approve",
            f"-var=project_id={project_id}",
            f"-var=region={region}",
            f"-var=sa_email={sa_email}",
        ],
        _WORK_DIR, env,
    )

    return _read_output(_WORK_DIR, env, "warehouse_bucket")


def _run(cmd: list[str], cwd: Path, env: dict) -> None:
    result = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(
            "Terraform command failed: %s\nSTDOUT: %s\nSTDERR: %s",
            " ".join(cmd), result.stdout, result.stderr,
        )
        raise RuntimeError(
            f"terraform {cmd[1]} failed (exit {result.returncode}): {result.stderr[-2000:]}"
        )
    logger.info("terraform %s OK", cmd[1])


def _read_output(work_dir: Path, env: dict, key: str) -> str:
    result = subprocess.run(
        ["terraform", "output", "-json"],
        cwd=str(work_dir), env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"terraform output failed: {result.stderr}")
    outputs = json.loads(result.stdout)
    if key not in outputs:
        raise RuntimeError(f"'{key}' not in terraform output. Got: {list(outputs)}")
    return outputs[key]["value"]
