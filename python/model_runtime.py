"""Carregamento e inferência comuns dos quatro modelos oficiais."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np


PYTHON_DIR = Path(__file__).resolve().parent
PROJECT_DIR = PYTHON_DIR.parent
TREATMENT_DIR = PROJECT_DIR / "tratamento_dados"
if not TREATMENT_DIR.exists():
    TREATMENT_DIR = Path("/tratamento_dados")
for import_path in (PYTHON_DIR, TREATMENT_DIR):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from experiment_core import NormalizadorRobusto  # noqa: E402
from experimentos.experimento_1.extractor import extract_features  # noqa: E402
from features_http import (  # noqa: E402
    FEATURES_EXPERIMENTO_2,
    HTTPRequest,
    extrair_features_experimento_2,
)
from mlp import MLP  # noqa: E402


MODEL_IDS = (
    "experimento_1:bp",
    "experimento_1:ag",
    "experimento_2:bp",
    "experimento_2:ag",
)


@dataclass(frozen=True)
class ModelDecision:
    model_id: str
    experiment_id: str
    algorithm: str
    score: float
    threshold: float
    comparison: str
    blocked: bool

    @property
    def decision(self) -> str:
        return "BLOQUEIA" if self.blocked else "LIBERA"


@dataclass(frozen=True)
class ParallelDecision:
    primary_model: str
    operational: ModelDecision
    experiment_one: ModelDecision
    experiment_two: ModelDecision


class OfficialModel:
    def __init__(self, model_id: str, artifacts_dir: Path):
        self.model_id = model_id
        self.experiment_id, self.algorithm = model_id.split(":", 1)
        result_path = artifacts_dir / self.algorithm / "resultado.json"
        weights_path = artifacts_dir / self.algorithm / "pesos.json"
        with result_path.open("r", encoding="utf-8") as stream:
            result = json.load(stream)
        self.architecture = [int(value) for value in result["architecture"]]
        self.threshold = float(result["threshold"])
        self.comparison = result["threshold_comparison"]
        if self.comparison not in {">", ">="}:
            raise ValueError(f"Comparador inválido em {result_path}")
        self.network = MLP(architecture=self.architecture)
        self.network.load(weights_path)
        if self.network.rede.tolist() != self.architecture:
            raise ValueError(f"Arquitetura dos pesos diverge em {model_id}")

    def infer(self, vector: Sequence[float]) -> ModelDecision:
        if len(vector) != self.architecture[0]:
            raise ValueError(f"Vetor incompatível com {self.model_id}")
        score = float(self.network.forward(vector)[0])
        blocked = score >= self.threshold if self.comparison == ">=" else score > self.threshold
        return ModelDecision(
            self.model_id, self.experiment_id, self.algorithm, score,
            self.threshold, self.comparison, blocked,
        )


def normalize_model_id(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace("/", ":")
    aliases = {
        "e1:bp": "experimento_1:bp", "e1:ag": "experimento_1:ag",
        "e2:bp": "experimento_2:bp", "e2:ag": "experimento_2:ag",
        "experimento_1:bp": "experimento_1:bp",
        "experimento_1:ag": "experimento_1:ag",
        "experimento_2:bp": "experimento_2:bp",
        "experimento_2:ag": "experimento_2:ag",
    }
    try:
        return aliases[normalized]
    except KeyError as error:
        raise ValueError(
            "Modelo deve ser experimento_1:bp, experimento_1:ag, "
            "experimento_2:bp ou experimento_2:ag"
        ) from error


class WAFRuntime:
    """Executa E1 e E2 em paralelo; somente ``primary_model`` decide o HTTP."""

    def __init__(
        self,
        primary_model: str = "experimento_1:bp",
        shadow_e1_algorithm: str = "bp",
        shadow_e2_algorithm: str = "bp",
        base_dir: Path = PYTHON_DIR,
    ):
        self.primary_model = normalize_model_id(primary_model)
        self.shadow_algorithms = {
            "experimento_1": self._algorithm(shadow_e1_algorithm),
            "experimento_2": self._algorithm(shadow_e2_algorithm),
        }
        self.models = {}
        for model_id in MODEL_IDS:
            experiment_id, _ = model_id.split(":", 1)
            artifacts = base_dir / "experimentos" / experiment_id / "artefatos"
            self.models[model_id] = OfficialModel(model_id, artifacts)

        expected_inputs = {"experimento_1": 9, "experimento_2": 76}
        for model_id, model in self.models.items():
            experiment_id, _ = model_id.split(":", 1)
            if model.architecture[0] != expected_inputs[experiment_id] or model.architecture[-1] != 1:
                raise ValueError(f"Arquitetura incompatível com as features em {model_id}")

        normalization_path = base_dir / "experimentos" / "experimento_2" / "artefatos" / "normalizacao.json"
        with normalization_path.open("r", encoding="utf-8") as stream:
            normalization = json.load(stream)
        self.e2_normalizer = NormalizadorRobusto.from_dict(normalization)
        if self.e2_normalizer.feature_names != list(FEATURES_EXPERIMENTO_2):
            raise ValueError("Ordem da normalização E2 diverge do extractor")

    @staticmethod
    def _algorithm(value: str) -> str:
        algorithm = value.strip().lower()
        if algorithm not in {"bp", "ag"}:
            raise ValueError("Algoritmo shadow deve ser bp ou ag")
        return algorithm

    def algorithm_for(self, experiment_id: str) -> str:
        primary_experiment, primary_algorithm = self.primary_model.split(":", 1)
        return primary_algorithm if experiment_id == primary_experiment else self.shadow_algorithms[experiment_id]

    @staticmethod
    def _http_request(headers, target, method, version, body):
        grouped: dict[str, list[str]] = {}
        ignored = {
            "x-original-uri", "x-original-target", "x-original-method",
            "x-real-ip", "x-forwarded-for", "x-forwarded-proto",
        }
        for name, value in headers.items():
            if name.lower() not in ignored:
                grouped.setdefault(name, []).append(value)
        return HTTPRequest.from_components(method, target, version, grouped, body)

    def evaluate(self, headers, target, method, version, body, client_ip):
        e1_vector, _ = extract_features(
            headers, target, method, body.decode("utf-8", errors="replace"), client_ip
        )
        request_e2 = self._http_request(headers, target, method, version, body)
        e2_raw = np.asarray(extrair_features_experimento_2(request_e2), dtype=float).reshape(1, -1)
        e2_vector = self.e2_normalizer.transform(e2_raw)[0]

        e1_model = f"experimento_1:{self.algorithm_for('experimento_1')}"
        e2_model = f"experimento_2:{self.algorithm_for('experimento_2')}"
        e1 = self.models[e1_model].infer(e1_vector)
        e2 = self.models[e2_model].infer(e2_vector)
        operational = e1 if self.primary_model == e1_model else e2
        if operational.model_id != self.primary_model:
            raise AssertionError("Modelo operacional não corresponde ao principal")
        return ParallelDecision(self.primary_model, operational, e1, e2)
