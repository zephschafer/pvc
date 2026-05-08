from __future__ import annotations

from typing import Any

from ..config.models import CrsReprojectTransform, Transform


def apply_transform(transform: Transform, record: dict) -> Any:
    if isinstance(transform, CrsReprojectTransform):
        return _crs_reproject(transform, record)
    raise ValueError(f"Unknown transform type: {type(transform)}")


def _crs_reproject(t: CrsReprojectTransform, record: dict) -> float | None:
    from pyproj import Transformer as ProjTransformer

    try:
        raw_x = record.get(t.from_columns[0])
        raw_y = record.get(t.from_columns[1])
        if raw_x is None or raw_y is None:
            return None
        x = float(raw_x)
        y = float(raw_y)
    except (TypeError, ValueError):
        return None

    proj = ProjTransformer.from_crs(t.from_crs, t.to_crs, always_xy=True)
    lon, lat = proj.transform(x, y)
    return lon if t.component == "x" else lat
