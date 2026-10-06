import json
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

import pytest
from pydantic import SecretStr

from app.config import Settings
from clipper_worker import llm
from clipper_worker.llm import (
    LLMError,
    OllamaClient,
    OpenAICompatibleClient,
    create_llm_client,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_ollama_client_sends_chat_and_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse({"message": {"content": '{"ok": true}'}})

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)

    result = OllamaClient("http://ollama:11434/", "llama3.2").generate(
        "Analyze this clip",
        system_prompt="Return JSON",
        temperature=0.4,
        json_mode=True,
        timeout_seconds=45,
    )

    request = captured["request"]
    assert isinstance(request, Request)
    assert request.full_url == "http://ollama:11434/api/chat"
    assert captured["timeout"] == 45
    assert json.loads(request.data or b"{}") == {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": "Return JSON"},
            {"role": "user", "content": "Analyze this clip"},
        ],
        "stream": False,
        "options": {"temperature": 0.4},
        "format": "json",
    }
    assert result == '{"ok": true}'


def test_openai_compatible_client_sends_auth_and_json_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_request: Request | None = None

    def fake_urlopen(request: Request, timeout: float) -> FakeResponse:
        nonlocal captured_request
        captured_request = request
        return FakeResponse(
            {"choices": [{"message": {"content": "Candidate response"}}]}
        )

    monkeypatch.setattr(llm, "urlopen", fake_urlopen)

    result = OpenAICompatibleClient(
        "https://example.test/v1/",
        "test-model",
        SecretStr("test-api-key"),
    ).generate("Analyze", json_mode=True)

    assert captured_request is not None
    assert captured_request.full_url == "https://example.test/v1/chat/completions"
    assert captured_request.get_header("Authorization") == "Bearer test-api-key"
    assert json.loads(captured_request.data or b"{}")["response_format"] == {
        "type": "json_object"
    }
    assert result == "Candidate response"


def test_create_llm_client_uses_configured_provider() -> None:
    ollama = create_llm_client(Settings(_env_file=None))
    api = create_llm_client(
        Settings(
            _env_file=None,
            llm_provider="openai-compatible",
            llm_model="local-model",
            llm_api_base_url="http://localhost:8080/v1",
        )
    )

    assert isinstance(ollama, OllamaClient)
    assert isinstance(api, OpenAICompatibleClient)


def test_llm_client_reports_backend_http_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_urlopen(request: Request, timeout: float) -> None:
        raise HTTPError(
            request.full_url,
            401,
            "Unauthorized",
            {},
            BytesIO(b"invalid API key"),
        )

    monkeypatch.setattr(llm, "urlopen", failed_urlopen)

    with pytest.raises(LLMError, match="HTTP 401: invalid API key"):
        OpenAICompatibleClient("https://example.test/v1", "test-model").generate(
            "Analyze"
        )


@pytest.mark.parametrize(
    ("prompt", "temperature", "timeout"),
    [
        (" ", 0.2, 30),
        ("prompt", -0.1, 30),
        ("prompt", 2.1, 30),
        ("prompt", 0.2, 0),
    ],
)
def test_llm_client_rejects_invalid_request_parameters(
    prompt: str, temperature: float, timeout: float
) -> None:
    with pytest.raises(ValueError):
        OllamaClient("http://ollama:11434", "model").generate(
            prompt,
            temperature=temperature,
            timeout_seconds=timeout,
        )
