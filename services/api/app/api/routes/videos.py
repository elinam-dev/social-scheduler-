import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import Video
from app.db.session import get_session
from app.schemas.transcript import TranscriptSchema

router = APIRouter(tags=["videos"])


@router.get("/videos/{video_id}/transcript", response_model=TranscriptSchema)
def get_video_transcript(
    video_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> TranscriptSchema:
    video = session.get(Video, video_id)
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )
    if video.transcript is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Transcript is not available yet",
        )
    return TranscriptSchema.model_validate(video.transcript)
