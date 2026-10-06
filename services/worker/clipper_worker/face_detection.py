import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FaceDetectionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DetectedFace:
    timestamp_seconds: float
    x: float
    y: float
    width: float
    height: float
    confidence: float


def detect_faces(
    video_path: str | Path,
    *,
    sample_interval_seconds: float = 1.0,
    min_detection_confidence: float = 0.5,
    model_selection: int = 1,
) -> list[DetectedFace]:
    path = Path(video_path)
    if not path.is_file():
        raise FaceDetectionError(f"Video file does not exist: {path}")
    if not math.isfinite(sample_interval_seconds) or sample_interval_seconds <= 0:
        raise ValueError("Frame sample interval must be finite and greater than zero")
    if (
        not math.isfinite(min_detection_confidence)
        or not 0 <= min_detection_confidence <= 1
    ):
        raise ValueError("Minimum face confidence must be between 0 and 1")
    if model_selection not in (0, 1):
        raise ValueError("Face detection model selection must be 0 or 1")

    try:
        import cv2
        import mediapipe as mp
    except ImportError as error:
        raise FaceDetectionError(
            "Face detection requires the worker's OpenCV and MediaPipe dependencies"
        ) from error

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        capture.release()
        raise FaceDetectionError(f"Could not open video for face detection: {path}")

    detector: Any | None = None
    detections: list[DetectedFace] = []
    next_sample_seconds = 0.0
    try:
        detector = mp.solutions.face_detection.FaceDetection(
            model_selection=model_selection,
            min_detection_confidence=min_detection_confidence,
        )
        while True:
            success, frame = capture.read()
            if not success:
                break

            timestamp_seconds = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
            if not math.isfinite(timestamp_seconds):
                raise FaceDetectionError(
                    f"Video decoder returned an invalid frame timestamp for {path}"
                )
            if timestamp_seconds + 1e-9 < next_sample_seconds:
                continue
            next_sample_seconds += sample_interval_seconds

            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            result = detector.process(rgb_frame)
            for detection in result.detections or ():
                box = detection.location_data.relative_bounding_box
                left = max(0.0, min(1.0, box.xmin))
                top = max(0.0, min(1.0, box.ymin))
                right = max(0.0, min(1.0, box.xmin + box.width))
                bottom = max(0.0, min(1.0, box.ymin + box.height))
                if right <= left or bottom <= top:
                    continue
                detections.append(
                    DetectedFace(
                        timestamp_seconds=timestamp_seconds,
                        x=left,
                        y=top,
                        width=right - left,
                        height=bottom - top,
                        confidence=float(detection.score[0]),
                    )
                )
    finally:
        if detector is not None:
            detector.close()
        capture.release()

    return detections
