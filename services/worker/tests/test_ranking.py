import pytest

from clipper_worker.candidate_review import CandidateEvaluation
from clipper_worker.candidates import CandidateWindow
from clipper_worker.ranking import (
    rank_and_deduplicate_candidates,
    rank_scored_candidates,
)
from clipper_worker.scoring import CandidateScore


def _candidate(start: float, end: float, text: str) -> CandidateWindow:
    return CandidateWindow(
        start_seconds=start,
        end_seconds=end,
        text=text,
        first_sentence_index=0,
        end_sentence_index=1,
    )


def _evaluation(score: float) -> CandidateEvaluation:
    return CandidateEvaluation(
        hook_strength=score,
        standalone_coherence=score,
        payoff=score,
        pacing=score,
        standalone=True,
        rationale="A complete moment.",
    )


def test_rank_and_deduplicate_sorts_by_score_and_suppresses_nested_windows() -> None:
    candidates = [
        (_candidate(0, 60, "Long version"), _evaluation(0.8)),
        (_candidate(5, 55, "Shorter duplicate"), _evaluation(0.9)),
        (_candidate(65, 100, "Separate moment"), _evaluation(0.7)),
    ]

    ranked = rank_and_deduplicate_candidates(candidates, top_n=2)

    assert [item.candidate.text for item in ranked] == [
        "Shorter duplicate",
        "Separate moment",
    ]
    assert [item.score for item in ranked] == [0.9, 0.7]


def test_rank_and_deduplicate_keeps_candidates_below_overlap_threshold() -> None:
    candidates = [
        (_candidate(0, 10, "First"), _evaluation(0.9)),
        (_candidate(5, 15, "Half overlap"), _evaluation(0.8)),
    ]

    ranked = rank_and_deduplicate_candidates(
        candidates,
        overlap_threshold=0.7,
    )

    assert [item.candidate.text for item in ranked] == ["First", "Half overlap"]


def test_rank_and_deduplicate_uses_stable_tie_breaking_and_top_n() -> None:
    candidates = [
        (_candidate(20, 30, "Later"), _evaluation(0.8)),
        (_candidate(0, 10, "Earlier"), _evaluation(0.8)),
        (_candidate(40, 50, "Third"), _evaluation(0.8)),
    ]

    ranked = rank_and_deduplicate_candidates(candidates, top_n=2)

    assert [item.candidate.text for item in ranked] == ["Earlier", "Later"]


@pytest.mark.parametrize(
    ("top_n", "overlap_threshold"),
    [(0, 0.7), (10, 0), (10, 1.1), (10, float("nan"))],
)
def test_rank_and_deduplicate_rejects_invalid_options(
    top_n: int, overlap_threshold: float
) -> None:
    with pytest.raises(ValueError):
        rank_and_deduplicate_candidates(
            [],
            top_n=top_n,
            overlap_threshold=overlap_threshold,
        )


def test_rank_and_deduplicate_rejects_invalid_candidate_boundaries() -> None:
    with pytest.raises(ValueError, match="positive time boundaries"):
        rank_and_deduplicate_candidates(
            [(_candidate(10, 10, "Empty"), _evaluation(0.9))]
        )


def test_rank_scored_candidates_uses_multi_signal_combined_score() -> None:
    candidates = [
        (
            _candidate(0, 10, "High LLM only"),
            _evaluation(0.95),
            CandidateScore(0.95, 0.1, 0.1, 60, 0, 0.6),
        ),
        (
            _candidate(20, 30, "Higher combined"),
            _evaluation(0.6),
            CandidateScore(0.6, 0.9, 0.8, 160, 0.5, 0.85),
        ),
    ]

    ranked = rank_scored_candidates(candidates, top_n=1)

    assert ranked[0].candidate.text == "Higher combined"
    assert ranked[0].score == 0.85
