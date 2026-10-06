from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker.diarization import (
    DiarizationError,
    DiarizationResult,
    DiarizationTurn,
    attach_speakers,
    diarize_audio,
)
from clipper_worker.transcription import (
    TranscriptionResult,
    TranscriptionSegment,
    WordTimestamp,
)


def test_diarize_audio_maps_pipeline_turns_and_speakers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    pipeline_calls = []

    class FakeAnnotation:
        def itertracks(self, *, yield_label: bool):
            assert yield_label is True
            return iter(
                [
                    (SimpleNamespace(start=0.1, end=1.2), 0, "SPEAKER_00"),
                    (SimpleNamespace(start=1.2, end=2.4), 0, "SPEAKER_01"),
                    (SimpleNamespace(start=-1.0, end=0.0), 0, "INVALID"),
                ]
            )

    class FakePipeline:
        def __call__(self, path: str):
            pipeline_calls.append(path)
            return FakeAnnotation()

    def load_pipeline(model_name: str, hf_token: str) -> FakePipeline:
        assert model_name == "pyannote/speaker-diarization-3.1"
        assert hf_token == "local-read-token"
        return FakePipeline()

    monkeypatch.setattr("clipper_worker.diarization._load_pipeline", load_pipeline)

    result = diarize_audio(audio_path, hf_token="local-read-token")

    assert pipeline_calls == [str(audio_path)]
    assert result.speakers == ("SPEAKER_00", "SPEAKER_01")
    assert result.turns == (
        DiarizationTurn(0.1, 1.2, "SPEAKER_00"),
        DiarizationTurn(1.2, 2.4, "SPEAKER_01"),
    )


def test_diarization_requires_token_before_loading_gated_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")
    monkeypatch.setattr(
        "clipper_worker.diarization._load_pipeline",
        lambda *_args: pytest.fail("Pipeline must not load without a token"),
    )

    with pytest.raises(DiarizationError, match="requires CLIPPER_HF_TOKEN"):
        diarize_audio(audio_path, hf_token=None)


def test_diarize_audio_surfaces_pipeline_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"wav")

    def failed_pipeline(*_args: object) -> None:
        raise OSError("model access denied")

    monkeypatch.setattr("clipper_worker.diarization._load_pipeline", failed_pipeline)

    with pytest.raises(DiarizationError, match="model access denied"):
        diarize_audio(audio_path, hf_token="local-read-token")


def test_attach_speakers_uses_largest_overlap_and_preserves_unmatched_words() -> None:
    transcription = TranscriptionResult(
        language="en",
        language_probability=0.95,
        duration_seconds=4,
        segments=(
            TranscriptionSegment(
                start_seconds=0,
                end_seconds=4,
                text="Two speakers.",
                words=(
                    WordTimestamp(0.5, 1.0, "One", 0.9),
                    WordTimestamp(1.1, 1.4, "overlap", 0.9),
                    WordTimestamp(3.5, 3.8, "unmatched", 0.8),
                ),
            ),
        ),
    )
    diarization = DiarizationResult(
        speakers=("SPEAKER_00", "SPEAKER_01"),
        turns=(
            DiarizationTurn(0, 1.2, "SPEAKER_00"),
            DiarizationTurn(1.2, 2.5, "SPEAKER_01"),
        ),
    )

    result = attach_speakers(transcription, diarization)

    assert [word.speaker_id for word in result.segments[0].words] == [
        "SPEAKER_00",
        "SPEAKER_01",
        None,
    ]
    assert transcription.segments[0].words[0].speaker_id is None
