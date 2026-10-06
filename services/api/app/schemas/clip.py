import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ClipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID
    start_seconds: float
    end_seconds: float
    rank: int | None
    score: float | None
    title: str | None
    aspect_ratio: str
    status: str
    created_at: datetime
    preview_url: str | None = None
