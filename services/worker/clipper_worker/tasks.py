import logging
import mimetypes
import socket
import tempfile
import uuid
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from rq.job import Job as RQJob
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.models import Clip, Job, Video
from app.db.session import SessionLocal
from app.logging_config import log_timing
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


def process_video(
    video_id: str,
    job_id: str,
    source_url: str | None = None,
) -> TranscriptionResult:
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
        audio_path = workdir / "audio.wav"
        with log_timing(logger, "source_download", video_id=video_id):
            if source_url is None:
                source_path = workdir / f"source{filename_suffix}"
                storage.download_file(source_key, source_path)
            else:
                source_path = _download_video_url(source_url, workdir)
                filename_suffix = source_path.suffix or filename_suffix
                try:
                    with source_path.open("rb") as source_file:
                        storage.upload_file(
                            source_file,
                            source_key,
                            mimetypes.guess_type(source_path.name)[0],
                        )
                    with SessionLocal() as session:
                        video = session.get(Video, video_uuid)
                        if video is None:
                            raise LookupError(f"Video not found: {video_id}")
                        video.original_filename = source_path.name
                        video.content_type = mimetypes.guess_type(source_path.name)[0]
                        video.size_bytes = source_path.stat().st_size
                        session.commit()
                except (BotoCoreError, ClientError, SQLAlchemyError):
                    _delete_render_object(
                        storage,
                        source_key,
                        "Failed to clean up URL-ingested source",
                    )
                    raise
        with log_timing(logger, "media_probe", video_id=video_id):
            metadata = probe_media(source_path)
        if not metadata.has_audio:
            raise AudioExtractionError("Video does not contain an audio stream")
        with log_timing(logger, "audio_extraction", video_id=video_id):
            extract_audio(source_path, audio_path)
        with log_timing(logger, "audio_upload", video_id=video_id):
            with audio_path.open("rb") as audio_file:
                storage.upload_file(audio_file, audio_key, "audio/wav")
        with log_timing(logger, "transcription", video_id=video_id):
            transcription = transcribe_audio(audio_path)
        hf_token = Settings().hf_token
        with log_timing(logger, "speaker_diarization", video_id=video_id):
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
    logger.info(
        "Finished processing video %s",
        video_id,
        extra={"event": "job_succeeded", "job_id": job_id, "video_id": video_id},
    )
    return transcription


def _validate_public_source_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Video URL must use HTTP or HTTPS and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("Video URL credentials are not allowed")

    hostname = parsed.hostname.lower().rstrip(".")
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise ValueError("Video URL host must be publicly reachable")
    try:
        port = parsed.port
    except ValueError as error:
        raise ValueError("Video URL contains an invalid port") from error

    try:
        address = ip_address(hostname)
    except ValueError:
        try:
            addresses = {
                ip_address(result[4][0])
                for result in socket.getaddrinfo(
                    hostname,
                    port
                    if port is not None
                    else (443 if parsed.scheme == "https" else 80),
                    type=socket.SOCK_STREAM,
                )
            }
        except OSError as error:
            raise ValueError("Video URL hostname could not be resolved") from error
    else:
        addresses = {address}

    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Video URL host must resolve only to public IP addresses")


def _download_video_url(url: str, destination: Path) -> Path:
    _validate_public_source_url(url)
    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError("URL ingestion requires yt-dlp in the worker") from error

    options = {
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "no_progress": True,
        "no_warnings": True,
        "outtmpl": str(destination / "source.%(ext)s"),
        "quiet": True,
        "restrictfilenames": True,
    }
    with YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp did not return video metadata")
        candidates: list[str] = []
        for value in (info.get("filepath"), downloader.prepare_filename(info)):
            if isinstance(value, str):
                candidates.append(value)
        requested_downloads = info.get("requested_downloads")
        if isinstance(requested_downloads, list):
            candidates.extend(
                download["filepath"]
                for download in requested_downloads
                if isinstance(download, dict)
                and isinstance(download.get("filepath"), str)
            )

    destination_root = destination.resolve()
    for filename in candidates:
        path = Path(filename)
        if not path.is_absolute():
            path = destination / path
        resolved_path = path.resolve()
        try:
            resolved_path.relative_to(destination_root)
        except ValueError as error:
            raise RuntimeError(
                "yt-dlp output escaped its temporary directory"
            ) from error
        if resolved_path.is_file():
            return resolved_path

    video_files = sorted(
        path
        for path in destination.glob("source.*")
        if path.is_file()
        and path.suffix.lower()
        in {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm"}
    )
    if len(video_files) == 1:
        return video_files[0]
    raise RuntimeError("yt-dlp did not produce one final video file")


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
        with log_timing(logger, "clip_source_download", clip_id=str(clip_uuid)):
            storage.download_file(source_key, source_path)
        subtitle_path.write_text(subtitle_content, encoding="utf-8")
        with log_timing(logger, "clip_render", clip_id=str(clip_uuid)):
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
            with log_timing(logger, "clip_upload", clip_id=str(clip_uuid)):
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
    logger.info(
        "Finished rendering clip %s",
        clip_id,
        extra={"event": "job_succeeded", "job_id": job_id, "clip_id": clip_id},
    )
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
    if rq_job.retries_left is not None and rq_job.retries_left > 0:
        logger.warning(
            "Video processing job %s failed; %s retries remain",
            rq_job.id,
            rq_job.retries_left,
            extra={
                "event": "job_retry_pending",
                "job_id": str(rq_job.id),
                "retry_count": rq_job.retries_left,
            },
        )
        return

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
    logger.error(
        "Video processing job %s failed: %s",
        job_id,
        exc_value,
        extra={"event": "job_failed", "job_id": str(job_id), "video_id": str(video_id)},
    )


def mark_clip_render_failed(
    rq_job: RQJob,
    _connection: object,
    _exc_type: type[BaseException],
    exc_value: BaseException,
    _traceback: object,
) -> None:
    if rq_job.retries_left is not None and rq_job.retries_left > 0:
        logger.warning(
            "Clip render job %s failed; %s retries remain",
            rq_job.id,
            rq_job.retries_left,
            extra={
                "event": "job_retry_pending",
                "job_id": str(rq_job.id),
                "retry_count": rq_job.retries_left,
            },
        )
        return

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
    logger.error(
        "Clip render job %s failed: %s",
        job_id,
        exc_value,
        extra={"event": "job_failed", "job_id": str(job_id), "clip_id": str(clip_id)},
    )
