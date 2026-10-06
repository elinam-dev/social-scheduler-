"""Store extracted audio in object storage.

Revision ID: 0002_audio_key
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_audio_key"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("audio_object_key", sa.String(length=1024)))
    op.create_index(
        "uq_videos_audio_object_key", "videos", ["audio_object_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_videos_audio_object_key", table_name="videos")
    op.drop_column("videos", "audio_object_key")
