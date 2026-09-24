"""Retreinamento unitário, validado e transacional para uso pelo dashboard."""

from __future__ import annotations

import copy
import csv
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from experiment_core import (
    calcular_metricas,
    escolher_threshold_validacao,
    probabilidades,
    salvar_json,
    treinar_ag,
    treinar_bp,
)
from experimentos.experimento_1.config import EXPERIMENT_CONFIG as CONFIG_E1
from experimentos.experimento_2.config import EXPERIMENT_CONFIG as CONFIG_E2
from experimentos.treinar_oficial import (
    file_sha256,
    prepare_experiment_one,
    prepare_experiment_two,
)


PYTHON_DIR = Path(__file__).resolve().parents[1]
TREATMENT_DIR = PYTHON_DIR.parent / "tratamento_dados"
if not TREATMENT_DIR.exists():
    TREATMENT_DIR = Path("/tratamento_dados")

BASE_CONFIGS = {
    "experimento_1": CONFIG_E1,
    "experimento_2": CONFIG_E2,
}


def _dataset_path(value):
    path = Path(value)
    if path.is_absolute():
        return path
    parts = path.parts
    if parts and parts[0] == "python":
        return PYTHON_DIR.joinpath(*parts[1:])
    if parts and parts[0] == "tratamento_dados":
        return TREATMENT_DIR.joinpath(*parts[1:])
    return PYTHON_DIR.parent / path


def _integer(value, name, minimum, maximum):
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} deve ser inteiro") from error
    if not minimum <= result <= maximum:
        raise ValueError(f"{name} deve estar entre {minimum} e {maximum}")
    return result


def _number(value, name, minimum, maximum, inclusive_min=True):
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} deve ser numérico") from error
    lower_ok = result >= minimum if inclusive_min else result > minimum
    if not lower_ok or result > maximum:
        relation = "maior que" if not inclusive_min else "a partir de"
        raise ValueError(f"{name} deve ser {relation} {minimum} e até {maximum}")
    return result


def _architecture(value, feature_count):
    if not isinstance(value, list):
        raise ValueError("architecture deve ser uma lista")
    architecture = [_integer(item, "neurônios", 1, 512) for item in value]
    if len(architecture) < 3 or len(architecture) > 5:
        raise ValueError("Use de uma a três camadas ocultas")
    if architecture[0] != feature_count or architecture[-1] != 1:
        raise ValueError(f"A arquitetura deve começar em {feature_count} e terminar em 1")
    parameter_count = sum(
        (architecture[index] + 1) * architecture[index + 1]
        for index in range(len(architecture) - 1)
    )
    if parameter_count > 250_000:
        raise ValueError("Arquitetura excede o limite operacional de 250.000 parâmetros")
    return architecture, parameter_count


def validate_training_request(payload):
    experiment_id = str(payload.get("experiment_id", ""))
    algorithm = str(payload.get("algorithm", "")).lower()
    if experiment_id not in BASE_CONFIGS:
        raise ValueError("Experimento inválido")
    if algorithm not in {"bp", "ag"}:
        raise ValueError("Algoritmo deve ser bp ou ag")
    feature_count = int(BASE_CONFIGS[experiment_id]["feature_count"])
    architecture, parameter_count = _architecture(payload.get("architecture"), feature_count)
    supplied = payload.get("parameters")
    if not isinstance(supplied, dict):
        raise ValueError("Parâmetros de treinamento ausentes")
    current_key = "backpropagation" if algorithm == "bp" else "genetic_algorithm"
    parameters = copy.deepcopy(BASE_CONFIGS[experiment_id][current_key])
    if algorithm == "bp":
        parameters["epochs"] = _integer(supplied.get("epochs"), "Épocas", 1, 2_000)
        parameters["learning_rate"] = _number(
            supplied.get("learning_rate"), "Learning rate", 0.0, 1.0, inclusive_min=False
        )
    else:
        parameters.pop("viability_note", None)
        parameters["population"] = _integer(supplied.get("population"), "População", 4, 500)
        if parameters["population"] % 2:
            raise ValueError("População deve ser um número par")
        parameters["generations"] = _integer(supplied.get("generations"), "Gerações", 1, 1_000)
        parameters["selection_type"] = _integer(supplied.get("selection_type"), "Seleção", 1, 2)
        parameters["tournament_size"] = _integer(
            supplied.get("tournament_size"), "Tamanho do torneio", 2, parameters["population"]
        )
        parameters["crossover_type"] = _integer(supplied.get("crossover_type"), "Crossover", 1, 2)
        parameters["crossover_rate"] = _number(supplied.get("crossover_rate"), "Taxa de crossover", 0.0, 1.0)
        parameters["sbx_eta"] = _number(supplied.get("sbx_eta"), "Eta SBX", 0.01, 100.0)
        parameters["mutation_type"] = _integer(supplied.get("mutation_type"), "Mutação", 1, 3)
        parameters["mutation_rate"] = _number(supplied.get("mutation_rate"), "Taxa de mutação", 0.0, 1.0)
        parameters["mutation_sigma"] = _number(supplied.get("mutation_sigma"), "Sigma", 0.0, 10.0)
        parameters["mutation_eta"] = _number(supplied.get("mutation_eta"), "Eta da mutação", 0.01, 200.0)
        parameters["weight_min"] = _number(supplied.get("weight_min"), "Gene mínimo", -100.0, 100.0)
        parameters["weight_max"] = _number(supplied.get("weight_max"), "Gene máximo", -100.0, 100.0)
        if parameters["weight_min"] >= parameters["weight_max"]:
            raise ValueError("Gene mínimo deve ser menor que o gene máximo")
    return {
        "experiment_id": experiment_id,
        "algorithm": algorithm,
        "architecture": architecture,
        "parameter_count": parameter_count,
        "parameters": parameters,
    }


