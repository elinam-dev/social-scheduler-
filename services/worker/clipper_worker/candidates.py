import math
from dataclasses import dataclass

from clipper_worker.segmentation import Sentence

DEFAULT_MIN_CANDIDATE_DURATION_SECONDS = 120.0
DEFAULT_MAX_CANDIDATE_DURATION_SECONDS = 300.0


@dataclass(frozen=True)
class CandidateWindow:
    start_seconds: float
    end_seconds: float
    text: str
    first_sentence_index: int
    end_sentence_index: int

    @property
    def duration_seconds(self) -> float:
        return self.end_seconds - self.start_seconds


def generate_candidate_windows(
    sentences: tuple[Sentence, ...],
    *,
    min_duration_seconds: float = DEFAULT_MIN_CANDIDATE_DURATION_SECONDS,
    max_duration_seconds: float = DEFAULT_MAX_CANDIDATE_DURATION_SECONDS,
) -> tuple[CandidateWindow, ...]:
    if (
        not math.isfinite(min_duration_seconds)
        or not math.isfinite(max_duration_seconds)
        or min_duration_seconds <= 0
        or max_duration_seconds < min_duration_seconds
    ):
        raise ValueError(
            "Candidate duration bounds must be finite, positive, and ordered"
        )
    _validate_sentence_order(sentences)

    candidates: list[CandidateWindow] = []
    for first_index, first_sentence in enumerate(sentences):
        text_parts: list[str] = []
        for last_index in range(first_index, len(sentences)):
            sentence = sentences[last_index]
            duration = sentence.end_seconds - first_sentence.start_seconds
            if duration > max_duration_seconds:
                break
            text_parts.append(sentence.text.strip())
            if duration >= min_duration_seconds:
                candidates.append(
                    CandidateWindow(
                        start_seconds=first_sentence.start_seconds,
                        end_seconds=sentence.end_seconds,
                        text=" ".join(part for part in text_parts if part),
                        first_sentence_index=first_index,
                        end_sentence_index=last_index + 1,
                    )
                )
    return tuple(candidates)


def _validate_sentence_order(sentences: tuple[Sentence, ...]) -> None:
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
