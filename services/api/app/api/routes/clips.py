import uuid
from collections.abc import Iterator

from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Video
from app.db.session import get_session
from app.schemas.clip import ClipRead, ClipTrimUpdate
from app.storage import ObjectStorage, get_object_storage

router = APIRouter(tags=["clips"])


def _clip_read(clip: Clip) -> ClipRead:
    return ClipRead.model_validate(clip).model_copy(
        update={
            "preview_url": (
                f"/clips/{clip.id}/preview"
                if clip.status == "ready" and clip.object_key
                else None
            )
        }
    )


@router.get("/videos/{video_id}/clips", response_model=list[ClipRead])
def list_video_clips(
    video_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> list[ClipRead]:
    if session.get(Video, video_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )

    clips = session.scalars(
        select(Clip)
        .where(Clip.video_id == video_id)
        .order_by(
            Clip.rank.asc().nulls_last(),
            Clip.start_seconds.asc(),
            Clip.created_at.asc(),
        )
    ).all()
    return [_clip_read(clip) for clip in clips]


@router.patch("/clips/{clip_id}/trim", response_model=ClipRead)
def update_clip_trim(
    clip_id: uuid.UUID,
    boundaries: ClipTrimUpdate,
    session: Session = Depends(get_session),
) -> ClipRead:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )
    if clip.status == "rendering":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Clip boundaries cannot be changed while rendering",
        )

    video = session.get(Video, clip.video_id)
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )
    if (
        video.duration_seconds is not None
        and boundaries.end_seconds > video.duration_seconds
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Clip end must not exceed the video duration",
        )

    if (
        boundaries.start_seconds != clip.start_seconds
        or boundaries.end_seconds != clip.end_seconds
    ):
        clip.start_seconds = boundaries.start_seconds
        clip.end_seconds = boundaries.end_seconds
        clip.status = "pending"
        session.commit()
        session.refresh(clip)

    return _clip_read(clip)


def _stream_body(body: StreamingBody) -> Iterator[bytes]:
    try:
        while chunk := body.read(64 * 1024):
            yield chunk
    finally:
        body.close()


@router.get("/clips/{clip_id}/preview")
def preview_clip(
    clip_id: uuid.UUID,
    range_header: str | None = Header(default=None, alias="Range"),
    session: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_object_storage),
) -> StreamingResponse:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )
    if clip.status != "ready" or clip.object_key is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Clip preview is not available yet",
        )

    try:
        body, content_length, content_type, content_range = storage.get_file(
            clip.object_key,
            range_header,
        )
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Clip preview file not found",
            ) from error
        if error_code == "InvalidRange":
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="Requested byte range is not available",
            ) from error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clip preview storage is unavailable",
        ) from error
    except BotoCoreError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clip preview storage is unavailable",
        ) from error

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(content_length),
        "Content-Disposition": "inline; filename=clip.mp4",
    }
    response_status = status.HTTP_200_OK
    if content_range is not None:
        headers["Content-Range"] = content_range
        response_status = status.HTTP_206_PARTIAL_CONTENT

    return StreamingResponse(
        _stream_body(body),
        status_code=response_status,
        media_type=content_type or "video/mp4",
        headers=headers,
    )
