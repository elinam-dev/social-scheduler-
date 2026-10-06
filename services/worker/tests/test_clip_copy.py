import json

import pytest

from clipper_worker.candidate_review import StructuredOutputError
from clipper_worker.candidates import CandidateWindow
from clipper_worker.clip_copy import ClipCopy, generate_clip_copy


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate(self, prompt: str, **kwargs: object) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        return self.responses.pop(0)


def _candidate(text: str = "How do you learn from mistakes?") -> CandidateWindow:
    return CandidateWindow(0, 30, text, 0, 1)


def test_generate_clip_copy_returns_validated_title_and_hook() -> None:
    client = FakeLLMClient(
        [
            json.dumps(
                {"title": "Learn from Mistakes", "hook_text": "What happens next?"}
            )
        ]
    )

    result = generate_clip_copy(_candidate(), client)

    assert result == ClipCopy(
        title="Learn from Mistakes",
        hook_text="What happens next?",
    )
    assert client.calls[0]["json_mode"] is True
    assert "title" in str(client.calls[0]["prompt"])
    assert "How do you learn from mistakes?" in str(client.calls[0]["prompt"])


def test_generate_clip_copy_retries_overlong_text() -> None:
    client = FakeLLMClient(
        [
            json.dumps({"title": "T" * 81, "hook_text": "A concise hook"}),
            json.dumps({"title": "A better title", "hook_text": "A concise hook"}),
        ]
    )

    result = generate_clip_copy(_candidate(), client)

    assert result.title == "A better title"
    assert len(client.calls) == 2
    assert "did not validate" in str(client.calls[1]["prompt"])


def test_generate_clip_copy_surfaces_repeated_schema_failures() -> None:
    client = FakeLLMClient(['{"title": "Only a title"}'])

    with pytest.raises(StructuredOutputError, match="after 1 attempts"):
        generate_clip_copy(_candidate(), client, max_attempts=1)


def test_clip_copy_trims_text_and_rejects_blank_values() -> None:
    assert ClipCopy(title="  A title  ", hook_text="  A hook  ").title == "A title"
    with pytest.raises(ValueError):
        ClipCopy(title="   ", hook_text="A hook")
