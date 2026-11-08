import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ReinforcementLab  # noqa: E402


def result(timeouts, latency):
    return {"timeouts": timeouts, "average_latency_ms": latency}


class ComparisonVerdictTest(unittest.TestCase):
    def test_medium_load_scenario_limit_matches_default_concurrency(self):
        loads = {"node1": 50.0, "node2": 50.0, "node3": 50.0}
        self.assertEqual(ReinforcementLab._scenario_concurrency_limit(loads), 6)

    def test_tiny_latency_difference_is_equivalent(self):
        verdict = ReinforcementLab._comparison_verdict(
            result(10, 348.6), result(10, 348.7), 300
        )
        self.assertTrue(verdict["equivalent"])
        self.assertIsNone(verdict["winner"])

    def test_material_timeout_difference_selects_lower_timeout_result(self):
        verdict = ReinforcementLab._comparison_verdict(
            result(12, 200), result(2, 250), 100
        )
        self.assertFalse(verdict["equivalent"])
        self.assertEqual(verdict["winner"], "q_learning")

    def test_material_latency_difference_requires_equal_timeouts(self):
        verdict = ReinforcementLab._comparison_verdict(
            result(0, 100), result(0, 80), 100
        )
        self.assertEqual(verdict["winner"], "q_learning")


if __name__ == "__main__":
    unittest.main()
