import io
import uuid

import anyio
from botocore.response import StreamingBody
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from rq.job import Callback
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes.clips import get_object_storage
from app.db import Base, Clip, Job, Project, Video
from app.db.session import get_session
from app.main import app
from app.queue import get_queue


class FakeQueue:
    def __init__(self, error: RedisError | None = None) -> None:
        self.error = error
        self.enqueued: list[tuple[str, tuple[str, ...], dict[str, object]]] = []

    def enqueue(self, function: str, *args: str, **kwargs: object) -> None:
        if self.error is not None:
            raise self.error
        self.enqueued.append((function, args, kwargs))


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects = {"clips/ready.mp4": b"clip-data"}
        self.requested_range: str | None = None

    def get_file(
        self, object_key: str, byte_range: str | None = None
    ) -> tuple[StreamingBody, int, str, str | None]:
        content = self.objects[object_key]
        self.requested_range = byte_range
        content_range = None
        if byte_range is not None:
            start_text, end_text = byte_range.removeprefix("bytes=").split("-", 1)
            start = int(start_text)
            end = min(int(end_text), len(content) - 1)
            content_range = f"bytes {start}-{end}/{len(content)}"
            content = content[start : end + 1]
        return (
            StreamingBody(io.BytesIO(content), len(content)),
            len(content),
            "video/mp4",
            content_range,
        )


