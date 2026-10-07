import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
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
        self.content_types: dict[str, str | None] = {}

    def download_file(self, object_key: str, destination: str | Path) -> None:
        assert object_key == "source-object"
        Path(destination).write_bytes(b"source video")

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        self.uploads[object_key] = file.read()
        self.content_types[object_key] = content_type


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


@pytest.mark.parametrize("source_url", [None, "https://video.example/watch?id=owned"])
def test_process_video_updates_job_and_persists_metadata(
    tmp_path: Path,
    monkeypatch,
    source_url: str | None,
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
            original_filename="episode.mp4" if source_url is None else "video",
            object_key="source-object",
            size_bytes=12 if source_url is None else 0,
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
    if source_url is not None:

        def download_source(url: str, destination: Path) -> Path:
            assert url == source_url
            source_path = destination / "source.mp4"
            source_path.write_bytes(b"downloaded video")
            return source_path

        monkeypatch.setattr(tasks, "_download_video_url", download_source)
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

    result = tasks.process_video(str(video_id), str(job_id), source_url)

    with Session(engine) as session:
        stored_video = session.get(Video, video_id)
        stored_job = session.get(Job, job_id)
        assert stored_video is not None
        assert stored_job is not None
        assert stored_video.status == "ready"
        assert stored_video.original_filename == (
            "episode.mp4" if source_url is None else "source.mp4"
        )
        assert stored_video.size_bytes == (
            12 if source_url is None else len(b"downloaded video")
        )
        assert stored_video.content_type == (
            None if source_url is None else "video/mp4"
        )
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
    expected_uploads = {f"{project_id}/{video_id}/audio.wav": b"wav bytes"}
    if source_url is not None:
        expected_uploads["source-object"] = b"downloaded video"
    assert storage.uploads == expected_uploads
    assert result.segments[0].words[0].speaker_id == "speaker_1"


def test_url_downloader_enforces_public_hosts_and_uses_no_playlist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = ModuleType("yt_dlp")
    observed_options = {}

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, object]) -> None:
            observed_options.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_info(self, url: str, *, download: bool) -> dict[str, str]:
            assert url == "https://video.example/watch?id=owned"
            assert download is True
            output_template = observed_options["outtmpl"]
            assert isinstance(output_template, str)
            output_path = Path(output_template.replace("%(ext)s", "mp4"))
            output_path.write_bytes(b"downloaded")
            return {"filepath": str(output_path)}

        def prepare_filename(self, _info: dict[str, str]) -> str:
            return str(tmp_path / "missing.mp4")

    module.__dict__["YoutubeDL"] = FakeYoutubeDL
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    monkeypatch.setattr(tasks, "_validate_public_source_url", lambda _url: None)

    downloaded = tasks._download_video_url(
        "https://video.example/watch?id=owned",
        tmp_path,
    )

    assert downloaded == tmp_path / "source.mp4"
    assert downloaded.read_bytes() == b"downloaded"
    assert observed_options["noplaylist"] is True
    assert observed_options["merge_output_format"] == "mp4"


def test_url_downloader_rejects_private_dns_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tasks.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(None, None, None, None, ("10.0.0.5", 443))],
    )

    with pytest.raises(ValueError, match="only to public IP addresses"):
        tasks._validate_public_source_url("https://video.example/watch")


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
    rq_job = SimpleNamespace(
        id=str(job_id),
        args=(str(video_id), str(job_id)),
        retries_left=0,
    )

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


@pytest.mark.parametrize(
    ("failure_handler", "target_id"),
    [
        (tasks.mark_job_failed, "video"),
        (tasks.mark_clip_render_failed, "clip"),
    ],
)
def test_failure_handler_preserves_running_state_while_retrying(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_handler,
    target_id: str,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / f'retrying-{target_id}.db'}")
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
            status="processing",
        )
        clip = Clip(
            id=clip_id,
            video=video,
            start_seconds=1,
            end_seconds=2,
            status="rendering",
        )
        job = Job(
            id=job_id,
            project_id=project_id,
            video=video,
            job_type="process_video" if target_id == "video" else "render_clip",
            rq_job_id=str(job_id),
            status="running",
        )
        session.add_all([project, video, clip, job])
        session.commit()

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    entity_id = video_id if target_id == "video" else clip_id
    rq_job = SimpleNamespace(
        id=str(job_id),
        args=(str(entity_id), str(job_id)),
        retries_left=2,
    )
    failure_handler(
        rq_job,
        object(),
        RuntimeError,
        RuntimeError("temporary worker failure"),
        None,
    )

    with Session(engine) as session:
        stored_video = session.get(Video, video_id)
        stored_clip = session.get(Clip, clip_id)
        stored_job = session.get(Job, job_id)
        assert stored_video is not None
        assert stored_clip is not None
        assert stored_job is not None
        assert stored_video.status == "processing"
        assert stored_clip.status == "rendering"
        assert stored_job.status == "running"
        assert stored_job.error_message is None


def test_process_video_cleans_temporary_files_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'temp-cleanup.db'}")
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
    created_directories: list[Path] = []
    original_temporary_directory = tempfile.TemporaryDirectory

    @contextmanager
    def track_temporary_directory(*, prefix: str) -> Iterator[str]:
        with original_temporary_directory(prefix=prefix) as directory:
            created_directories.append(Path(directory))
            yield directory

    monkeypatch.setattr(tasks, "SessionLocal", session_factory)
    monkeypatch.setattr(tasks, "get_object_storage", lambda: storage)
    monkeypatch.setattr(
        tasks.tempfile,
        "TemporaryDirectory",
        track_temporary_directory,
    )

    def fail_probe(_path: Path) -> MediaMetadata:
        raise RuntimeError("ffprobe failed")

    monkeypatch.setattr(
        tasks,
        "probe_media",
        fail_probe,
    )

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        tasks.process_video(str(video_id), str(job_id))

    assert len(created_directories) == 1
    assert not created_directories[0].exists()


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
    rq_job = SimpleNamespace(
        id=str(job_id),
        args=(str(clip_id), str(job_id)),
        retries_left=0,
    )
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
