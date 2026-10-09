import logging
import mimetypes
import socket
import tempfile
import time
import uuid
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from rq.job import Job as RQJob
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db.models import Clip, Job, PlatformToken, ScheduledPost, Video
from clipper_worker.candidate_review import StructuredOutputError, review_candidate
from clipper_worker.candidates import generate_candidate_windows
from clipper_worker.llm import LLMError, create_llm_client
from clipper_worker.ranking import rank_scored_candidates
from clipper_worker.scoring import score_candidate
from clipper_worker.segmentation import segment_sentences
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
        job.progress = 80
        session.commit()

    # --- Clip generation ---
    clips = _generate_clips(video_uuid, transcription, audio_key)

    with SessionLocal() as session:
        job = session.get(Job, job_uuid)
        if job is None:
            raise LookupError(f"Processing job not found: {job_id}")
        for clip in clips:
            session.add(clip)
        job.status = "succeeded"
        job.progress = 100
        job.completed_at = datetime.now(UTC)
        session.commit()
        # Refresh to get DB-assigned IDs
        for clip in clips:
            session.refresh(clip)
        clip_ids = [str(clip.id) for clip in clips]
        project_id = str(clips[0].video_id) if clips else None

    # Auto-enqueue render jobs for all clips
    if clip_ids:
        _enqueue_render_jobs(clip_ids, str(video_uuid))

    logger.info(
        "Finished processing video %s — %d clips created",
        video_id,
        len(clips),
        extra={"event": "job_succeeded", "job_id": job_id, "video_id": video_id},
    )
    return transcription


def _enqueue_render_jobs(clip_ids: list[str], video_id: str) -> None:
    import os
    from redis import Redis
    from rq import Queue
    from rq.job import Callback
    from app.queue import JOB_RETRY_POLICY

    connection = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    queue = Queue("render", connection=connection)

    with SessionLocal() as session:
        video = session.get(Video, uuid.UUID(video_id))
        if video is None:
            return
        project_id = video.project_id

    for clip_id in clip_ids:
        render_job_id = uuid.uuid4()
        with SessionLocal() as session:
            clip = session.get(Clip, uuid.UUID(clip_id))
            if clip is None:
                continue
            render_job = Job(
                id=render_job_id,
                project_id=project_id,
                video_id=uuid.UUID(video_id),
                job_type="render_clip",
                rq_job_id=str(render_job_id),
            )
            clip.status = "rendering"
            session.add(render_job)
            session.commit()
        try:
            queue.enqueue(
                "clipper_worker.tasks.render_clip_job",
                clip_id,
                str(render_job_id),
                job_id=str(render_job_id),
                job_timeout=21600,
                retry=JOB_RETRY_POLICY,
                on_failure=Callback("clipper_worker.tasks.mark_clip_render_failed"),
            )
            logger.info("Auto-enqueued render job for clip %s", clip_id)
        except Exception:
            logger.exception("Failed to enqueue render job for clip %s", clip_id)


# Minimum silence gap to consider a sentence start a topic boundary
_TOPIC_BOUNDARY_GAP_SECONDS = 1.5


def _generate_clips(
    video_uuid: uuid.UUID,
    transcription: TranscriptionResult,
    audio_key: str,
) -> list[Clip]:
    """Candidate selection, scoring, and ranking; return Clip rows."""
    sentences = segment_sentences(transcription)
    if not sentences:
        logger.warning("No sentences found for video %s — skipping clip generation", video_uuid)
        return []

    # Find sentence indices that follow a meaningful pause (topic boundaries)
    boundary_indices: set[int] = {0}  # always allow starting at the very beginning
    for i in range(1, len(sentences)):
        gap = sentences[i].start_seconds - sentences[i - 1].end_seconds
        if gap >= _TOPIC_BOUNDARY_GAP_SECONDS:
            boundary_indices.add(i)

    # Only generate windows that start at a topic boundary
    boundary_sentences = tuple(
        s for i, s in enumerate(sentences) if i in boundary_indices
    )
    # Build candidates using boundary starts but full sentence list for end alignment
    from clipper_worker.candidates import CandidateWindow, DEFAULT_MIN_CANDIDATE_DURATION_SECONDS, DEFAULT_MAX_CANDIDATE_DURATION_SECONDS
    candidates: list[CandidateWindow] = []
    sentence_list = list(sentences)
    for first_index, first_sentence in enumerate(sentence_list):
        if first_index not in boundary_indices:
            continue
        text_parts: list[str] = []
        for last_index in range(first_index, len(sentence_list)):
            sentence = sentence_list[last_index]
            duration = sentence.end_seconds - first_sentence.start_seconds
            if duration > DEFAULT_MAX_CANDIDATE_DURATION_SECONDS:
                break
            text_parts.append(sentence.text.strip())
            if duration >= DEFAULT_MIN_CANDIDATE_DURATION_SECONDS:
                candidates.append(
                    CandidateWindow(
                        start_seconds=first_sentence.start_seconds,
                        end_seconds=sentence.end_seconds,
                        text=" ".join(p for p in text_parts if p),
                        first_sentence_index=first_index,
                        end_sentence_index=last_index + 1,
                    )
                )

    if not candidates:
        logger.warning("No candidate windows for video %s — skipping clip generation", video_uuid)
        return []

    logger.info("Generated %d candidates from %d boundary sentences for video %s",
                len(candidates), len(boundary_indices), video_uuid)

    storage = get_object_storage()
    with tempfile.TemporaryDirectory(prefix="clipper-clips-") as tmpdir:
        audio_path = Path(tmpdir) / "audio.wav"
        storage.download_file(audio_key, audio_path)
        return _review_score_rank(video_uuid, tuple(candidates), sentences, audio_path)


