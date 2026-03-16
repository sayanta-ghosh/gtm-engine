"""Pydantic v2 request/response schemas for the execution module."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ExecuteRequest(BaseModel):
    operation: str  # e.g. "enrich_person", "search_companies"
    provider: str | None = None  # auto-select if None
    params: dict[str, Any] = {}


class ExecuteResponse(BaseModel):
    execution_id: str
    status: str
    credits_charged: float
    result: dict[str, Any]


class CostEstimateRequest(BaseModel):
    operation: str
    params: dict[str, Any] = {}


class CostEstimateResponse(BaseModel):
    operation: str
    estimated_credits: float
    breakdown: str  # human-readable explanation
    is_free_with_byok: bool = True


class BatchExecuteRequest(BaseModel):
    operations: list[ExecuteRequest]


class BatchExecuteResponse(BaseModel):
    batch_id: str
    total: int
    status: str  # "processing" | "completed"


class BatchStatusResponse(BaseModel):
    batch_id: str
    total: int
    completed: int
    failed: int
    status: str
    results: list[dict[str, Any]]
