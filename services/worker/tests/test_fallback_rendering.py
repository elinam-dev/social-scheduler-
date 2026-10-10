import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker import fallback_rendering
from clipper_worker.fallback_rendering import FallbackLayout, render_fallback_clip
from clipper_worker.media import MediaMetadata
from clipper_worker.rendering import ClipRenderError


@pytest.mark.parametrize(
    ("layout", "filter_fragments"),
    [
        (
            "blurred-background",
            ("scale=iw/20:ih/20", "overlay=(W-w)/2:(H-h)/2"),
        ),
        ("split-screen", ("crop=iw/2:ih:0:0", "vstack=inputs=2")),
    ],
)
def test_render_fallback_clip_builds_layout_and_audio_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    layout: FallbackLayout,
    filter_fragments: tuple[str, ...],
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        fallback_rendering,
        "probe_media",
        lambda _path: MediaMetadata(10, 1920, 1080, 30, True),
    )

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        Path(command[-1]).write_bytes(b"rendered")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    render_fallback_clip(
        source,
        tmp_path / "clip.mp4",
        0.5,
        2.5,
        layout=layout,
        output_width=90,
        output_height=160,
    )

    command = captured["command"]
    assert isinstance(command, list)
    filters = command[command.index("-filter_complex") + 1]
    assert all(fragment in filters for fragment in filter_fragments)
    assert "asetpts=PTS-STARTPTS" in filters
    assert "-map" in command


def test_render_fallback_clip_accepts_video_only_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "silent.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        fallback_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 640, 360, 30, False),
    )
    command: list[str] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> None:
        command.extend(arguments)
        Path(arguments[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(subprocess, "run", fake_run)
    render_fallback_clip(
        source,
        tmp_path / "clip.mp4",
        0,
        1,
        layout="blurred-background",
        output_width=90,
        output_height=160,
    )

    assert "-filter_complex" in command
    assert "[0:a:0]" not in command[command.index("-filter_complex") + 1]


def test_render_fallback_clip_burns_in_ass_subtitles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    subtitles = tmp_path / "captions.ass"
    subtitles.write_text("[Events]\n", encoding="utf-8")
    monkeypatch.setattr(
        fallback_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 320, 180, 30, False),
    )
    command: list[str] = []

    def fake_run(arguments: list[str], **_kwargs: object) -> None:
        command.extend(arguments)
        Path(arguments[-1]).write_bytes(b"rendered")

    monkeypatch.setattr(subprocess, "run", fake_run)
    render_fallback_clip(
        source,
        tmp_path / "clip.mp4",
        0,
        1,
        layout="blurred-background",
        output_width=90,
        output_height=160,
        subtitle_path=subtitles,
    )

    assert "subtitles=filename=" in command[command.index("-filter_complex") + 1]


def test_render_fallback_clip_rejects_unknown_layout(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    with pytest.raises(ValueError, match="Unsupported fallback layout"):
        render_fallback_clip(
            source,
            tmp_path / "clip.mp4",
            0,
            1,
            layout="unknown",  # type: ignore[arg-type]
        )


def test_render_fallback_clip_reports_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    monkeypatch.setattr(
        fallback_rendering,
        "probe_media",
        lambda _path: MediaMetadata(2, 640, 360, 30, False),
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(1, "ffmpeg", stderr="layout failed")
        ),
    )

    with pytest.raises(ClipRenderError, match="layout failed"):
        render_fallback_clip(
            source,
            tmp_path / "clip.mp4",
            0,
            1,
            layout="split-screen",
            output_width=90,
            output_height=160,
        )
