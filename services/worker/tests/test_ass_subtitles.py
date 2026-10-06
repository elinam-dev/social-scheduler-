from dataclasses import replace

import pytest

from clipper_worker.ass_subtitles import build_ass_subtitles
from clipper_worker.caption_styles import CAPTION_STYLE_PRESETS
from clipper_worker.captions import CaptionChunk
from clipper_worker.transcription import WordTimestamp


def _chunk(start: float, end: float, text: str) -> CaptionChunk:
    words = (WordTimestamp(start, end, text, 0.9),)
    return CaptionChunk(start, end, text, words)


def test_build_ass_subtitles_writes_header_and_timed_dialogue() -> None:
    ass = build_ass_subtitles([_chunk(1.234, 2.345, "Hello, world!")])

    assert "[Script Info]" in ass
    assert "PlayResX: 1080\nPlayResY: 1920" in ass
    assert "[V4+ Styles]" in ass
    assert "[Events]" in ass
    assert "Dialogue: 0,0:00:01.23,0:00:02.35,Default,,0,0,0,,Hello, world!" in ass


def test_build_ass_subtitles_escapes_ass_controls_and_newlines() -> None:
    ass = build_ass_subtitles([_chunk(0, 1, "Keep {this}\\\\ safe\nNext")])

    expected_text = r"Keep \{this\}" + "\\" * 4 + r" safe\NNext"
    assert expected_text in ass


def test_build_ass_subtitles_highlights_words_with_timestamped_karaoke() -> None:
    words = (
        WordTimestamp(0, 0.3, "First", 0.9),
        WordTimestamp(0.4, 0.7, "second!", 0.9),
    )
    chunk = CaptionChunk(0, 0.7, "First second!", words)

    ass = build_ass_subtitles([chunk], style=CAPTION_STYLE_PRESETS["word-highlight"])

    assert "Style: WordHighlight," in ass
    assert (
        r"Dialogue: 0,0:00:00.00,0:00:00.70,WordHighlight,,0,0,0,,"
        r"{\k40}First {\k30}second!"
    ) in ass


def test_build_ass_subtitles_truncates_karaoke_at_clip_boundaries() -> None:
    words = (
        WordTimestamp(0, 0.3, "First", 0.9),
        WordTimestamp(0.4, 0.7, "second", 0.9),
    )
    chunk = CaptionChunk(0, 0.7, "First second", words)

    ass = build_ass_subtitles(
        [chunk],
        style=CAPTION_STYLE_PRESETS["word-highlight"],
        clip_start_seconds=0.1,
        clip_end_seconds=0.6,
    )

    assert (
        r"Dialogue: 0,0:00:00.00,0:00:00.50,WordHighlight,,0,0,0,,"
        r"{\k30}First {\k20}second"
    ) in ass


def test_build_ass_subtitles_emphasizes_keywords_case_insensitively() -> None:
    words = (
        WordTimestamp(0, 0.2, "This", 0.9),
        WordTimestamp(0.2, 0.4, "is", 0.9),
        WordTimestamp(0.4, 0.8, "huge!", 0.9),
    )
    ass = build_ass_subtitles(
        [CaptionChunk(0, 0.8, "This is huge!", words)],
        emphasized_keywords=["huge"],
    )

    assert r"This is {\c&H0000FFFF&}huge!{\c}" in ass


def test_build_ass_subtitles_adds_only_caller_mapped_emoji() -> None:
    words = (
        WordTimestamp(0, 0.4, "Great,", 0.9),
        WordTimestamp(0.5, 0.9, "work!", 0.9),
    )
    ass = build_ass_subtitles(
        [CaptionChunk(0, 0.9, "Great, work!", words)],
        emoji_by_keyword={"great": "🔥"},
    )

    assert "Great, 🔥 work!" in ass
    assert r"{\c&H0000FFFF&}" not in ass


def test_build_ass_subtitles_combines_keyword_emphasis_and_karaoke() -> None:
    words = (WordTimestamp(0, 0.5, "Amazing!", 0.9),)
    chunk = CaptionChunk(0, 0.5, "Amazing!", words)

    ass = build_ass_subtitles(
        [chunk],
        style=CAPTION_STYLE_PRESETS["word-highlight"],
        emphasized_keywords=["amazing"],
    )

    assert r"{\k50}{\c&H0000FFFF&}Amazing!{\c}" in ass


@pytest.mark.parametrize(
    ("keywords", "emoji", "message"),
    [
        ((), {" ": "🔥"}, "keywords must not be blank"),
        ((), {"great": " "}, "values must not be blank"),
    ],
)
def test_build_ass_subtitles_rejects_invalid_emoji_mapping(
    keywords: tuple[str, ...], emoji: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_ass_subtitles([], emphasized_keywords=keywords, emoji_by_keyword=emoji)


def test_build_ass_subtitles_rejects_unsafe_style_fields() -> None:
    unsafe_style = replace(CAPTION_STYLE_PRESETS["default"], font_name="Arial,Other")

    with pytest.raises(ValueError, match="exclude commas"):
        build_ass_subtitles([], style=unsafe_style)


def test_build_ass_subtitles_rebases_and_clips_caption_times() -> None:
    ass = build_ass_subtitles(
        [_chunk(1, 3, "partly visible"), _chunk(4, 5, "outside")],
        clip_start_seconds=2,
        clip_end_seconds=4,
        play_res_x=1080,
        play_res_y=1920,
    )

    assert "Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,partly visible" in ass
    assert "outside" not in ass


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"play_res_x": 0}, "resolution"),
        ({"clip_start_seconds": -1}, "start time"),
        ({"clip_start_seconds": float("nan")}, "start time"),
        ({"clip_end_seconds": 1, "clip_start_seconds": 1}, "after its start"),
    ],
)
def test_build_ass_subtitles_rejects_invalid_options(
    kwargs: dict[str, int | float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_ass_subtitles([], **kwargs)


def test_build_ass_subtitles_rejects_invalid_caption_range() -> None:
    with pytest.raises(ValueError, match="finite positive time ranges"):
        build_ass_subtitles([_chunk(2, 1, "bad")])


def test_build_ass_subtitles_returns_valid_empty_events_section() -> None:
    ass = build_ass_subtitles([])

    assert ass.endswith(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n"
    )
