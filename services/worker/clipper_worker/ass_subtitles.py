import math
import re
from collections.abc import Iterable, Mapping

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
    emphasized_keywords: Iterable[str] = (),
    emoji_by_keyword: Mapping[str, str] | None = None,
    hook_text: str | None = None,
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
    normalized_keywords = {
        _normalize_keyword(keyword) for keyword in emphasized_keywords
    }
    normalized_keywords.discard("")
    normalized_emoji = (
        {
            _normalize_keyword(keyword): emoji
            for keyword, emoji in emoji_by_keyword.items()
        }
        if emoji_by_keyword is not None
        else {}
    )
    if any(not keyword for keyword in normalized_emoji):
        raise ValueError("Emoji mapping keywords must not be blank")
    if any(not emoji.strip() for emoji in normalized_emoji.values()):
        raise ValueError("Emoji mapping values must not be blank")

    events: list[str] = []
    if hook_text is not None:
        normalized_hook = hook_text.strip()
        if normalized_hook:
            if len(normalized_hook) > 120:
                raise ValueError("Hook text must not exceed 120 characters")
            overlay_duration = min(
                2.5,
                (
                    clip_end_seconds - clip_start_seconds
                    if clip_end_seconds is not None
                    else 2.5
                ),
            )
            overlay_font_size = max(32, round(style.font_size * 0.75))
            overlay_position = (play_res_x // 2, max(1, round(play_res_y * 0.08)))
            overlay_text = _escape_ass_text(normalized_hook)
            events.append(
                f"Dialogue: 1,0:00:00.00,{_format_ass_time(overlay_duration)},"
                f"{style.name},,0,0,0,,"
                f"{{\\q0\\an8\\pos({overlay_position[0]},{overlay_position[1]})"
                f"\\fs{overlay_font_size}\\b1\\bord3\\shad2}}{overlay_text}"
            )

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
            text = _karaoke_text(
                visible_words,
                clip_start_seconds,
                clip_end_seconds,
                style,
                normalized_keywords,
                normalized_emoji,
            )
        else:
            text = " ".join(
                _format_word(word.text, normalized_keywords, normalized_emoji, style)
                for word in visible_words
            )
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
    style: CaptionStyle,
    emphasized_keywords: set[str],
    emoji_by_keyword: Mapping[str, str],
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
        parts.append(
            f"{{\\k{duration}}}"
            f"{_format_word(word.text, emphasized_keywords, emoji_by_keyword, style)}"
        )
    return " ".join(parts)


def _format_word(
    text: str,
    emphasized_keywords: set[str],
    emoji_by_keyword: Mapping[str, str],
    style: CaptionStyle,
) -> str:
    escaped = _escape_ass_text(text)
    keyword = _normalize_keyword(text)
    if keyword not in emphasized_keywords and keyword not in emoji_by_keyword:
        return escaped

    emphasis = (
        f"{{\\c{style.emphasis_colour}&}}{escaped}{{\\c}}"
        if keyword in emphasized_keywords
        else escaped
    )
    emoji = emoji_by_keyword.get(keyword)
    if emoji is not None:
        emphasis += f" {_escape_ass_text(emoji)}"
    return emphasis


def _normalize_keyword(text: str) -> str:
    return re.sub(r"^[^\w]+|[^\w]+$", "", text.strip(), flags=re.UNICODE).casefold()


def _validate_style(style: CaptionStyle) -> None:
    text_fields = (
        style.name,
        style.font_name,
        style.primary_colour,
        style.secondary_colour,
        style.outline_colour,
        style.back_colour,
        style.emphasis_colour,
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
