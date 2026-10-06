import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MediaProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaMetadata:
    duration_seconds: float
    width: int
    height: int
    frame_rate: float | None
    has_audio: bool


def probe_media(
    input_path: str | Path, ffprobe_binary: str = "ffprobe"
) -> MediaMetadata:
    path = Path(input_path)
    if not path.is_file():
        raise MediaProbeError(f"Video file does not exist: {path}")

    command = [
        ffprobe_binary,
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,duration,width,height,avg_frame_rate",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except FileNotFoundError as error:
        raise MediaProbeError(
            f"FFprobe executable not found: {ffprobe_binary}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise MediaProbeError(f"FFprobe timed out for video: {path}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "FFprobe rejected the input file"
        raise MediaProbeError(f"FFprobe failed for {path}: {detail}") from error

    try:
        payload = json.loads(result.stdout)
        return _parse_probe_payload(payload)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as error:
        raise MediaProbeError(
            f"FFprobe returned invalid media metadata for {path}"
        ) from error


def _parse_probe_payload(payload: Any) -> MediaMetadata:
    if not isinstance(payload, dict):
        raise ValueError("Expected an object")

    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise ValueError("Expected a streams array")
    video_streams = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("codec_type") == "video"
    ]
    if not video_streams:
        raise ValueError("No video stream found")

    video = video_streams[0]
    width = int(video["width"])
    height = int(video["height"])
    if width <= 0 or height <= 0:
        raise ValueError("Video dimensions must be positive")

    format_info = payload.get("format")
    format_duration = (
        format_info.get("duration") if isinstance(format_info, dict) else None
    )
    raw_duration = format_duration or video.get("duration")
    duration = float(raw_duration)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Video duration must be finite and nonnegative")

    frame_rate = _parse_frame_rate(video.get("avg_frame_rate"))
    has_audio = any(
        isinstance(stream, dict) and stream.get("codec_type") == "audio"
        for stream in streams
    )
    return MediaMetadata(
        duration_seconds=duration,
        width=width,
        height=height,
        frame_rate=frame_rate,
        has_audio=has_audio,
    )


def _parse_frame_rate(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        numerator, denominator = value.split("/", maxsplit=1)
        rate = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        return None
    if not math.isfinite(rate) or rate <= 0:
        return None
    return rate
