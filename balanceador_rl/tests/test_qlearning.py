import random
import sys
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from qlearning import (  # noqa: E402
    ACTIONS,
    calculate_reward,
    new_q_table,
    policy,
    select_action,
    update_q_table,
)


class FixedRandom(random.Random):
    def __init__(self, probability, choice_value="node2"):
        super().__init__(42)
        self.probability = probability
        self.choice_value = choice_value

    def random(self):
        return self.probability

    def choice(self, sequence):
        return self.choice_value if self.choice_value in sequence else sequence[0]


class QLearningTest(unittest.TestCase):
    def test_reward_boundaries(self):
        self.assertEqual(calculate_reward(99.99, False), 20.0)
        self.assertEqual(calculate_reward(100.0, False), 2.0)
        self.assertEqual(calculate_reward(249.99, False), 2.0)
        self.assertEqual(calculate_reward(250.0, False), -15.0)
        self.assertEqual(calculate_reward(10.0, True), -100.0)

    def test_epsilon_greedy_explores_and_exploits(self):
        table = new_q_table()
        table["carga_baixa"].update(node1=1.0, node2=9.0, node3=-3.0)
        action, mode = select_action(table, "carga_baixa", 0.30, FixedRandom(0.10, "node3"))
        self.assertEqual((action, mode), ("node3", "exploracao"))
        action, mode = select_action(table, "carga_baixa", 0.30, FixedRandom(0.90))
        self.assertEqual((action, mode), ("node2", "explotacao"))

    def test_bellman_updates_only_executed_cell(self):
        table = new_q_table()
        table["carga_baixa"]["node2"] = 10.0
        table["carga_media"]["node1"] = 20.0
        before = deepcopy(table)
        value = update_q_table(table, "carga_baixa", "node2", 2.0, "carga_media")
        self.assertAlmostEqual(value, 12.25)
        for state in table:
            for action in ACTIONS:
                if (state, action) != ("carga_baixa", "node2"):
                    self.assertEqual(table[state][action], before[state][action])

    def test_policy_uses_highest_q_value_per_state(self):
        table = new_q_table()
        table["carga_baixa"]["node1"] = 3.0
        table["carga_media"]["node2"] = 5.0
        table["carga_alta"]["node3"] = 7.0
        self.assertEqual(policy(table), {
            "carga_baixa": "node1",
            "carga_media": "node2",
            "carga_alta": "node3",
        })


if __name__ == "__main__":
    unittest.main()
