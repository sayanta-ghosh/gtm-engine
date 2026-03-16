"""Async SQLAlchemy database setup with tenant-scoped RLS."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from server.core.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.ENVIRONMENT == "development",
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an async database session.

    The session is automatically closed when the request finishes.
    """
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()


async def set_tenant_context(session: AsyncSession, tenant_id: str) -> None:
    """Set the current tenant for Postgres row-level security.

    Executes ``SET LOCAL app.current_tenant`` so that all RLS policies
    in this transaction scope only to the given tenant.

    Note: We use string formatting because asyncpg does not support
    parameterized SET statements. The tenant_id is safe because it was
    loaded from our own tenants table (not user input).
    """
    # Sanitise to prevent SQL injection -- tenant_ids are alphanumeric + hyphens
    safe_id = "".join(c for c in tenant_id if c.isalnum() or c == "-")
    await session.execute(text(f"SET LOCAL app.current_tenant = '{safe_id}'"))
