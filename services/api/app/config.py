from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CLIPPER_", case_sensitive=False)

    project_name: str = "Local AI Video Clipper API"
    database_url: str = (
        "postgresql+psycopg://clipper:clipper-dev-password@localhost:5432/clipper"
    )
    redis_url: str = "redis://localhost:6379/0"
    object_storage_endpoint_url: str = "http://localhost:9000"
    object_storage_access_key: str = "clipper"
    object_storage_secret_key: str = "clipper-dev-password"
    object_storage_bucket: str = "videos"
    whisper_model: str = "small"
    hf_token: SecretStr | None = None
