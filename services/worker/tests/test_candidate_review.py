import json

import pytest

from clipper_worker.candidate_review import (
    CandidateEvaluation,
    StructuredOutputError,
    review_candidate,
)
from clipper_worker.candidates import CandidateWindow
from clipper_worker.llm import LLMError

VALID_EVALUATION = {
    "hook_strength": 0.8,
    "standalone_coherence": 0.9,
    "payoff": 0.7,
    "pacing": 0.85,
    "standalone": True,
    "rationale": "The opening poses a clear question and the excerpt answers it.",
}


class FakeLLMClient:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def generate(self, prompt: str, **kwargs: object) -> str:
        self.calls.append({"prompt": prompt, **kwargs})
        if not self.responses:
            raise AssertionError("No fake response available")
        return self.responses.pop(0)


def _candidate() -> CandidateWindow:
    return CandidateWindow(
        start_seconds=10,
        end_seconds=45,
        text="Here's the question. This is the answer.",
        first_sentence_index=0,
        end_sentence_index=2,
    )


def test_review_candidate_validates_structured_json() -> None:
    client = FakeLLMClient([json.dumps(VALID_EVALUATION)])

    result = review_candidate(_candidate(), client)

    assert isinstance(result, CandidateEvaluation)
    assert result.hook_strength == 0.8
    assert result.standalone is True
    assert len(client.calls) == 1
    assert client.calls[0]["json_mode"] is True
    assert client.calls[0]["temperature"] == 0
    assert "hook_strength" in str(client.calls[0]["prompt"])


def test_review_candidate_retries_invalid_output_with_schema_feedback() -> None:
    invalid = json.dumps({**VALID_EVALUATION, "hook_strength": 2})
    client = FakeLLMClient([invalid, json.dumps(VALID_EVALUATION)])

    result = review_candidate(_candidate(), client)

    assert result.payoff == 0.7
    assert len(client.calls) == 2
    retry_prompt = str(client.calls[1]["prompt"])
    assert "did not validate" in retry_prompt
    assert "hook_strength" in retry_prompt


def test_review_candidate_exhausts_validation_retries_explicitly() -> None:
    client = FakeLLMClient(['{"hook_strength": 0.5}', "not JSON"])

    with pytest.raises(StructuredOutputError, match="after 2 attempts"):
        review_candidate(_candidate(), client, max_attempts=2)

    assert len(client.calls) == 2


def test_review_candidate_does_not_retry_backend_failures() -> None:
    class FailedLLMClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, _prompt: str, **_kwargs: object) -> str:
            self.calls += 1
            raise LLMError("backend unavailable")

    client = FailedLLMClient()

    with pytest.raises(LLMError, match="backend unavailable"):
        review_candidate(_candidate(), client)

    assert client.calls == 1


def test_review_candidate_requires_positive_attempt_limit() -> None:
    client = FakeLLMClient([])

    with pytest.raises(ValueError, match="attempts must be positive"):
        review_candidate(_candidate(), client, max_attempts=0)

    assert client.calls == []
