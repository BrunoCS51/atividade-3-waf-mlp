#!/usr/bin/env python3
"""Calcula estatísticas agregadas das features candidatas do Experimento 2."""

from __future__ import annotations

import argparse
import csv
import math
from array import array
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from analisar_csic import DEFAULT_INPUTS, iter_requests
from features_http import (
    FEATURE_DEFINITIONS,
    HTTPRequest,
    FeatureDefinition,
    catalogo_features,
    extrair_features_candidatas,
)


DEFAULT_OUTPUT = Path(__file__).resolve().parent / "resultados"
DISTINCT_LIMIT = 10_000


@dataclass
class FeatureAccumulator:
    definition: FeatureDefinition
    total: int = 0
    missing: int = 0
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    zero_count: int = 0
    nonzero_count: int = 0
    values: array = field(default_factory=lambda: array("d"))
    frequencies: Counter[float] = field(default_factory=Counter)
    distinct_values: set[float] | None = field(default_factory=set)
    distinct_overflow: bool = False

    def add(self, value: float | None) -> None:
        self.total += 1
        if value is None or not math.isfinite(value):
            self.missing += 1
            return
        numeric = float(value)
        self.count += 1
        delta = numeric - self.mean
        self.mean += delta / self.count
        self.m2 += delta * (numeric - self.mean)
        self.minimum = numeric if self.minimum is None else min(self.minimum, numeric)
        self.maximum = numeric if self.maximum is None else max(self.maximum, numeric)
        self.zero_count += numeric == 0.0
        self.nonzero_count += numeric != 0.0
        self.values.append(numeric)
        if self.definition.tipo == "binaria":
            self.frequencies[numeric] += 1
        if self.definition.contar_distintos and self.distinct_values is not None:
            self.distinct_values.add(numeric)
            if len(self.distinct_values) > DISTINCT_LIMIT:
                self.distinct_values = None
                self.distinct_overflow = True

    @staticmethod
    def percentile(sorted_values: list[float], percentile: float) -> float | None:
        if not sorted_values:
            return None
        position = (len(sorted_values) - 1) * percentile
        lower = math.floor(position)
        upper = math.ceil(position)
        if lower == upper:
            return sorted_values[lower]
        weight = position - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight

    def summarize(self) -> dict[str, object]:
        ordered = sorted(self.values)
        result = {
            "quantidade_total": self.total,
            "quantidade_valida": self.count,
            "quantidade_ausente": self.missing,
            "percentual_valido": 100.0 * self.count / self.total if self.total else 0.0,
            "minimo": self.minimum,
            "maximo": self.maximum,
            "media": self.mean if self.count else None,
            "mediana": self.percentile(ordered, 0.50),
            "desvio_padrao": math.sqrt(self.m2 / self.count) if self.count else None,
            "p01": self.percentile(ordered, 0.01),
            "p05": self.percentile(ordered, 0.05),
            "p25": self.percentile(ordered, 0.25),
            "p75": self.percentile(ordered, 0.75),
            "p95": self.percentile(ordered, 0.95),
            "p99": self.percentile(ordered, 0.99),
            "quantidade_zero": self.zero_count,
            "quantidade_nao_zero": self.nonzero_count,
            "percentual_nao_zero": 100.0 * self.nonzero_count / self.count if self.count else 0.0,
            "quantidade_distintos": (
                f">{DISTINCT_LIMIT}" if self.distinct_overflow
                else len(self.distinct_values or ()) if self.definition.contar_distintos
                else "não calculado"
            ),
            "frequencias": (
                "; ".join(f"{format_number(value)}={count}" for value, count in sorted(self.frequencies.items()))
                if self.frequencies else ""
            ),
        }
        return result


def format_number(value: object, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.{digits}f}".rstrip("0").rstrip(".")


def analyze_dataset(label: str, path: Path) -> tuple[int, dict[str, dict[str, object]]]:
    accumulators = {
        definition.nome_feature: FeatureAccumulator(definition)
        for definition in catalogo_features()
    }
    parser_info: Counter[str] = Counter()
    requests, _reader = iter_requests(path, parser_info)
    total = 0
    for parsed in requests:
        request = HTTPRequest.from_components(
            parsed.method, parsed.target, parsed.version, parsed.headers, parsed.body
        )
        features = extrair_features_candidatas(request)
        for name, value in features.items():
            accumulators[name].add(value)
        total += 1
        if total % 10_000 == 0:
            print(f"{label}: {total} requisições processadas")
    if parser_info.get("corpo_truncado") or parser_info.get("fim_durante_headers"):
        raise RuntimeError(f"Leitura incompleta em {label}: {dict(parser_info)}")
    return total, {name: accumulator.summarize() for name, accumulator in accumulators.items()}


