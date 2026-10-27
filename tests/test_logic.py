import unittest

from src.logic import (
    calculate_direction,
    calculate_distance,
    calculate_group_synchrony,
    calculate_pair_distances,
    calculate_speed,
    calculate_synchrony,
    calculate_velocity,
)
from src.vision import PoseDetection, PoseTracker


class InteractionMetricsTests(unittest.TestCase):
    def test_distance_between_normalized_centers(self) -> None:
        self.assertAlmostEqual(calculate_distance((0, 0), (0.3, 0.4)), 0.5)

    def test_velocity_uses_elapsed_time(self) -> None:
        velocity = calculate_velocity((0.2, 0.4), (0.4, 0.1), 2)
        self.assertAlmostEqual(velocity[0], 0.1)
        self.assertAlmostEqual(velocity[1], -0.15)
        self.assertAlmostEqual(
            calculate_speed(velocity), (0.1**2 + 0.15**2) ** 0.5
        )

    def test_velocity_requires_positive_elapsed_time(self) -> None:
        with self.assertRaises(ValueError):
            calculate_velocity((0, 0), (1, 1), 0)

    def test_direction_uses_image_axes(self) -> None:
        self.assertAlmostEqual(calculate_direction((1, 1)), 45)
        self.assertAlmostEqual(calculate_direction((0, -1)), 270)
        self.assertIsNone(calculate_direction((0, 0)))

    def test_synchrony_accounts_for_direction_and_speed(self) -> None:
        self.assertAlmostEqual(calculate_synchrony((1, 0), (1, 0)), 1)
        self.assertAlmostEqual(calculate_synchrony((1, 0), (-1, 0)), 0)
        self.assertAlmostEqual(calculate_synchrony((1, 0), (0, 1)), 0.5)
        self.assertAlmostEqual(calculate_synchrony((1, 0), (0.5, 0)), 0.5)
        self.assertIsNone(calculate_synchrony((0, 0), (1, 0)))

    def test_group_synchrony_averages_moving_pairs(self) -> None:
        self.assertAlmostEqual(
            calculate_group_synchrony(
                [(1, 0), (1, 0), (-1, 0), (0, 0)]
            ),
            1 / 3,
        )
        self.assertIsNone(calculate_group_synchrony([(0, 0), (0, 0)]))

    def test_pair_distances_are_sorted_by_participant_id(self) -> None:
        self.assertEqual(
            calculate_pair_distances({2: (1, 0), 1: (0, 0)}),
            [(1, 2, 1.0)],
        )


class PoseTrackerMetricsTests(unittest.TestCase):
    def test_tracker_preserves_displacement_and_calculates_velocity(self) -> None:
        tracker = PoseTracker()
        first = PoseDetection(
            (0.2, 0.4), None, None, None, None, None, None, None, None
        )
        second = PoseDetection(
            (0.3, 0.4), None, None, None, None, None, None, None, None
        )

        initial = tracker.update([first], 1.0)[0]
        updated = tracker.update([second], 1.5)[0]

        self.assertEqual(initial.movement, 0.0)
        self.assertAlmostEqual(updated.movement, 0.1)
        self.assertAlmostEqual(updated.velocity[0], 0.2)
        self.assertAlmostEqual(updated.velocity[1], 0.0)


if __name__ == "__main__":
    unittest.main()
