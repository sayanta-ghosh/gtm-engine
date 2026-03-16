"""Pydantic v2 request/response schemas for the data module."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class TableListResponse(BaseModel):
    tables: list[str]


class TableQueryParams(BaseModel):
    filters: dict[str, Any] = {}
    order_by: str | None = None
    limit: int = 100
    offset: int = 0


class TableQueryResponse(BaseModel):
    table: str
    rows: list[dict[str, Any]]
    total: int


class RawQueryRequest(BaseModel):
    sql: str
    params: dict[str, Any] = {}


class RawQueryResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
