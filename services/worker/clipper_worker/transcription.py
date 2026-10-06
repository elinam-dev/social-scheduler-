from dataclasses import dataclass
from pathlib import Path

import ctranslate2
from faster_whisper import WhisperModel

from app.config import Settings


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class TranscriptionSegment:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class TranscriptionResult:
    language: str
    language_probability: float
    duration_seconds: float
    segments: tuple[TranscriptionSegment, ...]


def transcribe_audio(
    audio_path: str | Path,
    *,
    model_name: str | None = None,
    language: str | None = None,
) -> TranscriptionResult:
    path = Path(audio_path)
    if not path.is_file():
        raise TranscriptionError(f"Audio file does not exist: {path}")

    model_name = model_name or Settings().whisper_model
    if ctranslate2.get_cuda_device_count() > 0:
        device = "cuda"
        compute_type = "float16"
    else:
        device = "cpu"
        compute_type = "int8"

    try:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
        raw_segments, info = model.transcribe(
            str(path),
            language=language,
            beam_size=5,
        )
        segments = tuple(
            TranscriptionSegment(
                start_seconds=float(segment.start),
                end_seconds=float(segment.end),
                text=segment.text.strip(),
            )
            for segment in raw_segments
        )
    except (OSError, RuntimeError, ValueError) as error:
        raise TranscriptionError(f"Whisper transcription failed: {error}") from error

    return TranscriptionResult(
        language=info.language,
        language_probability=float(info.language_probability),
        duration_seconds=float(info.duration),
        segments=segments,
    )
