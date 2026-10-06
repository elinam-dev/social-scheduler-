from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.video import Video


class Clip(Base):
    __tablename__ = "clips"
    __table_args__ = (
        CheckConstraint("start_seconds >= 0", name="ck_clips_start_nonnegative"),
        CheckConstraint("end_seconds > start_seconds", name="ck_clips_end_after_start"),
        CheckConstraint("rank IS NULL OR rank > 0", name="ck_clips_rank_positive"),
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_clips_score_range",
        ),
        CheckConstraint(
            "status IN ('pending', 'rendering', 'ready', 'failed')",
            name="ck_clips_status",
        ),
        Index("ix_clips_video_id", "video_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("videos.id", ondelete="CASCADE"),
        nullable=False,
    )
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    score: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str | None] = mapped_column(String(200))
    object_key: Mapped[str | None] = mapped_column(String(1024), unique=True)
    aspect_ratio: Mapped[str] = mapped_column(
        String(10), nullable=False, default="9:16", server_default="9:16"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    video: Mapped[Video] = relationship(back_populates="clips")
