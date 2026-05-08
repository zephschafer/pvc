from __future__ import annotations

import os
from pathlib import Path


def find_project_root(start: Path | None = None) -> Path:
    """Return the pvc project root directory.

    Resolution order:
      1. PVC_PROJECT_DIR environment variable (absolute path)
      2. Walk up from `start` (default: cwd) looking for project.yml
    """
    if env := os.environ.get("PVC_PROJECT_DIR"):
        return Path(env).resolve()
    start = (start or Path.cwd()).resolve()
    for p in [start, *start.parents]:
        if (p / "project.yml").exists():
            return p
    raise RuntimeError(
        "No project.yml found in current directory or any parent. "
        "Run 'pvc init' to create one, or set PVC_PROJECT_DIR."
    )
