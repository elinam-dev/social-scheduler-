import math
from dataclasses import dataclass

from clipper_worker.diarization import DiarizationTurn
from clipper_worker.face_tracking import FaceTrack


@dataclass(frozen=True)
class ActiveSpeakerMatch:
    speaker_id: str
    track_id: int
    evidence_samples: int
    cooccurrence_ratio: float


def match_speakers_to_face_tracks(
    turns: tuple[DiarizationTurn, ...],
    tracks: list[FaceTrack],
    *,
    minimum_evidence_samples: int = 2,
) -> tuple[ActiveSpeakerMatch, ...]:
    if minimum_evidence_samples < 1:
        raise ValueError("Minimum evidence samples must be at least one")

    turns_by_speaker: dict[str, list[DiarizationTurn]] = {}
    for turn in turns:
        if (
            not math.isfinite(turn.start_seconds)
            or not math.isfinite(turn.end_seconds)
            or turn.start_seconds < 0
            or turn.end_seconds <= turn.start_seconds
        ):
            raise ValueError("Diarization turns must have finite, positive time ranges")
        turns_by_speaker.setdefault(turn.speaker_id, []).append(turn)

    candidates: list[tuple[int, float, str, int]] = []
    for track in tracks:
        if not track.detections:
            continue
        for speaker_id, speaker_turns in turns_by_speaker.items():
            evidence = sum(
                any(
                    turn.start_seconds <= detection.timestamp_seconds < turn.end_seconds
                    for turn in speaker_turns
                )
                for detection in track.detections
            )
            if evidence >= minimum_evidence_samples:
                ratio = evidence / len(track.detections)
                candidates.append((evidence, ratio, speaker_id, track.track_id))

    candidates.sort(
        key=lambda candidate: (-candidate[0], -candidate[1], candidate[2], candidate[3])
    )
    assigned_speakers: set[str] = set()
    assigned_tracks: set[int] = set()
    matches: list[ActiveSpeakerMatch] = []
    for evidence, ratio, speaker_id, track_id in candidates:
        if speaker_id in assigned_speakers or track_id in assigned_tracks:
            continue
        assigned_speakers.add(speaker_id)
        assigned_tracks.add(track_id)
        matches.append(
            ActiveSpeakerMatch(
                speaker_id=speaker_id,
                track_id=track_id,
                evidence_samples=evidence,
                cooccurrence_ratio=ratio,
            )
        )

    return tuple(sorted(matches, key=lambda match: match.speaker_id))
