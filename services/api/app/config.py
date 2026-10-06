from typing import Literal

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
    llm_provider: Literal["ollama", "openai-compatible"] = "ollama"
    llm_model: str = "llama3.2"
    ollama_base_url: str = "http://ollama:11434"
    llm_api_base_url: str = "https://api.openai.com/v1"
    llm_api_key: SecretStr | None = None
