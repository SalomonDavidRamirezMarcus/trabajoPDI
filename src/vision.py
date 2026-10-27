from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Sequence

import cv2
import mediapipe as mp
from mediapipe.framework.formats import landmark_pb2
from mediapipe.tasks.python.components.containers.landmark import (
    NormalizedLandmark,
)

if __package__:
    from . import logic
else:
    import logic


CAMERA_INDEX = 0
MAX_PEOPLE = 4
CONTACT_DISTANCE_RATIO = 0.18
MODEL_PATH = Path(__file__).resolve().parent.parent / "assets" / "pose_landmarker_lite.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)

Point = tuple[float, float]


@dataclass(frozen=True)
class PoseDetection:
    center: Point
    left_shoulder: Point | None
    right_shoulder: Point | None
    left_hip: Point | None
    right_hip: Point | None
    left_elbow: Point | None
    right_elbow: Point | None
    left_wrist: Point | None
    right_wrist: Point | None


@dataclass(frozen=True)
class TrackedPose:
    track_id: int
    detection: PoseDetection
    movement: float
    velocity: Point


@dataclass(frozen=True)
class PoseInteraction:
    first_id: int
    second_id: int
    kind: str
    first_point: Point
    second_point: Point


@dataclass
class _Track:
    center: Point
    timestamp_seconds: float
    missed_frames: int = 0


def _visible_point(
    landmarks: Sequence[NormalizedLandmark], index: int
) -> Point | None:
    landmark = landmarks[index]
    if (
        landmark.visibility is None
        or landmark.visibility < 0.5
        or landmark.x is None
        or landmark.y is None
    ):
        return None
    return landmark.x, landmark.y


def _midpoint(first: Point | None, second: Point | None) -> Point | None:
    if first is None or second is None:
        return None
    return (first[0] + second[0]) / 2, (first[1] + second[1]) / 2


def _point_distance(first: Point, second: Point) -> float:
    return logic.calculate_distance(first, second)


def _make_detection(
    landmarks: Sequence[NormalizedLandmark],
) -> PoseDetection | None:
    left_shoulder = _visible_point(landmarks, 11)
    right_shoulder = _visible_point(landmarks, 12)
    left_elbow = _visible_point(landmarks, 13)
    right_elbow = _visible_point(landmarks, 14)
    left_wrist = _visible_point(landmarks, 15)
    right_wrist = _visible_point(landmarks, 16)
    left_hip = _visible_point(landmarks, 23)
    right_hip = _visible_point(landmarks, 24)

    center = _midpoint(left_hip, right_hip) or _midpoint(
        left_shoulder, right_shoulder
    )
    if center is None:
        visible = [
            (landmark.x, landmark.y)
            for landmark in landmarks
            if landmark.visibility is not None
            and landmark.visibility >= 0.5
            and landmark.x is not None
            and landmark.y is not None
        ]
        if not visible:
            return None
        center = (
            sum(point[0] for point in visible) / len(visible),
            sum(point[1] for point in visible) / len(visible),
        )

    return PoseDetection(
        center=center,
        left_shoulder=left_shoulder,
        right_shoulder=right_shoulder,
        left_hip=left_hip,
        right_hip=right_hip,
        left_elbow=left_elbow,
        right_elbow=right_elbow,
        left_wrist=left_wrist,
        right_wrist=right_wrist,
    )


class PoseTracker:
    """Asocia poses entre fotogramas por cercanía de sus centros normalizados."""

    def __init__(
        self, max_match_distance: float = 0.15, max_missed_frames: int = 10
    ) -> None:
        self.max_match_distance = max_match_distance
        self.max_missed_frames = max_missed_frames
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1

    def update(
        self, detections: Sequence[PoseDetection], timestamp_seconds: float
    ) -> list[TrackedPose]:
        candidates = [
            (self._distance(track.center, detection.center), track_id, index)
            for track_id, track in self._tracks.items()
            for index, detection in enumerate(detections)
        ]
        candidates.sort()

        matched_tracks: set[int] = set()
        matched_detections: set[int] = set()
        assignments: dict[int, tuple[int, float]] = {}
        for distance, track_id, index in candidates:
            if (
                distance > self.max_match_distance
                or track_id in matched_tracks
                or index in matched_detections
            ):
                continue
            matched_tracks.add(track_id)
            matched_detections.add(index)
            assignments[index] = (track_id, distance)

        for track_id, track in list(self._tracks.items()):
            if track_id not in matched_tracks:
                track.missed_frames += 1
                if track.missed_frames > self.max_missed_frames:
                    del self._tracks[track_id]

        tracked: list[TrackedPose] = []
        for index, detection in enumerate(detections):
            assignment = assignments.get(index)
            if assignment is None:
                track_id = self._next_id
                self._next_id += 1
                movement = 0.0
                velocity = (0.0, 0.0)
                self._tracks[track_id] = _Track(
                    detection.center, timestamp_seconds
                )
            else:
                track_id, movement = assignment
                previous = self._tracks[track_id]
                velocity = logic.calculate_velocity(
                    previous.center,
                    detection.center,
                    timestamp_seconds - previous.timestamp_seconds,
                )
                self._tracks[track_id] = _Track(
                    detection.center, timestamp_seconds
                )
            tracked.append(TrackedPose(track_id, detection, movement, velocity))
        return tracked

    @staticmethod
    def _distance(first: Point, second: Point) -> float:
        return logic.calculate_distance(first, second)


