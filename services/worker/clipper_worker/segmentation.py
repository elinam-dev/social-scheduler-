import math
import re
import subprocess
import wave
from dataclasses import dataclass
from pathlib import Path

from clipper_worker.transcription import TranscriptionResult, WordTimestamp


class SilenceDetectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Sentence:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[WordTimestamp, ...]


@dataclass(frozen=True)
class SilenceInterval:
    start_seconds: float
    end_seconds: float


DEFAULT_MAX_INTERWORD_GAP_SECONDS = 1.0
DEFAULT_SILENCE_THRESHOLD_DB = -35.0
DEFAULT_MIN_SILENCE_DURATION_SECONDS = 0.5
_SENTENCE_END = re.compile(r"[.!?…。！？]+$")
_PUNCTUATION_SPACE = re.compile(r"\s+([,.;:!?…。！？])")
_SILENCE_EVENT = re.compile(r"silence_(start|end):\s*([0-9]+(?:\.[0-9]+)?)")


def segment_sentences(
    transcription: TranscriptionResult,
    *,
    max_interword_gap_seconds: float = DEFAULT_MAX_INTERWORD_GAP_SECONDS,
) -> tuple[Sentence, ...]:
    if not math.isfinite(max_interword_gap_seconds) or max_interword_gap_seconds < 0:
        raise ValueError("Maximum inter-word gap must be finite and nonnegative")

    sentences: list[Sentence] = []
    words: list[WordTimestamp] = []

    def flush() -> None:
        if not words:
            return
        text = " ".join(word.text.strip() for word in words if word.text.strip())
        text = _PUNCTUATION_SPACE.sub(r"\1", text)
        sentences.append(
            Sentence(
                start_seconds=words[0].start_seconds,
                end_seconds=words[-1].end_seconds,
                text=text,
                words=tuple(words),
            )
        )
        words.clear()

    for segment in transcription.segments:
        if not segment.words:
            flush()
            if segment.text.strip():
                sentences.append(
                    Sentence(
                        start_seconds=segment.start_seconds,
                        end_seconds=segment.end_seconds,
                        text=segment.text.strip(),
                        words=(),
                    )
                )
            continue

        for word in segment.words:
            if (
                words
                and word.start_seconds - words[-1].end_seconds
                > max_interword_gap_seconds
            ):
                flush()
            words.append(word)
            if _SENTENCE_END.search(word.text.strip()):
                flush()

    flush()
    return tuple(sentences)


def detect_silences(
    audio_path: str | Path,
    *,
    threshold_db: float = DEFAULT_SILENCE_THRESHOLD_DB,
    min_duration_seconds: float = DEFAULT_MIN_SILENCE_DURATION_SECONDS,
    ffmpeg_binary: str = "ffmpeg",
) -> tuple[SilenceInterval, ...]:
    path = Path(audio_path)
    if not path.is_file():
        raise SilenceDetectionError(f"Audio file does not exist: {path}")
    if not math.isfinite(threshold_db) or threshold_db > 0:
        raise ValueError("Silence threshold must be finite and no greater than 0 dB")
    if not math.isfinite(min_duration_seconds) or min_duration_seconds <= 0:
        raise ValueError("Minimum silence duration must be finite and positive")

    duration_seconds = _read_audio_duration(path)
    command = [
        ffmpeg_binary,
        "-hide_banner",
        "-nostdin",
        "-v",
        "info",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_duration_seconds}",
        "-f",
        "null",
        "-",
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except FileNotFoundError as error:
        raise SilenceDetectionError(
            f"FFmpeg executable not found: {ffmpeg_binary}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise SilenceDetectionError(
            f"FFmpeg silence detection timed out for {path}"
        ) from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "FFmpeg could not analyze the audio"
        raise SilenceDetectionError(
            f"FFmpeg silence detection failed for {path}: {detail}"
        ) from error

    return _parse_silence_events(result.stderr, duration_seconds)


def _read_audio_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as audio:
            frame_rate = audio.getframerate()
            if frame_rate <= 0:
                raise SilenceDetectionError(f"Audio has an invalid sample rate: {path}")
            duration = audio.getnframes() / frame_rate
    except (wave.Error, EOFError) as error:
        raise SilenceDetectionError(
            f"Audio is not a readable WAV file: {path}"
        ) from error
    if not math.isfinite(duration) or duration <= 0:
        raise SilenceDetectionError(f"Audio has no usable duration: {path}")
    return duration


def _parse_silence_events(
    log: str, duration_seconds: float
) -> tuple[SilenceInterval, ...]:
    intervals: list[SilenceInterval] = []
    pending_start: float | None = None

    for match in _SILENCE_EVENT.finditer(log):
        event, raw_timestamp = match.groups()
        timestamp = float(raw_timestamp)
        if not math.isfinite(timestamp):
            continue
        timestamp = min(max(timestamp, 0.0), duration_seconds)
        if event == "start":
            pending_start = timestamp
        elif pending_start is not None and timestamp > pending_start:
            intervals.append(SilenceInterval(pending_start, timestamp))
            pending_start = None

    if pending_start is not None and duration_seconds > pending_start:
        intervals.append(SilenceInterval(pending_start, duration_seconds))
    return tuple(intervals)
