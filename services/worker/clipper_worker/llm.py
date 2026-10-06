import json
import math
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import SecretStr

from app.config import Settings


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        timeout_seconds: float = 120,
    ) -> str: ...


class OllamaClient:
    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        timeout_seconds: float = 120,
    ) -> str:
        _validate_request(prompt, temperature, timeout_seconds)
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _messages(prompt, system_prompt),
            "stream": False,
            "options": {"temperature": temperature},
        }
        if json_mode:
            payload["format"] = "json"
        response = _post_json(
            f"{self.base_url}/api/chat",
            payload,
            timeout_seconds=timeout_seconds,
        )
        message = response.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LLMError("Ollama returned an invalid chat response")
        return message["content"]


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: SecretStr | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    def generate(
        self,
        prompt: str,
        *,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        json_mode: bool = False,
        timeout_seconds: float = 120,
    ) -> str:
        _validate_request(prompt, temperature, timeout_seconds)
        payload: dict[str, object] = {
            "model": self.model,
            "messages": _messages(prompt, system_prompt),
            "temperature": temperature,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = _post_json(
            f"{self.base_url}/chat/completions",
            payload,
            api_key=self.api_key,
            timeout_seconds=timeout_seconds,
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMError("OpenAI-compatible backend returned no choices")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise LLMError(
                "OpenAI-compatible backend returned an invalid chat response"
            )
        return message["content"]


def create_llm_client(settings: Settings | None = None) -> LLMClient:
    config = settings or Settings()
    if config.llm_provider == "ollama":
        return OllamaClient(config.ollama_base_url, config.llm_model)
    if config.llm_provider == "openai-compatible":
        return OpenAICompatibleClient(
            config.llm_api_base_url,
            config.llm_model,
            config.llm_api_key,
        )
    raise LLMError(f"Unsupported LLM provider: {config.llm_provider}")


def _messages(prompt: str, system_prompt: str | None) -> list[dict[str, str]]:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    return messages


def _validate_request(prompt: str, temperature: float, timeout_seconds: float) -> None:
    if not prompt.strip():
        raise ValueError("LLM prompt must not be blank")
    if not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError("LLM temperature must be finite and between 0 and 2")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("LLM timeout must be finite and positive")


def _post_json(
    url: str,
    payload: dict[str, object],
    *,
    timeout_seconds: float,
    api_key: SecretStr | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key is not None:
        secret = api_key.get_secret_value()
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace").strip()
        raise LLMError(
            f"LLM request failed with HTTP {error.code}: {detail or error.reason}"
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise LLMError(f"LLM request failed: {error}") from error
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise LLMError("LLM backend returned invalid JSON") from error
    if not isinstance(result, dict):
        raise LLMError("LLM backend returned a non-object JSON response")
    return result
