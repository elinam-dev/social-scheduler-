from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlatformToken(Base):
    __tablename__ = "platform_tokens"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('youtube', 'tiktok', 'instagram')",
            name="ck_platform_tokens_platform",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Single-user local app — platform is the unique key
    platform: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    # Fernet-encrypted JSON blob: {access_token, refresh_token, expires_at, ...}
    encrypted_token: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
