from app.config import Settings


def test_settings_read_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CLIPPER_REDIS_URL", "redis://localhost:6380/1")
    monkeypatch.setenv("CLIPPER_HF_TOKEN", "test-token")

    settings = Settings()
    assert settings.redis_url == "redis://localhost:6380/1"
    assert settings.hf_token is not None
    assert settings.hf_token.get_secret_value() == "test-token"
