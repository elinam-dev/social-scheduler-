import math

import pytest

from clipper_worker.boundaries import SnappedBoundaries, snap_clip_boundaries
from clipper_worker.segmentation import Sentence


def _sentences() -> tuple[Sentence, ...]:
    return (
        Sentence(0, 10, "First.", ()),
        Sentence(10, 20, "Second.", ()),
        Sentence(20, 30, "Third.", ()),
        Sentence(30, 40, "Fourth.", ()),
    )


def test_snap_clip_boundaries_chooses_nearest_sentence_aligned_times() -> None:
    snapped = snap_clip_boundaries(11.2, 27.4, _sentences())

    assert snapped == SnappedBoundaries(
        start_seconds=10,
        end_seconds=30,
        first_sentence_index=1,
        end_sentence_index=3,
    )


def test_snap_clip_boundaries_keeps_at_least_one_full_sentence() -> None:
    snapped = snap_clip_boundaries(21, 22, _sentences())

    assert snapped == SnappedBoundaries(
        start_seconds=20,
        end_seconds=30,
        first_sentence_index=2,
        end_sentence_index=3,
    )


def test_snap_clip_boundaries_clamps_times_outside_transcript() -> None:
    snapped = snap_clip_boundaries(100, 120, _sentences())

    assert snapped == SnappedBoundaries(
        start_seconds=30,
        end_seconds=40,
        first_sentence_index=3,
        end_sentence_index=4,
    )


@pytest.mark.parametrize(
    ("start", "end"),
    [(math.nan, 10), (0, math.inf), (-1, 10), (10, 10)],
)
def test_snap_clip_boundaries_rejects_invalid_requested_range(
    start: float, end: float
) -> None:
    with pytest.raises(ValueError, match="finite, positive"):
        snap_clip_boundaries(start, end, _sentences())


def test_snap_clip_boundaries_requires_sentences() -> None:
    with pytest.raises(ValueError, match="At least one sentence"):
        snap_clip_boundaries(0, 10, ())
