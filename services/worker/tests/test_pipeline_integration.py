import io
import uuid
from pathlib import Path

import anyio
from botocore.response import StreamingBody
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.projects import get_object_storage, get_queue
from app.db import Base, Clip, Job, Video
from app.db.session import get_session
from app.main import app
from app.queue import JOB_RETRY_POLICY
from clipper_worker import tasks
from clipper_worker.diarization import DiarizationResult
from clipper_worker.media import MediaMetadata
from clipper_worker.transcription import (
    TranscriptionResult,
    TranscriptionSegment,
    WordTimestamp,
)


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        self.objects[object_key] = (file.read(), content_type)

    def download_file(self, object_key: str, destination: str | Path) -> None:
        Path(destination).write_bytes(self.objects[object_key][0])

    def get_file(
        self, object_key: str, byte_range: str | None = None
    ) -> tuple[StreamingBody, int, str, str | None]:
        content, content_type = self.objects[object_key]
        if byte_range is not None:
            raise AssertionError("The integration flow does not request byte ranges")
        return (
            StreamingBody(io.BytesIO(content), len(content)),
            len(content),
            content_type or "application/octet-stream",
            None,
        )

    def delete_file(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


class InMemoryQueue:
    def __init__(self) -> None:
        self.enqueued: list[tuple[str, tuple[str, ...], dict[str, object]]] = []

    def enqueue(self, function: str, *args: str, **kwargs: object) -> None:
        self.enqueued.append((function, args, kwargs))


def test_upload_transcribe_render_and_download_flow(
    tmp_path: Path,
    monkeypatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'pipeline.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = InMemoryObjectStorage()
    queue = InMemoryQueue()

    def override_session():
        with session_factory() as session:
            yield session

    previous_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue
    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_object_storage", lambda: storage)
    monkeypatch.setattr(
        tasks,
        "probe_media",
        lambda _path: MediaMetadata(12, 1920, 1080, 30, True),
    )

    def write_audio(_source: Path, destination: Path) -> Path:
        destination.write_bytes(b"synthetic wav")
        return destination

    transcript = TranscriptionResult(
        language="en",
        language_probability=0.99,
        duration_seconds=5,
        segments=(
            TranscriptionSegment(
                0,
                5,
                "This is an integration test clip.",
                words=(
                    WordTimestamp(0, 0.6, "This", 0.99),
                    WordTimestamp(0.6, 1, "is", 0.99),
                    WordTimestamp(1, 1.5, "an", 0.99),
                    WordTimestamp(1.5, 2.5, "integration", 0.99),
                    WordTimestamp(2.5, 3, "test", 0.99),
                    WordTimestamp(3, 5, "clip.", 0.99),
                ),
            ),
        ),
    )
    monkeypatch.setattr(tasks, "extract_audio", write_audio)
    monkeypatch.setattr(tasks, "transcribe_audio", lambda _path: transcript)
    monkeypatch.setattr(
        tasks,
        "diarize_audio",
        lambda _path, **_kwargs: DiarizationResult(speakers=(), turns=()),
    )

    def render_clip(
        _source: Path,
        destination: Path,
        start_seconds: float,
        end_seconds: float,
        **_options: object,
    ) -> Path:
        assert start_seconds == 0
        assert end_seconds == 5
        destination.write_bytes(b"captioned integration clip")
        return destination

    monkeypatch.setattr(tasks, "render_fallback_clip", render_clip)

    async def run_flow() -> tuple[str, str, str, bytes]:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            project_response = await client.post(
                "/projects",
                json={"name": "End-to-end pipeline"},
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]

            upload_response = await client.post(
                f"/projects/{project_id}/videos",
                files={"file": ("episode.mp4", b"synthetic video", "video/mp4")},
            )
            assert upload_response.status_code == 201
            uploaded = upload_response.json()
            video_id = uploaded["video"]["id"]
            processing_job_id = uploaded["job"]["id"]
            function, args, options = queue.enqueued[0]
            assert function == "clipper_worker.tasks.process_video"
            assert args == (video_id, processing_job_id)
            assert options["retry"] == JOB_RETRY_POLICY

            tasks.process_video(*args)

            transcript_response = await client.get(f"/videos/{video_id}/transcript")
            processing_status = await client.get(f"/jobs/{processing_job_id}")
            assert transcript_response.status_code == 200
            assert transcript_response.json()["segments"][0]["text"] == (
                "This is an integration test clip."
            )
            assert processing_status.json()["status"] == "succeeded"

            with session_factory() as session:
                video = session.get(Video, uuid.UUID(video_id))
                assert video is not None
                assert video.status == "ready"
                clip = Clip(
                    video_id=video.id,
                    start_seconds=0,
                    end_seconds=5,
                    rank=1,
                    title="Integration clip",
                )
                session.add(clip)
                session.commit()
                clip_id = str(clip.id)

            render_response = await client.post(f"/clips/{clip_id}/render")
            assert render_response.status_code == 202
            render_job_id = render_response.json()["id"]
            function, args, options = queue.enqueued[1]
            assert function == "clipper_worker.tasks.render_clip_job"
            assert args == (clip_id, render_job_id)
            assert options["retry"] == JOB_RETRY_POLICY

            tasks.render_clip_job(*args)
            download_response = await client.get(f"/clips/{clip_id}/download")
            render_status = await client.get(f"/jobs/{render_job_id}")

            assert download_response.status_code == 200
            assert download_response.content == b"captioned integration clip"
            assert render_status.json()["status"] == "succeeded"

            return video_id, processing_job_id, render_job_id, download_response.content

    try:
        video_id, processing_job_id, render_job_id, downloaded = anyio.run(run_flow)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)

    assert downloaded == b"captioned integration clip"
    with Session(engine) as session:
        stored_video = session.get(Video, uuid.UUID(video_id))
        process_job = session.get(Job, uuid.UUID(processing_job_id))
        render_job = session.get(Job, uuid.UUID(render_job_id))
        assert stored_video is not None
        assert process_job is not None
        assert render_job is not None
        assert stored_video.status == "ready"
        assert process_job.status == "succeeded"
        assert render_job.status == "succeeded"
