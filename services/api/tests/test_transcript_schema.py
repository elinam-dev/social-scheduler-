import pytest
from pydantic import ValidationError

from app.schemas.transcript import TranscriptSchema


def test_transcript_schema_accepts_word_timestamps_and_speakers() -> None:
    transcript = TranscriptSchema.model_validate(
        {
            "language": "en",
            "language_probability": 0.98,
            "duration_seconds": 10,
            "segments": [
                {
                    "start_seconds": 1,
                    "end_seconds": 3,
                    "text": "Hello there.",
                    "words": [
                        {
                            "start_seconds": 1,
                            "end_seconds": 1.5,
                            "text": "Hello",
                            "probability": 0.9,
                            "speaker_id": "SPEAKER_00",
                        },
                        {
                            "start_seconds": 1.6,
                            "end_seconds": 2,
                            "text": "there.",
                            "probability": None,
                            "speaker_id": None,
                        },
                    ],
                }
            ],
        }
    )

    assert transcript.segments[0].words[0].speaker_id == "SPEAKER_00"
    assert (
        transcript.model_dump(mode="json")["segments"][0]["words"][1]["probability"]
        is None
    )


@pytest.mark.parametrize(
    "payload",
    [
        {
            "language": "en",
            "language_probability": 1.1,
            "duration_seconds": 10,
            "segments": [],
        },
        {
            "language": "en",
            "language_probability": 0.9,
            "duration_seconds": 10,
            "segments": [
                {
                    "start_seconds": 2,
                    "end_seconds": 1,
                    "text": "Invalid segment",
                    "words": [],
                }
            ],
        },
        {
            "language": "en",
            "language_probability": 0.9,
            "duration_seconds": 10,
            "segments": [
                {
                    "start_seconds": 1,
                    "end_seconds": 2,
                    "text": "Invalid word",
                    "words": [
                        {
                            "start_seconds": 1,
                            "end_seconds": 2,
                            "text": "Invalid",
                            "probability": -0.1,
                        }
                    ],
                }
            ],
        },
    ],
)
def test_transcript_schema_rejects_invalid_ranges(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        TranscriptSchema.model_validate(payload)
