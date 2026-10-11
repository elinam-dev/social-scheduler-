"""Add scheduled_posts and platform_tokens tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_scheduled_posts"
down_revision: str | None = "0005_allow_unknown_video_size"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False, unique=True),
        sa.Column("encrypted_token", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "platform IN ('youtube', 'tiktok', 'instagram')",
            name="ck_platform_tokens_platform",
        ),
    )

    op.create_table(
        "scheduled_posts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("clip_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column("platform_post_id", sa.String(512)),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["clip_id"], ["clips.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "platform IN ('youtube', 'tiktok', 'instagram')",
            name="ck_scheduled_posts_platform",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'publishing', 'published', 'failed', 'cancelled')",
            name="ck_scheduled_posts_status",
        ),
    )
    op.create_index(
        "ix_scheduled_posts_clip_id", "scheduled_posts", ["clip_id"]
    )
    op.create_index(
        "ix_scheduled_posts_scheduled_at", "scheduled_posts", ["scheduled_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_scheduled_posts_scheduled_at", "scheduled_posts")
    op.drop_index("ix_scheduled_posts_clip_id", "scheduled_posts")
    op.drop_table("scheduled_posts")
    op.drop_table("platform_tokens")
