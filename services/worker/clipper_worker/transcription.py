import math
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ctranslate2
from faster_whisper import WhisperModel

from app.config import Settings


class TranscriptionError(RuntimeError):
    pass


DEFAULT_CHUNK_DURATION_SECONDS = 1800


@dataclass(frozen=True)
class WordTimestamp:
    start_seconds: float
    end_seconds: float
    text: str
    probability: float | None
    speaker_id: str | None = None


@dataclass(frozen=True)
class TranscriptionSegment:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[WordTimestamp, ...]


@dataclass(frozen=True)
class TranscriptionResult:
    language: str
    language_probability: float
    duration_seconds: float
    segments: tuple[TranscriptionSegment, ...]


def is_cuda_available() -> bool:
    return ctranslate2.get_cuda_device_count() > 0


def transcribe_audio(
    audio_path: str | Path,
    *,
    model_name: str | None = None,
    language: str | None = None,
    chunk_duration_seconds: int = DEFAULT_CHUNK_DURATION_SECONDS,
    ffmpeg_binary: str = "ffmpeg",
) -> TranscriptionResult:
    path = Path(audio_path)
    if not path.is_file():
        raise TranscriptionError(f"Audio file does not exist: {path}")
    if chunk_duration_seconds <= 0:
        raise TranscriptionError("Chunk duration must be a positive number of seconds")

    model_name = model_name or Settings().whisper_model
    if is_cuda_available():
        device = "cuda"
        compute_type = "float16"
    else:
        device = "cpu"
        compute_type = "int8"

    duration = _read_wav_duration(path)
    if not math.isfinite(duration) or duration <= 0:
        raise TranscriptionError(f"Audio has no usable duration: {path}")

    try:
        model = WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )
        with tempfile.TemporaryDirectory(prefix="clipper-transcribe-") as temp_dir:
            chunks = _prepare_chunks(
                path,
                duration,
                chunk_duration_seconds,
                Path(temp_dir),
                ffmpeg_binary,
            )
            segments: list[TranscriptionSegment] = []
            language_info: Any | None = None
            weighted_language_probability = 0.0
            for chunk_path, offset_seconds, chunk_duration in chunks:
                raw_segments, info = model.transcribe(
                    str(chunk_path),
                    language=language,
                    beam_size=5,
                    word_timestamps=True,
                )
                if language_info is None:
                    language_info = info
                weighted_language_probability += (
                    float(info.language_probability) * chunk_duration
                )
                segments.extend(
                    _offset_segment(segment, offset_seconds) for segment in raw_segments
                )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        raise TranscriptionError(f"Whisper transcription failed: {error}") from error

    if language_info is None:
        raise TranscriptionError("Whisper did not return language metadata")
    return TranscriptionResult(
        language=language_info.language,
        language_probability=weighted_language_probability / duration,
        duration_seconds=duration,
        segments=tuple(segments),
    )


def _read_wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            if frame_rate <= 0:
                raise TranscriptionError(f"Audio has an invalid sample rate: {path}")
            return audio.getnframes() / frame_rate
    except (wave.Error, EOFError) as error:
        raise TranscriptionError(f"Audio is not a readable WAV file: {path}") from error


def _prepare_chunks(
    audio_path: Path,
    duration_seconds: float,
    chunk_duration_seconds: int,
    temporary_directory: Path,
    ffmpeg_binary: str,
) -> list[tuple[Path, float, float]]:
    if duration_seconds <= chunk_duration_seconds:
        return [(audio_path, 0.0, duration_seconds)]

    chunks = []
    offset_seconds = 0.0
    chunk_index = 0
    while offset_seconds < duration_seconds:
        chunk_length = min(chunk_duration_seconds, duration_seconds - offset_seconds)
        chunk_path = temporary_directory / f"chunk-{chunk_index:04d}.wav"
        command = [
            ffmpeg_binary,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-i",
            str(audio_path),
            "-ss",
            f"{offset_seconds:.6f}",
            "-t",
            f"{chunk_length:.6f}",
            "-map",
            "0:a:0",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(chunk_path),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
        except (OSError, subprocess.SubprocessError) as error:
            detail = getattr(error, "stderr", None) or str(error)
            raise TranscriptionError(
                f"FFmpeg failed to create audio chunks: {detail}"
            ) from error
        if not chunk_path.is_file():
            raise TranscriptionError(f"FFmpeg did not create audio chunk: {chunk_path}")
        chunks.append((chunk_path, offset_seconds, chunk_length))
        offset_seconds += chunk_length
        chunk_index += 1
    return chunks


def _offset_segment(segment: Any, offset_seconds: float) -> TranscriptionSegment:
    words = tuple(
        WordTimestamp(
            start_seconds=float(word.start) + offset_seconds,
            end_seconds=float(word.end) + offset_seconds,
            text=word.word.strip(),
            probability=(
                float(word.probability) if word.probability is not None else None
            ),
        )
        for word in (segment.words or ())
    )
    return TranscriptionSegment(
        start_seconds=float(segment.start) + offset_seconds,
        end_seconds=float(segment.end) + offset_seconds,
        text=segment.text.strip(),
        words=words,
    )
