import uuid
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, Clip, Job, Project, Video
from clipper_worker import tasks
from clipper_worker.diarization import DiarizationResult, DiarizationTurn
from clipper_worker.media import MediaMetadata
from clipper_worker.transcription import (
    TranscriptionResult,
    TranscriptionSegment,
    WordTimestamp,
)


class FakeObjectStorage:
    def __init__(self) -> None:
        self.uploads: dict[str, bytes] = {}

    def download_file(self, object_key: str, destination: str | Path) -> None:
        assert object_key == "source-object"
        Path(destination).write_bytes(b"source video")

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        assert content_type == "audio/wav"
        self.uploads[object_key] = file.read()


class FakeRenderStorage:
    def __init__(self) -> None:
        self.uploads: dict[str, tuple[bytes, str | None]] = {}
        self.deleted_keys: list[str] = []

    def download_file(self, object_key: str, destination: str | Path) -> None:
        assert object_key == "source-object"
        Path(destination).write_bytes(b"source video")

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        self.uploads[object_key] = (file.read(), content_type)

    def delete_file(self, object_key: str) -> None:
        self.deleted_keys.append(object_key)


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
        segments=(
            TranscriptionSegment(
                0,
                3,
                "An example transcript.",
                words=(WordTimestamp(0, 3, "transcript.", 0.98),),
            ),
        ),
    )
    monkeypatch.setattr(tasks, "transcribe_audio", lambda _path: transcription_result)
    diarization_result = DiarizationResult(
        speakers=("speaker_1",),
        turns=(DiarizationTurn(0, 3, "speaker_1"),),
    )
    monkeypatch.setattr(
        tasks, "diarize_audio", lambda _path, **_kwargs: diarization_result
    )

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
        assert stored_video.transcript == {
            "language": "en",
            "language_probability": 0.99,
            "duration_seconds": 3.0,
            "segments": [
                {
                    "start_seconds": 0.0,
                    "end_seconds": 3.0,
                    "text": "An example transcript.",
                    "words": [
                        {
                            "start_seconds": 0.0,
                            "end_seconds": 3.0,
                            "text": "transcript.",
                            "probability": 0.98,
                            "speaker_id": "speaker_1",
                        }
                    ],
                }
            ],
        }
        assert stored_job.status == "succeeded"
        assert stored_job.progress == 100
    assert storage.uploads == {f"{project_id}/{video_id}/audio.wav": b"wav bytes"}
    assert result.segments[0].words[0].speaker_id == "speaker_1"


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


def test_render_clip_job_burns_saved_style_and_replaces_preview(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'clip-render.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    video_id = uuid.uuid4()
    clip_id = uuid.uuid4()
    job_id = uuid.uuid4()
    transcript = {
        "language": "en",
        "language_probability": 0.99,
        "duration_seconds": 20,
        "segments": [
            {
                "start_seconds": 1,
                "end_seconds": 3,
                "text": "Hello world.",
                "words": [
                    {
                        "start_seconds": 1,
                        "end_seconds": 2,
                        "text": "Hello",
                        "probability": 0.99,
                        "speaker_id": "speaker_1",
                    },
                    {
                        "start_seconds": 2,
                        "end_seconds": 3,
                        "text": "world.",
                        "probability": 0.98,
                        "speaker_id": "speaker_1",
                    },
                ],
            }
        ],
    }
    with session_factory() as session:
        project = Project(id=project_id, name="Interview")
        video = Video(
            id=video_id,
            project=project,
            original_filename="episode.mp4",
            object_key="source-object",
            size_bytes=12,
            duration_seconds=20,
            status="ready",
            transcript=transcript,
        )
        clip = Clip(
            id=clip_id,
            video=video,
            start_seconds=0,
            end_seconds=5,
            rank=1,
            object_key="previous-render.mp4",
            aspect_ratio="1:1",
            status="rendering",
            caption_style="word-highlight",
        )
        job = Job(
            id=job_id,
            project_id=project_id,
            video_id=video_id,
            job_type="render_clip",
            status="queued",
            rq_job_id=str(job_id),
        )
        session.add_all([clip, job])
        session.commit()

    storage = FakeRenderStorage()
    render_call: dict[str, object] = {}

    def fake_render(
        _source: Path,
        output: Path,
        start_seconds: float,
        end_seconds: float,
        **options: object,
    ) -> Path:
        render_call.update(
            {
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                **options,
                "subtitle": Path(str(options["subtitle_path"])).read_text(
                    encoding="utf-8"
                ),
            }
        )
        output.write_bytes(b"rendered clip")
        return output

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_object_storage", lambda: storage)
    monkeypatch.setattr(tasks, "render_fallback_clip", fake_render)

    object_key = tasks.render_clip_job(str(clip_id), str(job_id))

    with Session(engine) as session:
        rendered_clip = session.get(Clip, clip_id)
        rendered_job = session.get(Job, job_id)
        assert rendered_clip is not None
        assert rendered_job is not None
        assert rendered_clip.status == "ready"
        assert rendered_clip.object_key == object_key
        assert rendered_job.status == "succeeded"
        assert rendered_job.progress == 100
    assert object_key.startswith(f"{project_id}/{video_id}/clips/{clip_id}/")
    assert storage.uploads == {object_key: (b"rendered clip", "video/mp4")}
    assert storage.deleted_keys == ["previous-render.mp4"]
    assert render_call["start_seconds"] == 0
    assert render_call["end_seconds"] == 5
    assert render_call["layout"] == "blurred-background"
    assert render_call["output_width"] == 1080
    assert render_call["output_height"] == 1080
    assert "Style: WordHighlight" in str(render_call["subtitle"])
    assert r"{\k100}" in str(render_call["subtitle"])


def test_clip_render_failure_handler_marks_clip_and_job_failed(
    tmp_path: Path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'failed-clip-render.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    project_id = uuid.uuid4()
    video_id = uuid.uuid4()
    clip_id = uuid.uuid4()
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
        clip = Clip(
            id=clip_id,
            video=video,
            start_seconds=0,
            end_seconds=5,
            status="rendering",
        )
        job = Job(
            id=job_id,
            project_id=project_id,
            video_id=video_id,
            job_type="render_clip",
            status="running",
            rq_job_id=str(job_id),
        )
        session.add_all([clip, job])
        session.commit()

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    rq_job = SimpleNamespace(id=str(job_id), args=(str(clip_id), str(job_id)))
    tasks.mark_clip_render_failed(
        rq_job,
        object(),
        RuntimeError,
        RuntimeError("FFmpeg failed"),
        None,
    )

    with Session(engine) as session:
        failed_clip = session.get(Clip, clip_id)
        failed_job = session.get(Job, job_id)
        assert failed_clip is not None
        assert failed_job is not None
        assert failed_clip.status == "failed"
        assert failed_job.status == "failed"
        assert failed_job.error_message == "FFmpeg failed"
