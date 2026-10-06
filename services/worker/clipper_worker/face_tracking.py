import math
from dataclasses import dataclass

from clipper_worker.face_detection import DetectedFace


@dataclass(frozen=True)
class FaceTrack:
    track_id: int
    detections: tuple[DetectedFace, ...]


def track_faces(
    detections: list[DetectedFace],
    *,
    iou_threshold: float = 0.3,
    max_gap_seconds: float = 2.0,
) -> list[FaceTrack]:
    if not math.isfinite(iou_threshold) or not 0 <= iou_threshold <= 1:
        raise ValueError("IoU threshold must be between 0 and 1")
    if not math.isfinite(max_gap_seconds) or max_gap_seconds < 0:
        raise ValueError("Maximum tracking gap must be finite and nonnegative")

    ordered = sorted(
        detections,
        key=lambda face: (
            face.timestamp_seconds,
            face.x,
            face.y,
            face.width,
            face.height,
        ),
    )
    grouped: list[list[DetectedFace]] = []
    for detection in ordered:
        if (
            not math.isfinite(detection.timestamp_seconds)
            or detection.timestamp_seconds < 0
        ):
            raise ValueError("Face detection timestamps must be finite and nonnegative")
        if grouped and grouped[-1][0].timestamp_seconds == detection.timestamp_seconds:
            grouped[-1].append(detection)
        else:
            grouped.append([detection])

    tracks: list[list[DetectedFace]] = []
    for frame_detections in grouped:
        timestamp = frame_detections[0].timestamp_seconds
        active_tracks = [
            index
            for index, track in enumerate(tracks)
            if 0 <= timestamp - track[-1].timestamp_seconds <= max_gap_seconds
        ]
        pairs = sorted(
            (
                _intersection_over_union(tracks[index][-1], detection),
                index,
                detection_index,
            )
            for index in active_tracks
            for detection_index, detection in enumerate(frame_detections)
        )
        assigned_tracks: set[int] = set()
        assigned_detections: set[int] = set()
        for overlap, track_index, detection_index in reversed(pairs):
            if overlap < iou_threshold or overlap <= 0:
                break
            if track_index in assigned_tracks or detection_index in assigned_detections:
                continue
            tracks[track_index].append(frame_detections[detection_index])
            assigned_tracks.add(track_index)
            assigned_detections.add(detection_index)

        for detection_index, detection in enumerate(frame_detections):
            if detection_index not in assigned_detections:
                tracks.append([detection])

    return [
        FaceTrack(track_id=index, detections=tuple(track))
        for index, track in enumerate(tracks)
    ]


def _intersection_over_union(first: DetectedFace, second: DetectedFace) -> float:
    left = max(first.x, second.x)
    top = max(first.y, second.y)
    right = min(first.x + first.width, second.x + second.width)
    bottom = min(first.y + first.height, second.y + second.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    union = first.width * first.height + second.width * second.height - intersection
    return intersection / union if union > 0 else 0.0
