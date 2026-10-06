import logging
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from rq.job import Job as RQJob

from app.config import Settings
from app.db.models import Job, Video
from app.db.session import SessionLocal
from app.schemas.transcript import TranscriptSchema
from app.storage import get_object_storage
from clipper_worker.diarization import attach_speakers, diarize_audio
from clipper_worker.media import AudioExtractionError, extract_audio, probe_media
from clipper_worker.transcription import TranscriptionResult, transcribe_audio

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
