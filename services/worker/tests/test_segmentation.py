import math
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker.segmentation import (
    SilenceDetectionError,
    SilenceInterval,
    detect_silences,
    segment_sentences,
)
from clipper_worker.transcription import (
    TranscriptionResult,
    TranscriptionSegment,
    WordTimestamp,
)


def _transcription(*segments: TranscriptionSegment) -> TranscriptionResult:
    return TranscriptionResult(
        language="en",
        language_probability=0.99,
        duration_seconds=10,
        segments=segments,
    )


def _write_wav(path: Path, duration_seconds: int = 4, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * duration_seconds * sample_rate)


def test_segment_sentences_uses_punctuation_and_preserves_word_times() -> None:
    transcription = _transcription(
        TranscriptionSegment(
            0,
            2.5,
            "We built it. It works!",
            (
                WordTimestamp(0, 0.3, "We", 0.99),
                WordTimestamp(0.3, 0.8, "built", 0.98),
                WordTimestamp(0.8, 1.1, "it.", 0.97),
                WordTimestamp(1.3, 1.5, "It", 0.96),
                WordTimestamp(1.5, 2.5, "works!", 0.95),
            ),
        )
    )

    sentences = segment_sentences(transcription)

    assert [sentence.text for sentence in sentences] == ["We built it.", "It works!"]
    assert [
        (sentence.start_seconds, sentence.end_seconds) for sentence in sentences
    ] == [
        (0, 1.1),
        (1.3, 2.5),
    ]
    assert sentences[0].words[-1].text == "it."


def test_segment_sentences_splits_long_gaps_and_keeps_wordless_segments() -> None:
    transcription = _transcription(
        TranscriptionSegment(
            0,
            2.5,
            "Wait. Again.",
            (
                WordTimestamp(0, 0.5, "Wait", 0.9),
                WordTimestamp(2, 2.5, "Again.", 0.9),
            ),
        ),
        TranscriptionSegment(3, 4, "A separate thought.", ()),
    )

    sentences = segment_sentences(transcription)

    assert [sentence.text for sentence in sentences] == [
        "Wait",
        "Again.",
        "A separate thought.",
    ]
    assert sentences[0].words[0].text == "Wait"
    assert sentences[2].words == ()


@pytest.mark.parametrize("gap", [-1, math.inf, math.nan])
def test_segment_sentences_rejects_invalid_gap_threshold(gap: float) -> None:
    with pytest.raises(ValueError, match="finite and nonnegative"):
        segment_sentences(_transcription(), max_interword_gap_seconds=gap)


def test_detect_silences_parses_closed_and_trailing_silence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path)

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        assert "silencedetect=noise=-35.0dB:d=0.5" in command
        assert kwargs["check"] is True
        return SimpleNamespace(
            stderr=(
                "[silencedetect] silence_start: 0.25\n"
                "[silencedetect] silence_end: 1.0 | silence_duration: 0.75\n"
                "[silencedetect] silence_start: 2.5\n"
            )
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    silences = detect_silences(audio_path)

    assert silences == (SilenceInterval(0.25, 1.0), SilenceInterval(2.5, 4.0))


def test_detect_silences_reports_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path)

    def failed_run(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="invalid audio",
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(SilenceDetectionError, match="invalid audio"):
        detect_silences(audio_path)
