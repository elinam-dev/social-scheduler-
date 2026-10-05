from app.config import Settings


def test_settings_read_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("CLIPPER_REDIS_URL", "redis://localhost:6380/1")

    assert Settings().redis_url == "redis://localhost:6380/1"
