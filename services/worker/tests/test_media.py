import json
import shutil
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker.media import (
    AudioExtractionError,
    MediaProbeError,
    extract_audio,
    probe_media,
)


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg and FFprobe are required for the generated sample fixture")

    video_path = tmp_path / "sample.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=160x90:r=10:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=16000:duration=2",
            "-t",
            "2",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-c:a",
            "aac",
            "-b:a",
            "32k",
            str(video_path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return video_path


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


def test_generated_sample_video_probes_and_extracts_audio(sample_video: Path) -> None:
    metadata = probe_media(sample_video)
    audio_path = extract_audio(sample_video, sample_video.with_suffix(".wav"))

    assert sample_video.stat().st_size < 10 * 1024 * 1024
    assert metadata.duration_seconds == pytest.approx(2, abs=0.1)
    assert (metadata.width, metadata.height) == (160, 90)
    assert metadata.has_audio is True
    with wave.open(str(audio_path), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.getframerate() == 16000
        assert audio.getnframes() / audio.getframerate() == pytest.approx(2, abs=0.1)


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


def test_extract_audio_creates_mono_16khz_pcm_wav(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "source video.mp4"
    video_path.write_bytes(b"video")
    audio_path = tmp_path / "audio" / "source.wav"
    captured_command: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured_command.extend(command)
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 3600
        Path(command[-1]).write_bytes(b"RIFF test audio")
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = extract_audio(video_path, audio_path)

    assert result == audio_path
    assert audio_path.read_bytes() == b"RIFF test audio"
    assert captured_command[captured_command.index("-ac") + 1] == "1"
    assert captured_command[captured_command.index("-ar") + 1] == "16000"
    assert captured_command[captured_command.index("-c:a") + 1] == "pcm_s16le"
    assert str(video_path) in captured_command


def test_extract_audio_reports_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "no-audio.mp4"
    video_path.write_bytes(b"video")

    def failed_run(command: list[str], **kwargs: object) -> None:
        raise subprocess.CalledProcessError(
            returncode=1,
            cmd=command,
            stderr="no audio stream",
        )

    monkeypatch.setattr(subprocess, "run", failed_run)

    with pytest.raises(AudioExtractionError, match="no audio stream"):
        extract_audio(video_path, tmp_path / "audio.wav")


def test_extract_audio_requires_wav_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video_path = tmp_path / "source.mp4"
    video_path.write_bytes(b"video")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("FFmpeg should not be called"),
    )

    with pytest.raises(AudioExtractionError, match="\\.wav extension"):
        extract_audio(video_path, tmp_path / "audio.mp3")
