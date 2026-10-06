import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker import rendering
from clipper_worker.media import MediaMetadata
from clipper_worker.rendering import ClipRenderError, render_clip


def test_render_clip_uses_frame_accurate_video_and_audio_trims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "renders" / "clip.mp4"
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        rendering,
        "probe_media",
        lambda _path: MediaMetadata(10, 1920, 1080, 30, True),
    )

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["kwargs"] = kwargs
        Path(command[-1]).write_bytes(b"rendered")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = render_clip(source, output, 0.51, 1.49)

    command = captured["command"]
    assert isinstance(command, list)
    filter_value = command[command.index("-filter_complex") + 1]
    assert "trim=start=0.510000000:end=1.490000000" in filter_value
    assert "atrim=start=0.510000000:end=1.490000000" in filter_value
    assert "-c:v" in command
    assert result == output
    assert result.read_bytes() == b"rendered"


def test_render_clip_handles_sources_without_audio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 640, 360, 24, False),
    )
    commands: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> None:
        commands.extend(command)
        Path(command[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(subprocess, "run", fake_run)

    render_clip(source, tmp_path / "silent-clip.mp4", 0, 1)

    assert "-vf" in commands
    assert "-filter_complex" not in commands
    assert "0:v:0" in commands


@pytest.mark.parametrize(
    ("start", "end"),
    [(float("nan"), 1), (0, float("inf")), (-1, 1), (1, 1)],
)
def test_render_clip_rejects_invalid_time_boundaries(
    tmp_path: Path, start: float, end: float
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="finite and have end after start"):
        render_clip(source, tmp_path / "clip.mp4", start, end)


def test_render_clip_rejects_range_past_source_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 640, 360, 24, True),
    )

    with pytest.raises(ValueError, match="exceeds the source"):
        render_clip(source, tmp_path / "clip.mp4", 1, 3)


def test_render_clip_reports_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 640, 360, 24, True),
    )

    def failed_run(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="invalid video",
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(ClipRenderError, match="invalid video"):
        render_clip(source, tmp_path / "clip.mp4", 0, 1)