def write_catalog(path: Path) -> None:
    columns = [
        "nome_feature",
        "origem",
        "tipo",
        "descricao",
        "forma_calculo",
        "aplicabilidade",
        "observacoes_limitacoes",
        "status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for definition in catalogo_features():
            row = {
                key: getattr(definition, key)
                for key in columns
                if key != "status"
            }
            row["status"] = "candidata; decisão pendente"
            writer.writerow(row)


def write_statistics(path: Path, statistics: dict[str, dict[str, dict[str, object]]]) -> None:
    metric_columns = [
        "quantidade_total",
        "quantidade_valida",
        "quantidade_ausente",
        "percentual_valido",
        "minimo",
        "maximo",
        "media",
        "mediana",
        "desvio_padrao",
        "p01",
        "p05",
        "p25",
        "p75",
        "p95",
        "p99",
        "quantidade_zero",
        "quantidade_nao_zero",
        "percentual_nao_zero",
        "quantidade_distintos",
        "frequencias",
    ]
    columns = ["nome_feature", "origem", "tipo", "dataset", *metric_columns]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for definition in catalogo_features():
            for dataset in ("normal", "anomalo"):
                summary = statistics[dataset][definition.nome_feature]
                row = {
                    "nome_feature": definition.nome_feature,
                    "origem": definition.origem,
                    "tipo": definition.tipo,
                    "dataset": dataset,
                }
                row.update({key: format_number(summary[key]) for key in metric_columns})
                writer.writerow(row)


def md_table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def stat_value(statistics: dict, dataset: str, name: str, metric: str) -> object:
    return statistics[dataset][name][metric]


def pct(value: object) -> str:
    return f"{float(value):.2f}%".replace(".", ",")


def ratio_pct(value: object) -> str:
    return pct(float(value) * 100.0)


def write_report(
    path: Path,
    totals: dict[str, int],
    statistics: dict[str, dict[str, dict[str, object]]],
) -> None:
    origin_counts = Counter(definition.origem for definition in catalogo_features())
    example = extrair_features_candidatas(
        b"GET http://localhost:8080/tienda1/imagenes/nuestratierra.jpg/.Inc HTTP/1.1\r\n"
        b"Host: localhost:8080\r\nUser-Agent: exemplo\r\n\r\n"
    )
    key_numeric = (
        "url_length_raw",
        "path_length_raw",
        "path_segment_count",
        "path_extension_like_segment_count",
        "query_parameter_count",
        "query_max_value_length",
        "body_parameter_count",
        "body_max_value_length",
        "header_unique_count",
        "url_percent_encoding_count",
        "query_sql_pattern_count",
        "query_xss_pattern_count",
        "query_traversal_pattern_count",
        "body_sql_pattern_count",
        "body_xss_pattern_count",
    )
    prevalence = (
        "method_is_get",
        "method_is_post",
        "method_is_put",
        "query_present",
        "body_present",
        "url_parse_error",
        "path_nested_extension_transition",
        "content_length_matches_body",
    )
    lines = [
        "# Análise de features candidatas — Experimento 2",
        "",
        "> Catálogo exploratório. Nenhuma candidata foi aprovada, normalizada ou selecionada, e nenhum modelo foi treinado.",
        "",
        "## Escopo e implementação reutilizável",
        "",
        f"Foram propostas e calculadas **{len(FEATURE_DEFINITIONS)} features candidatas** para "
        f"**{totals['normal']} requisições normais** e **{totals['anomalo']} anômalas**. "
        "A função `extrair_features_candidatas` em `features_http.py` recebe uma requisição "
        "bruta ou um objeto HTTP canônico e não recebe label, dataset ou estado temporal. "
        "Ela poderá ser chamada sem duplicação tanto pela futura montagem do dataset quanto pelo WAF.",
        "",
        "`request_rate` e outras informações de replay/tempo não fazem parte deste catálogo.",
        "",
        "## Famílias estudadas",
        "",
        *md_table(
            ["Origem", "Quantidade", "Conteúdo"],
            [
                ["method", origin_counts["method"], "one-hot GET/POST/PUT/outros"],
                ["url", origin_counts["url"], "versão, forma, scheme, host, porta e composição"],
                ["path", origin_counts["path"], "segmentos, profundidade, extensões e composição"],
                ["query", origin_counts["query"], "presença, parâmetros, comprimentos, composição e padrões"],
                ["body", origin_counts["body"], "presença, parâmetros, comprimentos, composição e padrões"],
                ["headers", origin_counts["headers"], "presença, cardinalidade, Content-Length, UA, Host e Cookie"],
            ],
        ),
        "",
        "Cada cálculo, aplicabilidade e limitação está documentado em `features_candidatas.csv`. "
        "As estatísticas completas, com ausentes, mínimo, máximo, média, mediana, desvio padrão, "
        "percentis, valores distintos e frequências binárias, estão em `estatisticas_features.csv`.",
        "",
        "## Comportamento observado — prevalência",
        "",
        *md_table(
            ["Feature", "Normal: valores válidos", "Normal: % igual a 1", "Anômalo: valores válidos", "Anômalo: % igual a 1"],
            [
                [
                    f"`{name}`",
                    stat_value(statistics, "normal", name, "quantidade_valida"),
                    ratio_pct(stat_value(statistics, "normal", name, "media")),
                    stat_value(statistics, "anomalo", name, "quantidade_valida"),
                    ratio_pct(stat_value(statistics, "anomalo", name, "media")),
                ]
                for name in prevalence
            ],
        ),
        "",
        "A diferença de prevalência descreve estes dois arquivos; ela não constitui seleção automática nem evidência de causalidade.",
        "",
        "## Comportamento observado — medidas numéricas",
        "",
        *md_table(
            ["Feature", "Dataset", "Válidos", "Ausentes", "Média", "Mediana", "P95", "Máximo", "% não zero"],
            [
                [
                    f"`{name}`",
                    dataset,
                    stat_value(statistics, dataset, name, "quantidade_valida"),
                    stat_value(statistics, dataset, name, "quantidade_ausente"),
                    format_number(stat_value(statistics, dataset, name, "media"), 3),
                    format_number(stat_value(statistics, dataset, name, "mediana"), 3),
                    format_number(stat_value(statistics, dataset, name, "p95"), 3),
                    format_number(stat_value(statistics, dataset, name, "maximo"), 3),
                    pct(stat_value(statistics, dataset, name, "percentual_nao_zero")),
                ]
                for name in key_numeric
                for dataset in ("normal", "anomalo")
            ],
        ),
        "",
        "## Preservação de informação do path",
        "",
        "A representação não reduz o path a query/body. Para o caso conhecido "
        "`/tienda1/imagenes/nuestratierra.jpg/.Inc`, ela produz, entre outras medidas:",
        "",
        *md_table(
            ["Medida", "Valor"],
            [
                ["segmentos", format_number(example["path_segment_count"])],
                ["segmentos com aparência de extensão", format_number(example["path_extension_like_segment_count"])],
                ["segmentos iniciados por ponto", format_number(example["path_hidden_segment_count"])],
                ["transição extensão → nova extensão", format_number(example["path_nested_extension_transition"])],
                ["maior comprimento de segmento", format_number(example["path_max_segment_length"])],
            ],
        ),
        "",
        "Assim, a ocorrência continua distinguível sem criar uma regra específica para `jpg` ou `.Inc`.",
        "",
        "## Redundâncias e riscos identificados",
        "",
        "- `path_depth` e `path_segment_count` são atualmente equivalentes; manter ambos no catálogo torna a redundância explícita, mas provavelmente apenas um deve chegar ao dataset.",
        "- Comprimentos de URL, path, query e body são parcialmente aditivos; comprimento bruto, decodificado e total de valores também podem carregar informação muito semelhante.",
        "- `alpha_ratio`, `digit_ratio` e `special_ratio` são composicionalmente dependentes e não devem ser tratados como totalmente independentes.",
        "- Presença de body, POST/PUT, Content-Type e Content-Length são fortemente relacionadas neste corpus.",
        "- `body_length_bytes`, `content_length_declared`, `content_length_delta` e `content_length_matches_body` formam outra família redundante.",
        "- Versão HTTP, scheme, vários headers, User-Agent e Cookie apresentam pouca ou nenhuma diversidade no CSIC e podem memorizar o gerador do corpus.",
        "- PUT ocorre apenas no anômalo, mas usar essa coincidência como regra causaria vazamento estrutural da composição do dataset.",
        "- Indicadores SQL/XSS/traversal/comando são genéricos, porém dependem de expressões finitas, decodificação e idioma; podem ter falsos positivos, falsos negativos e redundância entre URL/query/body.",
        "- Entropia é instável em strings curtas e relativamente mais custosa em execução real.",
        "- A porta possui três estados distintos: ausente, válida e inválida. Preencher porta inválida com zero apagaria a informação encontrada em 231 requisições anômalas.",
        "- Valores ausentes foram mantidos como `None` nas candidatas aplicáveis apenas a query, body, porta ou header. A estratégia numérica de imputação ainda precisa ser decidida.",
        "- Nenhum nome concreto de parâmetro (`OpenServer`, `xmlfile` etc.) virou feature; isso reduz memorização direta de particularidades do CSIC.",
        "",
        "## Informações ainda sujeitas a perda",
        "",
        "- Uma única decodificação percentual pode não revelar codificação em múltiplas camadas; decodificar repetidamente também pode alterar semanticamente entradas legítimas.",
        "- O parser agrega parâmetros por `&` e `=`. Separadores alternativos, bodies não form-urlencoded e multipart exigirão tratamento futuro.",
        "- Contagens agregadas não preservam ordem dos parâmetros, nomes exatos, valores completos nem posição exata de cada padrão.",
        "- Headers dobrados são contabilizados, mas ordem, capitalização original e whitespace não viram candidatas.",
        "- Targets em forma de origem, HTTP/2 e tráfego HTTPS real não têm variedade suficiente nestes arquivos para validar todas as categorias propostas.",
        "",
        "## Decisões pendentes antes do dataset",
        "",
        "1. Reduzir famílias redundantes com justificativa e, se necessário, análise de correlação posterior sem usar a label como único critério.",
        "2. Definir política explícita para valores ausentes e preservar indicadores de ausência/validade.",
        "3. Decidir profundidade de percent-decoding e política consistente para bytes/Unicode entre construção do dataset e WAF.",
        "4. Revisar e versionar as expressões de conteúdo, considerando custo, evasões e falsos positivos.",
        "5. Decidir se características com variância zero no CSIC serão mantidas para compatibilidade com tráfego real ou removidas do modelo.",
        "6. Validar as candidatas em requisições externas antes de fixar o esquema, especialmente Host, User-Agent, Cookie, forms e request-target relativo.",
        "7. Definir a lista final e sua ordem; somente depois estabelecer normalização, limites e representação final de missing values.",
        "8. Planejar a reserva de requisições brutas antes de qualquer split, sem permitir que essas requisições participem das decisões de engenharia posteriores.",
        "",
        "## Garantias desta etapa",
        "",
        "Não foi criado dataset final, realizado split, reservado subconjunto, normalizado valor, treinado modelo, executado AG ou definido threshold. Os arquivos brutos foram abertos somente para leitura.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal", type=Path, default=DEFAULT_INPUTS["normal"])
    parser.add_argument("--anomalo", type=Path, default=DEFAULT_INPUTS["anomalo"])
    parser.add_argument("--saida", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = {"normal": args.normal.resolve(), "anomalo": args.anomalo.resolve()}
    for label, source in inputs.items():
        if not source.is_file():
            raise FileNotFoundError(f"Arquivo {label} não encontrado: {source}")
    output = args.saida.resolve()
    output.mkdir(parents=True, exist_ok=True)

    totals: dict[str, int] = {}
    statistics: dict[str, dict[str, dict[str, object]]] = {}
    for label, source in inputs.items():
        totals[label], statistics[label] = analyze_dataset(label, source)

    write_catalog(output / "features_candidatas.csv")
    write_statistics(output / "estatisticas_features.csv", statistics)
    write_report(output / "relatorio_features.md", totals, statistics)
    print(f"{len(FEATURE_DEFINITIONS)} features candidatas analisadas")
    print(f"Resultados gravados em: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
