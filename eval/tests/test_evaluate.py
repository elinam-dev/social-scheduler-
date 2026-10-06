import json

import pytest

from eval.evaluate import (
    DEFAULT_WEIGHTS,
    CandidatePrediction,
    ClipLabel,
    ScoringWeights,
    VideoLabels,
    evaluate_predictions,
    load_manifest,
    load_predictions,
    main,
    tune_weights,
)


def _prediction(
    start: float,
    end: float,
    llm: float,
    energy: float,
    speech: float,
    laughter: float,
) -> CandidatePrediction:
    return CandidatePrediction(
        start,
        end,
        {
            "llm_score": llm,
            "audio_energy": energy,
            "speech_rate": speech,
            "laughter": laughter,
        },
    )


def test_evaluate_predictions_measures_top_n_iou_recall_and_deduplicates() -> None:
    labels = (VideoLabels("talk", (ClipLabel(10, 20), ClipLabel(50, 60))),)
    predictions = {
        "talk": (
            _prediction(0, 10, 0.9, 0, 0, 0),
            _prediction(10, 20, 0.8, 0, 0, 0),
            _prediction(10, 20, 0.7, 0, 0, 0),
            _prediction(52, 62, 0.6, 0, 0, 0),
        )
    }

    result = evaluate_predictions(
        labels,
        predictions,
        weights=ScoringWeights(1, 0, 0, 0),
        top_n=2,
        min_iou=0.6,
    )

    assert result.annotated_videos == 1
    assert result.labeled_clips == 2
    assert result.recovered_clips == 1
    assert result.recall_at_n == 0.5


def test_tune_weights_improves_recall_on_signal_separated_examples() -> None:
    labels = (VideoLabels("talk", (ClipLabel(0, 10),)),)
    predictions = {
        "talk": (
            _prediction(0, 10, 0.2, 0.9, 0.9, 0.9),
            _prediction(20, 30, 0.9, 0.1, 0.1, 0.1),
        )
    }

    baseline = evaluate_predictions(labels, predictions, top_n=1)
    best_weights, best_result = tune_weights(
        labels,
        predictions,
        top_n=1,
        step=0.1,
    )

    assert baseline.recall_at_n == 0
    assert best_result.recall_at_n == 1
    assert best_weights != DEFAULT_WEIGHTS
    assert (
        best_weights.llm_score
        + best_weights.audio_energy
        + best_weights.speech_rate
        + best_weights.laughter
        == pytest.approx(1)
    )


def test_load_manifest_and_predictions_validate_input(tmp_path) -> None:
    manifest_path = tmp_path / "manifest.json"
    predictions_path = tmp_path / "predictions.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "videos": [
                    {
                        "id": "talk",
                        "path": "videos/talk.mp4",
                        "clips": [{"start_seconds": 2, "end_seconds": 7}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    predictions_path.write_text(
        json.dumps(
            {
                "version": 1,
                "videos": [
                    {
                        "id": "talk",
                        "candidates": [
                            {
                                "start_seconds": 2,
                                "end_seconds": 7,
                                "scores": {
                                    "llm_score": 0.8,
                                    "audio_energy": 0.5,
                                    "speech_rate": 0.7,
                                    "laughter": 0,
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    labels = load_manifest(manifest_path)
    predictions = load_predictions(predictions_path)

    assert evaluate_predictions(labels, predictions).recall_at_n == 1


def test_evaluate_requires_annotations_and_valid_options() -> None:
    with pytest.raises(ValueError, match="at least one labeled clip"):
        evaluate_predictions((VideoLabels("empty", ()),), {})
    with pytest.raises(ValueError, match="Top-N"):
        evaluate_predictions(
            (VideoLabels("talk", (ClipLabel(0, 1),)),),
            {},
            top_n=0,
        )
    with pytest.raises(ValueError, match="step"):
        tune_weights(
            (VideoLabels("talk", (ClipLabel(0, 1),)),),
            {},
            step=0.3,
        )


def test_one_prediction_cannot_recover_multiple_labeled_clips() -> None:
    labels = (VideoLabels("talk", (ClipLabel(0, 10), ClipLabel(1, 11))),)
    predictions = {"talk": (_prediction(0, 10, 0.9, 0.9, 0.9, 0.9),)}

    result = evaluate_predictions(labels, predictions, min_iou=0.5)

    assert result.recovered_clips == 1
    assert result.recall_at_n == 0.5


def test_evaluate_rejects_prediction_ids_not_in_manifest() -> None:
    labels = (VideoLabels("talk", (ClipLabel(0, 10),)),)

    with pytest.raises(ValueError, match="missing from manifest"):
        evaluate_predictions(
            labels,
            {"typo": (_prediction(0, 10, 0.9, 0.9, 0.9, 0.9),)},
        )


def test_cli_reports_baseline_and_tuned_recall(tmp_path, capsys) -> None:
    manifest_path = tmp_path / "manifest.json"
    predictions_path = tmp_path / "predictions.json"
    manifest_path.write_text(
        json.dumps(
            {
                "version": 1,
                "videos": [
                    {
                        "id": "talk",
                        "path": "talk.mp4",
                        "clips": [{"start_seconds": 0, "end_seconds": 10}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    predictions_path.write_text(
        json.dumps(
            {
                "version": 1,
                "videos": [
                    {
                        "id": "talk",
                        "candidates": [
                            {
                                "start_seconds": 0,
                                "end_seconds": 10,
                                "scores": {
                                    "llm_score": 0.2,
                                    "audio_energy": 0.9,
                                    "speech_rate": 0.9,
                                    "laughter": 0.9,
                                },
                            },
                            {
                                "start_seconds": 20,
                                "end_seconds": 30,
                                "scores": {
                                    "llm_score": 0.9,
                                    "audio_energy": 0.1,
                                    "speech_rate": 0.1,
                                    "laughter": 0.1,
                                },
                            },
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = main(
        [
            "--manifest",
            str(manifest_path),
            "--predictions",
            str(predictions_path),
            "--top-n",
            "1",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert result == 0
    assert output["baseline_recall_at_n"] == 0
    assert output["best_recall_at_n"] == 1
    assert output["labeled_clips"] == 1
