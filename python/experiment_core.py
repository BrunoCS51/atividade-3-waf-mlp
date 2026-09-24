"""Infraestrutura comum e configurável para experimentos com a MLP acadêmica."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ga import criar_populacao, crossover, fitness, mutacao, selecao
from mlp import MLP


def carregar_dataset_csv(path, feature_names, label_name="label"):
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as stream:
        header = next(csv.reader(stream))
    expected = [*feature_names, label_name]
    if header != expected:
        raise ValueError(
            "Contrato do dataset incompatível. "
            f"Esperado {len(expected)} colunas na ordem congelada."
        )
    data = np.loadtxt(path, delimiter=",", skiprows=1, dtype=float)
    if data.ndim != 2 or data.shape[1] != len(expected):
        raise ValueError(f"Dimensão inesperada do dataset: {data.shape}")
    X = data[:, :-1]
    y = data[:, -1]
    if not np.all(np.isfinite(X)):
        raise ValueError("Dataset contém feature não finita")
    if not np.all(np.isin(y, [0.0, 1.0])):
        raise ValueError("Label deve conter somente 0 e 1")
    return X, y


def split_estratificado(y, seed, train_ratio=0.70, validation_ratio=0.15):
    y = np.asarray(y)
    rng = np.random.default_rng(seed)
    groups = {"treino": [], "validacao": [], "teste": []}
    for label in sorted(np.unique(y)):
        indices = np.where(y == label)[0]
        indices = rng.permutation(indices)
        train_end = int(len(indices) * train_ratio)
        validation_end = train_end + int(len(indices) * validation_ratio)
        groups["treino"].append(indices[:train_end])
        groups["validacao"].append(indices[train_end:validation_end])
        groups["teste"].append(indices[validation_end:])
    result = {}
    for name, parts in groups.items():
        joined = np.concatenate(parts).astype(np.int64)
        result[name] = rng.permutation(joined)
    all_indices = np.concatenate(list(result.values()))
    if len(all_indices) != len(y) or len(np.unique(all_indices)) != len(y):
        raise AssertionError("Split perdeu ou repetiu amostras")
    return result


def indices_sha256(indices):
    canonical = np.sort(np.asarray(indices, dtype=np.int64)).astype(">i8", copy=False)
    return hashlib.sha256(canonical.tobytes()).hexdigest()


class NormalizadorRobusto:
    """Normalização feature-aware ajustada exclusivamente no treino."""

    def __init__(self, feature_names, feature_types, quantile=0.995):
        self.feature_names = list(feature_names)
        self.feature_types = dict(feature_types)
        self.quantile = float(quantile)
        self.parameters = []
        self.fit_sample_count = 0
        self.fit_indices_sha256 = None

    def fit(self, X_train, train_indices):
        X_train = np.asarray(X_train, dtype=float)
        if X_train.shape[1] != len(self.feature_names):
            raise ValueError("Número de features incompatível na normalização")
        self.parameters = []
        for column, name in enumerate(self.feature_names):
            values = X_train[:, column]
            feature_type = self.feature_types[name]
            if feature_type == "binaria":
                spec = {"feature": name, "metodo": "binaria_identidade"}
            elif name.endswith("_ratio"):
                spec = {"feature": name, "metodo": "razao_clip_0_1"}
            elif feature_type == "contagem_assinada":
                scale = float(np.quantile(np.abs(values), self.quantile))
                if not math.isfinite(scale) or scale <= 0:
                    scale = 1.0
                spec = {
                    "feature": name,
                    "metodo": "escala_assinada_robusta",
                    "escala_abs_p995": scale,
                }
            else:
                cap = float(np.quantile(values, self.quantile))
                if not math.isfinite(cap) or cap <= 0:
                    cap = 1.0
                spec = {
                    "feature": name,
                    "metodo": "cap_robusto_divisao",
                    "limite_superior_p995": cap,
                }
            self.parameters.append(spec)
        self.fit_sample_count = int(X_train.shape[0])
        self.fit_indices_sha256 = indices_sha256(train_indices)
        return self

    def transform(self, X):
        if not self.parameters:
            raise RuntimeError("Normalizador ainda não ajustado")
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(self.parameters):
            raise ValueError("Matriz incompatível com o normalizador")
        transformed = np.empty_like(X, dtype=float)
        for column, spec in enumerate(self.parameters):
            values = X[:, column]
            method = spec["metodo"]
            if method in {"binaria_identidade", "razao_clip_0_1"}:
                transformed[:, column] = np.clip(values, 0.0, 1.0)
            elif method == "escala_assinada_robusta":
                transformed[:, column] = np.clip(
                    values / spec["escala_abs_p995"], -1.0, 1.0
                )
            elif method == "cap_robusto_divisao":
                transformed[:, column] = np.clip(
                    values / spec["limite_superior_p995"], 0.0, 1.0
                )
            else:
                raise ValueError(f"Método desconhecido: {method}")
        if not np.all(np.isfinite(transformed)):
            raise ValueError("Normalização produziu valor não finito")
        return transformed

    def to_dict(self):
        return {
            "estrategia": "feature-aware robusta; fit somente no treino",
            "quantil_cap": self.quantile,
            "fit_origem": "treino",
            "fit_amostras": self.fit_sample_count,
            "fit_indices_sha256": self.fit_indices_sha256,
            "features": self.parameters,
        }

    @classmethod
    def from_dict(cls, data, feature_types=None):
        parameters = list(data["features"])
        feature_names = [item["feature"] for item in parameters]
        instance = cls(
            feature_names,
            feature_types or {name: "carregado" for name in feature_names},
            data["quantil_cap"],
        )
        instance.parameters = parameters
        instance.fit_sample_count = int(data["fit_amostras"])
        instance.fit_indices_sha256 = data["fit_indices_sha256"]
        return instance


def probabilidades(mlp, X):
    output = mlp.forward_batch(X)
    if output.shape != (len(X), 1):
        raise ValueError(f"Saída inesperada da MLP: {output.shape}")
    return output[:, 0]


def calcular_metricas(probabilities, y, threshold, inclusive=False):
    probabilities = np.asarray(probabilities, dtype=float)
    y = np.asarray(y, dtype=int)
    predicted = (
        probabilities >= threshold
        if inclusive
        else probabilities > threshold
    ).astype(int)
    tp = int(np.sum((y == 1) & (predicted == 1)))
    tn = int(np.sum((y == 0) & (predicted == 0)))
    fp = int(np.sum((y == 0) & (predicted == 1)))
    fn = int(np.sum((y == 1) & (predicted == 0)))

    def safe(num, den):
        return float(num / den) if den else 0.0

    precision = safe(tp, tp + fp)
    recall = safe(tp, tp + fn)
    return {
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "tp": tp,
        "accuracy": safe(tp + tn, tp + tn + fp + fn),
        "precision": precision,
        "recall": recall,
        "f1": safe(2 * precision * recall, precision + recall),
        "fpr": safe(fp, fp + tn),
        "fnr": safe(fn, fn + tp),
        "threshold": float(threshold),
    }


def escolher_threshold_validacao(
    probabilities,
    y_validation,
    minimum,
    maximum,
    step,
    alpha_fn,
    beta_fp,
    inclusive=False,
):
    best = None
    best_key = None
    thresholds = np.arange(minimum, maximum + step / 2.0, step)
    for threshold in thresholds:
        metrics = calcular_metricas(
            probabilities,
            y_validation,
            float(threshold),
            inclusive=inclusive,
        )
        metrics["security_cost"] = float(
            alpha_fn * metrics["fn"] + beta_fp * metrics["fp"]
        )
        key = (
            metrics["security_cost"],
            metrics["fn"],
            metrics["fp"],
            -metrics["f1"],
            -metrics["precision"],
            -metrics["recall"],
            -metrics["accuracy"],
            metrics["threshold"],
        )
        if best_key is None or key < best_key:
            best_key = key
            best = metrics
    best["threshold_source"] = "validacao"
    best["security_cost_formula"] = "alpha_fn * FN + beta_fp * FP"
    best["alpha_fn"] = float(alpha_fn)
    best["beta_fp"] = float(beta_fp)
    return best


def _mse(mlp, X, y):
    prediction = probabilidades(mlp, X)
    return float(np.mean((y - prediction) ** 2))


def treinar_bp(
    architecture,
    X_train,
    y_train,
    config,
    seed,
    X_validation=None,
    y_validation=None,
    progress_callback=None,
):
    np.random.seed(seed)
    mlp = MLP(architecture=architecture)
    rng = np.random.default_rng(seed)
    history = []
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    for epoch in range(int(config["epochs"])):
        epoch_start = time.perf_counter()
        epoch_cpu_start = time.process_time()
        order = rng.permutation(len(X_train))
        online_mse = 0.0
        activation_total = 0
        saturation_total = 0
        delta_sum = np.zeros(len(architecture) - 1, dtype=float)
        delta_count = np.zeros(len(architecture) - 1, dtype=np.int64)
        delta_max = np.zeros(len(architecture) - 1, dtype=float)
        for index in order:
            online_mse += mlp.backward(
                X_train[index],
                [y_train[index]],
                taxa=float(config["learning_rate"]),
            )
            hidden = np.asarray(mlp.ultimas_ativacoes_ocultas, dtype=float)
            activation_total += hidden.size
            saturation_total += int(np.sum((hidden < 0.05) | (hidden > 0.95)))
            for layer, delta in enumerate(mlp.ultimos_delta_w):
                absolute = np.abs(delta)
                delta_sum[layer] += float(np.sum(absolute))
                delta_count[layer] += absolute.size
                delta_max[layer] = max(delta_max[layer], float(np.max(absolute)))
        train_mse = _mse(mlp, X_train, y_train)
        validation_mse = (
            _mse(mlp, X_validation, y_validation)
            if X_validation is not None and y_validation is not None
            else None
        )
        record = {
            "epoch": epoch + 1,
            "online_mse_mean": float(online_mse / len(X_train)),
            "train_mse_after_epoch": train_mse,
            "validation_mse": validation_mse,
            "train_validation_gap": (
                validation_mse - train_mse
                if validation_mse is not None
                else None
            ),
            "wall_seconds": float(time.perf_counter() - epoch_start),
            "cpu_seconds": float(time.process_time() - epoch_cpu_start),
            "hidden_saturation_percentage": (
                100.0 * saturation_total / activation_total
                if activation_total
                else 0.0
            ),
        }
        for layer in range(len(architecture) - 1):
            previous = architecture[layer]
            current = architecture[layer + 1]
            weights = mlp.w[: previous + 1, :current, layer]
            number = layer + 1
            record[f"layer_{number}_weight_abs_mean"] = float(
                np.mean(np.abs(weights))
            )
            record[f"layer_{number}_weight_std"] = float(np.std(weights))
            record[f"layer_{number}_delta_abs_mean"] = float(
                delta_sum[layer] / delta_count[layer]
            )
            record[f"layer_{number}_delta_abs_max"] = float(delta_max[layer])
        history.append(record)
        if progress_callback is not None:
            progress_callback(record)
    timing = {
        "wall_seconds": float(time.perf_counter() - start_wall),
        "cpu_seconds": float(time.process_time() - start_cpu),
    }
    return mlp, history, timing


def treinar_ag(
    architecture,
    X_train,
    y_train,
    config,
    seed,
    X_validation=None,
    y_validation=None,
    progress_callback=None,
):
    np.random.seed(seed)
    mlp = MLP(architecture=architecture)
    np.random.seed(seed)
    population = criar_populacao(
        int(config["population"]),
        len(mlp.get_cromossomo()),
        float(config["weight_min"]),
        float(config["weight_max"]),
    )
    best_individual = None
    best_cost = float("inf")
    history = []
    start_wall = time.perf_counter()
    start_cpu = time.process_time()
    for generation in range(int(config["generations"])):
        generation_start = time.perf_counter()
        generation_cpu_start = time.process_time()
        costs = np.array([
            fitness(individual, mlp, X_train, y_train)
            for individual in population
        ])
        generation_best_index = int(np.argmin(costs))
        generation_best = float(costs[generation_best_index])
        if generation_best < best_cost:
            best_cost = generation_best
            best_individual = population[generation_best_index].copy()

        mlp.set_cromossomo(best_individual)
        validation_mse = (
            _mse(mlp, X_validation, y_validation)
            if X_validation is not None and y_validation is not None
            else None
        )
        diversity = float(np.mean(np.std(population, axis=0)))
        gene_mean = float(np.mean(population))
        gene_std = float(np.std(population))
        weight_range = float(config["weight_max"] - config["weight_min"])
        boundary_distance = 0.05 * weight_range
        near_boundaries = np.mean(
            (population <= float(config["weight_min"]) + boundary_distance)
            | (population >= float(config["weight_max"]) - boundary_distance)
        )

        parents = selecao(
            population,
            costs,
            tipo=int(config["selection_type"]),
            tamanho_torneio=int(config["tournament_size"]),
        )
        new_population = []
        for index in range(0, len(population), 2):
            child1, child2 = crossover(
                parents[index],
                parents[(index + 1) % len(population)],
                tipo=int(config["crossover_type"]),
                taxa_crossover=float(config["crossover_rate"]),
                eta=float(config["sbx_eta"]),
            )
            child1 = mutacao(
                child1,
                tipo=int(config["mutation_type"]),
                taxa_mutacao=float(config["mutation_rate"]),
                rmin=float(config["weight_min"]),
                rmax=float(config["weight_max"]),
                sigma=float(config["mutation_sigma"]),
                eta_m=float(config["mutation_eta"]),
            )
            child2 = mutacao(
                child2,
                tipo=int(config["mutation_type"]),
                taxa_mutacao=float(config["mutation_rate"]),
                rmin=float(config["weight_min"]),
                rmax=float(config["weight_max"]),
                sigma=float(config["mutation_sigma"]),
                eta_m=float(config["mutation_eta"]),
            )
            new_population.extend((child1, child2))
        population = np.asarray(new_population[: len(population)])
        population[np.random.randint(len(population))] = best_individual.copy()
        record = {
            "generation": generation + 1,
            "generation_best_train_mse": generation_best,
            "global_best_train_mse": best_cost,
            "mean_train_mse": float(np.mean(costs)),
            "validation_mse": validation_mse,
            "train_validation_gap": (
                validation_mse - best_cost
                if validation_mse is not None
                else None
            ),
            "population_diversity": diversity,
            "gene_mean": gene_mean,
            "gene_std": gene_std,
            "near_weight_boundaries_percentage": float(100.0 * near_boundaries),
            "wall_seconds": float(time.perf_counter() - generation_start),
            "cpu_seconds": float(time.process_time() - generation_cpu_start),
        }
        history.append(record)
        if progress_callback is not None:
            progress_callback(record)
    mlp.set_cromossomo(best_individual)
    timing = {
        "wall_seconds": float(time.perf_counter() - start_wall),
        "cpu_seconds": float(time.process_time() - start_cpu),
        "fitness_evaluations": int(config["population"] * config["generations"]),
        "genes": int(len(best_individual)),
    }
    return mlp, history, timing


def candidate_selection_key(candidate):
    metrics = candidate["validation"]
    return (
        metrics["security_cost"],
        metrics["fn"],
        metrics["fp"],
        -metrics["f1"],
        -metrics["precision"],
        -metrics["recall"],
        -metrics["accuracy"],
        candidate["training"]["wall_seconds"],
        candidate["candidate_id"],
    )


def salvar_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
