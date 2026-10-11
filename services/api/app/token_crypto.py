import json
from typing import Any

from app.config import Settings


def _fernet(settings: Settings | None = None):  # type: ignore[return]
    try:
        from cryptography.fernet import Fernet
    except ImportError as error:
        raise RuntimeError(
            "cryptography package is required for token encryption"
        ) from error
    config = settings or Settings()
    if config.token_encryption_key is None:
        raise RuntimeError(
            "CLIPPER_TOKEN_ENCRYPTION_KEY must be set to use platform publishing. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(config.token_encryption_key.get_secret_value().encode())


def encrypt_token(data: dict[str, Any], settings: Settings | None = None) -> str:
    return _fernet(settings).encrypt(json.dumps(data).encode()).decode()


def decrypt_token(encrypted: str, settings: Settings | None = None) -> dict[str, Any]:
    raw = _fernet(settings).decrypt(encrypted.encode())
    return json.loads(raw)
