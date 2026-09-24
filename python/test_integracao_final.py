"""Testes mínimos de integridade da reorganização final (sem treinamento)."""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


PYTHON_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PYTHON_DIR.parent
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from model_runtime import MODEL_IDS, WAFRuntime  # noqa: E402


def load_json(path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


class FinalIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e1 = PYTHON_DIR / "experimentos" / "experimento_1" / "artefatos"
        cls.e2 = PYTHON_DIR / "experimentos" / "experimento_2" / "artefatos"

    def test_four_models_and_separate_artifacts(self):
        expected_inputs = {"experimento_1": 9, "experimento_2": 76}
        hashes = set()
        for model_id in MODEL_IDS:
            experiment, algorithm = model_id.split(":")
            base = self.e1 if experiment == "experimento_1" else self.e2
            result = load_json(base / algorithm / "resultado.json")
            weights = base / algorithm / "pesos.json"
            architecture = result["architecture"]
            self.assertEqual(architecture[0], expected_inputs[experiment])
            self.assertEqual(architecture[-1], 1)
            self.assertGreaterEqual(len(architecture), 3)
            self.assertLessEqual(len(architecture), 5)
            self.assertEqual(result["threshold_source"], "validacao")
            self.assertFalse(result["test_used_for_threshold"])
            hashes.add(hashlib.sha256(weights.read_bytes()).hexdigest())
        self.assertEqual(len(hashes), 4)

    def test_frozen_e2_split_and_train_only_normalization(self):
        split = load_json(self.e2 / "split_manifest.json")
        normalization = load_json(self.e2 / "normalizacao.json")
        self.assertEqual(split["treino"]["total"], 21000)
        self.assertEqual(split["validacao"]["total"], 4500)
        self.assertEqual(split["teste"]["total"], 4500)
        self.assertEqual(normalization["fit_amostras"], 21000)
        self.assertEqual(normalization["fit_indices_sha256"], split["indices_sha256"]["treino"])

    def test_same_request_parallel_and_primary_controls_response(self):
        if importlib.util.find_spec("flask") is None:
            self.skipTest("Flask não instalado no host; caso executado no container WAF")
        from server import create_app

        headers = {
            "Host": "localhost", "User-Agent": "Mozilla/5.0",
            "X-Original-URI": "/", "X-Original-Target": "http://localhost/",
            "X-Original-Method": "GET", "X-Real-IP": "integration-test",
        }
        with tempfile.TemporaryDirectory() as directory:
            e1_app = create_app(WAFRuntime("experimento_1:bp"), Path(directory) / "e1.csv")
            e2_app = create_app(WAFRuntime("experimento_2:bp"), Path(directory) / "e2.csv")
            e1_response = e1_app.test_client().get("/", headers=headers)
            e2_response = e2_app.test_client().get("/", headers=headers)
            self.assertIn("X-WAF-E1-Score", e1_response.headers)
            self.assertIn("X-WAF-E2-Score", e1_response.headers)
            self.assertEqual(e1_response.status_code, 200)
            self.assertEqual(e2_response.status_code, 403)
            self.assertEqual(e1_response.headers["X-WAF-E2-Decision"], "BLOQUEIA")
            self.assertEqual(e1_response.headers["X-WAF-Decision"], "NORMAL")
            with (Path(directory) / "e1.csv").open(encoding="utf-8", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["primary_model"], "experimento_1:bp")
            self.assertEqual(row["operational_decision"], "LIBERA")

    def test_dashboard_reads_artifacts_and_empty_history(self):
        spec = importlib.util.spec_from_file_location(
            "dashboard_server", PROJECT_DIR / "dashboard" / "server.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.DATA_DIR = PYTHON_DIR
        data = module.build_data()
        self.assertEqual(set(data["experiments"]), {"experimento_1", "experimento_2"})
        self.assertEqual(data["experiments"]["experimento_1"]["architecture"], [9, 10, 1])
        self.assertEqual(data["experiments"]["experimento_2"]["architecture"], [76, 77, 1])
        with tempfile.TemporaryDirectory() as directory:
            module.DATA_DIR = Path(directory)
            self.assertEqual(module.request_page()["total"], 0)


if __name__ == "__main__":
    unittest.main()
