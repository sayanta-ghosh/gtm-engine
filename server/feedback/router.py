"""Feedback router: submit feedback, bugs, feature requests."""

from __future__ import annotations

from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.models import Tenant
from server.core.config import settings
from server.core.database import get_db, set_tenant_context
from server.auth.flexible import get_tenant_flexible as _get_tenant_flexible

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message: str
    type: str = "feedback"  # feedback, bug, feature


@router.post("/feedback", status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    body: FeedbackRequest,
    deps: tuple = Depends(_get_tenant_flexible),
) -> dict:
    """Submit feedback."""
    tenant, db = deps
    user_id = None  # Could be extracted from JWT if available

    await db.execute(
        text(
            "INSERT INTO feedback (id, tenant_id, user_id, type, message, context) "
            "VALUES (:id, :tenant_id, :user_id, :type, :message, :context)"
        ),
        {
            "id": str(uuid4()),
            "tenant_id": tenant.id,
            "user_id": user_id,
            "type": body.type,
            "message": body.message,
            "context": None,  # JSON serialization handled by driver
        },
    )
    await db.commit()
    return {"status": "ok", "message": "Feedback submitted"}
