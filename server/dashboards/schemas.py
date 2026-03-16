"""Pydantic v2 request/response schemas for the dashboards module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CreateDashboardRequest(BaseModel):
    name: str
    data_queries: dict[str, Any] | None = None
    password: str | None = None
    refresh_interval: int = 3600


class DashboardResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    status: str
    refresh_interval: int
    created_at: datetime
    updated_at: datetime


class DashboardListResponse(BaseModel):
    dashboards: list[DashboardResponse]
    total: int
