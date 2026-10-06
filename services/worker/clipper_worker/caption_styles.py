from dataclasses import dataclass, replace


@dataclass(frozen=True)
class CaptionStyle:
    name: str
    font_name: str
    font_size: int
    primary_colour: str
    secondary_colour: str
    outline_colour: str
    back_colour: str
    bold: bool
    italic: bool
    outline: int
    shadow: int
    alignment: int
    margin_left: int
    margin_right: int
    margin_vertical: int
    highlight_words: bool = False
    emphasis_colour: str = "&H0000FFFF"


DEFAULT_CAPTION_STYLE = CaptionStyle(
    name="Default",
    font_name="Arial",
    font_size=64,
    primary_colour="&H00FFFFFF",
    secondary_colour="&H0000FFFF",
    outline_colour="&H00000000",
    back_colour="&H80000000",
    bold=True,
    italic=False,
    outline=3,
    shadow=1,
    alignment=2,
    margin_left=60,
    margin_right=60,
    margin_vertical=120,
)

CAPTION_STYLE_PRESETS: dict[str, CaptionStyle] = {
    "default": DEFAULT_CAPTION_STYLE,
    "word-highlight": replace(
        DEFAULT_CAPTION_STYLE,
        name="WordHighlight",
        highlight_words=True,
    ),
    "minimal": CaptionStyle(
        name="Minimal",
        font_name="Arial",
        font_size=56,
        primary_colour="&H00FFFFFF",
        secondary_colour="&H0000FFFF",
        outline_colour="&H00000000",
        back_colour="&H80000000",
        bold=False,
        italic=False,
        outline=2,
        shadow=0,
        alignment=2,
        margin_left=60,
        margin_right=60,
        margin_vertical=120,
    ),
}
