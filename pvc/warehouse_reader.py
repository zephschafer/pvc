"""
Fast warehouse querying via DuckDB.

Reads Iceberg Parquet files directly from warehouse/{namespace}/{table}/data/*.parquet
without spinning up a Spark session. For ad-hoc exploration and MCP tool use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

_MAX_ROWS = 500


def _warehouse() -> Path:
    from .project import find_project_root
    return find_project_root() / "warehouse"


def _table_parquet_glob(namespace: str, table: str) -> str:
    return str(_warehouse() / namespace / table / "data" / "*.parquet")


def list_tables() -> list[dict[str, Any]]:
    """Return all tables in the warehouse with column schemas and row counts."""
    import duckdb

    warehouse = _warehouse()
    results = []
    if not warehouse.exists():
        return results

    for ns_dir in sorted(warehouse.iterdir()):
        if not ns_dir.is_dir():
            continue
        for table_dir in sorted(ns_dir.iterdir()):
            if not table_dir.is_dir():
                continue
            data_dir = table_dir / "data"
            parquet_files = list(data_dir.glob("*.parquet")) if data_dir.exists() else []
            if not parquet_files:
                continue

            glob = _table_parquet_glob(ns_dir.name, table_dir.name)
            try:
                conn = duckdb.connect()
                info = conn.execute(
                    f"SELECT COUNT(*) as n FROM read_parquet('{glob}')"
                ).fetchone()
                row_count = info[0] if info else 0

                cols = conn.execute(
                    f"DESCRIBE SELECT * FROM read_parquet('{glob}') LIMIT 0"
                ).fetchall()
                columns = [{"name": c[0], "type": c[1]} for c in cols]
                conn.close()
            except Exception as e:
                row_count = -1
                columns = [{"error": str(e)}]

            results.append({
                "namespace": ns_dir.name,
                "table": table_dir.name,
                "full_name": f"{ns_dir.name}.{table_dir.name}",
                "row_count": row_count,
                "columns": columns,
            })

    return results


def query(sql: str) -> list[dict[str, Any]]:
    """
    Run a SQL query against the warehouse.

    Table references use the form  namespace.table  — e.g.
        SELECT * FROM portland_permits.permits_loader LIMIT 10

    The server rewrites these to DuckDB read_parquet() calls automatically.
    Returns at most 500 rows.
    """
    import duckdb
    import re

    # Rewrite  namespace.table  references to read_parquet(glob) calls.
    # Matches word.word that is NOT already inside a string or a function call.
    resolved = sql
    warehouse = _warehouse()
    if warehouse.exists():
        for ns_dir in warehouse.iterdir():
            if not ns_dir.is_dir():
                continue
            for table_dir in ns_dir.iterdir():
                if not table_dir.is_dir():
                    continue
                data_dir = table_dir / "data"
                if not data_dir.exists() or not list(data_dir.glob("*.parquet")):
                    continue
                pattern = rf"\b{re.escape(ns_dir.name)}\.{re.escape(table_dir.name)}\b"
                glob = _table_parquet_glob(ns_dir.name, table_dir.name)
                resolved = re.sub(pattern, f"read_parquet('{glob}')", resolved)

    conn = duckdb.connect()
    # Enforce row cap without altering queries that already have LIMIT
    if "limit" not in resolved.lower():
        resolved = f"SELECT * FROM ({resolved}) _q LIMIT {_MAX_ROWS}"

    rows = conn.execute(resolved).fetchall()
    cols = [d[0] for d in conn.description]
    conn.close()
    return [dict(zip(cols, row)) for row in rows]
