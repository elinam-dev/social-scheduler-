import math
import subprocess
from pathlib import Path

from clipper_worker.crop_path import CropFrame
from clipper_worker.media import probe_media
from clipper_worker.rendering import ClipRenderError


def render_vertical_clip(
    input_path: str | Path,
    output_path: str | Path,
    crop_path: tuple[CropFrame, ...],
    start_seconds: float,
    end_seconds: float,
    *,
    output_width: int = 1080,
    output_height: int = 1920,
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
    if output_width <= 0 or output_height <= 0 or output_width % 2 or output_height % 2:
        raise ValueError("Output dimensions must be positive even integers")
    if not 0 <= crf <= 51:
        raise ValueError("H.264 CRF must be between 0 and 51")
    if not preset:
        raise ValueError("H.264 preset must not be blank")
    if not crop_path:
        raise ValueError("A non-empty crop path is required for vertical rendering")

    metadata = probe_media(source)
    if end_seconds > metadata.duration_seconds:
        raise ValueError("Clip end time exceeds the source video duration")
    _validate_crop_path(crop_path, metadata.width, metadata.height)

    time_expression = f"t+{start_seconds:.9f}" if start_seconds else "t"
    x_expression = _coordinate_expression(crop_path, "x", time_expression)
    y_expression = _coordinate_expression(crop_path, "y", time_expression)
    first_crop = crop_path[0]
    video_filter = (
        f"trim=start={start_seconds:.9f}:end={end_seconds:.9f},"
        "setpts=PTS-STARTPTS,"
        f"crop=w={first_crop.width}:h={first_crop.height}:"
        f"x='{x_expression}':y='{y_expression}',"
        f"scale={output_width}:{output_height}:flags=lanczos,setsar=1"
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
        command.extend(["-vf", video_filter, "-map", "0:v:0"])
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
            f"FFmpeg vertical rendering failed for {source}: {detail}"
        ) from error

    if not destination.is_file() or destination.stat().st_size == 0:
        raise ClipRenderError(f"FFmpeg did not create a rendered clip: {destination}")
    return destination


def _validate_crop_path(
    crop_path: tuple[CropFrame, ...], source_width: int, source_height: int
) -> None:
    first = crop_path[0]
    previous_timestamp = -1.0
    for frame in crop_path:
        if (
            not math.isfinite(frame.timestamp_seconds)
            or frame.timestamp_seconds < 0
            or frame.timestamp_seconds <= previous_timestamp
        ):
            raise ValueError("Crop path timestamps must be finite and increasing")
        if (frame.width, frame.height) != (first.width, first.height):
            raise ValueError("Crop path dimensions must remain constant")
        if (
            frame.x < 0
            or frame.y < 0
            or frame.width <= 0
            or frame.height <= 0
            or frame.x + frame.width > source_width
            or frame.y + frame.height > source_height
            or frame.x % 2
            or frame.y % 2
            or frame.width % 2
            or frame.height % 2
        ):
            raise ValueError("Crop rectangles must be even, positive, and in bounds")
        previous_timestamp = frame.timestamp_seconds


def _coordinate_expression(
    crop_path: tuple[CropFrame, ...], coordinate: str, time_expression: str
) -> str:
    values = [
        (frame.timestamp_seconds, getattr(frame, coordinate)) for frame in crop_path
    ]
    expression = str(values[-1][1])
    for (start_time, start_value), (end_time, end_value) in reversed(
        list(zip(values, values[1:]))
    ):
        interpolation = (
            f"{start_value}+({end_value}-{start_value})*"
            f"({time_expression}-{start_time:.9f})/"
            f"({end_time:.9f}-{start_time:.9f})"
        )
        expression = (
            f"if(lt({time_expression}\\,{end_time:.9f})"
            f"\\,{interpolation}\\,{expression})"
        )
    first_time, first_value = values[0]
    return (
        f"if(lt({time_expression}\\,{first_time:.9f})\\,{first_value}\\,{expression})"
    )
