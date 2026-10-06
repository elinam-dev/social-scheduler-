import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker import transcription
from clipper_worker.transcription import TranscriptionError, transcribe_audio


def _write_wav(path: Path, duration_seconds: float, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        audio.writeframes(b"\x00\x00" * int(duration_seconds * sample_rate))


def test_transcribe_audio_uses_cpu_int8_without_cuda(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, 2.5)
    model_options = {}
    transcribe_options = {}

    class FakeModel:
        def __init__(self, model_name: str, **kwargs: str) -> None:
            model_options.update(model_name=model_name, **kwargs)

        def transcribe(self, path: str, **kwargs: object):
            transcribe_options.update(path=path, **kwargs)
            return iter(
                [
                    SimpleNamespace(
                        start=0,
                        end=1.25,
                        text=" Hello there! ",
                        words=[
                            SimpleNamespace(
                                start=0.0,
                                end=0.42,
                                word=" Hello",
                                probability=0.98,
                            ),
                            SimpleNamespace(
                                start=0.42,
                                end=1.25,
                                word=" there!",
                                probability=0.96,
                            ),
                        ],
                    ),
                    SimpleNamespace(
                        start=1.25,
                        end=2.5,
                        text=" Next sentence. ",
                        words=[
                            SimpleNamespace(
                                start=1.25,
                                end=1.75,
                                word=" Next",
                                probability=0.95,
                            ),
                            SimpleNamespace(
                                start=1.75,
                                end=2.5,
                                word=" sentence.",
                                probability=0.94,
                            ),
                        ],
                    ),
                ]
            ), SimpleNamespace(
                language="en",
                language_probability=0.99,
                duration=2.5,
            )

    monkeypatch.setattr(transcription.ctranslate2, "get_cuda_device_count", lambda: 0)
    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)

    result = transcribe_audio(audio_path, model_name="tiny", language="en")

    assert model_options == {
        "model_name": "tiny",
        "device": "cpu",
        "compute_type": "int8",
    }
    assert transcribe_options == {
        "path": str(audio_path),
        "language": "en",
        "beam_size": 5,
        "word_timestamps": True,
    }
    assert result.language == "en"
    assert result.language_probability == 0.99
    assert result.duration_seconds == 2.5
    assert [segment.text for segment in result.segments] == [
        "Hello there!",
        "Next sentence.",
    ]
    assert [
        (word.start_seconds, word.end_seconds, word.text, word.probability)
        for word in result.segments[0].words
    ] == [
        (0.0, 0.42, "Hello", 0.98),
        (0.42, 1.25, "there!", 0.96),
    ]


def test_transcribe_audio_uses_cuda_float16_when_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, 2.5)
    model_options = {}

    class FakeModel:
        def __init__(self, _model_name: str, **kwargs: str) -> None:
            model_options.update(kwargs)

        def transcribe(self, _path: str, **_kwargs: object):
            return iter(()), SimpleNamespace(
                language="en",
                language_probability=1.0,
                duration=0.0,
            )

    monkeypatch.setattr(transcription.ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)

    transcribe_audio(audio_path, model_name="small")

    assert model_options == {"device": "cuda", "compute_type": "float16"}


def test_transcribe_audio_handles_segments_without_word_alignment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, 1)

    class FakeModel:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def transcribe(self, *_args: object, **_kwargs: object):
            return iter(
                [SimpleNamespace(start=0, end=1, text=" Unaligned words. ", words=None)]
            ), SimpleNamespace(
                language="en",
                language_probability=1.0,
                duration=1.0,
            )

    monkeypatch.setattr(transcription.ctranslate2, "get_cuda_device_count", lambda: 0)
    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)

    result = transcribe_audio(audio_path, model_name="tiny")

    assert result.segments[0].text == "Unaligned words."
    assert result.segments[0].words == ()


def test_transcribe_audio_splits_long_wav_and_offsets_all_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "long-audio.wav"
    _write_wav(audio_path, 5, sample_rate=10)
    model_calls: list[Path] = []
    ffmpeg_commands: list[list[str]] = []

    class FakeModel:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def transcribe(self, path: str, **_kwargs: object):
            chunk_path = Path(path)
            model_calls.append(chunk_path)
            index = (
                int(chunk_path.stem.split("-")[-1]) if chunk_path != audio_path else 0
            )
            with wave.open(str(chunk_path), "rb") as chunk:
                chunk_duration = chunk.getnframes() / chunk.getframerate()
            probability = 0.8 + index * 0.05
            return iter(
                [
                    SimpleNamespace(
                        start=0.0,
                        end=chunk_duration,
                        text=f" chunk {index} ",
                        words=[
                            SimpleNamespace(
                                start=0.25,
                                end=min(0.75, chunk_duration),
                                word=f" {index}",
                                probability=probability,
                            )
                        ],
                    )
                ]
            ), SimpleNamespace(
                language="en",
                language_probability=probability,
                duration=chunk_duration,
            )

    def fake_ffmpeg(command: list[str], **kwargs: object) -> SimpleNamespace:
        ffmpeg_commands.append(command)
        output_path = Path(command[-1])
        length = float(command[command.index("-t") + 1])
        _write_wav(output_path, length, sample_rate=10)
        return SimpleNamespace(stdout="", stderr="")

    monkeypatch.setattr(transcription.ctranslate2, "get_cuda_device_count", lambda: 0)
    monkeypatch.setattr(transcription, "WhisperModel", FakeModel)
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)

    result = transcribe_audio(
        audio_path,
        model_name="tiny",
        chunk_duration_seconds=2,
    )

    assert len(ffmpeg_commands) == 3
    assert len(model_calls) == 3
    assert all(
        path.parent.name.startswith("clipper-transcribe-") for path in model_calls
    )
    assert [segment.start_seconds for segment in result.segments] == [0, 2, 4]
    assert [segment.end_seconds for segment in result.segments] == [2, 4, 5]
    assert [segment.text for segment in result.segments] == [
        "chunk 0",
        "chunk 1",
        "chunk 2",
    ]
    assert [segment.words[0].start_seconds for segment in result.segments] == [
        0.25,
        2.25,
        4.25,
    ]
    assert [segment.words[0].end_seconds for segment in result.segments] == [
        0.75,
        2.75,
        4.75,
    ]
    assert result.duration_seconds == 5
    assert result.language_probability == pytest.approx(0.84)


def test_transcribe_audio_reports_missing_file(tmp_path: Path) -> None:
    with pytest.raises(TranscriptionError, match="Audio file does not exist"):
        transcribe_audio(tmp_path / "missing.wav", model_name="tiny")


def test_transcribe_audio_surfaces_model_load_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    audio_path = tmp_path / "audio.wav"
    _write_wav(audio_path, 1)
    monkeypatch.setattr(transcription.ctranslate2, "get_cuda_device_count", lambda: 0)

    def fail_model(*_args: object, **_kwargs: object) -> None:
        raise OSError("model weights unavailable")

    monkeypatch.setattr(transcription, "WhisperModel", fail_model)

    with pytest.raises(TranscriptionError, match="model weights unavailable"):
        transcribe_audio(audio_path, model_name="tiny")
