"""Allow URL-imported videos to be pending with unknown size."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_allow_unknown_video_size"
down_revision: str | None = "0004_clip_caption_style"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_constraint("ck_videos_size_positive", type_="check")
        batch_op.create_check_constraint(
            "ck_videos_size_nonnegative",
            sa.text("size_bytes >= 0"),
        )


def downgrade() -> None:
    with op.batch_alter_table("videos") as batch_op:
        batch_op.drop_constraint("ck_videos_size_nonnegative", type_="check")
        batch_op.create_check_constraint(
            "ck_videos_size_positive",
            sa.text("size_bytes > 0"),
        )
