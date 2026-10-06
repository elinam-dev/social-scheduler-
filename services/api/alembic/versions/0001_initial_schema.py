"""Create project, video, job, and clip tables.

Revision ID: 0001_initial
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "videos",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="uploaded", nullable=False
        ),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("frame_rate", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("size_bytes > 0", name="ck_videos_size_positive"),
        sa.CheckConstraint(
            "duration_seconds IS NULL OR duration_seconds >= 0",
            name="ck_videos_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')",
            name="ck_videos_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_videos_project_id", "videos", ["project_id"], unique=False)
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("video_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=20), server_default="queued", nullable=False
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rq_job_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "progress >= 0 AND progress <= 100", name="ck_jobs_progress"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rq_job_id"),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"], unique=False)
    op.create_index("ix_jobs_video_id", "jobs", ["video_id"], unique=False)
    op.create_table(
        "clips",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("video_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("object_key", sa.String(length=1024), nullable=True),
        sa.Column(
            "aspect_ratio", sa.String(length=10), server_default="9:16", nullable=False
        ),
        sa.Column(
            "status", sa.String(length=20), server_default="pending", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("start_seconds >= 0", name="ck_clips_start_nonnegative"),
        sa.CheckConstraint(
            "end_seconds > start_seconds", name="ck_clips_end_after_start"
        ),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="ck_clips_rank_positive"),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)",
            name="ck_clips_score_range",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'rendering', 'ready', 'failed')",
            name="ck_clips_status",
        ),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("object_key"),
    )
    op.create_index("ix_clips_video_id", "clips", ["video_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_clips_video_id", table_name="clips")
    op.drop_table("clips")
    op.drop_index("ix_jobs_video_id", table_name="jobs")
    op.drop_index("ix_jobs_project_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_videos_project_id", table_name="videos")
    op.drop_table("videos")
    op.drop_table("projects")
