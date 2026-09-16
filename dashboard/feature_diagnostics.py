"""Estatisticas observacionais das features originais e da simulacao CSIC."""

import ast
import csv
import math
from pathlib import Path
import statistics


BINARY_FEATURES = {
    "is_post_put",
    "has_sql_keywords",
    "has_xss_keywords",
    "is_standard_browser",
}

_ORIGINAL_CACHE = {
    "key": None,
    "value": None,
}


def read_feature_schema(extractor_path):
    """Le nomes e limites diretamente do extractor, sem importa-lo."""
    path = Path(extractor_path)
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assignments = {}

    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if target.id not in {"NOMES_FEATURES", "LIMITES"}:
            continue
        assignments[target.id] = ast.literal_eval(node.value)

    names = assignments.get("NOMES_FEATURES")
    limits = assignments.get("LIMITES")
    if not isinstance(names, list) or not isinstance(limits, list):
        raise ValueError("Schema de features nao encontrado no extractor.")
    if len(names) != 9 or len(limits) != 9:
        raise ValueError("Schema do extractor deve conter exatamente 9 features.")

    return [
        {
            "nome": str(name),
            "limite": float(limit),
            "tipo": "binaria" if name in BINARY_FEATURES else "numerica",
        }
        for name, limit in zip(names, limits)
    ]


def percentile(values, percentile_value):
    """Percentil com interpolacao linear sobre valores ordenados."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile_value
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_values(values, feature):
    values = [float(value) for value in values]
    total = len(values)
    limit = float(feature["limite"])
    above = sum(value > limit for value in values)
    base = {
        "quantidade": total,
        "limite": limit,
        "minimo": min(values) if values else None,
        "maximo": max(values) if values else None,
        "acima_limite": above,
        "percentual_acima_limite": above / total if total else 0.0,
        "clipping": above,
        "percentual_clipping": above / total if total else 0.0,
    }

    if feature["tipo"] == "binaria":
        ones = sum(value == 1 for value in values)
        zeros = sum(value == 0 for value in values)
        return {
            **base,
            "percentual_zero": zeros / total if total else 0.0,
            "percentual_um": ones / total if total else 0.0,
        }

    if not values:
        return {
            **base,
            "media": None,
            "mediana": None,
            "p95": None,
        }
    return {
        **base,
        "media": statistics.fmean(values),
        "mediana": statistics.median(values),
        "minimo": min(values),
        "maximo": max(values),
        "p95": percentile(values, 0.95),
    }


def _empty_columns(schema):
    return {feature["nome"]: [] for feature in schema}


def _summarize_columns(columns, schema):
    return {
        feature["nome"]: summarize_values(
            columns.get(feature["nome"], []),
            feature,
        )
        for feature in schema
    }


def summarize_original_dataset(dataset_path, schema):
    path = Path(dataset_path)
    key = (str(path.resolve()), path.stat().st_mtime_ns, tuple(
        (feature["nome"], feature["limite"], feature["tipo"])
        for feature in schema
    ))
    if _ORIGINAL_CACHE["key"] == key:
        return _ORIGINAL_CACHE["value"]

    columns = _empty_columns(schema)
    total = 0
    with path.open("r", encoding="utf-8", newline="") as source:
        for row in csv.reader(source):
            if not row:
                continue
            if len(row) < len(schema) + 1:
                raise ValueError("Linha incompleta no dataset original.")
            values = [float(value) for value in row[:len(schema)]]
            for feature, value in zip(schema, values):
                columns[feature["nome"]].append(value)
            total += 1

    result = {
        "quantidade": total,
        "features": _summarize_columns(columns, schema),
    }
    _ORIGINAL_CACHE["key"] = key
    _ORIGINAL_CACHE["value"] = result
    return result


def summarize_csic(records, schema):
    total_columns = _empty_columns(schema)
    class_columns = {
        "NORMAL": _empty_columns(schema),
        "ATAQUE": _empty_columns(schema),
    }
    class_counts = {"NORMAL": 0, "ATAQUE": 0}

    for record in records:
        label = record.get("rotulo_real")
        if label not in class_columns:
            continue
        feature_map = {
            item.get("nome"): item.get("valor_bruto")
            for item in record.get("features", [])
        }
        if any(feature["nome"] not in feature_map for feature in schema):
            continue
        class_counts[label] += 1
        for feature in schema:
            name = feature["nome"]
            value = float(feature_map[name])
            total_columns[name].append(value)
            class_columns[label][name].append(value)

    return {
        "quantidade": sum(class_counts.values()),
        "features": _summarize_columns(total_columns, schema),
        "classes": {
            label: {
                "quantidade": class_counts[label],
                "features": _summarize_columns(class_columns[label], schema),
            }
            for label in ("NORMAL", "ATAQUE")
        },
    }


def build_feature_analysis(extractor_path, dataset_path, csic_records):
    try:
        schema = read_feature_schema(extractor_path)
        original = summarize_original_dataset(dataset_path, schema)
        csic = summarize_csic(csic_records, schema)
    except (OSError, ValueError, SyntaxError, csv.Error) as error:
        return {
            "disponivel": False,
            "mensagem": f"Analise de features indisponivel: {error}",
        }

    clipping = []
    for feature in schema:
        name = feature["nome"]
        original_stats = original["features"][name]
        csic_stats = csic["features"][name]
        clipping.append({
            "nome": name,
            "tipo": feature["tipo"],
            "limite": feature["limite"],
            "maximo_original": original_stats.get("maximo"),
            "maximo_csic": csic_stats.get("maximo"),
            "percentual_original_acima": original_stats["percentual_acima_limite"],
            "percentual_csic_acima": csic_stats["percentual_acima_limite"],
            "percentual_csic_clipping": csic_stats["percentual_clipping"],
        })

    return {
        "disponivel": csic["quantidade"] > 0,
        "mensagem": (
            "Execute uma simulacao CSIC para gerar a comparacao."
            if csic["quantidade"] == 0
            else "Comparacao calculada com valores brutos das 9 features."
        ),
        "schema": schema,
        "original": original,
        "csic": csic,
        "impacto_limites": clipping,
        "metodologia": {
            "percentil": "P95 com interpolacao linear.",
            "acima_limite": "Contagem estrita de valor bruto > limite.",
            "clipping": "Valor bruto > limite, normalizado para 1.0 pelo extractor.",
        },
    }
