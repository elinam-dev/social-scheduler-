from app.config import Settings


def test_settings_read_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CLIPPER_REDIS_URL", "redis://localhost:6380/1")
    monkeypatch.setenv("CLIPPER_HF_TOKEN", "test-token")
    monkeypatch.setenv("CLIPPER_LLM_PROVIDER", "openai-compatible")
    monkeypatch.setenv("CLIPPER_LLM_API_KEY", "test-api-key")

    settings = Settings()
    assert settings.redis_url == "redis://localhost:6380/1"
    assert settings.hf_token is not None
    assert settings.hf_token.get_secret_value() == "test-token"
    assert settings.llm_provider == "openai-compatible"
    assert settings.llm_api_key is not None
    assert settings.llm_api_key.get_secret_value() == "test-api-key"
