import pytest

from clipper_worker.face_detection import DetectedFace
from clipper_worker.face_tracking import FaceTrack, track_faces


def _face(
    timestamp: float, x: float, *, width: float = 0.2, height: float = 0.2
) -> DetectedFace:
    return DetectedFace(timestamp, x, 0.2, width, height, 0.9)


def test_track_faces_links_moving_faces_and_returns_chronological_tracks() -> None:
    detections = [
        _face(1, 0.12),
        _face(0, 0.1),
        _face(1, 0.72),
        _face(0, 0.7),
    ]

    tracks = track_faces(detections)

    assert tracks == [
        FaceTrack(0, (_face(0, 0.1), _face(1, 0.12))),
        FaceTrack(1, (_face(0, 0.7), _face(1, 0.72))),
    ]


def test_track_faces_starts_new_track_after_maximum_gap() -> None:
    tracks = track_faces([_face(0, 0.1), _face(3, 0.1)], max_gap_seconds=2)

    assert tracks == [
        FaceTrack(0, (_face(0, 0.1),)),
        FaceTrack(1, (_face(3, 0.1),)),
    ]


def test_track_faces_does_not_assign_one_detection_to_two_tracks() -> None:
    detections = [
        _face(0, 0.1, width=0.3),
        _face(0, 0.2, width=0.3),
        _face(1, 0.15, width=0.3),
    ]

    tracks = track_faces(detections, iou_threshold=0.3)

    assert [len(track.detections) for track in tracks] == [2, 1]
    assert tracks[0].detections[-1] == _face(1, 0.15, width=0.3)


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ({"iou_threshold": -0.1}, "IoU threshold"),
        ({"iou_threshold": float("nan")}, "IoU threshold"),
        ({"max_gap_seconds": -1}, "Maximum tracking gap"),
        ({"max_gap_seconds": float("inf")}, "Maximum tracking gap"),
    ],
)
def test_track_faces_rejects_invalid_options(
    options: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        track_faces([], **options)


def test_track_faces_rejects_invalid_detection_timestamp() -> None:
    with pytest.raises(ValueError, match="timestamps must be finite"):
        track_faces([_face(float("nan"), 0.1)])


def test_track_faces_returns_empty_result_without_detections() -> None:
    assert track_faces([]) == []
