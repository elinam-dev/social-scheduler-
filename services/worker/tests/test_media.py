import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker.media import MediaProbeError, probe_media


def test_probe_media_extracts_video_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "episode.mp4"
    video_path.write_bytes(b"video")
    probe_result = {
        "format": {"duration": "125.75"},
        "streams": [
            {
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "30000/1001",
            },
            {"codec_type": "audio"},
        ],
    }
    captured_command: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured_command.extend(command)
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 60
        return SimpleNamespace(stdout=json.dumps(probe_result), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    metadata = probe_media(video_path)

    assert metadata.duration_seconds == 125.75
    assert metadata.width == 1920
    assert metadata.height == 1080
    assert metadata.frame_rate == pytest.approx(30000 / 1001)
    assert metadata.has_audio is True
    assert "-show_entries" in captured_command
    assert str(video_path) in captured_command


def test_probe_media_rejects_file_without_video_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "audio-only.mp4"
    video_path.write_bytes(b"audio")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps({"format": {"duration": "1"}, "streams": []}),
            stderr="",
        ),
    )

    with pytest.raises(MediaProbeError, match="invalid media metadata"):
        probe_media(video_path)


def test_probe_media_reports_ffprobe_process_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "broken.mp4"
    video_path.write_bytes(b"not a video")

    def failed_run(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="invalid data",
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(MediaProbeError, match="invalid data"):
        probe_media(video_path)
