"""Pydantic v2 request/response schemas for the billing module."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class CreditBalanceResponse(BaseModel):
    tenant_id: str
    balance: float
    spend_this_month: float


class LedgerEntryResponse(BaseModel):
    id: int
    entry_type: str
    amount: float
    balance_after: float
    operation: str | None
    reference_id: str | None
    description: str | None
    created_at: datetime


class CreditHistoryResponse(BaseModel):
    entries: list[LedgerEntryResponse]
    total: int


class TopupRequest(BaseModel):
    package: str  # "starter" | "growth" | "scale"
    success_url: str | None = None
    cancel_url: str | None = None


class TopupResponse(BaseModel):
    checkout_url: str
    session_id: str
