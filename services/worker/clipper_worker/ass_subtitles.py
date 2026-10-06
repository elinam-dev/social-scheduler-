import math
from collections.abc import Iterable

from clipper_worker.caption_styles import DEFAULT_CAPTION_STYLE, CaptionStyle
from clipper_worker.captions import CaptionChunk
from clipper_worker.transcription import WordTimestamp


def build_ass_subtitles(
    chunks: Iterable[CaptionChunk],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    clip_start_seconds: float = 0,
    clip_end_seconds: float | None = None,
    style: CaptionStyle = DEFAULT_CAPTION_STYLE,
) -> str:
    if play_res_x <= 0 or play_res_y <= 0:
        raise ValueError("ASS play resolution must be positive")
    if not math.isfinite(clip_start_seconds) or clip_start_seconds < 0:
        raise ValueError("Clip start time must be finite and nonnegative")
    if clip_end_seconds is not None and (
        not math.isfinite(clip_end_seconds) or clip_end_seconds <= clip_start_seconds
    ):
        raise ValueError("Clip end time must be finite and after its start")
    _validate_style(style)

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
        visible_words = tuple(
            word
            for word in chunk.words
            if word.end_seconds > clip_start_seconds
            and (clip_end_seconds is None or word.start_seconds < clip_end_seconds)
        )
        if not visible_words:
            continue
        if style.highlight_words:
            text = _karaoke_text(visible_words, clip_start_seconds, clip_end_seconds)
        else:
            text = " ".join(_escape_ass_text(word.text) for word in visible_words)
        event_start = max(start, visible_words[0].start_seconds) - clip_start_seconds
        events.append(
            f"Dialogue: 0,{_format_ass_time(event_start)},"
            f"{_format_ass_time(end - clip_start_seconds)},{style.name},,"
            f"0,0,0,,{text}"
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
        f"Style: {style.name},{style.font_name},{style.font_size},"
        f"{style.primary_colour},{style.secondary_colour},{style.outline_colour},"
        f"{style.back_colour},{-1 if style.bold else 0},"
        f"{-1 if style.italic else 0},0,0,100,100,0,0,1,{style.outline},"
        f"{style.shadow},{style.alignment},{style.margin_left},"
        f"{style.margin_right},{style.margin_vertical},1\n"
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


def _karaoke_text(
    words: tuple[WordTimestamp, ...],
    clip_start_seconds: float,
    clip_end_seconds: float | None,
) -> str:
    parts: list[str] = []
    for index, word in enumerate(words):
        start = max(word.start_seconds, clip_start_seconds)
        next_start = (
            words[index + 1].start_seconds
            if index + 1 < len(words)
            else word.end_seconds
        )
        end = (
            min(next_start, word.end_seconds) if index + 1 == len(words) else next_start
        )
        if clip_end_seconds is not None:
            end = min(end, clip_end_seconds)
        duration = max(0, round((end - start) * 100))
        parts.append(f"{{\\k{duration}}}{_escape_ass_text(word.text)}")
    return " ".join(parts)


def _validate_style(style: CaptionStyle) -> None:
    text_fields = (
        style.name,
        style.font_name,
        style.primary_colour,
        style.secondary_colour,
        style.outline_colour,
        style.back_colour,
    )
    if any(
        not value or any(character in value for character in ",\r\n")
        for value in text_fields
    ):
        raise ValueError(
            "ASS style text fields must be nonempty and exclude commas or newlines"
        )
    if style.font_size <= 0:
        raise ValueError("ASS style font size must be positive")
    if not 1 <= style.alignment <= 9:
        raise ValueError("ASS style alignment must be between 1 and 9")
    if (
        min(
            style.outline,
            style.shadow,
            style.margin_left,
            style.margin_right,
            style.margin_vertical,
        )
        < 0
    ):
        raise ValueError("ASS style outline, shadow, and margins must be nonnegative")
