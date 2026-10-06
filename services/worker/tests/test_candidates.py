import math

import pytest

from clipper_worker.candidates import generate_candidate_windows
from clipper_worker.segmentation import Sentence


def _sentences(count: int, interval_seconds: float = 10) -> tuple[Sentence, ...]:
    return tuple(
        Sentence(
            start_seconds=index * interval_seconds,
            end_seconds=(index + 1) * interval_seconds,
            text=f"Sentence {index}.",
            words=(),
        )
        for index in range(count)
    )


def test_generate_candidate_windows_includes_duration_boundaries() -> None:
    windows = generate_candidate_windows(
        _sentences(10),
        min_duration_seconds=30,
        max_duration_seconds=90,
    )

    assert windows
    assert all(30 <= window.duration_seconds <= 90 for window in windows)
    assert windows[0].duration_seconds == 30
    assert max(window.duration_seconds for window in windows) == 90
    assert windows[0].text == "Sentence 0. Sentence 1. Sentence 2."
    assert (windows[0].first_sentence_index, windows[0].end_sentence_index) == (0, 3)


def test_generate_candidate_windows_returns_empty_if_video_is_too_short() -> None:
    assert (
        generate_candidate_windows(
            _sentences(2),
            min_duration_seconds=30,
            max_duration_seconds=90,
        )
        == ()
    )


@pytest.mark.parametrize(
    ("minimum", "maximum"),
    [
        (0, 30),
        (30, 0),
        (30, 29),
        (math.inf, 90),
        (30, math.nan),
    ],
)
def test_generate_candidate_windows_rejects_invalid_bounds(
    minimum: float, maximum: float
) -> None:
    with pytest.raises(ValueError, match="duration bounds"):
        generate_candidate_windows(
            _sentences(10),
            min_duration_seconds=minimum,
            max_duration_seconds=maximum,
        )


def test_generate_candidate_windows_rejects_out_of_order_sentences() -> None:
    sentences = (
        Sentence(10, 20, "Later.", ()),
        Sentence(0, 10, "Earlier.", ()),
    )

    with pytest.raises(ValueError, match="ordered"):
        generate_candidate_windows(
            sentences,
            min_duration_seconds=5,
            max_duration_seconds=30,
        )
