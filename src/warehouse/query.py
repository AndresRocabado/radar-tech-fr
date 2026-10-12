"""Small query helpers shared by the pipeline and the dashboard."""

from __future__ import annotations

from typing import Any

import duckdb


def fetch_one(
    con: duckdb.DuckDBPyConnection, sql: str, params: object | None = None
) -> tuple[Any, ...]:
    """Run an aggregate query and return its single row.

    An aggregate without ``GROUP BY`` always yields one row, even on an empty
    table; ``fetchone()`` is still typed as optional, hence this check.

    Raises:
        RuntimeError: when the query returns no row at all.
    """
    row = con.execute(sql, params).fetchone()
    if row is None:
        raise RuntimeError(f"query returned no row: {sql.strip()[:80]}")
    return row
