"""Store validated video transcripts as JSON.

Revision ID: 0003_video_transcript
Revises: 0002_audio_key
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_video_transcript"
down_revision: str | None = "0002_audio_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("videos", sa.Column("transcript", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("videos", "transcript")
