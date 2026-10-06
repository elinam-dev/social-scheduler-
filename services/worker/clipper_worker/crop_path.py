import math
from dataclasses import dataclass

from clipper_worker.face_tracking import FaceTrack


@dataclass(frozen=True)
class CropFrame:
    timestamp_seconds: float
    x: int
    y: int
    width: int
    height: int


def build_smoothed_crop_path(
    track: FaceTrack,
    source_width: int,
    source_height: int,
    *,
    output_aspect_ratio: float = 9 / 16,
    smoothing: float = 0.35,
) -> tuple[CropFrame, ...]:
    if source_width < 2 or source_height < 2:
        raise ValueError("Source dimensions must be at least two pixels")
    if not math.isfinite(output_aspect_ratio) or output_aspect_ratio <= 0:
        raise ValueError("Output aspect ratio must be finite and greater than zero")
    if not math.isfinite(smoothing) or not 0 <= smoothing <= 1:
        raise ValueError("Crop smoothing must be between 0 and 1")

    frame_width = source_width - source_width % 2
    frame_height = source_height - source_height % 2
    crop_width, crop_height = _crop_dimensions(
        frame_width, frame_height, output_aspect_ratio
    )
    path: list[CropFrame] = []
    smoothed_x: float | None = None
    smoothed_y: float | None = None
    previous_timestamp = -1.0

    for detection in track.detections:
        timestamp = detection.timestamp_seconds
        if (
            not math.isfinite(timestamp)
            or timestamp < 0
            or timestamp <= previous_timestamp
        ):
            raise ValueError("Face track timestamps must be finite and increasing")
        if (
            not all(
                math.isfinite(value)
                for value in (
                    detection.x,
                    detection.y,
                    detection.width,
                    detection.height,
                )
            )
            or detection.x < 0
            or detection.y < 0
            or detection.width <= 0
            or detection.height <= 0
            or detection.x + detection.width > 1
            or detection.y + detection.height > 1
        ):
            raise ValueError("Face boxes must be finite normalized rectangles")

        target_x = (detection.x + detection.width / 2) * frame_width
        target_y = (detection.y + detection.height / 2) * frame_height
        if smoothed_x is None or smoothed_y is None:
            smoothed_x, smoothed_y = target_x, target_y
        else:
            smoothed_x += smoothing * (target_x - smoothed_x)
            smoothed_y += smoothing * (target_y - smoothed_y)

        max_x = frame_width - crop_width
        max_y = frame_height - crop_height
        x = _even_clamped_origin(smoothed_x - crop_width / 2, max_x)
        y = _even_clamped_origin(smoothed_y - crop_height / 2, max_y)
        path.append(
            CropFrame(
                timestamp_seconds=timestamp,
                x=x,
                y=y,
                width=crop_width,
                height=crop_height,
            )
        )
        previous_timestamp = timestamp

    return tuple(path)


def _crop_dimensions(
    frame_width: int, frame_height: int, output_aspect_ratio: float
) -> tuple[int, int]:
    source_aspect_ratio = frame_width / frame_height
    if source_aspect_ratio >= output_aspect_ratio:
        crop_height = frame_height
        crop_width = min(frame_width, _even_floor(crop_height * output_aspect_ratio))
    else:
        crop_width = frame_width
        crop_height = min(frame_height, _even_floor(crop_width / output_aspect_ratio))
    if crop_width < 2 or crop_height < 2:
        raise ValueError("Output aspect ratio produces a crop smaller than two pixels")
    return crop_width, crop_height


def _even_floor(value: float) -> int:
    return int(value) // 2 * 2


def _even_clamped_origin(value: float, maximum: int) -> int:
    even_maximum = maximum - maximum % 2
    rounded = round(value / 2) * 2
    return max(0, min(even_maximum, rounded))
