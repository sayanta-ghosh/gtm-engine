"""Pydantic v2 request/response schemas for the vault module."""

from __future__ import annotations

from pydantic import BaseModel


class AddKeyRequest(BaseModel):
    provider: str
    api_key: str  # raw key - will be encrypted before storage


class KeyInfoResponse(BaseModel):
    provider: str
    key_hint: str | None
    status: str


class KeyListResponse(BaseModel):
    keys: list[KeyInfoResponse]
