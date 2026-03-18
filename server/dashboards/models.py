"""Dashboard model for tenant-deployed dashboards."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class Dashboard(Base):
    """A deployed dashboard for a tenant."""

    __tablename__ = "dashboards"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_dashboards_tenant_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    s3_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    dataset_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("datasets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    config: Mapped[dict | None] = mapped_column(JSONB, server_default="{}")
    data_queries: Mapped[dict | None] = mapped_column(JSONB)
    read_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    read_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_interval: Mapped[int] = mapped_column(Integer, server_default="3600")
    password_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
