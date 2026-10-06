import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from clipper_worker.caption_styles import CaptionStyle


class CaptionStyleConfigError(ValueError):
    pass


class CaptionStyleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    version: Literal[1]
    name: str = Field(min_length=1, pattern=r"^[^,\r\n]+$")
    font_name: str = Field(min_length=1, pattern=r"^[^,\r\n]+$")
    font_size: int = Field(gt=0)
    primary_colour: str = Field(pattern=r"^&H[0-9A-Fa-f]{8}$")
    secondary_colour: str = Field(pattern=r"^&H[0-9A-Fa-f]{8}$")
    outline_colour: str = Field(pattern=r"^&H[0-9A-Fa-f]{8}$")
    back_colour: str = Field(pattern=r"^&H[0-9A-Fa-f]{8}$")
    emphasis_colour: str = Field(pattern=r"^&H[0-9A-Fa-f]{8}$")
    bold: bool
    italic: bool
    outline: int = Field(ge=0)
    shadow: int = Field(ge=0)
    alignment: int = Field(ge=1, le=9)
    margin_left: int = Field(ge=0)
    margin_right: int = Field(ge=0)
    margin_vertical: int = Field(ge=0)
    highlight_words: bool = False


def load_caption_style(path: str | Path) -> CaptionStyle:
    style_path = Path(path)
    try:
        config_json = style_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CaptionStyleConfigError(
            f"Could not read caption style config: {style_path}"
        ) from error
    return parse_caption_style(config_json, source=str(style_path))


def parse_caption_style(
    config_json: str, *, source: str = "caption style JSON"
) -> CaptionStyle:
    try:
        payload = json.loads(config_json)
    except json.JSONDecodeError as error:
        raise CaptionStyleConfigError(
            f"Invalid JSON in {source}: {error.msg}"
        ) from error
    try:
        config = CaptionStyleConfig.model_validate(payload)
    except ValidationError as error:
        raise CaptionStyleConfigError(
            f"Invalid caption style config in {source}: {error}"
        ) from error
    return CaptionStyle(**config.model_dump(exclude={"version"}))
