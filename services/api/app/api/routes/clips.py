import logging
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import BinaryIO
from zipfile import ZIP_STORED, ZipFile

from botocore.exceptions import BotoCoreError, ClientError
from botocore.response import StreamingBody
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import StreamingResponse
from redis.exceptions import RedisError
from rq import Queue
from rq.job import Callback
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Job, Video
from app.db.session import get_session
from app.queue import get_queue
from app.schemas.clip import (
    ClipCaptionStyleUpdate,
    ClipRead,
    ClipTrimUpdate,
)
from app.schemas.job import JobRead
from app.storage import ObjectStorage, get_object_storage

logger = logging.getLogger(__name__)
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


@router.patch("/clips/{clip_id}/caption-style", response_model=ClipRead)
def update_clip_caption_style(
    clip_id: uuid.UUID,
    style: ClipCaptionStyleUpdate,
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
            detail="Caption style cannot be changed while rendering",
        )

    if style.caption_style != clip.caption_style:
        clip.caption_style = style.caption_style
        clip.status = "pending"
        session.commit()
        session.refresh(clip)

    return _clip_read(clip)


@router.post(
    "/clips/{clip_id}/render",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def render_clip(
    clip_id: uuid.UUID,
    session: Session = Depends(get_session),
    queue: Queue = Depends(get_queue),
) -> JobRead:
    clip = session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clip not found",
        )
    if clip.status == "rendering":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Clip is already rendering",
        )

    video = session.get(Video, clip.video_id)
    if video is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )
    if video.status != "ready" or video.transcript is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Video transcript is not available for rendering",
        )
    if video.duration_seconds is not None and clip.end_seconds > video.duration_seconds:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Clip end must not exceed the video duration",
        )

    job_id = uuid.uuid4()
    job = Job(
        id=job_id,
        project_id=video.project_id,
        video_id=video.id,
        job_type="render_clip",
        rq_job_id=str(job_id),
    )
    clip.status = "rendering"
    session.add(job)
    session.commit()
    session.refresh(job)

    try:
        queue.enqueue(
            "clipper_worker.tasks.render_clip_job",
            str(clip.id),
            str(job.id),
            job_id=job.rq_job_id,
            job_timeout=21600,
            on_failure=Callback("clipper_worker.tasks.mark_clip_render_failed"),
        )
    except RedisError as error:
        logger.exception("Could not queue render job for clip %s", clip.id)
        clip.status = "failed"
        job.status = "failed"
        job.error_message = "Could not submit clip render job to Redis"
        job.completed_at = datetime.now(UTC)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Clip render job could not be queued",
        ) from error

    return JobRead.model_validate(job)


def _stream_body(body: StreamingBody) -> Iterator[bytes]:
    try:
        while chunk := body.read(64 * 1024):
            yield chunk
    finally:
        body.close()


def _stream_file(body: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := body.read(64 * 1024):
            yield chunk
    finally:
        body.close()


def _get_storage_file(
    storage: ObjectStorage,
    object_key: str,
    *,
    purpose: str,
    range_header: str | None = None,
) -> tuple[StreamingBody, int, str | None, str | None]:
    try:
        return storage.get_file(object_key, range_header)
    except ClientError as error:
        error_code = error.response.get("Error", {}).get("Code")
        if error_code in {"NoSuchKey", "404", "NotFound"}:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{purpose} file not found",
            ) from error
        if error_code == "InvalidRange":
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="Requested byte range is not available",
            ) from error
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{purpose} storage is unavailable",
        ) from error
    except BotoCoreError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{purpose} storage is unavailable",
        ) from error


def _create_clip_archive(clips: list[Clip], storage: ObjectStorage) -> BinaryIO:
    archive = tempfile.TemporaryFile()
    try:
        with ZipFile(archive, mode="w", compression=ZIP_STORED) as zip_file:
            for index, clip in enumerate(clips, start=1):
                if clip.object_key is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Clip download is not available yet",
                    )
                body, _, _, _ = _get_storage_file(
                    storage,
                    clip.object_key,
                    purpose="Clip download",
                )
                filename = (
                    f"clip-{clip.rank if clip.rank is not None else index:02d}-"
                    f"{clip.id}.mp4"
                )
                try:
                    with zip_file.open(filename, mode="w", force_zip64=True) as entry:
                        while chunk := body.read(64 * 1024):
                            entry.write(chunk)
                finally:
                    body.close()
        archive.seek(0)
    except Exception:
        archive.close()
        raise
    return archive


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

    body, content_length, content_type, content_range = _get_storage_file(
        storage,
        clip.object_key,
        purpose="Clip preview",
        range_header=range_header,
    )

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


@router.get("/clips/{clip_id}/download")
def download_clip(
    clip_id: uuid.UUID,
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
            detail="Clip download is not available yet",
        )

    body, content_length, content_type, _ = _get_storage_file(
        storage,
        clip.object_key,
        purpose="Clip download",
    )
    headers = {
        "Content-Length": str(content_length),
        "Content-Disposition": f'attachment; filename="clip-{clip.id}.mp4"',
    }
    return StreamingResponse(
        _stream_body(body),
        media_type=content_type or "video/mp4",
        headers=headers,
    )


@router.get("/videos/{video_id}/clips/download")
def download_video_clips(
    video_id: uuid.UUID,
    session: Session = Depends(get_session),
    storage: ObjectStorage = Depends(get_object_storage),
) -> StreamingResponse:
    if session.get(Video, video_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found",
        )
    clips = session.scalars(
        select(Clip)
        .where(
            Clip.video_id == video_id,
            Clip.status == "ready",
            Clip.object_key.is_not(None),
        )
        .order_by(
            Clip.rank.asc().nulls_last(),
            Clip.start_seconds.asc(),
            Clip.created_at.asc(),
        )
    ).all()
    if not clips:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No rendered clips are available for download",
        )

    archive = _create_clip_archive(clips, storage)
    return StreamingResponse(
        _stream_file(archive),
        media_type="application/zip",
        headers={
            "Content-Disposition": (f'attachment; filename="clips-{video_id}.zip"')
        },
    )
