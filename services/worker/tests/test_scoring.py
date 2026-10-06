import math
import wave
from pathlib import Path

import pytest

from clipper_worker.candidate_review import CandidateEvaluation
from clipper_worker.candidates import CandidateWindow
from clipper_worker.scoring import (
    AUDIO_ENERGY_WEIGHT,
    LAUGHTER_WEIGHT,
    LLM_SCORE_WEIGHT,
    SPEECH_RATE_WEIGHT,
    AudioScoreError,
    score_audio_energy,
    score_candidate,
    score_laughter,
    score_speech_rate,
)
from clipper_worker.segmentation import Sentence
from clipper_worker.transcription import WordTimestamp


def _write_wav(path: Path, samples: list[int], sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(
            b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
        )


def _evaluation(score: float = 0.8) -> CandidateEvaluation:
    return CandidateEvaluation(
        hook_strength=score,
        standalone_coherence=score,
        payoff=score,
        pacing=score,
        standalone=True,
        rationale="Complete and clear.",
    )


def test_score_audio_energy_orders_silence_and_louder_audio(tmp_path: Path) -> None:
    quiet_path = tmp_path / "quiet.wav"
    loud_path = tmp_path / "loud.wav"
    _write_wav(quiet_path, [0] * 1600)
    _write_wav(loud_path, [8000] * 1600)

    quiet = score_audio_energy(quiet_path, 0, 0.1)
    loud = score_audio_energy(loud_path, 0, 0.1)

    assert quiet == 0
    assert 0 < loud <= 1
    assert loud > quiet


def test_score_audio_energy_rejects_invalid_or_out_of_range_boundaries(
    tmp_path: Path,
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, [1000] * 1600)

    with pytest.raises(ValueError, match="finite, positive"):
        score_audio_energy(audio_path, math.nan, 0.1)
    with pytest.raises(ValueError, match="exceeds"):
        score_audio_energy(audio_path, 0, 0.2)


def test_score_speech_rate_rewards_normal_pace_and_rejects_invalid_values() -> None:
    score, words_per_minute = score_speech_rate(16, 6)

    assert score == 1
    assert words_per_minute == 160
    assert score_speech_rate(0, 60)[0] == 0
    with pytest.raises(ValueError, match="Word count"):
        score_speech_rate(-1, 60)


def test_score_laughter_recognizes_markers_and_caps_score() -> None:
    words = (
        WordTimestamp(0, 0.2, "Ha-ha!", 0.9),
        WordTimestamp(0.2, 0.4, "laughing", 0.9),
        WordTimestamp(0.4, 0.6, "laughter", 0.9),
        WordTimestamp(0.6, 0.8, "ordinary", 0.9),
    )

    assert score_laughter(words) == 1
    assert score_laughter(words[-1:]) == 0


def test_score_candidate_combines_all_documented_signals(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, [5000] * 16000)
    words = (
        WordTimestamp(0, 0.5, "Ha-ha!", 0.9),
        WordTimestamp(0.5, 1.0, "story.", 0.9),
    )
    sentences = (Sentence(0, 1, "Ha-ha! story.", words),)
    candidate = CandidateWindow(0, 1, "Ha-ha! story.", 0, 1)

    score = score_candidate(candidate, _evaluation(), sentences, audio_path)
    expected = (
        LLM_SCORE_WEIGHT * score.llm_score
        + AUDIO_ENERGY_WEIGHT * score.audio_energy
        + SPEECH_RATE_WEIGHT * score.speech_rate
        + LAUGHTER_WEIGHT * score.laughter
    )

    assert score.llm_score == pytest.approx(0.8)
    assert score.laughter == pytest.approx(1 / 3)
    assert score.combined_score == pytest.approx(expected)
    assert 0 <= score.combined_score <= 1


def test_score_candidate_rejects_invalid_sentence_indices(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, [1000] * 16000)

    with pytest.raises(ValueError, match="sentence indices"):
        score_candidate(
            CandidateWindow(0, 1, "Text", 0, 2),
            _evaluation(),
            (Sentence(0, 1, "Text", ()),),
            audio_path,
        )


def test_score_audio_energy_requires_mono_16_bit_pcm(tmp_path: Path) -> None:
    audio_path = tmp_path / "stereo.wav"
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(2)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\x00\x00\x00\x00" * 1600)

    with pytest.raises(AudioScoreError, match="mono 16-bit"):
        score_audio_energy(audio_path, 0, 0.1)
