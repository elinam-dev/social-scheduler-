import math
from collections.abc import Iterable

from clipper_worker.captions import CaptionChunk


def build_ass_subtitles(
    chunks: Iterable[CaptionChunk],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    clip_start_seconds: float = 0,
    clip_end_seconds: float | None = None,
) -> str:
    if play_res_x <= 0 or play_res_y <= 0:
        raise ValueError("ASS play resolution must be positive")
    if not math.isfinite(clip_start_seconds) or clip_start_seconds < 0:
        raise ValueError("Clip start time must be finite and nonnegative")
    if clip_end_seconds is not None and (
        not math.isfinite(clip_end_seconds) or clip_end_seconds <= clip_start_seconds
    ):
        raise ValueError("Clip end time must be finite and after its start")

    events: list[str] = []
    for chunk in chunks:
        if (
            not math.isfinite(chunk.start_seconds)
            or not math.isfinite(chunk.end_seconds)
            or chunk.start_seconds < 0
            or chunk.end_seconds <= chunk.start_seconds
        ):
            raise ValueError("Caption chunks must have finite positive time ranges")
        start = max(chunk.start_seconds, clip_start_seconds)
        end = (
            min(chunk.end_seconds, clip_end_seconds)
            if clip_end_seconds is not None
            else chunk.end_seconds
        )
        if end <= start:
            continue
        text = _escape_ass_text(chunk.text)
        events.append(
            f"Dialogue: 0,{_format_ass_time(start - clip_start_seconds)},"
            f"{_format_ass_time(end - clip_start_seconds)},Default,,0,0,0,,{text}"
        )

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        "Style: Default,Arial,64,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
        "-1,0,0,0,100,100,0,0,1,3,1,2,60,60,120,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
    return header + "\n".join(events) + ("\n" if events else "")


def _format_ass_time(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    total_seconds, fraction = divmod(centiseconds, 100)
    total_minutes, second = divmod(total_seconds, 60)
    hour, minute = divmod(total_minutes, 60)
    return f"{hour}:{minute:02d}:{second:02d}.{fraction:02d}"


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\r\n", r"\N")
        .replace("\n", r"\N")
        .replace("\r", r"\N")
    )
