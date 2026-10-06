import argparse
import itertools
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator, Sequence

FEATURES = ("llm_score", "audio_energy", "speech_rate", "laughter")
DEFAULT_TOP_N = 5
DEFAULT_MIN_IOU = 0.5
DEFAULT_OVERLAP_THRESHOLD = 0.7


@dataclass(frozen=True)
class ScoringWeights:
    llm_score: float
    audio_energy: float
    speech_rate: float
    laughter: float

    def __post_init__(self) -> None:
        values = tuple(getattr(self, feature) for feature in FEATURES)
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("Weights must be finite values between 0 and 1")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
            raise ValueError("Scoring weights must sum to 1")

    def apply(self, components: dict[str, float]) -> float:
        return sum(getattr(self, feature) * components[feature] for feature in FEATURES)


DEFAULT_WEIGHTS = ScoringWeights(0.70, 0.10, 0.15, 0.05)


@dataclass(frozen=True)
class ClipLabel:
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class CandidatePrediction:
    start_seconds: float
    end_seconds: float
    components: dict[str, float]


@dataclass(frozen=True)
class VideoLabels:
    video_id: str
    clips: tuple[ClipLabel, ...]


@dataclass(frozen=True)
class EvaluationResult:
    annotated_videos: int
    labeled_clips: int
    recovered_clips: int
    recall_at_n: float


def load_manifest(path: str | Path) -> tuple[VideoLabels, ...]:
    document = _read_json(path)
    videos = document.get("videos")
    if document.get("version") != 1 or not isinstance(videos, list):
        raise ValueError("Manifest must have version 1 and a videos array")
    parsed: list[VideoLabels] = []
    seen_ids: set[str] = set()
    for item in videos:
        if not isinstance(item, dict):
            raise ValueError("Manifest videos must be JSON objects")
        video_id = item.get("id")
        path_value = item.get("path")
        clips = item.get("clips")
        if not isinstance(video_id, str) or not video_id:
            raise ValueError("Every manifest video must have a non-empty id")
        if video_id in seen_ids:
            raise ValueError(f"Duplicate video id in manifest: {video_id}")
        if not isinstance(path_value, str) or not path_value:
            raise ValueError(f"Video {video_id} must have a non-empty path")
        if not isinstance(clips, list):
            raise ValueError(f"Video {video_id} must have a clips array")
        seen_ids.add(video_id)
        parsed_clips = tuple(
            ClipLabel(
                _time(clip, "start_seconds", video_id),
                _time(clip, "end_seconds", video_id),
            )
            for clip in clips
            if isinstance(clip, dict)
        )
        if len(parsed_clips) != len(clips):
            raise ValueError(f"Video {video_id} clips must be JSON objects")
        if any(
            clip.start_seconds < 0 or clip.end_seconds <= clip.start_seconds
            for clip in parsed_clips
        ):
            raise ValueError(f"Video {video_id} has invalid clip time boundaries")
        parsed.append(VideoLabels(video_id, parsed_clips))
    return tuple(parsed)


def load_predictions(path: str | Path) -> dict[str, tuple[CandidatePrediction, ...]]:
    document = _read_json(path)
    videos = document.get("videos")
    if document.get("version") != 1 or not isinstance(videos, list):
        raise ValueError("Predictions must have version 1 and a videos array")
    parsed: dict[str, tuple[CandidatePrediction, ...]] = {}
    for item in videos:
        if not isinstance(item, dict):
            raise ValueError("Prediction videos must be JSON objects")
        video_id = item.get("id")
        candidates = item.get("candidates")
        if not isinstance(video_id, str) or not video_id:
            raise ValueError("Every prediction video must have a non-empty id")
        if video_id in parsed:
            raise ValueError(f"Duplicate video id in predictions: {video_id}")
        if not isinstance(candidates, list):
            raise ValueError(f"Video {video_id} must have a candidates array")
        parsed[video_id] = tuple(
            _parse_candidate(candidate, video_id) for candidate in candidates
        )
    return parsed