def estimate_seconds(validated):
    experiment_id = validated["experiment_id"]
    algorithm = validated["algorithm"]
    artifact = PYTHON_DIR / "experimentos" / experiment_id / "artefatos" / algorithm / "resultado.json"
    try:
        current = json.loads(artifact.read_text(encoding="utf-8"))
        seconds = float(current["training"]["wall_seconds"])
        current_parameters = current["parameters"]
        current_count = int(current["parameter_count"])
        ratio = validated["parameter_count"] / max(current_count, 1)
        if algorithm == "bp":
            ratio *= validated["parameters"]["epochs"] / max(int(current_parameters["epochs"]), 1)
        else:
            ratio *= validated["parameters"]["population"] / max(int(current_parameters["population"]), 1)
            ratio *= validated["parameters"]["generations"] / max(int(current_parameters["generations"]), 1)
        return max(1.0, seconds * ratio)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_diagnostic(path, history):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)
    temporary.replace(path)


def _archive_current(experiment_id, algorithm):
    base = PYTHON_DIR / "experimentos" / experiment_id
    artifacts = base / "artefatos"
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
    archive = base / "historico_treinamentos" / f"{stamp}-{algorithm}"
    archive.mkdir(parents=True, exist_ok=False)
    shutil.copytree(artifacts / algorithm, archive / algorithm)
    for name in ("resultados.json", "configuracao.json", "relatorio.md"):
        source = artifacts / name
        if source.is_file():
            shutil.copy2(source, archive / name)
    return archive


