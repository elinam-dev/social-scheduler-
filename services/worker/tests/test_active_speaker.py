import pytest

from clipper_worker.active_speaker import (
    ActiveSpeakerMatch,
    match_speakers_to_face_tracks,
)
from clipper_worker.diarization import DiarizationTurn
from clipper_worker.face_detection import DetectedFace
from clipper_worker.face_tracking import FaceTrack


def _track(track_id: int, timestamps: tuple[float, ...]) -> FaceTrack:
    return FaceTrack(
        track_id,
        tuple(DetectedFace(time, 0.1, 0.1, 0.2, 0.2, 0.9) for time in timestamps),
    )


def test_match_speakers_to_face_tracks_uses_speech_time_cooccurrence() -> None:
    turns = (
        DiarizationTurn(0, 2, "speaker_1"),
        DiarizationTurn(2, 4, "speaker_2"),
    )
    tracks = [_track(0, (0, 1, 2, 3)), _track(1, (2, 3))]

    matches = match_speakers_to_face_tracks(turns, tracks)

    assert matches == (
        ActiveSpeakerMatch("speaker_1", 0, 2, 0.5),
        ActiveSpeakerMatch("speaker_2", 1, 2, 1.0),
    )


def test_match_speakers_to_face_tracks_assigns_each_track_and_speaker_once() -> None:
    turns = (
        DiarizationTurn(0, 3, "speaker_1"),
        DiarizationTurn(0, 3, "speaker_2"),
    )
    tracks = [_track(0, (0, 1, 2)), _track(1, (0, 1))]

    matches = match_speakers_to_face_tracks(turns, tracks)

    assert matches == (
        ActiveSpeakerMatch("speaker_1", 0, 3, 1.0),
        ActiveSpeakerMatch("speaker_2", 1, 2, 1.0),
    )


def test_match_speakers_to_face_tracks_ignores_insufficient_evidence() -> None:
    turns = (DiarizationTurn(0, 1, "speaker_1"),)

    assert (
        match_speakers_to_face_tracks(
            turns, [_track(0, (0, 1))], minimum_evidence_samples=2
        )
        == ()
    )


def test_match_speakers_to_face_tracks_uses_half_open_turn_ranges() -> None:
    turns = (DiarizationTurn(0, 1, "speaker_1"),)

    assert match_speakers_to_face_tracks(turns, [_track(0, (1,))]) == ()


def test_match_speakers_to_face_tracks_rejects_invalid_turn() -> None:
    with pytest.raises(ValueError, match="finite, positive time ranges"):
        match_speakers_to_face_tracks(
            (DiarizationTurn(1, 1, "speaker_1"),), [_track(0, (0,))]
        )


def test_match_speakers_to_face_tracks_rejects_invalid_minimum_evidence() -> None:
    with pytest.raises(ValueError, match="at least one"):
        match_speakers_to_face_tracks((), [], minimum_evidence_samples=0)
