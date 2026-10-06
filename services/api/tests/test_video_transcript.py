import uuid

import anyio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, Project, Video
from app.db.session import get_session
from app.main import app


def test_get_video_transcript_returns_saved_schema_and_pending_status(
    tmp_path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'transcripts.db'}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    video_id = uuid.uuid4()
    pending_video_id = uuid.uuid4()
    transcript = {
        "language": "en",
        "language_probability": 0.99,
        "duration_seconds": 2.0,
        "segments": [
            {
                "start_seconds": 0.0,
                "end_seconds": 2.0,
                "text": "Hello.",
                "words": [
                    {
                        "start_seconds": 0.0,
                        "end_seconds": 1.0,
                        "text": "Hello.",
                        "probability": 0.95,
                        "speaker_id": "SPEAKER_00",
                    }
                ],
            }
        ],
    }
    with session_factory() as session:
        video = Video(
            id=video_id,
            project=Project(name="Interview"),
            original_filename="episode.mp4",
            object_key="source-object",
            size_bytes=10,
            transcript=transcript,
        )
        pending_video = Video(
            id=pending_video_id,
            project=video.project,
            original_filename="pending.mp4",
            object_key="pending-object",
            size_bytes=10,
        )
        session.add_all([video, pending_video])
        session.commit()

    def override_session():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_session

    async def request_transcript():
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            available = await client.get(f"/videos/{video_id}/transcript")
            pending = await client.get(f"/videos/{pending_video_id}/transcript")
            missing = await client.get(f"/videos/{uuid.uuid4()}/transcript")
        return available, pending, missing

    try:
        available, pending, missing = anyio.run(request_transcript)
    finally:
        app.dependency_overrides.clear()

    assert available.status_code == 200
    assert available.json() == transcript
    assert pending.status_code == 409
    assert missing.status_code == 404
