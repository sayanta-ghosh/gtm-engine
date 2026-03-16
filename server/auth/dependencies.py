"""Shared FastAPI dependencies for authentication and authorisation."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.config import settings
from server.core.database import get_db, set_tenant_context
from server.billing.models import CreditBalance
from server.auth.models import Tenant, User


async def get_current_user(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT from the Authorization header.

    Returns the authenticated User ORM object.
    Raises 401 if the token is missing, malformed, or expired.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use Bearer scheme",
        )
    token = authorization.removeprefix("Bearer ")
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token missing subject claim",
            )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


async def get_current_tenant(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Tenant:
    """Resolve the tenant for the authenticated user and activate RLS context.

    Returns the Tenant ORM object.
    """
    result = await db.execute(select(Tenant).where(Tenant.id == user.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )
    await set_tenant_context(db, tenant.id)
    return tenant


def require_credits(amount: float):
    """Return a dependency that checks the tenant has at least *amount* credits.

    Raises HTTP 402 Payment Required when the balance is insufficient.

    Usage::

        @router.post("/execute", dependencies=[Depends(require_credits(1.0))])
        async def execute(...): ...
    """

    async def _check(
        tenant: Tenant = Depends(get_current_tenant),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        result = await db.execute(
            select(CreditBalance).where(CreditBalance.tenant_id == tenant.id)
        )
        balance_row = result.scalar_one_or_none()
        current_balance = float(balance_row.balance) if balance_row else 0.0
        if current_balance < amount:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Insufficient credits: need {amount}, have {current_balance}",
            )

    return _check
