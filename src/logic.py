from __future__ import annotations

from itertools import combinations
from math import atan2, degrees, hypot
from typing import Mapping, Sequence


Point = tuple[float, float]
_MIN_MOVING_SPEED = 1e-9


def calculate_distance(first: Point, second: Point) -> float:
    """Return the Euclidean distance between normalized image points."""
    return hypot(second[0] - first[0], second[1] - first[1])


def calculate_velocity(
    previous: Point, current: Point, elapsed_seconds: float
) -> Point:
    """Return normalized image displacement per second."""
    if elapsed_seconds <= 0:
        raise ValueError("elapsed_seconds debe ser mayor que cero.")
    return (
        (current[0] - previous[0]) / elapsed_seconds,
        (current[1] - previous[1]) / elapsed_seconds,
    )


def calculate_speed(velocity: Point) -> float:
    """Return the magnitude of a normalized image velocity."""
    return hypot(velocity[0], velocity[1])


def calculate_direction(velocity: Point) -> float | None:
    """Return direction in degrees (right=0, down=90), or None if stationary."""
    if calculate_speed(velocity) <= _MIN_MOVING_SPEED:
        return None
    return degrees(atan2(velocity[1], velocity[0])) % 360


def calculate_synchrony(
    first_velocity: Point, second_velocity: Point
) -> float | None:
    """Compare two participants' instantaneous direction and speed (0 to 1).

    Stationary participants are excluded because their movement direction is
    undefined. A score of 1 means equal speeds in the same direction.
    """
    first_speed = calculate_speed(first_velocity)
    second_speed = calculate_speed(second_velocity)
    if min(first_speed, second_speed) <= _MIN_MOVING_SPEED:
        return None

    cosine = (
        first_velocity[0] * second_velocity[0]
        + first_velocity[1] * second_velocity[1]
    ) / (first_speed * second_speed)
    direction_similarity = (max(-1.0, min(1.0, cosine)) + 1.0) / 2.0
    speed_similarity = min(first_speed, second_speed) / max(
        first_speed, second_speed
    )
    return direction_similarity * speed_similarity


def calculate_group_synchrony(velocities: Sequence[Point]) -> float | None:
    """Return mean instantaneous synchrony for all pairs of moving people."""
    scores = [
        score
        for first, second in combinations(velocities, 2)
        if (score := calculate_synchrony(first, second)) is not None
    ]
    if not scores:
        return None
    return sum(scores) / len(scores)


def calculate_pair_distances(
    positions: Mapping[int, Point],
) -> list[tuple[int, int, float]]:
    """Return normalized center distances for each pair of participant IDs."""
    return [
        (first_id, second_id, calculate_distance(first, second))
        for (first_id, first), (second_id, second) in combinations(
            sorted(positions.items()), 2
        )
    ]
