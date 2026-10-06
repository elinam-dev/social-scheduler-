import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from rq.job import Job as RQJob
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.models import Clip, Job, Video
from app.db.session import SessionLocal
from app.schemas.transcript import TranscriptSchema
from app.storage import ObjectStorage, get_object_storage
from clipper_worker.ass_subtitles import build_ass_subtitles
from clipper_worker.caption_styles import CAPTION_STYLE_PRESETS
from clipper_worker.captions import build_caption_chunks
from clipper_worker.diarization import attach_speakers, diarize_audio
from clipper_worker.fallback_rendering import render_fallback_clip
from clipper_worker.media import AudioExtractionError, extract_audio, probe_media
from clipper_worker.transcription import (
    TranscriptionResult,
    WordTimestamp,
    transcribe_audio,
)

logger = logging.getLogger(__name__)


def process_video(video_id: str, job_id: str) -> TranscriptionResult:
    video_uuid = uuid.UUID(video_id)
    job_uuid = uuid.UUID(job_id)
    with SessionLocal() as session:
        video = session.get(Video, video_uuid)
        job = session.get(Job, job_uuid)
        if video is None or job is None:
            raise LookupError(
                f"Video or processing job not found: {video_id}, {job_id}"
            )
        source_key = video.object_key
        filename_suffix = Path(video.original_filename).suffix or ".video"
        audio_key = f"{video.project_id}/{video.id}/audio.wav"
        video.status = "processing"
        job.status = "running"
        job.progress = 10
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.commit()

    storage = get_object_storage()
    with tempfile.TemporaryDirectory(prefix="clipper-") as temporary_directory:
        workdir = Path(temporary_directory)
        source_path = workdir / f"source{filename_suffix}"
        audio_path = workdir / "audio.wav"
        storage.download_file(source_key, source_path)
        metadata = probe_media(source_path)
        if not metadata.has_audio:
            raise AudioExtractionError("Video does not contain an audio stream")
        extract_audio(source_path, audio_path)
        with audio_path.open("rb") as audio_file:
            storage.upload_file(audio_file, audio_key, "audio/wav")
        transcription = transcribe_audio(audio_path)
        hf_token = Settings().hf_token
        diarization = diarize_audio(
            audio_path,
            hf_token=hf_token.get_secret_value() if hf_token else None,
        )
        transcription = attach_speakers(transcription, diarization)

    with SessionLocal() as session:
        video = session.get(Video, video_uuid)
        job = session.get(Job, job_uuid)
        if video is None or job is None:
            raise LookupError(
                f"Video or processing job not found: {video_id}, {job_id}"
            )
        video.audio_object_key = audio_key
        video.duration_seconds = metadata.duration_seconds
        video.width = metadata.width
        video.height = metadata.height
        video.frame_rate = metadata.frame_rate
        video.transcript = TranscriptSchema.model_validate(transcription).model_dump(
            mode="json"
        )
        video.status = "ready"
        job.status = "succeeded"
        job.progress = 100
        job.completed_at = datetime.now(UTC)
        session.commit()
    logger.info("Finished processing video %s", video_id)
    return transcription


