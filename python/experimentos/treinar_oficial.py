#!/usr/bin/env python3
"""Executa exatamente uma rodada oficial BP/AG para E1 e E2."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
PYTHON_DIR = ROOT / "python"
TREATMENT_DIR = ROOT / "tratamento_dados"
for import_path in (PYTHON_DIR, TREATMENT_DIR, Path(__file__).resolve().parent):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from experiment_core import (  # noqa: E402
    NormalizadorRobusto,
    calcular_metricas,
    carregar_dataset_csv,
    escolher_threshold_validacao,
    indices_sha256,
    probabilidades,
    salvar_json,
    split_estratificado,
    treinar_ag,
    treinar_bp,
)
from experimentos.experimento_1.config import (  # noqa: E402
    EXPERIMENT_CONFIG as CONFIG_E1,
)
from experimentos.experimento_1.extractor import (  # noqa: E402
    LIMITES as LIMITES_E1,
    NOMES_FEATURES as FEATURES_E1,
)
from experimentos.experimento_2.config import (  # noqa: E402
    EXPERIMENT_CONFIG as CONFIG_E2,
)
from features_http import (  # noqa: E402
    FEATURE_DEFINITIONS,
    FEATURES_EXPERIMENTO_2,
)


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def class_counts(y):
    counts = Counter(int(value) for value in y)
    return {
        "normal_0": counts[0],
        "anomalo_1": counts[1],
        "total": int(len(y)),
    }


def split_legacy_e1(y, seed):
    """Reproduz a divisao RandomState usada originalmente no Experimento 1."""
    rng = np.random.RandomState(seed)
    by_class = []
    for label in (0, 1):
        values = np.where(y == label)[0]
        rng.shuffle(values)
        train_end = int(len(values) * 0.70)
        validation_end = train_end + int(len(values) * 0.15)
        by_class.append((
            values[:train_end],
            values[train_end:validation_end],
            values[validation_end:],
        ))
    result = {}
    for index, name in enumerate(("treino", "validacao", "teste")):
        joined = np.concatenate((by_class[0][index], by_class[1][index]))
        rng.shuffle(joined)
        result[name] = joined.astype(np.int64)
    return result


def prepare_experiment_one(config):
    dataset_path = ROOT / config["dataset"]
    data = np.loadtxt(dataset_path, delimiter=",", dtype=float)
    if data.ndim != 2 or data.shape[1] != 10:
        raise ValueError(f"Dataset E1 inesperado: {data.shape}")
    X = data[:, :9]
    y = data[:, 9]
    if not np.all(np.isin(y, [0.0, 1.0])):
        raise ValueError("Labels invalidas no Experimento 1")
    indices = split_legacy_e1(y, config["seed"])
    limits = np.asarray(LIMITES_E1, dtype=float)
    if list(limits) != list(config["normalization"]["limits"]):
        raise ValueError("Limites do E1 divergem do extractor")

    def transform(values):
        return np.clip(np.asarray(values, dtype=float) / limits, 0.0, 1.0)

    normalization = {
        "estrategia": "limites fixos do extractor do Experimento 1",
        "fit_origem": "configuracao academica original",
        "features": [
            {
                "feature": name,
                "metodo": "divisao_por_limite_e_clip_0_1",
                "limite": float(limit),
            }
            for name, limit in zip(FEATURES_E1, limits)
        ],
    }
    return dataset_path, list(FEATURES_E1), X, y, indices, transform, normalization


def prepare_experiment_two(config):
    dataset_path = ROOT / config["dataset"]
    features = list(FEATURES_EXPERIMENTO_2)
    X, y = carregar_dataset_csv(dataset_path, features)
    if X.shape != (30_000, 76) or y.shape != (30_000,):
        raise ValueError(f"Dataset E2 inesperado: X={X.shape}, y={y.shape}")
    indices = split_estratificado(
        y,
        config["seed"],
        config["split"]["train_ratio"],
        config["split"]["validation_ratio"],
    )
    expected_hashes = config["split"]["expected_indices_sha256"]
    observed_hashes = {
        name: indices_sha256(values) for name, values in indices.items()
    }
    if observed_hashes != expected_hashes:
        raise ValueError("O split reproduzido do E2 diverge do split congelado")
    feature_types = {
        name: FEATURE_DEFINITIONS[name].tipo for name in features
    }
    normalizer = NormalizadorRobusto(
        features,
        feature_types,
        config["normalization"]["upper_quantile"],
    ).fit(X[indices["treino"]], indices["treino"])
    normalization = normalizer.to_dict()
    if normalization["fit_amostras"] != 21_000:
        raise ValueError("Normalizacao E2 nao foi ajustada em 21.000 amostras")

    def transform(values):
        return normalizer.transform(values)

    return dataset_path, features, X, y, indices, transform, normalization


def save_diagnostic_csv(path, history):
    if not history:
        raise ValueError("Historico de treinamento vazio")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(history[0]))
        writer.writeheader()
        writer.writerows(history)


def progress(experiment_id, algorithm):
    def report(record):
        if algorithm == "bp":
            current = record["epoch"]
            total_key = "epoch"
            mse = record["train_mse_after_epoch"]
        else:
            current = record["generation"]
            total_key = "generation"
            mse = record["global_best_train_mse"]
        print(
            f"[{experiment_id}][{algorithm.upper()}] {total_key} {current}: "
            f"mse_treino={mse:.8f}, mse_validacao={record['validation_mse']:.8f}",
            flush=True,
        )
    return report


def feature_contract(features):
    return {
        "count": len(features),
        "ordered_features": list(features),
        "sha256": hashlib.sha256(
            ("\n".join(features) + "\n").encode("ascii")
        ).hexdigest(),
    }


def train_experiment(config, prepared):
    experiment_id = config["experiment_id"]
    base_dir = PYTHON_DIR / "experimentos" / experiment_id
    artifacts = base_dir / "artefatos"
    marker = artifacts / "rodada_oficial.json"
    if marker.exists():
        raise RuntimeError(
            f"A rodada oficial de {experiment_id} ja foi concluida; "
            "uma segunda execucao foi recusada."
        )
    if artifacts.exists() and any(artifacts.iterdir()):
        raise RuntimeError(
            f"Diretorio de artefatos de {experiment_id} deve estar vazio antes da rodada oficial"
        )
    artifacts.mkdir(parents=True, exist_ok=True)

    dataset_path, features, X, y, indices, transform, normalization = prepared
    architecture = list(config["architecture"])
    if architecture != [len(features), len(features) + 1, 1]:
        raise ValueError(f"Arquitetura baseline invalida: {architecture}")

    X_train = transform(X[indices["treino"]])
    y_train = y[indices["treino"]]
    X_validation = transform(X[indices["validacao"]])
    y_validation = y[indices["validacao"]]
    X_test = transform(X[indices["teste"]])
    y_test = y[indices["teste"]]

    split_manifest = {
        "seed": config["seed"],
        "method": config["split"]["method"],
        "estratificado": True,
        "treino": class_counts(y_train),
        "validacao": class_counts(y_validation),
        "teste": class_counts(y_test),
        "indices_sha256": {
            name: indices_sha256(values) for name, values in indices.items()
        },
        "test_used_for_threshold": False,
    }
    np.savez_compressed(
        artifacts / "split_indices.npz",
        treino=indices["treino"],
        validacao=indices["validacao"],
        teste=indices["teste"],
    )
    salvar_json(artifacts / "split_manifest.json", split_manifest)
    salvar_json(artifacts / "configuracao.json", config)
    salvar_json(artifacts / "features.json", feature_contract(features))
    salvar_json(artifacts / "normalizacao.json", normalization)

    inclusive = config["threshold"]["comparison"] == ">="
    results = {}
    experiment_started = time.perf_counter()
    for algorithm in ("bp", "ag"):
        algorithm_dir = artifacts / algorithm
        algorithm_dir.mkdir(parents=True, exist_ok=True)
        algorithm_config = config[
            "backpropagation" if algorithm == "bp" else "genetic_algorithm"
        ]
        seed = int(algorithm_config["seed"])
        print(
            f"Iniciando {experiment_id} {algorithm.upper()} "
            f"com arquitetura {architecture}",
            flush=True,
        )
        if algorithm == "bp":
            model, history, timing = treinar_bp(
                architecture,
                X_train,
                y_train,
                algorithm_config,
                seed,
                X_validation,
                y_validation,
                progress_callback=progress(experiment_id, algorithm),
            )
        else:
            model, history, timing = treinar_ag(
                architecture,
                X_train,
                y_train,
                algorithm_config,
                seed,
                X_validation,
                y_validation,
                progress_callback=progress(experiment_id, algorithm),
            )

        validation_probabilities = probabilidades(model, X_validation)
        threshold_metrics = escolher_threshold_validacao(
            validation_probabilities,
            y_validation,
            config["threshold"]["minimum"],
            config["threshold"]["maximum"],
            config["threshold"]["step"],
            config["security_cost"]["alpha_fn"],
            config["security_cost"]["beta_fp"],
            inclusive=inclusive,
        )
        threshold = threshold_metrics["threshold"]
        train_metrics = calcular_metricas(
            probabilidades(model, X_train),
            y_train,
            threshold,
            inclusive=inclusive,
        )
        test_metrics = calcular_metricas(
            probabilidades(model, X_test),
            y_test,
            threshold,
            inclusive=inclusive,
        )
        weights_path = algorithm_dir / "pesos.json"
        model.save(weights_path)
        save_diagnostic_csv(algorithm_dir / "diagnostico.csv", history)
        result = {
            "experiment_id": experiment_id,
            "algorithm": algorithm,
            "architecture": architecture,
            "parameter_count": int(len(model.get_cromossomo())),
            "seed": seed,
            "parameters": algorithm_config,
            "threshold": threshold,
            "threshold_source": "validacao",
            "threshold_comparison": config["threshold"]["comparison"],
            "training": timing,
            "metrics": {
                "treino": train_metrics,
                "validacao": threshold_metrics,
                "teste": test_metrics,
            },
            "diagnostic": {
                "records": len(history),
                "final": history[-1],
                "path": str(
                    (algorithm_dir / "diagnostico.csv").relative_to(ROOT)
                ).replace("\\", "/"),
            },
            "weights": {
                "path": str(weights_path.relative_to(ROOT)).replace("\\", "/"),
                "sha256": file_sha256(weights_path),
            },
            "test_used_for_threshold": False,
        }
        salvar_json(algorithm_dir / "resultado.json", result)
        results[algorithm] = result
        print(
            f"Concluido {experiment_id} {algorithm.upper()}: "
            f"threshold={threshold:.2f}, F1 teste={test_metrics['f1']:.6f}",
            flush=True,
        )

    official = {
        "experiment_id": experiment_id,
        "title": config["title"],
        "architecture": architecture,
        "feature_count": len(features),
        "dataset": {
            "path": str(dataset_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": file_sha256(dataset_path),
            "samples": int(len(y)),
            "classes": class_counts(y),
        },
        "split": split_manifest,
        "normalization": {
            "path": str((artifacts / "normalizacao.json").relative_to(ROOT)).replace("\\", "/"),
            "fit_source": normalization["fit_origem"],
        },
        "models": results,
        "official_round": 1,
        "architecture_search_performed": False,
        "external_reserved_used": False,
        "total_wall_seconds": float(time.perf_counter() - experiment_started),
    }
    salvar_json(artifacts / "resultados.json", official)
    write_report(artifacts / "relatorio.md", official)
    salvar_json(marker, {
        "official_round": 1,
        "completed_at": datetime.now().astimezone().isoformat(),
        "models": ["bp", "ag"],
        "second_run_blocked_by_default": True,
    })
    return official


def metric_line(metrics):
    return (
        f"TN={metrics['tn']}, FP={metrics['fp']}, FN={metrics['fn']}, "
        f"TP={metrics['tp']}, accuracy={metrics['accuracy']:.6f}, "
        f"precision={metrics['precision']:.6f}, recall={metrics['recall']:.6f}, "
        f"F1={metrics['f1']:.6f}, FPR={metrics['fpr']:.6f}, "
        f"FNR={metrics['fnr']:.6f}"
    )


def write_report(path, result):
    lines = [
        f"# {result['title']} — rodada oficial",
        "",
        f"Arquitetura baseline única: `{' → '.join(map(str, result['architecture']))}`.",
        "Não houve busca de arquitetura e o conjunto reservado não foi utilizado.",
        "",
        "## Dataset e metodologia",
        "",
        f"- Amostras: {result['dataset']['samples']}",
        f"- Treino: {result['split']['treino']['total']}",
        f"- Validação: {result['split']['validacao']['total']}",
        f"- Teste: {result['split']['teste']['total']}",
        f"- Normalização: {result['normalization']['fit_source']}",
        "",
    ]
    for algorithm in ("bp", "ag"):
        model = result["models"][algorithm]
        lines.extend([
            f"## {algorithm.upper()}",
            "",
            f"- Threshold: {model['threshold']:.2f} ({model['threshold_comparison']})",
            f"- Tempo: {model['training']['wall_seconds']:.3f} s",
            f"- Parâmetros: `{json.dumps(model['parameters'], ensure_ascii=False)}`",
            f"- Validação: {metric_line(model['metrics']['validacao'])}",
            f"- Teste: {metric_line(model['metrics']['teste'])}",
            f"- Diagnóstico: `{model['diagnostic']['path']}`",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    print("Preparando Experimento 1", flush=True)
    e1 = train_experiment(CONFIG_E1, prepare_experiment_one(CONFIG_E1))
    print("Preparando Experimento 2", flush=True)
    e2 = train_experiment(CONFIG_E2, prepare_experiment_two(CONFIG_E2))
    print(json.dumps({
        "experimento_1": {
            name: model["metrics"]["teste"] for name, model in e1["models"].items()
        },
        "experimento_2": {
            name: model["metrics"]["teste"] for name, model in e2["models"].items()
        },
    }, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
