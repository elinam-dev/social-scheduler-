import math
import subprocess
from pathlib import Path

from clipper_worker.media import probe_media


class ClipRenderError(RuntimeError):
    pass


def render_clip(
    input_path: str | Path,
    output_path: str | Path,
    start_seconds: float,
    end_seconds: float,
    *,
    ffmpeg_binary: str = "ffmpeg",
    preset: str = "medium",
    crf: int = 20,
) -> Path:
    source = Path(input_path)
    destination = Path(output_path)
    if not source.is_file():
        raise ClipRenderError(f"Video file does not exist: {source}")
    if source.resolve() == destination.resolve():
        raise ClipRenderError("Rendered clip path must differ from its source")
    if destination.suffix.lower() != ".mp4":
        raise ClipRenderError("Rendered clip output path must have an .mp4 extension")
    if (
        not math.isfinite(start_seconds)
        or not math.isfinite(end_seconds)
        or start_seconds < 0
        or end_seconds <= start_seconds
    ):
        raise ValueError("Clip boundaries must be finite and have end after start")
    if not 0 <= crf <= 51:
        raise ValueError("H.264 CRF must be between 0 and 51")
    if not preset:
        raise ValueError("H.264 preset must not be blank")

    metadata = probe_media(source)
    if end_seconds > metadata.duration_seconds:
        raise ValueError("Clip end time exceeds the source video duration")

    video_filter = (
        f"trim=start={start_seconds:.9f}:end={end_seconds:.9f},setpts=PTS-STARTPTS"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_binary,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
    ]
    if metadata.has_audio:
        audio_filter = (
            f"atrim=start={start_seconds:.9f}:end={end_seconds:.9f},"
            "asetpts=PTS-STARTPTS"
        )
        command.extend(
            [
                "-filter_complex",
                f"[0:v:0]{video_filter}[v];[0:a:0]{audio_filter}[a]",
                "-map",
                "[v]",
                "-map",
                "[a]",
            ]
        )
    else:
        command.extend(
            [
                "-vf",
                video_filter,
                "-map",
                "0:v:0",
            ]
        )
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )

    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except FileNotFoundError as error:
        raise ClipRenderError(
            f"FFmpeg executable not found: {ffmpeg_binary}"
        ) from error
    except subprocess.TimeoutExpired as error:
        raise ClipRenderError(f"FFmpeg timed out rendering {source}") from error
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "FFmpeg could not render the requested clip"
        raise ClipRenderError(
            f"FFmpeg clip rendering failed for {source}: {detail}"
        ) from error

    if not destination.is_file() or destination.stat().st_size == 0:
        raise ClipRenderError(f"FFmpeg did not create a rendered clip: {destination}")
    return destination
