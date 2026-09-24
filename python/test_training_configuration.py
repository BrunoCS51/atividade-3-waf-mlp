"""Valida somente configurações de retreinamento; não executa treinamento."""

import sys
import unittest
from pathlib import Path

PYTHON_DIR = Path(__file__).resolve().parent
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from experimentos.retreinar_modelo import validate_training_request


class TrainingConfigurationTest(unittest.TestCase):
    def test_bp_accepts_multiple_hidden_layers(self):
        result = validate_training_request({
            "experiment_id": "experimento_2",
            "algorithm": "bp",
            "architecture": [76, 77, 39, 1],
            "parameters": {"epochs": 60, "learning_rate": 0.005},
        })
        self.assertEqual(result["architecture"], [76, 77, 39, 1])
        self.assertEqual(result["parameter_count"], 9011)

    def test_ag_exposes_named_operator_codes_without_changing_seed(self):
        result = validate_training_request({
            "experiment_id": "experimento_1",
            "algorithm": "ag",
            "architecture": [9, 10, 1],
            "parameters": {
                "population": 40, "generations": 30,
                "selection_type": 2, "tournament_size": 3,
                "crossover_type": 2, "crossover_rate": 0.8, "sbx_eta": 1,
                "mutation_type": 3, "mutation_rate": 0.02,
                "mutation_sigma": 0.1, "mutation_eta": 20,
                "weight_min": -5, "weight_max": 5,
            },
        })
        self.assertEqual(result["parameters"]["selection_type"], 2)
        self.assertEqual(result["parameters"]["crossover_type"], 2)
        self.assertEqual(result["parameters"]["mutation_type"], 3)
        self.assertEqual(result["parameters"]["seed"], 43)

    def test_rejects_wrong_input_dimension_and_odd_population(self):
        with self.assertRaisesRegex(ValueError, "começar em 76"):
            validate_training_request({
                "experiment_id": "experimento_2", "algorithm": "bp",
                "architecture": [75, 77, 1],
                "parameters": {"epochs": 10, "learning_rate": 0.01},
            })
        with self.assertRaisesRegex(ValueError, "número par"):
            validate_training_request({
                "experiment_id": "experimento_1", "algorithm": "ag",
                "architecture": [9, 10, 1],
                "parameters": {
                    "population": 15, "generations": 10,
                    "selection_type": 1, "tournament_size": 3,
                    "crossover_type": 1, "crossover_rate": 0.8, "sbx_eta": 1,
                    "mutation_type": 1, "mutation_rate": 0.02,
                    "mutation_sigma": 0.1, "mutation_eta": 20,
                    "weight_min": -1, "weight_max": 1,
                },
            })


if __name__ == "__main__":
    unittest.main()
