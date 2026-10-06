import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker import vertical_rendering
from clipper_worker.crop_path import CropFrame
from clipper_worker.media import MediaMetadata
from clipper_worker.rendering import ClipRenderError
from clipper_worker.vertical_rendering import render_vertical_clip


def test_render_vertical_clip_applies_smoothed_crop_path_and_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "renders" / "clip.mp4"
    crop_path = (CropFrame(0, 0, 0, 100, 178), CropFrame(1, 20, 0, 100, 178))
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        vertical_rendering,
        "probe_media",
        lambda _path: MediaMetadata(10, 320, 180, 30, True),
    )

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        Path(command[-1]).write_bytes(b"rendered")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = render_vertical_clip(
        source, output, crop_path, 0.5, 1.5, output_width=90, output_height=160
    )

    command = captured["command"]
    assert isinstance(command, list)
    filter_value = command[command.index("-filter_complex") + 1]
    assert "crop=w=100:h=178" in filter_value
    assert "scale=90:160:flags=lanczos" in filter_value
    assert "20-0" in filter_value
    assert "atrim=start=0.500000000:end=1.500000000" in filter_value
    assert result == output


def test_render_vertical_clip_handles_video_without_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        vertical_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 320, 180, 30, False),
    )
    command: list[str] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> None:
        command.extend(arguments)
        Path(arguments[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(subprocess, "run", fake_run)
    render_vertical_clip(
        source,
        tmp_path / "clip.mp4",
        (CropFrame(0, 0, 0, 100, 178),),
        0,
        1,
        output_width=90,
        output_height=160,
    )

    assert "-vf" in command
    assert "-filter_complex" not in command
    assert "0:v:0" in command


def test_render_vertical_clip_burns_in_ass_subtitles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    subtitles = tmp_path / "captions.ass"
    subtitles.write_text("[Events]\n", encoding="utf-8")
    monkeypatch.setattr(
        vertical_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 320, 180, 30, False),
    )
    command: list[str] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> None:
        command.extend(arguments)
        Path(arguments[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(subprocess, "run", fake_run)
    render_vertical_clip(
        source,
        tmp_path / "clip.mp4",
        (CropFrame(0, 0, 0, 100, 178),),
        0,
        1,
        output_width=90,
        output_height=160,
        subtitle_path=subtitles,
    )

    assert "subtitles=filename=" in command[command.index("-vf") + 1]


def test_render_vertical_clip_rejects_invalid_crop_rectangle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        vertical_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 320, 180, 30, False),
    )

    with pytest.raises(ValueError, match="even, positive, and in bounds"):
        render_vertical_clip(
            source,
            tmp_path / "clip.mp4",
            (CropFrame(0, 1, 0, 100, 178),),
            0,
            1,
            output_width=90,
            output_height=160,
        )


def test_render_vertical_clip_rejects_empty_crop_path(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="non-empty crop path"):
        render_vertical_clip(source, tmp_path / "clip.mp4", (), 0, 1)


def test_render_vertical_clip_reports_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        vertical_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 320, 180, 30, False),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "ffmpeg", stderr="crop failed")
        ),
    )

    with pytest.raises(ClipRenderError, match="crop failed"):
        render_vertical_clip(
            source,
            tmp_path / "clip.mp4",
            (CropFrame(0, 0, 0, 100, 178),),
            0,
            1,
            output_width=90,
            output_height=160,
        )