def _distance_to_segment(
    point: Point, start: Point, end: Point
) -> tuple[float, Point]:
    segment_x = end[0] - start[0]
    segment_y = end[1] - start[1]
    segment_length_squared = segment_x * segment_x + segment_y * segment_y
    if segment_length_squared == 0:
        closest = start
    else:
        projection = (
            (point[0] - start[0]) * segment_x
            + (point[1] - start[1]) * segment_y
        ) / segment_length_squared
        projection = max(0.0, min(1.0, projection))
        closest = (
            start[0] + projection * segment_x,
            start[1] + projection * segment_y,
        )
    return _point_distance(point, closest), closest


def _shoulder_width(detection: PoseDetection) -> float | None:
    if detection.left_shoulder is None or detection.right_shoulder is None:
        return None
    return _point_distance(detection.left_shoulder, detection.right_shoulder)


def _detect_interactions(poses: Sequence[TrackedPose]) -> list[PoseInteraction]:
    interactions: list[PoseInteraction] = []
    for first_index, first in enumerate(poses):
        first_wrists = [
            point
            for point in (first.detection.left_wrist, first.detection.right_wrist)
            if point is not None
        ]
        if not first_wrists:
            continue

        for second in poses[first_index + 1 :]:
            second_wrists = [
                point
                for point in (
                    second.detection.left_wrist,
                    second.detection.right_wrist,
                )
                if point is not None
            ]
            if not second_wrists:
                continue

            widths = [
                width
                for width in (
                    _shoulder_width(first.detection),
                    _shoulder_width(second.detection),
                )
                if width is not None
            ]
            scale = sum(widths) / len(widths) if widths else 0.0
            threshold = max(0.025, min(0.06, scale * CONTACT_DISTANCE_RATIO))

            hand_contact = min(
                (
                    (
                        _point_distance(first_hand, second_hand),
                        first_hand,
                        second_hand,
                    )
                    for first_hand in first_wrists
                    for second_hand in second_wrists
                ),
                key=lambda candidate: candidate[0],
            )
            if hand_contact[0] <= threshold:
                interactions.append(
                    PoseInteraction(
                        first.track_id,
                        second.track_id,
                        "posible contacto de manos",
                        hand_contact[1],
                        hand_contact[2],
                    )
                )
                continue

            arm_segments = [
                (elbow, wrist)
                for elbow, wrist in (
                    (second.detection.left_elbow, second.detection.left_wrist),
                    (second.detection.right_elbow, second.detection.right_wrist),
                )
                if elbow is not None and wrist is not None
            ]
            reverse_arm_segments = [
                (elbow, wrist)
                for elbow, wrist in (
                    (first.detection.left_elbow, first.detection.left_wrist),
                    (first.detection.right_elbow, first.detection.right_wrist),
                )
                if elbow is not None and wrist is not None
            ]
            arm_contacts = [
                (
                    *_distance_to_segment(hand, elbow, wrist),
                    hand,
                )
                for hand in first_wrists
                for elbow, wrist in arm_segments
            ]
            arm_contacts.extend(
                (
                    *_distance_to_segment(hand, elbow, wrist),
                    hand,
                )
                for hand in second_wrists
                for elbow, wrist in reverse_arm_segments
            )
            if arm_contacts:
                distance, arm_point, hand_point = min(
                    arm_contacts, key=lambda candidate: candidate[0]
                )
                if distance <= threshold:
                    interactions.append(
                        PoseInteraction(
                            first.track_id,
                            second.track_id,
                            "posible contacto de brazos",
                            hand_point,
                            arm_point,
                        )
                    )
    return interactions