_DEFAULT_EVALUATION = None  # resolved lazily below
_MAX_CANDIDATES_FOR_LLM = 40


def _default_evaluation() -> "CandidateEvaluation":
    from clipper_worker.candidate_review import CandidateEvaluation
    return CandidateEvaluation(
        hook_strength=0.5,
        standalone_coherence=0.5,
        payoff=0.5,
        pacing=0.5,
        standalone=True,
        rationale="LLM review unavailable; using default scores.",
    )


def _review_score_rank(
    video_uuid: uuid.UUID,
    candidates: tuple,
    sentences: tuple,
    audio_path: Path,
) -> list[Clip]:
    from clipper_worker.scoring import AudioScoreError

    reviewed: list[tuple] = []
    default_eval = _default_evaluation()
    for candidate in candidates:
        try:
            score = score_candidate(candidate, default_eval, sentences, audio_path)
        except (AudioScoreError, ValueError) as exc:
            logger.warning("Scoring failed for candidate, skipping: %s", exc)
            continue
        reviewed.append((candidate, default_eval, score))

    if not reviewed:
        logger.warning("No candidates survived review/scoring for video %s", video_uuid)
        return []

    ranked = rank_scored_candidates(
        ((c, e, s) for c, e, s in reviewed),
    )

    clips: list[Clip] = []
    for rank, item in enumerate(ranked, start=1):
        clips.append(
            Clip(
                video_id=video_uuid,
                start_seconds=item.candidate.start_seconds,
                end_seconds=item.candidate.end_seconds,
                rank=rank,
                score=item.score,
                title=None,
                status="pending",
            )
        )
    return clips


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
        hook_text = clip.title
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
        hook_text=hook_text,
    )

    storage = get_object_storage()
    object_key = f"{project_uuid}/{video_uuid}/clips/{clip_uuid}/{uuid.uuid4().hex}.mp4"
    with tempfile.TemporaryDirectory(prefix="clipper-render-") as temporary_directory:
        workdir = Path(temporary_directory)
        subtitle_path = workdir / "captions.ass"
        output_path = workdir / "clip.mp4"

        # --- source video cache ---
        _CACHE_DIR = Path("/tmp/clipper-source-cache")
        source_path = workdir / f"source{filename_suffix}"  # fallback default
        try:
            _CACHE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
            safe_key = source_key.replace("/", "_").replace("\\", "_")
            # strip leading underscores that would hide the file
            safe_key = safe_key.lstrip("_") or "source"
            cache_filename = f"{safe_key}{filename_suffix}"
            cache_path = _CACHE_DIR / cache_filename
            if cache_path.exists() and cache_path.stat().st_size > 0:
                logger.info("Cache hit for source %s", source_key)
                source_path = cache_path
            else:
                logger.info("Downloading source %s to cache", source_key)
                tmp_cache_path = _CACHE_DIR / f"{cache_filename}.tmp"
                with log_timing(logger, "clip_source_download", clip_id=str(clip_uuid)):
                    storage.download_file(source_key, tmp_cache_path)
                tmp_cache_path.rename(cache_path)
                source_path = cache_path
        except Exception:
            logger.warning(
                "Source cache unavailable for %s, falling back to direct download",
                source_key,
                exc_info=True,
            )
            source_path = workdir / f"source{filename_suffix}"
            with log_timing(logger, "clip_source_download", clip_id=str(clip_uuid)):
                storage.download_file(source_key, source_path)
        # --- end source video cache ---

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


