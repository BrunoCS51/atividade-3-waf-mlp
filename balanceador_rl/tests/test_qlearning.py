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
    NODE_CAPACITY,
    STATE_BASE_LOAD,
    add_request_load,
    calculate_operational_reward,
    calculate_reward,
    decay_loads,
    load_wait_ms,
    new_q_table,
    node_telemetry,
    policy,
    select_action,
    select_operational_action,
    state_from_loads,
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

    def test_loads_are_discretized_and_capacity_changes_latency(self):
        self.assertEqual(state_from_loads({"node1": 10, "node2": 20, "node3": 30}), "carga_baixa")
        self.assertEqual(state_from_loads({"node1": 50, "node2": 50, "node3": 50}), "carga_media")
        self.assertEqual(state_from_loads({"node1": 80, "node2": 80, "node3": 80}), "carga_alta")
        self.assertLess(load_wait_ms("node1", 50), load_wait_ms("node2", 50))
        self.assertLess(load_wait_ms("node2", 50), load_wait_ms("node3", 50))

    def test_telemetry_combines_capacity_and_concurrency(self):
        self.assertEqual(NODE_CAPACITY, {"node1": 1.0, "node2": 0.25, "node3": 0.05})
        telemetry = node_telemetry(
            {"node1": 30, "node2": 30, "node3": 30},
            {"node1": 2, "node2": 2, "node3": 2},
        )
        self.assertLess(telemetry["node1"]["cpu"], telemetry["node3"]["cpu"])
        self.assertEqual(telemetry["node2"]["active_requests"], 2)
        saturated = node_telemetry(
            {"node1": 95, "node2": 10, "node3": 10},
            {node: 0 for node in ACTIONS},
        )
        self.assertTrue(saturated["node1"]["saturated"])

    def test_exploration_does_not_choose_saturated_node_when_healthy_exists(self):
        table = new_q_table()
        telemetry = node_telemetry(
            {"node1": 95, "node2": 20, "node3": 20},
            {node: 0 for node in ACTIONS},
        )
        action, mode, _ = select_operational_action(
            table, "carga_media", 1.0, telemetry, FixedRandom(0.0, "node1")
        )
        self.assertEqual(mode, "exploracao")
        self.assertIn(action, {"node2", "node3"})

    def test_operational_policy_avoids_saturated_best_q_action(self):
        table = new_q_table()
        table["carga_media"].update(node1=100, node2=20, node3=10)
        telemetry = node_telemetry(
            {"node1": 98, "node2": 30, "node3": 35},
            {node: 0 for node in ACTIONS},
        )
        action, mode, scores = select_operational_action(
            table, "carga_media", 0.0, telemetry, FixedRandom(0.9)
        )
        self.assertEqual((action, mode), ("node2", "explotacao"))
        self.assertLess(scores["node1"], table["carga_media"]["node1"])

    def test_operational_reward_penalizes_saturation(self):
        healthy = calculate_operational_reward(80, False, 50, 1, False)
        overloaded = calculate_operational_reward(80, False, 95, 6, True)
        self.assertEqual(healthy["latency_reward"], 20.0)
        self.assertEqual(healthy["total"], 20.0)
        self.assertLess(overloaded["total"], healthy["total"])
        self.assertEqual(overloaded["saturation_penalty"], 25.0)

    def test_dynamic_load_increases_on_arrival_and_decays_with_time(self):
        initial = {"node1": 40.0, "node2": 40.0, "node3": 40.0}
        received = add_request_load(initial, "node2")
        self.assertEqual(received["node1"], 40.0)
        self.assertGreater(received["node2"], 40.0)
        released = decay_loads(received, 2.0)
        self.assertAlmostEqual(released["node1"], 28.0)
        self.assertLess(released["node2"], received["node2"])
        self.assertEqual(decay_loads({node: 1.0 for node in ACTIONS}, 1.0)["node1"], 0.0)

    def test_residual_impact_is_capacity_aware_but_bounded(self):
        initial = {node: 20.0 for node in ACTIONS}
        node1 = add_request_load(initial, "node1")["node1"] - 20.0
        node3 = add_request_load(initial, "node3")["node3"] - 20.0
        self.assertGreater(node3, node1)
        self.assertLess(node3, 10.0)

    def test_training_states_use_the_same_latency_model_as_simulation(self):
        waits = {}
        for state, base_load in STATE_BASE_LOAD.items():
            waits[state] = {}
            for node in ACTIONS:
                loads = add_request_load({action: base_load for action in ACTIONS}, node)
                active = {action: int(action == node) for action in ACTIONS}
                telemetry = node_telemetry(loads, active)[node]
                waits[state][node] = load_wait_ms(node, telemetry["cpu"], telemetry["active_requests"])
        self.assertLess(waits["carga_alta"]["node1"], 100.0)
        self.assertGreaterEqual(waits["carga_alta"]["node2"], 250.0)
        self.assertGreaterEqual(waits["carga_baixa"]["node3"], 250.0)


if __name__ == "__main__":
    unittest.main()
