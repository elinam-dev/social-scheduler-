import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Platform = Literal["youtube", "tiktok", "instagram"]


class ScheduledPostCreate(BaseModel):
    platforms: list[Platform]
    scheduled_at: datetime


class ScheduledPostRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clip_id: uuid.UUID
    platform: str
    scheduled_at: datetime
    status: str
    platform_post_id: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class PlatformConnectionStatus(BaseModel):
    platform: str
    connected: bool
    auth_url: str | None = None
