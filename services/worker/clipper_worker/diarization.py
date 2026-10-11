import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from clipper_worker.transcription import TranscriptionResult, is_cuda_available


class DiarizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class DiarizationTurn:
    start_seconds: float
    end_seconds: float
    speaker_id: str


@dataclass(frozen=True)
class DiarizationResult:
    speakers: tuple[str, ...]
    turns: tuple[DiarizationTurn, ...]


def diarize_audio(
    audio_path: str | Path,
    *,
    hf_token: str | None,
    model_name: str = "pyannote/speaker-diarization-3.1",
) -> DiarizationResult:
    path = Path(audio_path)
    if not path.is_file():
        raise DiarizationError(f"Audio file does not exist: {path}")
    if not hf_token:
        return DiarizationResult(speakers=(), turns=())

    try:
        pipeline = _load_pipeline(model_name, hf_token)
        if is_cuda_available():
            pipeline.to("cuda")
        annotation = pipeline(str(path))
        turns = tuple(
            DiarizationTurn(
                start_seconds=float(turn.start),
                end_seconds=float(turn.end),
                speaker_id=str(speaker_id),
            )
            for turn, _track, speaker_id in annotation.itertracks(yield_label=True)
            if _valid_turn(turn.start, turn.end)
        )
    except DiarizationError:
        raise
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        raise DiarizationError(
            f"Speaker diarization failed for {path}: {error}"
        ) from error

    return DiarizationResult(
        speakers=tuple(sorted({turn.speaker_id for turn in turns})),
        turns=turns,
    )


def _load_pipeline(model_name: str, hf_token: str) -> Any:
    try:
        from pyannote.audio import Pipeline
    except ImportError as error:
        raise DiarizationError(
            "pyannote.audio is not installed in the worker environment"
        ) from error

    pipeline = Pipeline.from_pretrained(model_name, use_auth_token=hf_token)
    if pipeline is None:
        raise DiarizationError(
            f"Could not load {model_name}; confirm its access terms on Hugging Face"
        )
    return pipeline


def _valid_turn(start_seconds: float, end_seconds: float) -> bool:
    return (
        math.isfinite(start_seconds)
        and math.isfinite(end_seconds)
        and start_seconds >= 0
        and end_seconds > start_seconds
    )


def attach_speakers(
    transcription: TranscriptionResult,
    diarization: DiarizationResult,
) -> TranscriptionResult:
    segments = tuple(
        replace(
            segment,
            words=tuple(
                replace(word, speaker_id=_speaker_for_word(word, diarization.turns))
                for word in segment.words
            ),
        )
        for segment in transcription.segments
    )
    return replace(transcription, segments=segments)


def _speaker_for_word(word: Any, turns: tuple[DiarizationTurn, ...]) -> str | None:
    best_speaker: str | None = None
    best_overlap = 0.0
    for turn in turns:
        overlap = min(word.end_seconds, turn.end_seconds) - max(
            word.start_seconds, turn.start_seconds
        )
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker_id
    return best_speaker
