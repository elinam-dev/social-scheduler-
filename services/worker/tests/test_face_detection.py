import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from clipper_worker.face_detection import (
    DetectedFace,
    FaceDetectionError,
    detect_faces,
)


class FakeCapture:
    def __init__(self, frames: list[tuple[float, object]]) -> None:
        self.frames = iter(frames)
        self.timestamp_seconds = 0.0
        self.released = False

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, object | None]:
        try:
            self.timestamp_seconds, frame = next(self.frames)
        except StopIteration:
            return False, None
        return True, frame

    def get(self, _property: int) -> float:
        return self.timestamp_seconds * 1000

    def release(self) -> None:
        self.released = True


def _fake_cv2(capture: FakeCapture) -> SimpleNamespace:
    return SimpleNamespace(
        VideoCapture=lambda _path: capture,
        CAP_PROP_POS_MSEC=0,
        COLOR_BGR2RGB=1,
        cvtColor=lambda frame, _conversion: frame,
    )


def test_detect_faces_samples_frames_and_clamps_normalized_boxes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    video = tmp_path / "video.mp4"
    video.touch()
    capture = FakeCapture([(0, "frame-0"), (0.5, "frame-1"), (1, "frame-2")])
    call_times: list[float] = []
    detection = SimpleNamespace(
        location_data=SimpleNamespace(
            relative_bounding_box=SimpleNamespace(
                xmin=-0.1, ymin=0.2, width=0.5, height=0.9
            )
        ),
        score=[0.95],
    )

    class FakeDetector:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs == {
                "model_selection": 1,
                "min_detection_confidence": 0.5,
            }

        def process(self, frame: str) -> SimpleNamespace:
            call_times.append(float(frame.removeprefix("frame-")) / 2)
            return SimpleNamespace(detections=[detection])

        def close(self) -> None:
            pass

    monkeypatch.setitem(
        sys.modules,
        "cv2",
        _fake_cv2(capture),
    )
    monkeypatch.setitem(
        sys.modules,
        "mediapipe",
        SimpleNamespace(
            solutions=SimpleNamespace(
                face_detection=SimpleNamespace(FaceDetection=FakeDetector)
            )
        ),
    )

    result = detect_faces(video, sample_interval_seconds=1)

    assert call_times == [0.0, 1.0]
    assert result == [
        DetectedFace(
            timestamp_seconds=0,
            x=0,
            y=0.2,
            width=0.4,
            height=0.8,
            confidence=0.95,
        ),
        DetectedFace(
            timestamp_seconds=1,
            x=0,
            y=0.2,
            width=0.4,
            height=0.8,
            confidence=0.95,
        ),
    ]
    assert capture.released


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"sample_interval_seconds": 0}, "sample interval"),
        ({"sample_interval_seconds": float("inf")}, "sample interval"),
        ({"min_detection_confidence": -0.1}, "confidence"),
        ({"min_detection_confidence": float("nan")}, "confidence"),
        ({"model_selection": 2}, "model selection"),
    ],
)
def test_detect_faces_rejects_invalid_options(
    tmp_path: Path, options: dict[str, float | int], message: str
) -> None:
    video = tmp_path / "video.mp4"
    video.touch()

    with pytest.raises(ValueError, match=message):
        detect_faces(video, **options)


def test_detect_faces_rejects_missing_video(tmp_path: Path) -> None:
    with pytest.raises(FaceDetectionError, match="does not exist"):
        detect_faces(tmp_path / "missing.mp4")
