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

router = APIRouter(prefix="/api/v1", tags=["feedback"])

_COOKIE_NAME = "nrv_session"


class FeedbackRequest(BaseModel):
    message: str
    type: str = "feedback"
    context: dict | None = None


async def _get_tenant_flexible(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> tuple[Tenant, AsyncSession]:
    """Authenticate via Bearer token, session cookie, or query param."""
    jwt_token: str | None = None
    from sqlalchemy import select

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header.removeprefix("Bearer ")
    if not jwt_token:
        jwt_token = request.cookies.get(_COOKIE_NAME)
    if not jwt_token and token:
        jwt_token = token
    if not jwt_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        payload = jwt.decode(jwt_token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired.")

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    await set_tenant_context(db, tenant.id)
    return tenant, db


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