def render_clip_job(clip_id: str, job_id: str) -> str:
    clip_uuid = uuid.UUID(clip_id)
    job_uuid = uuid.UUID(job_id)
    with SessionLocal() as session:
        clip = session.get(Clip, clip_uuid)
        job = session.get(Job, job_uuid)
        if clip is None or job is None:
            raise LookupError(f"Clip or render job not found: {clip_id}, {job_id}")
        video = session.get(Video, clip.video_id)
        if video is None or video.transcript is None:
            raise LookupError(f"Video transcript not found for clip {clip_id}")
        if video.status != "ready":
            raise ValueError(f"Source video is not ready for clip {clip_id}")

        project_uuid = video.project_id
        video_uuid = video.id
        source_key = video.object_key
        filename_suffix = Path(video.original_filename).suffix or ".video"
        start_seconds = clip.start_seconds
        end_seconds = clip.end_seconds
        aspect_ratio = clip.aspect_ratio
        caption_style_name = clip.caption_style
        previous_object_key = clip.object_key
        transcript_data = video.transcript
        clip.status = "rendering"
        job.status = "running"
        job.progress = 10
        job.started_at = datetime.now(UTC)
        job.error_message = None
        session.commit()

    transcript = TranscriptSchema.model_validate(transcript_data)
    if end_seconds > transcript.duration_seconds:
        raise ValueError("Clip end time exceeds the transcript duration")
    words = tuple(
        WordTimestamp(
            start_seconds=word.start_seconds,
            end_seconds=word.end_seconds,
            text=word.text,
            probability=word.probability,
            speaker_id=word.speaker_id,
        )
        for segment in transcript.segments
        for word in segment.words
        if word.end_seconds > start_seconds and word.start_seconds < end_seconds
    )
    chunks = build_caption_chunks(words)
    if not chunks:
        raise ValueError(f"No transcript words are available for clip {clip_id}")

    style = CAPTION_STYLE_PRESETS.get(caption_style_name)
    if style is None:
        raise ValueError(f"Unsupported caption style: {caption_style_name}")
    dimensions = {
        "9:16": (1080, 1920),
        "1:1": (1080, 1080),
        "16:9": (1920, 1080),
    }.get(aspect_ratio)
    if dimensions is None:
        raise ValueError(f"Unsupported clip aspect ratio: {aspect_ratio}")
    output_width, output_height = dimensions
    subtitle_content = build_ass_subtitles(
        chunks,
        play_res_x=output_width,
        play_res_y=output_height,
        clip_start_seconds=start_seconds,
        clip_end_seconds=end_seconds,
        style=style,
    )

    storage = get_object_storage()
    object_key = f"{project_uuid}/{video_uuid}/clips/{clip_uuid}/{uuid.uuid4().hex}.mp4"
    with tempfile.TemporaryDirectory(prefix="clipper-render-") as temporary_directory:
        workdir = Path(temporary_directory)
        source_path = workdir / f"source{filename_suffix}"
        subtitle_path = workdir / "captions.ass"
        output_path = workdir / "clip.mp4"
        storage.download_file(source_key, source_path)
        subtitle_path.write_text(subtitle_content, encoding="utf-8")
        render_fallback_clip(
            source_path,
            output_path,
            start_seconds,
            end_seconds,
            layout="blurred-background",
            output_width=output_width,
            output_height=output_height,
            subtitle_path=subtitle_path,
        )

        try:
            with output_path.open("rb") as rendered_file:
                storage.upload_file(rendered_file, object_key, "video/mp4")
        except (BotoCoreError, ClientError):
            _delete_render_object(
                storage,
                object_key,
                "Failed to clean up incomplete clip render",
            )
            raise

    try:
        with SessionLocal() as session:
            clip = session.get(Clip, clip_uuid)
            job = session.get(Job, job_uuid)
            if clip is None or job is None:
                raise LookupError(f"Clip or render job not found: {clip_id}, {job_id}")
            clip.object_key = object_key
            clip.status = "ready"
            job.status = "succeeded"
            job.progress = 100
            job.completed_at = datetime.now(UTC)
            session.commit()
    except (LookupError, SQLAlchemyError):
        _delete_render_object(
            storage,
            object_key,
            "Failed to clean up an uncommitted clip render",
        )
        raise

    if previous_object_key is not None and previous_object_key != object_key:
        _delete_render_object(
            storage,
            previous_object_key,
            "Failed to clean up the previous clip render",
        )
    logger.info("Finished rendering clip %s", clip_id)
    return object_key


def _delete_render_object(
    storage: ObjectStorage, object_key: str, message: str
) -> None:
    try:
        storage.delete_file(object_key)
    except (BotoCoreError, ClientError):
        logger.exception("%s: %s", message, object_key)


def mark_job_failed(
    rq_job: RQJob,
    _connection: object,
    _exc_type: type[BaseException],
    exc_value: BaseException,
    _traceback: object,
) -> None:
    video_id = uuid.UUID(rq_job.args[0])
    job_id = uuid.UUID(rq_job.args[1])
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        job = session.get(Job, job_id)
        if video is None or job is None:
            raise LookupError(
                f"Video or processing job not found: {video_id}, {job_id}"
            )
        video.status = "failed"
        job.status = "failed"
        job.error_message = str(exc_value)[:4000]
        job.completed_at = datetime.now(UTC)
        session.commit()
    logger.error("Video processing job %s failed: %s", job_id, exc_value)


def mark_clip_render_failed(
    rq_job: RQJob,
    _connection: object,
    _exc_type: type[BaseException],
    exc_value: BaseException,
    _traceback: object,
) -> None:
    clip_id = uuid.UUID(rq_job.args[0])
    job_id = uuid.UUID(rq_job.args[1])
    with SessionLocal() as session:
        clip = session.get(Clip, clip_id)
        job = session.get(Job, job_id)
        if clip is None or job is None:
            raise LookupError(f"Clip or render job not found: {clip_id}, {job_id}")
        clip.status = "failed"
        job.status = "failed"
        job.error_message = str(exc_value)[:4000]
        job.completed_at = datetime.now(UTC)
        session.commit()
    logger.error("Clip render job %s failed: %s", job_id, exc_value)