def _write_report(path, result):
    lines = [
        f"# {result['title']} — estado atual dos modelos",
        "",
        "Cada modelo pode possuir arquitetura e configuração próprias após retreinamento controlado.",
        "O conjunto reservado externo não participa do treinamento.",
        "",
    ]
    for algorithm in ("bp", "ag"):
        model = result["models"][algorithm]
        metrics = model["metrics"]["teste"]
        lines.extend([
            f"## {algorithm.upper()}", "",
            f"- Arquitetura: `{' → '.join(map(str, model['architecture']))}`",
            f"- Threshold: {model['threshold']:.2f} ({model['threshold_comparison']})",
            f"- Tempo: {model['training']['wall_seconds']:.3f} s",
            f"- Teste: TN={metrics['tn']}, FP={metrics['fp']}, FN={metrics['fn']}, TP={metrics['tp']}, F1={metrics['f1']:.6f}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def retrain_model(payload, progress_callback=None):
    validated = validate_training_request(payload)
    experiment_id = validated["experiment_id"]
    algorithm = validated["algorithm"]
    architecture = validated["architecture"]
    algorithm_parameters = validated["parameters"]
    artifacts = PYTHON_DIR / "experimentos" / experiment_id / "artefatos"
    current_config = json.loads((artifacts / "configuracao.json").read_text(encoding="utf-8"))
    config = copy.deepcopy(BASE_CONFIGS[experiment_id])
    config.update({key: value for key, value in current_config.items() if key not in {"architecture", "model_architectures"}})
    config["dataset"] = str(_dataset_path(config["dataset"]))
    config["architecture"] = architecture
    config["backpropagation" if algorithm == "bp" else "genetic_algorithm"] = algorithm_parameters
    prepared = prepare_experiment_one(config) if experiment_id == "experimento_1" else prepare_experiment_two(config)
    _, features, X, y, indices, transform, _ = prepared
    X_train = transform(X[indices["treino"]])
    y_train = y[indices["treino"]]
    X_validation = transform(X[indices["validacao"]])
    y_validation = y[indices["validacao"]]
    X_test = transform(X[indices["teste"]])
    y_test = y[indices["teste"]]
    total = int(algorithm_parameters["epochs" if algorithm == "bp" else "generations"])

    def report(record):
        if progress_callback:
            current = int(record["epoch" if algorithm == "bp" else "generation"])
            progress_callback(current, total, record)

    seed = int(algorithm_parameters["seed"])
    if algorithm == "bp":
        model, history, timing = treinar_bp(
            architecture, X_train, y_train, algorithm_parameters, seed,
            X_validation, y_validation, progress_callback=report,
        )
    else:
        model, history, timing = treinar_ag(
            architecture, X_train, y_train, algorithm_parameters, seed,
            X_validation, y_validation, progress_callback=report,
        )
    inclusive = config["threshold"]["comparison"] == ">="
    validation_metrics = escolher_threshold_validacao(
        probabilidades(model, X_validation), y_validation,
        config["threshold"]["minimum"], config["threshold"]["maximum"],
        config["threshold"]["step"], config["security_cost"]["alpha_fn"],
        config["security_cost"]["beta_fp"], inclusive=inclusive,
    )
    threshold = validation_metrics["threshold"]
    result = {
        "experiment_id": experiment_id,
        "algorithm": algorithm,
        "architecture": architecture,
        "parameter_count": validated["parameter_count"],
        "seed": seed,
        "parameters": algorithm_parameters,
        "threshold": threshold,
        "threshold_source": "validacao",
        "threshold_comparison": config["threshold"]["comparison"],
        "training": timing,
        "metrics": {
            "treino": calcular_metricas(probabilidades(model, X_train), y_train, threshold, inclusive),
            "validacao": validation_metrics,
            "teste": calcular_metricas(probabilidades(model, X_test), y_test, threshold, inclusive),
        },
        "diagnostic": {
            "records": len(history),
            "final": history[-1],
            "path": f"python/experimentos/{experiment_id}/artefatos/{algorithm}/diagnostico.csv",
        },
        "weights": {},
        "test_used_for_threshold": False,
        "retrained_at": datetime.now().astimezone().isoformat(),
    }

    archive = _archive_current(experiment_id, algorithm)
    algorithm_dir = artifacts / algorithm
    weights_tmp = algorithm_dir / "pesos.json.retrain.tmp"
    model.save(weights_tmp)
    result["weights"] = {
        "path": f"python/experimentos/{experiment_id}/artefatos/{algorithm}/pesos.json",
        "sha256": file_sha256(weights_tmp),
    }
    weights_tmp.replace(algorithm_dir / "pesos.json")
    _write_diagnostic(algorithm_dir / "diagnostico.csv", history)
    salvar_json(algorithm_dir / "resultado.json", result)

    combined = json.loads((artifacts / "resultados.json").read_text(encoding="utf-8"))
    combined["models"][algorithm] = result
    model_architectures = {
        name: combined["models"][name]["architecture"] for name in ("bp", "ag")
    }
    combined["model_architectures"] = model_architectures
    if model_architectures["bp"] == model_architectures["ag"]:
        combined["architecture"] = model_architectures["bp"]
    combined["architecture_search_performed"] = True
    combined["last_retraining"] = {
        "algorithm": algorithm,
        "completed_at": result["retrained_at"],
        "previous_artifacts": str(archive.relative_to(PYTHON_DIR.parent)).replace("\\", "/"),
    }
    combined["total_wall_seconds"] = sum(
        float(combined["models"][name]["training"]["wall_seconds"]) for name in ("bp", "ag")
    )
    salvar_json(artifacts / "resultados.json", combined)

    current_config["model_architectures"] = model_architectures
    current_config["backpropagation" if algorithm == "bp" else "genetic_algorithm"] = algorithm_parameters
    if model_architectures["bp"] == model_architectures["ag"]:
        current_config["architecture"] = model_architectures["bp"]
    salvar_json(artifacts / "configuracao.json", current_config)
    _write_report(artifacts / "relatorio.md", combined)
    return {
        "experiment_id": experiment_id,
        "algorithm": algorithm,
        "architecture": architecture,
        "training": timing,
        "threshold": threshold,
        "validation": validation_metrics,
        "test": result["metrics"]["teste"],
        "archive": str(archive),
    }
