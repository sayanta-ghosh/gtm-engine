"""Data service: query execution and table management."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.database import set_tenant_context

ALLOWED_TABLES = {"contacts", "companies", "search_results", "enrichment_log"}


async def list_tables() -> list[str]:
    """Return the sorted list of allowed interactive tables."""
    return sorted(ALLOWED_TABLES)


async def query_table(
    db: AsyncSession,
    tenant_id: str,
    table: str,
    limit: int = 100,
    offset: int = 0,
    order_by: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Query a specific interactive table with RLS.

    Returns (rows, total_count).
    """
    await set_tenant_context(db, tenant_id)

    # Build safe order clause
    order_clause = ""
    if order_by:
        col = order_by.lstrip("-")
        if not col.isidentifier():
            raise ValueError("Invalid order_by column name")
        direction = "DESC" if order_by.startswith("-") else "ASC"
        order_clause = f" ORDER BY {col} {direction}"

    count_result = await db.execute(text(f"SELECT COUNT(*) FROM {table}"))  # noqa: S608
    total = count_result.scalar_one()

    query = text(
        f"SELECT * FROM {table}{order_clause} LIMIT :limit OFFSET :offset"  # noqa: S608
    )
    result = await db.execute(query, {"limit": limit, "offset": offset})
    rows = [dict(row._mapping) for row in result.fetchall()]

    return rows, total


async def execute_raw_query(
    db: AsyncSession,
    tenant_id: str,
    sql: str,
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Execute a read-only SQL query scoped to the tenant via RLS.

    Returns (rows, column_names).
    """
    await set_tenant_context(db, tenant_id)

    result = await db.execute(text(sql), params)
    rows = [dict(row._mapping) for row in result.fetchall()]
    columns = list(result.keys()) if rows else []
    return rows, columns
