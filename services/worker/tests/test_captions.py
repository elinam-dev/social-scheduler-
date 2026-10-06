import pytest

from clipper_worker.captions import CaptionChunk, build_caption_chunks
from clipper_worker.transcription import WordTimestamp


def _word(
    start: float,
    text: str,
    *,
    end: float | None = None,
    speaker: str | None = None,
) -> WordTimestamp:
    return WordTimestamp(
        start_seconds=start,
        end_seconds=end if end is not None else start + 0.25,
        text=text,
        probability=0.9,
        speaker_id=speaker,
    )


def test_build_caption_chunks_preserves_timestamps_and_sentence_boundaries() -> None:
    words = [
        _word(0, "This"),
        _word(0.3, "is"),
        _word(0.6, "one."),
        _word(0.9, "Here"),
        _word(1.2, "comes"),
        _word(1.5, "two!"),
    ]

    chunks = build_caption_chunks(words)

    assert chunks == (
        CaptionChunk(0, 0.85, "This is one.", tuple(words[:3])),
        CaptionChunk(0.9, 1.75, "Here comes two!", tuple(words[3:])),
    )


def test_build_caption_chunks_respects_word_count_duration_and_pause() -> None:
    chunks = build_caption_chunks(
        [_word(0, "one"), _word(0.3, "two"), _word(0.6, "three"), _word(3, "four")],
        max_words=2,
        max_duration_seconds=1,
        max_gap_seconds=0.5,
    )

    assert [chunk.text for chunk in chunks] == ["one two", "three", "four"]


def test_build_caption_chunks_splits_when_known_speaker_changes() -> None:
    chunks = build_caption_chunks(
        [
            _word(0, "First", speaker="speaker_1"),
            _word(0.3, "Second", speaker="speaker_2"),
        ]
    )

    assert [chunk.text for chunk in chunks] == ["First", "Second"]


def test_build_caption_chunks_sorts_words_and_skips_blank_text() -> None:
    chunks = build_caption_chunks(
        [_word(0.4, "world"), _word(0, "hello"), _word(0.2, "   ")]
    )

    assert len(chunks) == 1
    assert chunks[0].text == "hello world"
    assert chunks[0].start_seconds == 0
    assert chunks[0].end_seconds == 0.65


@pytest.mark.parametrize(
    ("words", "message"),
    [
        ([_word(float("nan"), "bad")], "finite positive ranges"),
        ([_word(1, "bad", end=1)], "finite positive ranges"),
        ([_word(-1, "bad")], "finite positive ranges"),
    ],
)
def test_build_caption_chunks_rejects_invalid_word_timestamps(
    words: list[WordTimestamp], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_caption_chunks(words)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"max_words": 0}, "word count"),
        ({"max_duration_seconds": float("inf")}, "duration"),
        ({"max_duration_seconds": 0}, "duration"),
        ({"max_gap_seconds": -1}, "gap"),
        ({"max_gap_seconds": float("nan")}, "gap"),
    ],
)
def test_build_caption_chunks_rejects_invalid_limits(
    options: dict[str, int | float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_caption_chunks([], **options)
