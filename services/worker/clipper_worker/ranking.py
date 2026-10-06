import math
from dataclasses import dataclass
from typing import Iterable

from clipper_worker.candidate_review import CandidateEvaluation
from clipper_worker.candidates import CandidateWindow
from clipper_worker.scoring import CandidateScore

DEFAULT_TOP_N = 10
DEFAULT_OVERLAP_THRESHOLD = 0.7


@dataclass(frozen=True)
class RankedCandidate:
    candidate: CandidateWindow
    evaluation: CandidateEvaluation
    score: float


def rank_and_deduplicate_candidates(
    candidates: Iterable[tuple[CandidateWindow, CandidateEvaluation]],
    *,
    top_n: int = DEFAULT_TOP_N,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> tuple[RankedCandidate, ...]:
    ranked = (
        RankedCandidate(candidate, evaluation, _evaluation_score(evaluation))
        for candidate, evaluation in candidates
    )
    return _deduplicate_ranked(
        ranked,
        top_n=top_n,
        overlap_threshold=overlap_threshold,
    )


def rank_scored_candidates(
    candidates: Iterable[tuple[CandidateWindow, CandidateEvaluation, CandidateScore]],
    *,
    top_n: int = DEFAULT_TOP_N,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> tuple[RankedCandidate, ...]:
    ranked = (
        RankedCandidate(candidate, evaluation, score.combined_score)
        for candidate, evaluation, score in candidates
    )
    return _deduplicate_ranked(
        ranked,
        top_n=top_n,
        overlap_threshold=overlap_threshold,
    )


def _deduplicate_ranked(
    candidates: Iterable[RankedCandidate],
    *,
    top_n: int,
    overlap_threshold: float,
) -> tuple[RankedCandidate, ...]:
    if top_n <= 0:
        raise ValueError("Top-N limit must be positive")
    if (
        not math.isfinite(overlap_threshold)
        or overlap_threshold <= 0
        or overlap_threshold > 1
    ):
        raise ValueError("Overlap threshold must be finite and within (0, 1]")

    ranked = list(candidates)
    for item in ranked:
        if not math.isfinite(item.score) or not 0 <= item.score <= 1:
            raise ValueError("Candidate score must be finite and between 0 and 1")
        if (
            not math.isfinite(item.candidate.start_seconds)
            or not math.isfinite(item.candidate.end_seconds)
            or item.candidate.start_seconds < 0
            or item.candidate.end_seconds <= item.candidate.start_seconds
        ):
            raise ValueError("Candidate must have finite, positive time boundaries")
    ranked.sort(
        key=lambda item: (
            -item.score,
            item.candidate.start_seconds,
            item.candidate.end_seconds,
            item.candidate.text,
        )
    )

    selected: list[RankedCandidate] = []
    for item in ranked:
        if any(
            _overlap_coefficient(item.candidate, existing.candidate)
            >= overlap_threshold
            for existing in selected
        ):
            continue
        selected.append(item)
        if len(selected) >= top_n:
            break
    return tuple(selected)


def _evaluation_score(evaluation: CandidateEvaluation) -> float:
    return (
        evaluation.hook_strength
        + evaluation.standalone_coherence
        + evaluation.payoff
        + evaluation.pacing
    ) / 4


def _overlap_coefficient(
    candidate: CandidateWindow, selected: CandidateWindow
) -> float:
    intersection_seconds = max(
        0.0,
        min(candidate.end_seconds, selected.end_seconds)
        - max(candidate.start_seconds, selected.start_seconds),
    )
    if intersection_seconds == 0:
        return 0.0
    shorter_duration = min(
        candidate.duration_seconds,
        selected.duration_seconds,
    )
    return intersection_seconds / shorter_duration