def test_clip_list_and_preview_routes(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'clips.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FakeObjectStorage()
    queue = FakeQueue()
    with session_factory() as session:
        project = Project(name="Interview")
        video = Video(
            project=project,
            original_filename="episode.mp4",
            object_key="source/episode.mp4",
            size_bytes=100,
            duration_seconds=60,
            status="ready",
            transcript={
                "language": "en",
                "language_probability": 0.99,
                "duration_seconds": 60,
                "segments": [
                    {
                        "start_seconds": 12,
                        "end_seconds": 16,
                        "text": "A sample clip.",
                        "words": [
                            {
                                "start_seconds": 12,
                                "end_seconds": 13,
                                "text": "A",
                                "probability": 0.99,
                                "speaker_id": None,
                            },
                            {
                                "start_seconds": 13,
                                "end_seconds": 14,
                                "text": "sample",
                                "probability": 0.99,
                                "speaker_id": None,
                            },
                            {
                                "start_seconds": 14,
                                "end_seconds": 16,
                                "text": "clip.",
                                "probability": 0.99,
                                "speaker_id": None,
                            },
                        ],
                    }
                ],
            },
        )
        ready_clip = Clip(
            video=video,
            start_seconds=10,
            end_seconds=25,
            rank=1,
            score=0.92,
            title="A strong opening",
            object_key="clips/ready.mp4",
            status="ready",
        )
        pending_clip = Clip(
            video=video,
            start_seconds=30,
            end_seconds=45,
            rank=2,
            status="pending",
        )
        session.add_all([ready_clip, pending_clip])
        session.commit()
        video_id = video.id
        ready_clip_id = ready_clip.id
        pending_clip_id = pending_clip.id

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue

    async def request_routes():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            clips = await client.get(f"/videos/{video_id}/clips")
            full_preview = await client.get(f"/clips/{ready_clip_id}/preview")
            partial_preview = await client.get(
                f"/clips/{ready_clip_id}/preview",
                headers={"Range": "bytes=1-3"},
            )
            pending_preview = await client.get(f"/clips/{pending_clip_id}/preview")
            updated_trim = await client.patch(
                f"/clips/{ready_clip_id}/trim",
                json={"start_seconds": 12, "end_seconds": 28},
            )
            preview_after_trim = await client.get(f"/clips/{ready_clip_id}/preview")
            outside_video = await client.patch(
                f"/clips/{ready_clip_id}/trim",
                json={"start_seconds": 50, "end_seconds": 61},
            )
            reversed_trim = await client.patch(
                f"/clips/{ready_clip_id}/trim",
                json={"start_seconds": 30, "end_seconds": 20},
            )
            updated_style = await client.patch(
                f"/clips/{ready_clip_id}/caption-style",
                json={"caption_style": "word-highlight"},
            )
            invalid_style = await client.patch(
                f"/clips/{ready_clip_id}/caption-style",
                json={"caption_style": "unlisted-style"},
            )
            render_job = await client.post(f"/clips/{ready_clip_id}/render")
            duplicate_render = await client.post(f"/clips/{ready_clip_id}/render")
            queue.error = RedisError("Redis unavailable")
            failed_render = await client.post(f"/clips/{pending_clip_id}/render")
            missing_clip = await client.get(f"/clips/{uuid.uuid4()}/preview")
            missing_video = await client.get(f"/videos/{uuid.uuid4()}/clips")
        return (
            clips,
            full_preview,
            partial_preview,
            pending_preview,
            updated_trim,
            preview_after_trim,
            outside_video,
            reversed_trim,
            updated_style,
            invalid_style,
            render_job,
            duplicate_render,
            failed_render,
            missing_clip,
            missing_video,
        )

    try:
        (
            clips,
            full_preview,
            partial_preview,
            pending_preview,
            updated_trim,
            preview_after_trim,
            outside_video,
            reversed_trim,
            updated_style,
            invalid_style,
            render_job,
            duplicate_render,
            failed_render,
            missing_clip,
            missing_video,
        ) = anyio.run(request_routes)
    finally:
        app.dependency_overrides.clear()

    assert clips.status_code == 200
    assert [clip["rank"] for clip in clips.json()] == [1, 2]
    assert clips.json()[0]["title"] == "A strong opening"
    assert clips.json()[0]["preview_url"] == f"/clips/{ready_clip_id}/preview"
    assert clips.json()[1]["preview_url"] is None

    assert full_preview.status_code == 200
    assert full_preview.content == b"clip-data"
    assert full_preview.headers["accept-ranges"] == "bytes"
    assert full_preview.headers["content-type"] == "video/mp4"
    assert partial_preview.status_code == 206
    assert partial_preview.content == b"lip"
    assert partial_preview.headers["content-range"] == "bytes 1-3/9"
    assert storage.requested_range == "bytes=1-3"

    assert pending_preview.status_code == 409
    assert updated_trim.status_code == 200
    assert updated_trim.json()["start_seconds"] == 12
    assert updated_trim.json()["end_seconds"] == 28
    assert updated_trim.json()["status"] == "pending"
    assert updated_trim.json()["preview_url"] is None
    assert preview_after_trim.status_code == 409
    assert outside_video.status_code == 422
    assert reversed_trim.status_code == 422
    assert updated_style.status_code == 200
    assert updated_style.json()["caption_style"] == "word-highlight"
    assert updated_style.json()["status"] == "pending"
    assert invalid_style.status_code == 422
    assert render_job.status_code == 202
    assert render_job.json()["status"] == "queued"
    assert duplicate_render.status_code == 409
    assert failed_render.status_code == 503
    assert len(queue.enqueued) == 1
    function, args, options = queue.enqueued[0]
    assert function == "clipper_worker.tasks.render_clip_job"
    assert args == (str(ready_clip_id), render_job.json()["id"])
    assert options["job_id"] == render_job.json()["id"]
    assert isinstance(options["on_failure"], Callback)
    assert options["on_failure"].name == "clipper_worker.tasks.mark_clip_render_failed"
    assert missing_clip.status_code == 404
    assert missing_video.status_code == 404

    with session_factory() as session:
        updated_clip = session.get(Clip, ready_clip_id)
        assert updated_clip is not None
        assert updated_clip.object_key == "clips/ready.mp4"
        assert updated_clip.caption_style == "word-highlight"
        assert updated_clip.status == "rendering"
        render_record = session.get(Job, uuid.UUID(render_job.json()["id"]))
        assert render_record is not None
        assert render_record.job_type == "render_clip"
        failed_clip = session.get(Clip, pending_clip_id)
        assert failed_clip is not None
        assert failed_clip.status == "failed"
        failed_job = (
            session.query(Job)
            .filter(Job.video_id == video_id, Job.status == "failed")
            .one()
        )
        assert failed_job.error_message == "Could not submit clip render job to Redis"
