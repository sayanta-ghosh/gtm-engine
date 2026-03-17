"""Pydantic v2 request/response schemas for the dashboards module."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CreateDashboardRequest(BaseModel):
    name: str
    dataset_id: str  # UUID of the dataset to back this dashboard
    config: dict[str, Any] | None = None  # widget layout; auto-generated if omitted
    password: str | None = None
    refresh_interval: int = 3600


class UpdateDashboardRequest(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    password: str | None = None
    refresh_interval: int | None = None


class DashboardResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    dataset_id: str | None = None
    dataset_name: str | None = None
    config: dict[str, Any] | None = None
    widget_count: int = 0
    status: str
    refresh_interval: int
    read_token: str | None = None  # only populated on creation
    created_at: datetime
    updated_at: datetime


class DashboardListResponse(BaseModel):
    dashboards: list[DashboardResponse]
    total: int
