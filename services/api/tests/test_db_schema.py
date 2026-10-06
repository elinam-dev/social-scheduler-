from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import Base, Clip, Project, Video


def test_initial_migration_creates_all_tables_and_constraints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("CLIPPER_DATABASE_URL", f"sqlite:///{database_path}")
    api_directory = Path(__file__).resolve().parents[1]
    alembic_config = Config(str(api_directory / "alembic.ini"))

    command.upgrade(alembic_config, "head")
    command.check(alembic_config)

    engine = create_engine(f"sqlite:///{database_path}")
    schema = inspect(engine)
    assert set(schema.get_table_names()) == {
        "alembic_version",
        "clips",
        "jobs",
        "projects",
        "videos",
    }
    assert "ck_clips_end_after_start" in {
        constraint["name"] for constraint in schema.get_check_constraints("clips")
    }
    assert "transcript" in {column["name"] for column in schema.get_columns("videos")}
    assert "caption_style" in {column["name"] for column in schema.get_columns("clips")}


def test_clip_schema_rejects_end_before_start() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        project = Project(name="Test project")
        video = Video(
            project=project,
            original_filename="source.mp4",
            object_key="projects/test/source.mp4",
            size_bytes=1,
        )
        session.add(video)
        session.flush()
        session.add(
            Clip(video=video, start_seconds=10, end_seconds=9, aspect_ratio="9:16")
        )

        with pytest.raises(IntegrityError, match="ck_clips_end_after_start"):
            session.flush()
