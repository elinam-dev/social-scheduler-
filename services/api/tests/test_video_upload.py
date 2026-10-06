import uuid

import anyio
from httpx import ASGITransport, AsyncClient
from redis.exceptions import RedisError
from rq.job import Callback
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.projects import get_object_storage, get_queue
from app.db import Base, Job, Video
from app.db.session import get_session
from app.main import app


class FakeObjectStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str | None]] = []
        self.deleted_keys: list[str] = []
        self.delete_error: Exception | None = None

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        self.uploads.append((object_key, file.read(), content_type))

    def delete_file(self, object_key: str) -> None:
        self.deleted_keys.append(object_key)
        if self.delete_error is not None:
            raise self.delete_error


class FakeQueue:
    def __init__(self, error: RedisError | None = None) -> None:
        self.error = error
        self.enqueued: list[tuple[str, tuple[str, ...], dict[str, object]]] = []

    def enqueue(self, function: str, *args: str, **kwargs: object) -> None:
        if self.error is not None:
            raise self.error
        self.enqueued.append((function, args, kwargs))


def test_project_upload_persists_metadata_and_stores_file(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'uploads.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FakeObjectStorage()
    queue = FakeQueue()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue

    async def exercise_upload():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            project_response = await client.post(
                "/projects", json={"name": "Interview"}
            )
            assert project_response.status_code == 201
            project_id = project_response.json()["id"]

            upload_response = await client.post(
                f"/projects/{project_id}/videos",
                files={"file": ("episode.mp4", b"video bytes", "video/mp4")},
            )
            job_response = await client.get(
                f"/jobs/{upload_response.json()['job']['id']}"
            )

        return upload_response, job_response

    try:
        response, job_response = anyio.run(exercise_upload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    upload_result = response.json()
    video = upload_result["video"]
    job = upload_result["job"]
    assert video["original_filename"] == "episode.mp4"
    assert video["size_bytes"] == len(b"video bytes")
    assert video["status"] == "uploaded"
    assert job["status"] == "queued"
    assert job_response.status_code == 200
    assert job_response.json()["id"] == job["id"]
    assert len(queue.enqueued) == 1
    function, args, options = queue.enqueued[0]
    assert function == "clipper_worker.tasks.process_video"
    assert args == (video["id"], job["id"])
    assert options["job_id"] == job["id"]
    assert isinstance(options["on_failure"], Callback)
    assert options["on_failure"].name == "clipper_worker.tasks.mark_job_failed"
    assert len(storage.uploads) == 1
    object_key, content, content_type = storage.uploads[0]
    assert object_key.startswith(f"{video['project_id']}/")
    assert content == b"video bytes"
    assert content_type == "video/mp4"

    with Session(engine) as session:
        stored_video = session.get(Video, uuid.UUID(video["id"]))
        assert stored_video is not None
        assert stored_video.object_key == object_key


def test_queue_failure_is_reported_and_saved_in_job_status(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'queue-failure.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FakeObjectStorage()
    queue = FakeQueue(error=RedisError("Redis unavailable"))

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: queue

    async def upload():
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            project_response = await client.post(
                "/projects", json={"name": "Interview"}
            )
            project_id = project_response.json()["id"]
            return await client.post(
                f"/projects/{project_id}/videos",
                files={"file": ("episode.mp4", b"video bytes", "video/mp4")},
            )

    try:
        response = anyio.run(upload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "could not be queued" in response.json()["detail"]
    assert len(storage.uploads) == 1
    with Session(engine) as session:
        job = session.query(Job).one()
        assert job.status == "failed"
        assert job.error_message == "Could not submit video processing job to Redis"


def test_database_failure_cleans_up_uploaded_object(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'database-failure.db'}")
    Base.metadata.create_all(engine)
    Video.__table__.drop(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FakeObjectStorage()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: storage
    app.dependency_overrides[get_queue] = lambda: FakeQueue()

    async def upload():
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            project_response = await client.post(
                "/projects", json={"name": "Interview"}
            )
            project_id = project_response.json()["id"]
            return await client.post(
                f"/projects/{project_id}/videos",
                files={"file": ("episode.mp4", b"video bytes", "video/mp4")},
            )

    try:
        response = anyio.run(upload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert len(storage.uploads) == 1
    assert storage.deleted_keys == [storage.uploads[0][0]]
