import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CaptionStyleName = Literal["default", "minimal", "word-highlight"]


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
    caption_style: CaptionStyleName
    created_at: datetime
    preview_url: str | None = None


class ClipTrimUpdate(BaseModel):
    start_seconds: float = Field(ge=0, allow_inf_nan=False)
    end_seconds: float = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_boundaries(self) -> Self:
        if self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must be greater than start_seconds")
        return self


class ClipCaptionStyleUpdate(BaseModel):
    caption_style: CaptionStyleName
