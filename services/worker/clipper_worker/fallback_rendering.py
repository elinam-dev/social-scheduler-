import math
import subprocess
from pathlib import Path
from typing import Literal

from clipper_worker.media import probe_media
from clipper_worker.rendering import ClipRenderError

FallbackLayout = Literal["blurred-background", "split-screen"]


def render_fallback_clip(
    input_path: str | Path,
    output_path: str | Path,
    start_seconds: float,
    end_seconds: float,
    *,
    layout: FallbackLayout,
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
    if layout not in ("blurred-background", "split-screen"):
        raise ValueError(f"Unsupported fallback layout: {layout}")
    if not 0 <= crf <= 51:
        raise ValueError("H.264 CRF must be between 0 and 51")
    if not preset:
        raise ValueError("H.264 preset must not be blank")

    metadata = probe_media(source)
    if end_seconds > metadata.duration_seconds:
        raise ValueError("Clip end time exceeds the source video duration")
    video_filter = _video_filter(layout, output_width, output_height)
    video_chain = (
        f"[0:v:0]trim=start={start_seconds:.9f}:end={end_seconds:.9f},"
        f"setpts=PTS-STARTPTS,{video_filter}[v]"
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
        audio_chain = (
            f"[0:a:0]atrim=start={start_seconds:.9f}:end={end_seconds:.9f},"
            "asetpts=PTS-STARTPTS[a]"
        )
        command.extend(
            [
                "-filter_complex",
                f"{video_chain};{audio_chain}",
                "-map",
                "[v]",
                "-map",
                "[a]",
            ]
        )
    else:
        command.extend(["-filter_complex", video_chain, "-map", "[v]"])
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
        detail = error.stderr.strip() or "FFmpeg could not render the fallback clip"
        raise ClipRenderError(
            f"FFmpeg fallback rendering failed for {source}: {detail}"
        ) from error

    if not destination.is_file() or destination.stat().st_size == 0:
        raise ClipRenderError(f"FFmpeg did not create a rendered clip: {destination}")
    return destination


def _video_filter(layout: FallbackLayout, output_width: int, output_height: int) -> str:
    if layout == "blurred-background":
        return (
            f"split=2[background_source][foreground_source];"
            f"[background_source]scale={output_width}:{output_height}:"
            "force_original_aspect_ratio=increase,"
            f"crop={output_width}:{output_height},"
            "boxblur=luma_radius=20:luma_power=1[background];"
            f"[foreground_source]scale={output_width}:{output_height}:"
            "force_original_aspect_ratio=decrease[foreground];"
            "[background][foreground]overlay=(W-w)/2:(H-h)/2,setsar=1"
        )
    panel_height = output_height // 2
    return (
        "split=2[left_source][right_source];"
        "[left_source]crop=iw/2:ih:0:0,"
        f"scale={output_width}:{panel_height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={output_width}:{panel_height}:"
        "(ow-iw)/2:(oh-ih)/2:color=black[top_panel];"
        "[right_source]crop=iw/2:ih:iw/2:0,"
        f"scale={output_width}:{panel_height}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={output_width}:{panel_height}:"
        "(ow-iw)/2:(oh-ih)/2:color=black[bottom_panel];"
        "[top_panel][bottom_panel]vstack=inputs=2,setsar=1"
    )
