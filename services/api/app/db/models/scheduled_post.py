from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.clip import Clip


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('youtube', 'tiktok', 'instagram')",
            name="ck_scheduled_posts_platform",
        ),
        CheckConstraint(
            "status IN ('scheduled', 'publishing', 'published', 'failed', 'cancelled')",
            name="ck_scheduled_posts_status",
        ),
        Index("ix_scheduled_posts_clip_id", "clip_id"),
        Index("ix_scheduled_posts_scheduled_at", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    clip_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("clips.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", server_default="scheduled"
    )
    platform_post_id: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    clip: Mapped[Clip] = relationship(back_populates="scheduled_posts")
