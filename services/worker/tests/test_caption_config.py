import json
from pathlib import Path

import pytest

from clipper_worker.caption_config import (
    CaptionStyleConfigError,
    load_caption_style,
    parse_caption_style,
)
from clipper_worker.caption_styles import CAPTION_STYLE_PRESETS


def test_load_caption_style_reads_versioned_json_template() -> None:
    template_path = (
        Path(__file__).parents[1] / "caption-templates" / "word-highlight.json"
    )

    style = load_caption_style(template_path)

    assert style == CAPTION_STYLE_PRESETS["word-highlight"]


def test_parse_caption_style_rejects_malformed_json() -> None:
    with pytest.raises(CaptionStyleConfigError, match="Invalid JSON"):
        parse_caption_style("{")


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"version": 2}, "version"),
        ({"extra_option": True}, "extra_option"),
        ({"font_size": 0}, "font_size"),
        ({"alignment": 10}, "alignment"),
        ({"primary_colour": "red"}, "primary_colour"),
        ({"name": "Unsafe,Style"}, "name"),
        ({"highlight_words": "yes"}, "highlight_words"),
    ],
)
def test_parse_caption_style_rejects_invalid_config(
    updates: dict[str, object], message: str
) -> None:
    config = {
        "version": 1,
        "name": "TestStyle",
        "font_name": "Arial",
        "font_size": 64,
        "primary_colour": "&H00FFFFFF",
        "secondary_colour": "&H0000FFFF",
        "outline_colour": "&H00000000",
        "back_colour": "&H80000000",
        "emphasis_colour": "&H0000FFFF",
        "bold": True,
        "italic": False,
        "outline": 3,
        "shadow": 1,
        "alignment": 2,
        "margin_left": 60,
        "margin_right": 60,
        "margin_vertical": 120,
        "highlight_words": False,
    }
    config.update(updates)

    with pytest.raises(CaptionStyleConfigError, match=message):
        parse_caption_style(json.dumps(config))


def test_load_caption_style_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CaptionStyleConfigError, match="Could not read"):
        load_caption_style(tmp_path / "missing.json")
