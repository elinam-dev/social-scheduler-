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

    # Token encryption — generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: SecretStr | None = None

    # Public base URL used to build OAuth redirect URIs (e.g. http://localhost:8001)
    public_api_url: str = "http://localhost:8001"

    # YouTube OAuth 2.0 (Google Cloud Console → APIs & Services → Credentials)
    youtube_client_id: str = ""
    youtube_client_secret: SecretStr | None = None

    # TikTok OAuth 2.0 (developers.tiktok.com → Manage Apps)
    tiktok_client_id: str = ""
    tiktok_client_secret: SecretStr | None = None

    # Instagram / Meta OAuth 2.0 (developers.facebook.com → My Apps)
    instagram_client_id: str = ""
    instagram_client_secret: SecretStr | None = None
