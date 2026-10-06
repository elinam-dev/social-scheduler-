from pathlib import Path

import pytest

from clipper_worker.subtitle_filter import build_ass_filter


def test_build_ass_filter_quotes_subtitle_path(tmp_path: Path) -> None:
    subtitle_path = tmp_path / "captions with spaces.ass"
    subtitle_path.write_text("[Events]\n", encoding="utf-8")

    result = build_ass_filter(subtitle_path)

    assert result.startswith("subtitles=filename='")
    assert result.endswith("'")
    assert "captions with spaces.ass" in result


def test_build_ass_filter_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="does not exist"):
        build_ass_filter(tmp_path / "missing.ass")


def test_build_ass_filter_requires_ass_extension(tmp_path: Path) -> None:
    subtitle_path = tmp_path / "captions.srt"
    subtitle_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="\\.ass extension"):
        build_ass_filter(subtitle_path)
