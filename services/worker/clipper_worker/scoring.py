import math
import re
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from clipper_worker.candidate_review import CandidateEvaluation
from clipper_worker.candidates import CandidateWindow
from clipper_worker.segmentation import Sentence
from clipper_worker.transcription import WordTimestamp

LLM_SCORE_WEIGHT = 0.70
AUDIO_ENERGY_WEIGHT = 0.10
SPEECH_RATE_WEIGHT = 0.15
LAUGHTER_WEIGHT = 0.05
_LAUGHTER_MARKER = re.compile(
    r"^(?:(?:ha|he)[- ]?){2,}$|^laugh(?:ing|ed|s)?$|^laughter$"
)


class AudioScoreError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateScore:
    llm_score: float
    audio_energy: float
    speech_rate: float
    words_per_minute: float
    laughter: float
    combined_score: float


def score_candidate(
    candidate: CandidateWindow,
    evaluation: CandidateEvaluation,
    sentences: Sequence[Sentence],
    audio_path: str | Path,
) -> CandidateScore:
    if (
        candidate.first_sentence_index < 0
        or candidate.end_sentence_index > len(sentences)
        or candidate.end_sentence_index <= candidate.first_sentence_index
    ):
        raise ValueError("Candidate sentence indices are outside the transcript")

    words = tuple(
        word
        for sentence in sentences[
            candidate.first_sentence_index : candidate.end_sentence_index
        ]
        for word in sentence.words
        if word.text.strip()
        and word.end_seconds > candidate.start_seconds
        and word.start_seconds < candidate.end_seconds
    )
    llm_score = (
        evaluation.hook_strength
        + evaluation.standalone_coherence
        + evaluation.payoff
        + evaluation.pacing
    ) / 4
    energy = score_audio_energy(
        audio_path,
        candidate.start_seconds,
        candidate.end_seconds,
    )
    rate, words_per_minute = score_speech_rate(len(words), candidate.duration_seconds)
    laughter = score_laughter(words)
    combined = (
        LLM_SCORE_WEIGHT * llm_score
        + AUDIO_ENERGY_WEIGHT * energy
        + SPEECH_RATE_WEIGHT * rate
        + LAUGHTER_WEIGHT * laughter
    )
    return CandidateScore(
        llm_score=llm_score,
        audio_energy=energy,
        speech_rate=rate,
        words_per_minute=words_per_minute,
        laughter=laughter,
        combined_score=combined,
    )


def score_audio_energy(
    audio_path: str | Path,
    start_seconds: float,
    end_seconds: float,
) -> float:
    path = Path(audio_path)
    if not path.is_file():
        raise AudioScoreError(f"Audio file does not exist: {path}")
    if (
        not math.isfinite(start_seconds)
        or not math.isfinite(end_seconds)
        or start_seconds < 0
        or end_seconds <= start_seconds
    ):
        raise ValueError("Audio scoring requires finite, positive time boundaries")

    try:
        with wave.open(str(path), "rb") as audio:
            if audio.getnchannels() != 1 or audio.getsampwidth() != 2:
                raise AudioScoreError("Audio scoring requires mono 16-bit PCM WAV")
            sample_rate = audio.getframerate()
            if sample_rate <= 0:
                raise AudioScoreError("Audio WAV has an invalid sample rate")
            total_frames = audio.getnframes()
            duration = total_frames / sample_rate
            if end_seconds > duration:
                raise ValueError("Candidate end time exceeds the audio duration")
            start_frame = round(start_seconds * sample_rate)
            end_frame = min(round(end_seconds * sample_rate), total_frames)
            audio.setpos(start_frame)
            raw_samples = audio.readframes(end_frame - start_frame)
    except (wave.Error, EOFError, OSError) as error:
        raise AudioScoreError(f"Could not read audio WAV {path}: {error}") from error

    samples = array("h")
    samples.frombytes(raw_samples)
    if not samples:
        raise AudioScoreError("Candidate contains no audio samples")
    rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples)) / 32768
    decibels_full_scale = 20 * math.log10(max(rms, 1e-6))
    return _clamp((decibels_full_scale + 60) / 50)


def score_speech_rate(word_count: int, duration_seconds: float) -> tuple[float, float]:
    if word_count < 0:
        raise ValueError("Word count must be nonnegative")
    if not math.isfinite(duration_seconds) or duration_seconds <= 0:
        raise ValueError("Speech rate duration must be finite and positive")
    words_per_minute = word_count * 60 / duration_seconds
    score = _clamp(1 - abs(words_per_minute - 160) / 120)
    return score, words_per_minute


def score_laughter(words: Sequence[WordTimestamp]) -> float:
    laughter_count = sum(
        bool(
            _LAUGHTER_MARKER.fullmatch(
                word.text.strip(" \t\r\n.,!?;:()[]{}\"'").lower()
            )
        )
        for word in words
    )
    return _clamp(laughter_count / 3)


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