def evaluate_predictions(
    labels: Sequence[VideoLabels],
    predictions: dict[str, tuple[CandidatePrediction, ...]],
    *,
    weights: ScoringWeights = DEFAULT_WEIGHTS,
    top_n: int = DEFAULT_TOP_N,
    min_iou: float = DEFAULT_MIN_IOU,
    overlap_threshold: float = DEFAULT_OVERLAP_THRESHOLD,
) -> EvaluationResult:
    _validate_eval_options(top_n, min_iou, overlap_threshold)
    known_ids = {video.video_id for video in labels}
    unknown_ids = set(predictions) - known_ids
    if unknown_ids:
        raise ValueError(
            f"Predictions contain video IDs missing from manifest: "
            f"{', '.join(sorted(unknown_ids))}"
        )
    labeled_videos = tuple(video for video in labels if video.clips)
    for video in labeled_videos:
        if any(
            not math.isfinite(label.start_seconds)
            or not math.isfinite(label.end_seconds)
            or label.start_seconds < 0
            or label.end_seconds <= label.start_seconds
            for label in video.clips
        ):
            raise ValueError(f"Video {video.video_id} has invalid labeled clip times")
    labeled_clip_count = sum(len(video.clips) for video in labeled_videos)
    if not labeled_clip_count:
        raise ValueError("Add at least one labeled clip to the evaluation manifest")

    recovered = 0
    for video in labeled_videos:
        candidates = predictions.get(video.video_id, ())
        for candidate in candidates:
            _validate_candidate(candidate, video.video_id)
        ranked = sorted(
            candidates,
            key=lambda candidate: (
                -weights.apply(candidate.components),
                candidate.start_seconds,
                candidate.end_seconds,
            ),
        )
        selected = _deduplicate(ranked, overlap_threshold, top_n)
        recovered += _count_recovered_labels(
            selected,
            video.clips,
            min_iou,
        )
    return EvaluationResult(
        annotated_videos=len(labeled_videos),
        labeled_clips=labeled_clip_count,
        recovered_clips=recovered,
        recall_at_n=recovered / labeled_clip_count,
    )


def tune_weights(
    labels: Sequence[VideoLabels],
    predictions: dict[str, tuple[CandidatePrediction, ...]],
    *,
    top_n: int = DEFAULT_TOP_N,
    min_iou: float = DEFAULT_MIN_IOU,
    step: float = 0.1,
) -> tuple[ScoringWeights, EvaluationResult]:
    units = round(1 / step) if math.isfinite(step) and step > 0 else 0
    if units <= 0 or not math.isclose(units * step, 1.0, abs_tol=1e-9):
        raise ValueError("Weight search step must be a positive divisor of 1")

    weight_sets = list(_weight_grid(units))
    if DEFAULT_WEIGHTS not in weight_sets:
        weight_sets.append(DEFAULT_WEIGHTS)
    results = [
        (
            weights,
            evaluate_predictions(
                labels,
                predictions,
                weights=weights,
                top_n=top_n,
                min_iou=min_iou,
            ),
        )
        for weights in weight_sets
    ]
    return max(
        results,
        key=lambda item: (
            item[1].recall_at_n,
            -_distance_from_default(item[0]),
            item[0].llm_score,
            item[0].audio_energy,
            item[0].speech_rate,
            item[0].laughter,
        ),
    )


def _weight_grid(units: int) -> Iterator[ScoringWeights]:
    for llm, audio, speech in itertools.product(range(units + 1), repeat=3):
        laughter = units - llm - audio - speech
        if laughter >= 0:
            yield ScoringWeights(
                llm / units,
                audio / units,
                speech / units,
                laughter / units,
            )


def _distance_from_default(weights: ScoringWeights) -> float:
    return sum(
        abs(getattr(weights, feature) - getattr(DEFAULT_WEIGHTS, feature))
        for feature in FEATURES
    )


def _deduplicate(
    candidates: Sequence[CandidatePrediction],
    overlap_threshold: float,
    top_n: int,
) -> list[CandidatePrediction]:
    selected: list[CandidatePrediction] = []
    for candidate in candidates:
        if any(
            _overlap_coefficient(candidate, accepted) >= overlap_threshold
            for accepted in selected
        ):
            continue
        selected.append(candidate)
        if len(selected) >= top_n:
            break
    return selected


def _count_recovered_labels(
    candidates: Sequence[CandidatePrediction],
    labels: Sequence[ClipLabel],
    min_iou: float,
) -> int:
    unmatched = set(range(len(labels)))
    recovered = 0
    for candidate in candidates:
        matches = [
            (index, _temporal_iou(candidate, label))
            for index, label in enumerate(labels)
            if index in unmatched
        ]
        if not matches:
            break
        best_index, best_iou = max(matches, key=lambda item: item[1])
        if best_iou >= min_iou:
            unmatched.remove(best_index)
            recovered += 1
    return recovered


