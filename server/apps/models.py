"""Hosted app model — static HTML/CSS/JS bundles backed by datasets."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from server.core.database import Base


class HostedApp(Base):
    __tablename__ = "hosted_apps"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    dataset_ids = Column(ARRAY(UUID(as_uuid=True)), nullable=False, default=[])
    app_token: Mapped[str] = mapped_column(Text, nullable=False)
    app_token_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    files: Mapped[dict] = mapped_column(JSONB, nullable=False, default={})
    entry_point: Mapped[str] = mapped_column(Text, default="index.html")
    status: Mapped[str] = mapped_column(Text, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