def _draw_pose(
    frame: cv2.typing.MatLike,
    landmarks: Sequence[NormalizedLandmark],
) -> None:
    landmark_list = landmark_pb2.NormalizedLandmarkList(
        landmark=[
            landmark_pb2.NormalizedLandmark(
                x=landmark.x if landmark.x is not None else 0.0,
                y=landmark.y if landmark.y is not None else 0.0,
                z=landmark.z if landmark.z is not None else 0.0,
                visibility=(
                    landmark.visibility
                    if landmark.visibility is not None
                    else 0.0
                ),
                presence=(
                    landmark.presence if landmark.presence is not None else 0.0
                ),
            )
            for landmark in landmarks
        ]
    )
    mp.solutions.drawing_utils.draw_landmarks(
        frame,
        landmark_list,
        mp.solutions.pose.POSE_CONNECTIONS,
    )


def main() -> None:
    if not MODEL_PATH.is_file():
        raise FileNotFoundError(
            f"No se encontró el modelo de MediaPipe: {MODEL_PATH}\n"
            f"Descárgalo desde: {MODEL_URL}"
        )

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        cap.release()
        raise RuntimeError(
            f"No se pudo abrir la cámara con índice {CAMERA_INDEX}."
        )

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=MAX_PEOPLE,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    tracker = PoseTracker()
    print("Iniciando Resonantia... Presiona ESC para salir.")

    try:
        with mp.tasks.vision.PoseLandmarker.create_from_options(options) as landmarker:
            while True:
                success, frame = cap.read()
                if not success:
                    print("No se pudo leer un fotograma de la cámara.")
                    break

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb_frame,
                )
                timestamp_ns = time.monotonic_ns()
                timestamp_ms = timestamp_ns // 1_000_000
                result = landmarker.detect_for_video(mp_image, timestamp_ms)

                valid_poses = []
                for landmarks in result.pose_landmarks:
                    detection = _make_detection(landmarks)
                    if detection is not None:
                        valid_poses.append((landmarks, detection))
                tracked_poses = tracker.update(
                    [detection for _, detection in valid_poses],
                    timestamp_ns / 1_000_000_000,
                )
                interactions = _detect_interactions(tracked_poses)
                pair_distances = logic.calculate_pair_distances(
                    {
                        tracked.track_id: tracked.detection.center
                        for tracked in tracked_poses
                    }
                )
                group_synchrony = logic.calculate_group_synchrony(
                    [tracked.velocity for tracked in tracked_poses]
                )

                for (landmarks, _), tracked in zip(valid_poses, tracked_poses):
                    _draw_pose(frame, landmarks)
                    height, width = frame.shape[:2]
                    center_x = int(tracked.detection.center[0] * width)
                    center_y = int(tracked.detection.center[1] * height)
                    cv2.circle(frame, (center_x, center_y), 6, (0, 255, 255), -1)
                    speed = logic.calculate_speed(tracked.velocity)
                    direction = logic.calculate_direction(tracked.velocity)
                    direction_label = (
                        f"{direction:.0f} deg" if direction is not None else "--"
                    )
                    cv2.putText(
                        frame,
                        (
                            f"ID {tracked.track_id} | mov {tracked.movement:.3f}"
                            f" | v {speed:.3f} norm/s | dir {direction_label}"
                        ),
                        (center_x + 8, center_y - 8),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 255, 255),
                        2,
                    )

                height, width = frame.shape[:2]
                for interaction in interactions:
                    first_point = (
                        int(interaction.first_point[0] * width),
                        int(interaction.first_point[1] * height),
                    )
                    second_point = (
                        int(interaction.second_point[0] * width),
                        int(interaction.second_point[1] * height),
                    )
                    midpoint = (
                        (first_point[0] + second_point[0]) // 2,
                        (first_point[1] + second_point[1]) // 2,
                    )
                    cv2.line(frame, first_point, second_point, (0, 0, 255), 3)
                    cv2.putText(
                        frame,
                        f"{interaction.kind}: {interaction.first_id}-{interaction.second_id}",
                        midpoint,
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 0, 255),
                        2,
                    )

                cv2.putText(
                    frame,
                    f"Personas detectadas: {len(tracked_poses)}",
                    (20, 35),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (0, 255, 0),
                    2,
                )
                cv2.putText(
                    frame,
                    f"Posibles contactos: {len(interactions)}",
                    (20, 65),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 0, 255),
                    2,
                )
                synchrony_label = (
                    f"{group_synchrony:.2f}"
                    if group_synchrony is not None
                    else "--"
                )
                cv2.putText(
                    frame,
                    f"Sincronia instantanea: {synchrony_label}",
                    (20, 95),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    (255, 255, 0),
                    2,
                )
                for index, (first_id, second_id, distance) in enumerate(
                    pair_distances
                ):
                    cv2.putText(
                        frame,
                        f"Distancia {first_id}-{second_id}: {distance:.3f}",
                        (20, 125 + index * 25),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 0),
                        2,
                    )
                cv2.imshow("Resonantia - Pose e interaccion", frame)
                if cv2.waitKey(5) & 0xFF == 27:
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
