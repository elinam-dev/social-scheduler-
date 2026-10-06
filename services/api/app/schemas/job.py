import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.video import VideoRead


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    video_id: uuid.UUID | None
    job_type: str
    status: str
    progress: int
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class VideoUploadResponse(BaseModel):
    video: VideoRead
    job: JobRead
