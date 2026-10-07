from __future__ import annotations

import uuid
from datetime import datetime
from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator, model_validator


class VideoUrlIngest(BaseModel):
    url: HttpUrl
    rights_confirmed: bool

    @field_validator("url")
    @classmethod
    def validate_public_http_url(cls, value: HttpUrl) -> HttpUrl:
        if value.username or value.password:
            raise ValueError("URL credentials are not allowed")
        hostname = urlsplit(str(value)).hostname
        if hostname is None:
            raise ValueError("URL must include a host")
        hostname = hostname.lower().rstrip(".")
        if hostname == "localhost" or hostname.endswith(
            (".localhost", ".local", ".internal")
        ):
            raise ValueError("URL host must be publicly reachable")
        try:
            address = ip_address(hostname)
        except ValueError:
            return value
        if not address.is_global:
            raise ValueError("URL host must be publicly reachable")
        return value

    @model_validator(mode="after")
    def require_rights_confirmation(self) -> VideoUrlIngest:
        if not self.rights_confirmed:
            raise ValueError(
                "Confirm that you own or have permission to use this video"
            )
        return self


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    original_filename: str
    content_type: str | None
    size_bytes: int
    status: str
    created_at: datetime
