import math
from dataclasses import dataclass
from typing import Iterable

from clipper_worker.transcription import WordTimestamp


@dataclass(frozen=True)
class CaptionChunk:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[WordTimestamp, ...]


def build_caption_chunks(
    words: Iterable[WordTimestamp],
    *,
    max_words: int = 7,
    max_duration_seconds: float = 3.5,
    max_gap_seconds: float = 0.6,
) -> tuple[CaptionChunk, ...]:
    if max_words < 1:
        raise ValueError("Maximum caption word count must be at least one")
    if not math.isfinite(max_duration_seconds) or max_duration_seconds <= 0:
        raise ValueError("Maximum caption duration must be finite and positive")
    if not math.isfinite(max_gap_seconds) or max_gap_seconds < 0:
        raise ValueError("Maximum caption gap must be finite and nonnegative")

    ordered_words: list[WordTimestamp] = []
    for word in words:
        if (
            not math.isfinite(word.start_seconds)
            or not math.isfinite(word.end_seconds)
            or word.start_seconds < 0
            or word.end_seconds <= word.start_seconds
        ):
            raise ValueError("Caption word timestamps must be finite positive ranges")
        text = word.text.strip()
        if text:
            ordered_words.append(
                WordTimestamp(
                    start_seconds=word.start_seconds,
                    end_seconds=word.end_seconds,
                    text=text,
                    probability=word.probability,
                    speaker_id=word.speaker_id,
                )
            )
    ordered_words.sort(key=lambda word: (word.start_seconds, word.end_seconds))

    chunks: list[CaptionChunk] = []
    current_words: list[WordTimestamp] = []

    def finish_chunk() -> None:
        if not current_words:
            return
        chunk_words = tuple(current_words)
        chunks.append(
            CaptionChunk(
                start_seconds=chunk_words[0].start_seconds,
                end_seconds=chunk_words[-1].end_seconds,
                text=" ".join(word.text for word in chunk_words),
                words=chunk_words,
            )
        )
        current_words.clear()

    for word in ordered_words:
        if current_words:
            previous = current_words[-1]
            exceeds_limit = (
                len(current_words) >= max_words
                or word.end_seconds - current_words[0].start_seconds
                > max_duration_seconds
                or word.start_seconds - previous.end_seconds > max_gap_seconds
                or (
                    previous.speaker_id is not None
                    and word.speaker_id is not None
                    and previous.speaker_id != word.speaker_id
                )
            )
            if exceeds_limit:
                finish_chunk()

        current_words.append(word)
        if _ends_sentence(word.text):
            finish_chunk()

    finish_chunk()
    return tuple(chunks)


def _ends_sentence(text: str) -> bool:
    return any(character in ".!?…。！？" for character in text[-1:])
