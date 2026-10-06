import math
from pathlib import Path
from typing import Literal

from clipper_worker.crop_path import build_smoothed_crop_path
from clipper_worker.face_tracking import FaceTrack
from clipper_worker.media import probe_media
from clipper_worker.vertical_rendering import render_vertical_clip

ExportProfile = Literal["9:16", "1:1", "16:9"]


def render_aspect_export(
    input_path: str | Path,
    output_path: str | Path,
    track: FaceTrack,
    start_seconds: float,
    end_seconds: float,
    *,
    profile: str,
    smoothing: float = 0.35,
    ffmpeg_binary: str = "ffmpeg",
    preset: str = "medium",
    crf: int = 20,
) -> Path:
    if profile == "9:16":
        output_width, output_height = 1080, 1920
    elif profile == "1:1":
        output_width, output_height = 1080, 1080
    elif profile == "16:9":
        output_width, output_height = 1920, 1080
    else:
        raise ValueError(f"Unsupported export profile: {profile}")
    if (
        not math.isfinite(start_seconds)
        or not math.isfinite(end_seconds)
        or start_seconds < 0
        or end_seconds <= start_seconds
    ):
        raise ValueError("Clip boundaries must be finite and have end after start")

    metadata = probe_media(input_path)
    crop_path = build_smoothed_crop_path(
        track,
        metadata.width,
        metadata.height,
        output_aspect_ratio=output_width / output_height,
        smoothing=smoothing,
    )
    return render_vertical_clip(
        input_path,
        output_path,
        crop_path,
        start_seconds,
        end_seconds,
        output_width=output_width,
        output_height=output_height,
        ffmpeg_binary=ffmpeg_binary,
        preset=preset,
        crf=crf,
    )
