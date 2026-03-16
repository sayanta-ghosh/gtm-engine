"""Tenant BYOK key vault model."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, LargeBinary, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class TenantKey(Base):
    """An encrypted BYOK API key stored for a tenant + provider pair."""

    __tablename__ = "tenant_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_tenant_keys_tenant_provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_hint: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
