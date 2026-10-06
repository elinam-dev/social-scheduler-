import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    content_type: str | None
    size_bytes: int
    status: str
    created_at: datetime
