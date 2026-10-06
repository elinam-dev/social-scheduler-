from pathlib import Path

import pytest

from clipper_worker import export_rendering
from clipper_worker.face_detection import DetectedFace
from clipper_worker.face_tracking import FaceTrack
from clipper_worker.media import MediaMetadata


@pytest.mark.parametrize(
    ("profile", "dimensions", "aspect_ratio"),
    [
        ("9:16", (1080, 1920), 9 / 16),
        ("1:1", (1080, 1080), 1),
        ("16:9", (1920, 1080), 16 / 9),
    ],
)
def test_render_aspect_export_builds_crop_for_selected_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile: export_rendering.ExportProfile,
    dimensions: tuple[int, int],
    aspect_ratio: float,
) -> None:
    source = tmp_path / "source.mp4"
    source.touch()
    subtitles = tmp_path / "captions.ass"
    subtitles.write_text("[Events]\n", encoding="utf-8")
    track = FaceTrack(
        7,
        (
            DetectedFace(0, 0.4, 0.3, 0.2, 0.3, 0.9),
            DetectedFace(1, 0.5, 0.3, 0.2, 0.3, 0.9),
        ),
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        export_rendering,
        "probe_media",
        lambda _path: MediaMetadata(10, 1920, 1080, 30, True),
    )

    def fake_render(
        _input: str | Path,
        output: str | Path,
        crop_path: tuple[object, ...],
        _start: float,
        _end: float,
        **kwargs: object,
    ) -> Path:
        captured["crop_path"] = crop_path
        captured["kwargs"] = kwargs
        return Path(output)

    monkeypatch.setattr(export_rendering, "render_vertical_clip", fake_render)

    result = export_rendering.render_aspect_export(
        source,
        tmp_path / "render.mp4",
        track,
        0,
        2,
        profile=profile,
        subtitle_path=subtitles,
    )

    assert result == tmp_path / "render.mp4"
    assert captured["kwargs"]["output_width"] == dimensions[0]
    assert captured["kwargs"]["output_height"] == dimensions[1]
    assert captured["kwargs"]["subtitle_path"] == subtitles
    crop = captured["crop_path"][0]
    assert crop.width / crop.height == pytest.approx(aspect_ratio, abs=0.01)


def test_render_aspect_export_rejects_unknown_profile(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unsupported export profile"):
        export_rendering.render_aspect_export(
            tmp_path / "source.mp4",
            tmp_path / "render.mp4",
            FaceTrack(0, ()),
            0,
            1,
            profile="4:3",
        )