def _validate_candidate(candidate: CandidatePrediction, video_id: str) -> None:
    if (
        not math.isfinite(candidate.start_seconds)
        or not math.isfinite(candidate.end_seconds)
        or candidate.start_seconds < 0
        or candidate.end_seconds <= candidate.start_seconds
    ):
        raise ValueError(f"Video {video_id} has invalid candidate boundaries")
    if set(candidate.components) != set(FEATURES):
        raise ValueError(f"Video {video_id} candidate has invalid score fields")
    if any(
        not math.isfinite(candidate.components[feature])
        or not 0 <= candidate.components[feature] <= 1
        for feature in FEATURES
    ):
        raise ValueError(f"Video {video_id} candidate scores must be between 0 and 1")


def _overlap_coefficient(
    first: CandidatePrediction,
    second: CandidatePrediction,
) -> float:
    overlap = max(
        0.0,
        min(first.end_seconds, second.end_seconds)
        - max(first.start_seconds, second.start_seconds),
    )
    if overlap == 0:
        return 0.0
    shorter_duration = min(
        first.end_seconds - first.start_seconds,
        second.end_seconds - second.start_seconds,
    )
    return overlap / shorter_duration


def _temporal_iou(candidate: CandidatePrediction, label: ClipLabel) -> float:
    intersection = max(
        0.0,
        min(candidate.end_seconds, label.end_seconds)
        - max(candidate.start_seconds, label.start_seconds),
    )
    union = max(candidate.end_seconds, label.end_seconds) - min(
        candidate.start_seconds, label.start_seconds
    )
    return intersection / union if union > 0 else 0.0


def _parse_candidate(value: Any, video_id: str) -> CandidatePrediction:
    if not isinstance(value, dict):
        raise ValueError(f"Video {video_id} candidates must be JSON objects")
    start = _time(value, "start_seconds", video_id)
    end = _time(value, "end_seconds", video_id)
    components = value.get("scores")
    if start < 0 or end <= start:
        raise ValueError(f"Video {video_id} candidate has invalid time boundaries")
    if not isinstance(components, dict) or set(components) != set(FEATURES):
        raise ValueError(
            f"Video {video_id} candidates must provide scores for: "
            f"{', '.join(FEATURES)}"
        )
    scores = {
        feature: _finite_number(components[feature], f"{video_id}.{feature}")
        for feature in FEATURES
    }
    if any(not 0 <= score <= 1 for score in scores.values()):
        raise ValueError(f"Video {video_id} candidate scores must be between 0 and 1")
    return CandidatePrediction(start, end, scores)


def _time(value: dict[str, Any], field: str, context: str) -> float:
    if field not in value:
        raise ValueError(f"{context} is missing {field}")
    return _finite_number(value[field], f"{context}.{field}")


def _finite_number(value: Any, context: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{context} must be finite")
    return number


def _validate_eval_options(
    top_n: int, min_iou: float, overlap_threshold: float
) -> None:
    if top_n <= 0:
        raise ValueError("Top-N limit must be positive")
    if not math.isfinite(min_iou) or not 0 <= min_iou <= 1:
        raise ValueError("Minimum IoU must be finite and between 0 and 1")
    if not math.isfinite(overlap_threshold) or not 0 < overlap_threshold <= 1:
        raise ValueError("Overlap threshold must be finite and within (0, 1]")


def _read_json(path: str | Path) -> dict[str, Any]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(document, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate candidate scores and tune their linear weights."
    )
    parser.add_argument("--manifest", default="eval/manifest.json")
    parser.add_argument("--predictions", default="eval/predictions.json")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--min-iou", type=float, default=DEFAULT_MIN_IOU)
    parser.add_argument("--step", type=float, default=0.1)
    args = parser.parse_args(argv)

    try:
        labels = load_manifest(args.manifest)
        predictions = load_predictions(args.predictions)
        baseline = evaluate_predictions(
            labels,
            predictions,
            top_n=args.top_n,
            min_iou=args.min_iou,
        )
        best_weights, best_result = tune_weights(
            labels,
            predictions,
            top_n=args.top_n,
            min_iou=args.min_iou,
            step=args.step,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(
        json.dumps(
            {
                "baseline_weights": asdict(DEFAULT_WEIGHTS),
                "baseline_recall_at_n": baseline.recall_at_n,
                "best_weights": asdict(best_weights),
                "best_recall_at_n": best_result.recall_at_n,
                "matched_clips": best_result.recovered_clips,
                "labeled_clips": best_result.labeled_clips,
                "annotated_videos": best_result.annotated_videos,
                "top_n": args.top_n,
                "min_iou": args.min_iou,
            },
            indent=2,
        )
    )
    return 0
