import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, Job, Project, Video
from clipper_worker import tasks
from clipper_worker.media import MediaMetadata
from clipper_worker.transcription import TranscriptionResult, TranscriptionSegment


class FakeObjectStorage:
    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}

    def download_file(self, object_key: str, destination: str | Path) -> None:
        assert object_key == "source-object"
        Path(destination).write_bytes(b"source video")

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        assert content_type == "audio/wav"
        self.uploads[object_key] = file.read()


def test_process_video_updates_job_and_persists_metadata(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    video_id = uuid.uuid4()
    job_id = uuid.uuid4()
    with session_factory() as session:
        project = Project(id=project_id, name="Interview")
        video = Video(
            id=video_id,
            project=project,
            original_filename="episode.mp4",
            object_key="source-object",
            size_bytes=12,
        )
        job = Job(
            id=job_id,
            project_id=project_id,
            video=video,
            job_type="process_video",
            rq_job_id=str(job_id),
        )
        session.add_all([project, video, job])
        session.commit()

    storage = FakeObjectStorage()
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_object_storage", lambda: storage)
    monkeypatch.setattr(
        tasks,
        "probe_media",
        lambda _path: MediaMetadata(
            duration_seconds=40.5,
            width=1920,
            height=1080,
            frame_rate=30,
            has_audio=True,
        ),
    )

    def write_audio(_source: Path, destination: Path) -> Path:
        destination.write_bytes(b"wav bytes")
        return destination

    monkeypatch.setattr(tasks, "extract_audio", write_audio)
    transcription_result = TranscriptionResult(
        language="en",
        language_probability=0.99,
        duration_seconds=3,
        segments=(TranscriptionSegment(0, 3, "An example transcript."),),
    )
    monkeypatch.setattr(tasks, "transcribe_audio", lambda _path: transcription_result)

    result = tasks.process_video(str(video_id), str(job_id))

    with Session(engine) as session:
        stored_video = session.get(Video, video_id)
        stored_job = session.get(Job, job_id)
        assert stored_video is not None
        assert stored_job is not None
        assert stored_video.status == "ready"
        assert stored_video.duration_seconds == 40.5
        assert stored_video.width == 1920
        assert stored_video.height == 1080
        assert stored_video.audio_object_key == f"{project_id}/{video_id}/audio.wav"
        assert stored_job.status == "succeeded"
        assert stored_job.progress == 100
    assert storage.uploads == {f"{project_id}/{video_id}/audio.wav": b"wav bytes"}
    assert result == transcription_result


def test_failure_handler_marks_job_and_video_failed(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'failed-worker.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    video_id = uuid.uuid4()
    job_id = uuid.uuid4()
    with session_factory() as session:
        project = Project(id=project_id, name="Interview")
        video = Video(
            id=video_id,
            project=project,
            original_filename="episode.mp4",
            object_key="source-object",
            size_bytes=12,
        )
        job = Job(
            id=job_id,
            project_id=project_id,
            video=video,
            job_type="process_video",
            rq_job_id=str(job_id),
            status="running",
        )
        session.add_all([project, video, job])
        session.commit()

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    rq_job = SimpleNamespace(id=str(job_id), args=(str(video_id), str(job_id)))

    tasks.mark_job_failed(
        rq_job,
        object(),
        RuntimeError,
        RuntimeError("ffprobe failed"),
        None,
    )

    with Session(engine) as session:
        stored_video = session.get(Video, video_id)
        stored_job = session.get(Job, job_id)
        assert stored_video is not None
        assert stored_job is not None
        assert stored_video.status == "failed"
        assert stored_job.status == "failed"
        assert stored_job.error_message == "ffprobe failed"
