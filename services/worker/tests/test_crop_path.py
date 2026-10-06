import pytest

from clipper_worker.crop_path import CropFrame, build_smoothed_crop_path
from clipper_worker.face_detection import DetectedFace
from clipper_worker.face_tracking import FaceTrack


def _track(*positions: tuple[float, float]) -> FaceTrack:
    return FaceTrack(
        0,
        tuple(
            DetectedFace(
                time,
                max(0, min(0.9, center_x - 0.05)),
                max(0, min(0.8, center_y - 0.1)),
                0.1,
                0.2,
                0.9,
            )
            for time, (center_x, center_y) in enumerate(positions)
        ),
    )


def test_crop_path_follows_face_with_smoothed_center_and_vertical_aspect() -> None:
    path = build_smoothed_crop_path(
        _track((0.2, 0.5), (0.8, 0.5)),
        1920,
        1080,
        smoothing=0.5,
    )

    assert path == (
        CropFrame(0, 80, 0, 606, 1080),
        CropFrame(1, 656, 0, 606, 1080),
    )


def test_crop_path_keeps_crop_inside_frame_and_uses_even_coordinates() -> None:
    path = build_smoothed_crop_path(
        _track((0.99, 0.99), (0.01, 0.01)),
        1280,
        720,
    )

    for crop in path:
        assert crop.x >= 0 and crop.y >= 0
        assert crop.x + crop.width <= 1280
        assert crop.y + crop.height <= 720
        assert crop.x % 2 == crop.y % 2 == crop.width % 2 == crop.height % 2 == 0


def test_crop_path_uses_full_width_when_source_is_narrower_than_target() -> None:
    path = build_smoothed_crop_path(_track((0.5, 0.5)), 720, 1280)

    assert path[0].width == 720
    assert path[0].height == 1280


def test_crop_path_returns_empty_path_without_face_detections() -> None:
    assert build_smoothed_crop_path(FaceTrack(0, ()), 1920, 1080) == ()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"output_aspect_ratio": 0}, "aspect ratio"),
        ({"output_aspect_ratio": float("inf")}, "aspect ratio"),
        ({"smoothing": -0.1}, "smoothing"),
        ({"smoothing": float("nan")}, "smoothing"),
    ],
)
def test_crop_path_rejects_invalid_options(
    kwargs: dict[str, float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        build_smoothed_crop_path(_track((0.5, 0.5)), 1920, 1080, **kwargs)


def test_crop_path_rejects_non_increasing_track_timestamps() -> None:
    track = FaceTrack(
        0,
        (
            DetectedFace(1, 0.4, 0.4, 0.2, 0.2, 0.9),
            DetectedFace(1, 0.5, 0.4, 0.2, 0.2, 0.9),
        ),
    )

    with pytest.raises(ValueError, match="timestamps must be finite and increasing"):
        build_smoothed_crop_path(track, 1920, 1080)


def test_crop_path_rejects_face_box_outside_normalized_frame() -> None:
    track = FaceTrack(0, (DetectedFace(0, 0.9, 0.4, 0.2, 0.2, 0.9),))

    with pytest.raises(ValueError, match="normalized rectangles"):
        build_smoothed_crop_path(track, 1920, 1080)
