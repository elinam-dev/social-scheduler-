"""Store selected caption style with each clip.

Revision ID: 0004_clip_caption_style
Revises: 0003_video_transcript
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_clip_caption_style"
down_revision: str | None = "0003_video_transcript"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clips",
        sa.Column(
            "caption_style",
            sa.String(length=32),
            nullable=False,
            server_default="default",
        ),
    )


def downgrade() -> None:
    op.drop_column("clips", "caption_style")