def post_clip_to_platform(post_id: str) -> str:
    """Download a rendered clip and publish it to the target platform."""
    post_uuid = uuid.UUID(post_id)

    with SessionLocal() as session:
        post = session.get(ScheduledPost, post_uuid)
        if post is None:
            raise LookupError(f"ScheduledPost not found: {post_id}")
        if post.status == "cancelled":
            return "cancelled"

        clip = session.get(Clip, post.clip_id)
        if clip is None or clip.object_key is None:
            raise LookupError(f"Clip or rendered file not found for post {post_id}")

        token_row = session.scalar(
            select(PlatformToken).where(PlatformToken.platform == post.platform)
        )
        if token_row is None:
            raise RuntimeError(
                f"No OAuth token for platform '{post.platform}'. "
                "Connect the platform in the UI first."
            )

        object_key = clip.object_key
        platform = post.platform
        title = clip.title or f"Clip {clip.id}"
        encrypted_token = token_row.encrypted_token
        post.status = "publishing"
        session.commit()

    from app.token_crypto import decrypt_token
    from clipper_worker.publishing import PublishError, publish_clip

    settings = Settings()
    token_data = decrypt_token(encrypted_token, settings)

    storage = get_object_storage()
    with tempfile.TemporaryDirectory(prefix="clipper-publish-") as tmpdir:
        clip_path = Path(tmpdir) / "clip.mp4"
        with log_timing(logger, "publish_download", post_id=post_id):
            storage.download_file(object_key, clip_path)

        # For Instagram we need a public URL — generate a pre-signed MinIO URL
        description = ""
        if platform == "instagram":
            import json as _json
            presigned = storage.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": storage.bucket, "Key": object_key},
                ExpiresIn=3600,
            )
            description = _json.dumps({"video_url": presigned, "caption": title})

        with log_timing(logger, "platform_publish", post_id=post_id, platform=platform):
            platform_post_id = publish_clip(
                platform, token_data, clip_path, title, description
            )

    # Persist refreshed token (YouTube may have refreshed it)
    from app.token_crypto import encrypt_token

    with SessionLocal() as session:
        post = session.get(ScheduledPost, post_uuid)
        token_row = session.scalar(
            select(PlatformToken).where(PlatformToken.platform == platform)
        )
        if post is not None:
            post.status = "published"
            post.platform_post_id = platform_post_id
        if token_row is not None:
            token_row.encrypted_token = encrypt_token(token_data, settings)
        session.commit()

    logger.info(
        "Published clip %s to %s: %s",
        post_id,
        platform,
        platform_post_id,
        extra={
            "event": "clip_published",
            "post_id": post_id,
            "platform": platform,
            "platform_post_id": platform_post_id,
        },
    )
    return platform_post_id


def mark_post_failed(
    rq_job: RQJob,
    _connection: object,
    _exc_type: type[BaseException],
    exc_value: BaseException,
    _traceback: object,
) -> None:
    if rq_job.retries_left is not None and rq_job.retries_left > 0:
        return

    post_id = uuid.UUID(rq_job.args[0])
    with SessionLocal() as session:
        post = session.get(ScheduledPost, post_id)
        if post is not None:
            post.status = "failed"
            post.error_message = str(exc_value)[:4000]
            session.commit()
    logger.error(
        "Scheduled post %s failed: %s",
        post_id,
        exc_value,
        extra={"event": "post_failed", "post_id": str(post_id)},
    )


def run_publish_scheduler(queue_name: str = "default") -> None:
    """
    Long-running loop that polls for due ScheduledPosts and enqueues them.
    Run this in a separate process or thread alongside the RQ worker.
    """
    import os

    from redis import Redis
    from rq import Queue
    from rq.job import Callback

    connection = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    queue = Queue(queue_name, connection=connection)

    logger.info("Publish scheduler started")
    while True:
        try:
            _enqueue_due_posts(queue)
        except Exception:
            logger.exception("Publish scheduler error")
        time.sleep(30)


def _enqueue_due_posts(queue: object) -> None:
    from rq import Queue
    from rq.job import Callback
    from rq.job import Retry

    assert isinstance(queue, Queue)
    now = datetime.now(UTC)
    with SessionLocal() as session:
        due = session.scalars(
            select(ScheduledPost).where(
                ScheduledPost.status == "scheduled",
                ScheduledPost.scheduled_at <= now,
            )
        ).all()
        for post in due:
            post.status = "publishing"
            session.commit()
            try:
                queue.enqueue(
                    "clipper_worker.tasks.post_clip_to_platform",
                    str(post.id),
                    job_timeout=1800,
                    retry=Retry(max=3, interval=[60, 120, 300]),
                    on_failure=Callback(
                        "clipper_worker.tasks.mark_post_failed"
                    ),
                )
                logger.info(
                    "Enqueued publish job for post %s (%s)",
                    post.id,
                    post.platform,
                )
            except Exception:
                post.status = "scheduled"
                session.commit()
                logger.exception("Failed to enqueue post %s", post.id)
