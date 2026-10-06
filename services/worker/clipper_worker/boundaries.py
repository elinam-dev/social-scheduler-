import math
from bisect import bisect_left
from dataclasses import dataclass

from clipper_worker.segmentation import Sentence


@dataclass(frozen=True)
class SnappedBoundaries:
    start_seconds: float
    end_seconds: float
    first_sentence_index: int
    end_sentence_index: int


def snap_clip_boundaries(
    start_seconds: float,
    end_seconds: float,
    sentences: tuple[Sentence, ...],
) -> SnappedBoundaries:
    if (
        not math.isfinite(start_seconds)
        or not math.isfinite(end_seconds)
        or start_seconds < 0
        or end_seconds <= start_seconds
    ):
        raise ValueError("Requested clip must have finite, positive time boundaries")
    if not sentences:
        raise ValueError("At least one sentence is required to snap clip boundaries")
    _validate_sentences(sentences)

    sentence_ends = tuple(sentence.end_seconds for sentence in sentences)
    best: SnappedBoundaries | None = None
    best_key: tuple[float, float, float] | None = None

    for start_index, sentence in enumerate(sentences):
        nearest_end_index = bisect_left(sentence_ends, end_seconds, lo=start_index)
        for end_index in {max(start_index, nearest_end_index - 1), nearest_end_index}:
            if end_index >= len(sentences):
                continue
            snapped_end = sentence_ends[end_index]
            distance = abs(sentence.start_seconds - start_seconds) + abs(
                snapped_end - end_seconds
            )
            key = (distance, sentence.start_seconds, snapped_end)
            if best_key is None or key < best_key:
                best_key = key
                best = SnappedBoundaries(
                    start_seconds=sentence.start_seconds,
                    end_seconds=snapped_end,
                    first_sentence_index=start_index,
                    end_sentence_index=end_index + 1,
                )

    if best is None:
        raise ValueError("No non-empty sentence-aligned clip boundaries are available")
    return best


def _validate_sentences(sentences: tuple[Sentence, ...]) -> None:
    previous_start = -math.inf
    previous_end = -math.inf
    for sentence in sentences:
        if (
            not math.isfinite(sentence.start_seconds)
            or not math.isfinite(sentence.end_seconds)
            or sentence.start_seconds < 0
            or sentence.end_seconds <= sentence.start_seconds
        ):
            raise ValueError("Sentences must have finite, positive time ranges")
        if (
            sentence.start_seconds < previous_start
            or sentence.end_seconds < previous_end
        ):
            raise ValueError("Sentences must be ordered by start and end time")
        previous_start = sentence.start_seconds
        previous_end = sentence.end_seconds
