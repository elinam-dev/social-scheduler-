import uuid

import anyio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.api.routes.projects import get_object_storage
from app.db import Base, Video
from app.db.session import get_session
from app.main import app


class FakeObjectStorage:
    def __init__(self) -> None:
        self.uploads: list[tuple[str, bytes, str | None]] = []
        self.deleted_keys: list[str] = []

    def upload_file(self, file, object_key: str, content_type: str | None) -> None:
        self.uploads.append((object_key, file.read(), content_type))

    def delete_file(self, object_key: str) -> None:
        self.deleted_keys.append(object_key)


def test_project_upload_persists_metadata_and_stores_file(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'uploads.db'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    storage = FakeObjectStorage()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_object_storage] = lambda: storage

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

        return upload_response

    try:
        response = anyio.run(exercise_upload)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    video = response.json()
    assert video["original_filename"] == "episode.mp4"
    assert video["size_bytes"] == len(b"video bytes")
    assert video["status"] == "uploaded"
    assert len(storage.uploads) == 1
    object_key, content, content_type = storage.uploads[0]
    assert object_key.startswith(f"{video['project_id']}/")
    assert content == b"video bytes"
    assert content_type == "video/mp4"

    with Session(engine) as session:
        stored_video = session.get(Video, uuid.UUID(video["id"]))
        assert stored_video is not None
        assert stored_video.object_key == object_key
