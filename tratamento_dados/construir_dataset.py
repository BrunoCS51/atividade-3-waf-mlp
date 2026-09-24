#!/usr/bin/env python3
"""Reserva requisições brutas e constrói o dataset do Experimento 2.

A seleção de desenvolvimento ocorre antes da extração de features. A ordenação
pseudoaleatória é determinada por SHA-256(seed, classe, posição, conteúdo), de
forma reproduzível e independente da versão do gerador aleatório do Python.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import random
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import BinaryIO, Iterable
from urllib.parse import urlsplit

from analisar_csic import DEFAULT_INPUTS
from features_http import (
    FEATURE_DEFINITIONS,
    FEATURES_EXPERIMENTO_2,
    INDICADORES_DE_AUSENCIA,
    HTTPRequest,
    extrair_features_experimento_2,
    parse_raw_http_request,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASETS = Path(__file__).resolve().parent / "datasets"
DEFAULT_RESULTS = Path(__file__).resolve().parent / "resultados"
SEED_EXPERIMENTO_2 = 20_260_917
EXPECTED_COUNTS = {
    "normal": {"total": 36_000, "development": 15_000, "reserved": 21_000, "label": 0},
    "anomalo": {"total": 25_065, "development": 15_000, "reserved": 10_065, "label": 1},
}
REQUEST_LINE_RE = re.compile(rb"^[^\s]+\s+.+?\s+HTTP/[^\s]+\r?\n$")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_raw_requests(path: Path) -> Iterable[bytes]:
    """Lê mensagens HTTP preservando exatamente start-line, headers e body."""

    with path.open("rb") as stream:
        while True:
            request_line = stream.readline()
            while request_line in {b"\n", b"\r\n"}:
                request_line = stream.readline()
            if not request_line:
                return
            if not REQUEST_LINE_RE.match(request_line):
                raise ValueError(f"Linha inicial HTTP inválida em {path}: {request_line[:120]!r}")

            parts = [request_line]
            content_length = 0
            while True:
                line = stream.readline()
                if not line:
                    raise ValueError(f"Fim inesperado durante headers em {path}")
                parts.append(line)
                if line in {b"\n", b"\r\n"}:
                    break
                if b":" in line:
                    raw_name, raw_value = line.split(b":", 1)
                    if raw_name.strip().lower() == b"content-length":
                        try:
                            content_length = int(raw_value.strip())
                        except ValueError as error:
                            raise ValueError(f"Content-Length inválido em {path}") from error
                        if content_length < 0:
                            raise ValueError(f"Content-Length negativo em {path}")

            body = stream.read(content_length) if content_length else b""
            if len(body) != content_length:
                raise ValueError(f"Body truncado em {path}")
            parts.append(body)
            yield b"".join(parts)


def record_id(dataset: str, sequence: int, raw: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(b"csic-experimento-2\0")
    digest.update(dataset.encode("ascii"))
    digest.update(b"\0")
    digest.update(sequence.to_bytes(8, "big", signed=False))
    digest.update(b"\0")
    digest.update(raw)
    return digest.hexdigest()


def selection_key(seed: int, dataset: str, sequence: int, content_hash: str) -> str:
    material = f"{seed}:{dataset}:{sequence}:{content_hash}".encode("ascii")
    return hashlib.sha256(material).hexdigest()


def select_development_indices(
    content_hashes: list[str], dataset: str, quantity: int, seed: int = SEED_EXPERIMENTO_2
) -> frozenset[int]:
    if quantity < 0 or quantity > len(content_hashes):
        raise ValueError("Quantidade de desenvolvimento incompatível com o total")
    ranked = sorted(
        range(len(content_hashes)),
        key=lambda index: (selection_key(seed, dataset, index, content_hashes[index]), index),
    )
    return frozenset(ranked[:quantity])


def scan_source(path: Path, dataset: str) -> tuple[list[str], list[str]]:
    content_hashes: list[str] = []
    record_ids: list[str] = []
    for sequence, raw in enumerate(iter_raw_requests(path)):
        content_hashes.append(sha256_bytes(raw))
        record_ids.append(record_id(dataset, sequence, raw))
    return content_hashes, record_ids


def format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else format(value, ".17g")


def target_parts(target: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(target)
        return parsed.path or "/", parsed.query
    except ValueError:
        without_fragment = target.split("#", 1)[0]
        if "?" in without_fragment:
            path, query = without_fragment.split("?", 1)
            return path or "/", query
        return without_fragment or "/", ""


def reserved_record(
    dataset: str,
    sequence: int,
    label: int,
    raw: bytes,
) -> dict[str, object]:
    request = parse_raw_http_request(raw)
    path, query = target_parts(request.target)
    content_hash = sha256_bytes(raw)
    headers = {name: list(values) for name, values in request.headers.items()}
    content_types = headers.get("content-type", [])
    return {
        "schema_version": 1,
        "record_id": record_id(dataset, sequence, raw),
        "content_sha256": content_hash,
        "label": label,
        "source_sequence": sequence,
        "method": request.method,
        "target": request.target,
        "http_version": request.version,
        "path": path,
        "query": query,
        "headers": headers,
        "content_type": content_types[0] if content_types else None,
        "body_base64": base64.b64encode(request.body).decode("ascii"),
        "raw_request_base64": base64.b64encode(raw).decode("ascii"),
    }


def reconstruct_reserved_request(record: dict[str, object]) -> bytes:
    raw = base64.b64decode(str(record["raw_request_base64"]), validate=True)
    if sha256_bytes(raw) != record["content_sha256"]:
        raise ValueError("Hash da requisição reservada não confere")
    request = parse_raw_http_request(raw)
    if request.target != record["target"] or request.method != record["method"]:
        raise ValueError("Campos estruturados não conferem com a requisição bruta")
    return raw


def final_justification(name: str) -> str:
    if name.startswith("method_is_"):
        return "Representa o método sem codificação ordinal; GET é a categoria-base e outros métodos continuam distinguíveis."
    if name in {"url_port_present", "url_port_valid"}:
        return "Preserva separadamente ausência e invalidade da porta, sem converter falha de parsing em valor válido."
    if name.startswith("url_host_") or name == "host_matches_url_host":
        return "Representa genericamente presença, forma e coerência do host sem memorizar hostname do CSIC."
    if name.startswith("url_"):
        return "Descreve formato geral do request-target e inconsistências reproduzíveis no WAF."
    if name.startswith("path_"):
        if any(token in name for token in ("sql_pattern", "xss_pattern", "traversal_pattern", "shell_metachar")):
            return "Sinal genérico de conteúdo defensivo aplicado ao path, sem depender de texto específico do corpus."
        return "Preserva estrutura do path, inclusive codificação, segmentos e extensões, pouco representadas no Experimento 1."
    if name.startswith(("query_", "body_")):
        if any(token in name for token in ("sql_pattern", "xss_pattern", "traversal_pattern", "shell_metachar")):
            return "Contagem genérica de padrões defensivos; reproduzível e independente de nomes específicos de parâmetros."
        if name.endswith("_present"):
            return "Distingue ausência legítima do componente de medidas numericamente iguais a zero."
        return "Resume estrutura, codificação ou composição de parâmetros sem memorizar seus nomes ou valores."
    if name.startswith("header_has_"):
        return "Indicador necessário para distinguir header ausente de valor inválido ou medida igual a zero."
    if name in {"content_type_is_form_urlencoded", "content_length_valid", "content_length_delta"}:
        return "Representa semântica e coerência do corpo usando propriedades reproduzíveis em tempo real."
    return "Resumo genérico da estrutura de headers, sem usar valores identificadores do corpus."


def removal_reason(name: str) -> str:
    if name == "method_is_get":
        return "Redundante com a categoria-base: GET é representado quando POST, PUT e other são zero."
    if name.startswith("http_version_"):
        return "Versão HTTP constante (1.1) no corpus e com risco de memorizar o ambiente de coleta."
    if name.endswith("length_decoded_once"):
        return "Redundante com comprimento bruto e contagem de percent-encoding."
    if name.endswith("alpha_ratio"):
        return "Dependência composicional com proporções numérica e especial."
    if name.endswith("entropy"):
        return "Custo maior em tempo real, instabilidade em strings curtas e sobreposição com medidas de composição."
    if name.endswith("max_repeat_run"):
        return "Baixa prioridade após manter comprimento, composição, codificação e padrões defensivos."
    if name.startswith("url_") and any(token in name for token in ("sql_pattern", "xss_pattern", "traversal_pattern", "shell_metachar")):
        return "Redundante com contagens separadas em path e query."
    if name.startswith("url_") and name in {
        "url_scheme_is_http", "url_scheme_is_https", "url_scheme_is_other", "url_scheme_missing"
    }:
        return "Scheme constante no CSIC e frequentemente indisponível em request-target relativo no WAF."
    if name in {"url_host_length", "url_host_label_count"}:
        return "Baixa diversidade no CSIC e risco de memorizar a infraestrutura; forma do host permanece representada."
    if name in {"url_port_value", "url_port_is_standard"}:
        return "Valor concreto da porta pode memorizar a infraestrutura; presença e validade foram preservadas."
    if name in {"path_depth", "path_segments_with_dot_count"}:
        return "Redundante com contagem de segmentos ou segmentos com aparência de extensão."
    if name in {"path_empty_inner_segment_count", "path_dot_segment_count", "path_max_extensions_in_segment", "path_trailing_slash"}:
        return "Detalhe estrutural de prioridade menor e parcialmente coberto por barras duplas, traversal e estrutura de extensões."
    if name.endswith("distinct_parameter_name_count"):
        return "Derivável aproximadamente da quantidade total e da repetição de parâmetros."
    if name.endswith(("mean_name_length", "mean_value_length", "total_value_length")):
        return "Reduzido por redundância com comprimento do componente e comprimentos máximos."
    if name.endswith("empty_name_count"):
        return "Prioridade menor; estrutura malformada continua parcialmente coberta por fragmentos sem '=' e valores vazios."
    if name == "header_value_count":
        return "Derivável de quantidade de headers únicos e duplicados."
    if name.startswith("header_has_"):
        return "Indicador constante ou pouco informativo no CSIC e desnecessário para interpretar as features finais mantidas."
    if name.startswith("user_agent_") or name.startswith("cookie_"):
        return "Pouca diversidade no CSIC e alto risco de memorizar o gerador, cliente ou sessão do corpus."
    if name.startswith("host_header_"):
        return "Parcialmente redundante com informações de host/porta da URL e coerência de host mantida."
    if name in {"content_length_declared", "body_length_bytes", "content_length_matches_body"}:
        return "Redundante com comprimento do body, presença/validade do header e diferença real-declarado."
    return "Removida por redundância, baixa diversidade no corpus ou menor prioridade de generalização."


def write_schema(path: Path) -> None:
    columns = ["ordem", "nome_feature", "origem", "tipo", "descricao", "justificativa_permanencia"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for order, name in enumerate(FEATURES_EXPERIMENTO_2, start=1):
            definition = FEATURE_DEFINITIONS[name]
            writer.writerow({
                "ordem": order,
                "nome_feature": name,
                "origem": definition.origem,
                "tipo": definition.tipo,
                "descricao": definition.descricao,
                "justificativa_permanencia": final_justification(name),
            })


def write_removed(path: Path) -> None:
    columns = ["feature", "origem", "tipo", "motivo_remocao"]
    selected = set(FEATURES_EXPERIMENTO_2)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for name, definition in FEATURE_DEFINITIONS.items():
            if name not in selected:
                writer.writerow({
                    "feature": name,
                    "origem": definition.origem,
                    "tipo": definition.tipo,
                    "motivo_remocao": removal_reason(name),
                })


def set_digest(values: set[str]) -> str:
    return sha256_bytes(("\n".join(sorted(values)) + "\n").encode("ascii"))


def write_report(path: Path, manifest: dict[str, object]) -> None:
    validation = manifest["validacoes"]
    files = manifest["arquivos"]
    lines = [
        "# Construção dos datasets — Experimento 2",
        "",
        "## Contrato final",
        "",
        f"O contrato oficial contém **{len(FEATURES_EXPERIMENTO_2)} features**, em ordem fixa, "
        f"selecionadas das {len(FEATURE_DEFINITIONS)} candidatas. Foram removidas "
        f"**{len(FEATURE_DEFINITIONS) - len(FEATURES_EXPERIMENTO_2)}**.",
        "",
        "A lista ordenada está em `esquema_final_features.csv` e na constante "
        "`FEATURES_EXPERIMENTO_2` de `features_http.py`. O CSV de desenvolvimento usa "
        "essa ordem e acrescenta somente `label` ao final.",
        "",
        "## Política de ausentes",
        "",
        "Nenhum `None` é gravado. Valores ausentes são convertidos para `0.0` apenas quando "
        "há indicador explícito no mesmo vetor. Exemplos: query/body usam `*_present`; host usa "
        "`url_host_present`; porta usa `url_port_present` + `url_port_valid`; Content-Type e "
        "Content-Length usam seus indicadores de presença/validade. Assim, ausência, zero real "
        "e invalidade continuam distinguíveis. Não houve normalização.",
        "",
        "## Reserva anterior ao desenvolvimento",
        "",
        f"Seed documentada: **{manifest['seed']}**. Cada requisição bruta recebeu uma chave "
        "pseudoaleatória SHA-256 formada por seed, classe, posição e hash do conteúdo. Os 15.000 "
        "menores valores de cada classe foram destinados ao desenvolvimento antes de qualquer "
        "extração de features. As demais requisições foram reservadas.",
        "",
        "O CSV de desenvolvimento foi posteriormente embaralhado com `random.Random(seed)`; "
        "não existe alternância artificial entre labels.",
        "",
        "| Partição | Normal | Anômalo | Total |",
        "| --- | ---: | ---: | ---: |",
        f"| Desenvolvimento | 15.000 | 15.000 | {manifest['contagens']['development_total']} |",
        f"| Reservado | 21.000 | 10.065 | {manifest['contagens']['reserved_total']} |",
        f"| Total | 36.000 | 25.065 | {manifest['contagens']['total']} |",
        "",
        "## Rastreabilidade e replay",
        "",
        "O reservado é JSONL e mantém target original, método, versão, path, query, headers, "
        "Content-Type, body em Base64 e a requisição HTTP exata em Base64. `record_id` identifica "
        "a ocorrência; `content_sha256` verifica os bytes. A ordem original é preservada dentro "
        "de cada arquivo de origem. `controle_particoes.jsonl` registra IDs e partição, mas não "
        "entra no modelo.",
        "",
        f"- Sobreposição de IDs: **{validation['sobreposicao_ids']}**.",
        f"- Sobreposição de conteúdo bruto: **{validation['sobreposicao_conteudo']}**.",
        f"- Requisições perdidas: **{validation['requisicoes_perdidas']}**.",
        f"- Reconstrução do reservado validada: **{validation['replay_recuperavel']}**.",
        "",
        "## Arquivos e hashes",
        "",
        "| Arquivo | Bytes | SHA-256 |",
        "| --- | ---: | --- |",
    ]
    for name in ("desenvolvimento", "reservado", "controle"):
        item = files[name]
        lines.append(f"| `{item['caminho']}` | {item['bytes']} | `{item['sha256']}` |")
    lines.extend([
        "",
        "## Principais remoções",
        "",
        "- versão HTTP e scheme constantes no CSIC;",
        "- GET one-hot redundante, usando GET como categoria-base;",
        "- comprimento bruto e decodificado simultâneos;",
        "- profundidade e número de segmentos simultâneos;",
        "- proporção alfabética dependente das demais proporções;",
        "- entropia e repetição máxima, pelo custo/instabilidade ou menor prioridade;",
        "- padrões no URL completo já representados em path e query;",
        "- médias/totais de parâmetros redundantes com comprimentos e máximos;",
        "- headers constantes, User-Agent e Cookie com risco de memorizar o ambiente CSIC;",
        "- medidas redundantes de Content-Length/body.",
        "",
        "Todos os 76 motivos individuais estão em `features_removidas.csv`.",
        "",
        "## Limitações conhecidas",
        "",
        "- `method_is_put` permanece para que o método seja representável, mas PUT só aparece no "
        "anômalo do CSIC e não deve ser interpretado como regra universal de ataque.",
        "- Expressões SQL/XSS/traversal são finitas e dependem da política de decodificação; podem "
        "produzir falsos positivos e negativos.",
        "- A validade externa do esquema ainda deve ser testada em tráfego não pertencente ao CSIC.",
        "- O reservado fica proibido para treinamento, validação, teste interno, threshold, "
        "arquitetura, hiperparâmetros, limites e seleção de modelo.",
        "",
        "Nenhum split interno, normalização, limite, treinamento, AG, arquitetura ou threshold foi executado.",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def build(inputs: dict[str, Path], datasets_dir: Path, results_dir: Path) -> dict[str, object]:
    datasets_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    scans: dict[str, dict[str, object]] = {}
    all_record_ids: set[str] = set()
    for dataset, source in inputs.items():
        content_hashes, record_ids = scan_source(source, dataset)
        expected = EXPECTED_COUNTS[dataset]
        if len(content_hashes) != expected["total"]:
            raise AssertionError(f"Total inesperado em {dataset}: {len(content_hashes)}")
        if len(record_ids) != len(set(record_ids)):
            raise AssertionError(f"IDs duplicados em {dataset}")
        if all_record_ids.intersection(record_ids):
            raise AssertionError("IDs repetidos entre fontes")
        all_record_ids.update(record_ids)
        selected = select_development_indices(
            content_hashes, dataset, expected["development"], SEED_EXPERIMENTO_2
        )
        scans[dataset] = {
            "content_hashes": content_hashes,
            "record_ids": record_ids,
            "selected": selected,
        }

    development_rows: list[tuple[tuple[float, ...], int]] = []
    development_ids: set[str] = set()
    reserved_ids: set[str] = set()
    development_content: set[str] = set()
    reserved_content: set[str] = set()
    counts = Counter()

    reserved_path = datasets_dir / "csic_experimento2_reservado.jsonl"
    control_path = datasets_dir / "controle_particoes.jsonl"
    reserved_tmp = reserved_path.with_suffix(".jsonl.tmp")
    control_tmp = control_path.with_suffix(".jsonl.tmp")
    with reserved_tmp.open("w", encoding="utf-8", newline="\n") as reserved_stream, control_tmp.open(
        "w", encoding="utf-8", newline="\n"
    ) as control_stream:
        for dataset, source in inputs.items():
            expected = EXPECTED_COUNTS[dataset]
            selected: frozenset[int] = scans[dataset]["selected"]  # type: ignore[assignment]
            known_hashes: list[str] = scans[dataset]["content_hashes"]  # type: ignore[assignment]
            known_ids: list[str] = scans[dataset]["record_ids"]  # type: ignore[assignment]
            for sequence, raw in enumerate(iter_raw_requests(source)):
                content_hash = sha256_bytes(raw)
                identifier = record_id(dataset, sequence, raw)
                if content_hash != known_hashes[sequence] or identifier != known_ids[sequence]:
                    raise AssertionError("Fonte mudou entre seleção e construção")
                partition = "development" if sequence in selected else "reserved"
                control_stream.write(json.dumps({
                    "record_id": identifier,
                    "content_sha256": content_hash,
                    "label": expected["label"],
                    "partition": partition,
                    "source_sequence": sequence,
                }, separators=(",", ":")) + "\n")
                counts[f"{partition}_{dataset}"] += 1
                if partition == "development":
                    request = parse_raw_http_request(raw)
                    vector = extrair_features_experimento_2(request)
                    development_rows.append((vector, expected["label"]))
                    development_ids.add(identifier)
                    development_content.add(content_hash)
                else:
                    record = reserved_record(dataset, sequence, expected["label"], raw)
                    reconstruct_reserved_request(record)
                    reserved_stream.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")) + "\n")
                    reserved_ids.add(identifier)
                    reserved_content.add(content_hash)

    reserved_tmp.replace(reserved_path)
    control_tmp.replace(control_path)

    random.Random(SEED_EXPERIMENTO_2).shuffle(development_rows)
    development_path = datasets_dir / "csic_experimento2_desenvolvimento.csv"
    development_tmp = development_path.with_suffix(".csv.tmp")
    with development_tmp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow([*FEATURES_EXPERIMENTO_2, "label"])
        for vector, label in development_rows:
            writer.writerow([*(format_number(value) for value in vector), label])
    development_tmp.replace(development_path)

    if development_ids & reserved_ids:
        raise AssertionError("Sobreposição de IDs entre desenvolvimento e reservado")
    content_overlap = development_content & reserved_content
    if content_overlap:
        raise AssertionError(f"Conteúdo bruto duplicado entre partições: {len(content_overlap)}")
    if development_ids | reserved_ids != all_record_ids:
        raise AssertionError("Requisições perdidas ou extras")

    expected_assertions = {
        "development_normal": 15_000,
        "development_anomalo": 15_000,
        "reserved_normal": 21_000,
        "reserved_anomalo": 10_065,
    }
    for key, expected_count in expected_assertions.items():
        if counts[key] != expected_count:
            raise AssertionError(f"Contagem incorreta {key}: {counts[key]}")

    schema_path = results_dir / "esquema_final_features.csv"
    removed_path = results_dir / "features_removidas.csv"
    manifest_path = results_dir / "manifest_dataset.json"
    report_path = results_dir / "relatorio_dataset.md"
    write_schema(schema_path)
    write_removed(removed_path)

    feature_contract_hash = sha256_bytes(("\n".join(FEATURES_EXPERIMENTO_2) + "\n").encode("ascii"))
    manifest: dict[str, object] = {
        "schema_version": 1,
        "seed": SEED_EXPERIMENTO_2,
        "estrategia_selecao": "15.000 menores SHA-256(seed:classe:posição:hash_conteúdo) por classe",
        "estrategia_shuffle_desenvolvimento": "random.Random(seed).shuffle",
        "features": {
            "quantidade_candidatas": len(FEATURE_DEFINITIONS),
            "quantidade_finais": len(FEATURES_EXPERIMENTO_2),
            "quantidade_removidas": len(FEATURE_DEFINITIONS) - len(FEATURES_EXPERIMENTO_2),
            "sha256_contrato_ordenado": feature_contract_hash,
            "ordem": list(FEATURES_EXPERIMENTO_2),
            "normalizadas": False,
            "politica_none": "0.0 somente quando acompanhado por indicador explícito de presença/validade",
            "indicadores_ausencia": INDICADORES_DE_AUSENCIA,
        },
        "contagens": {
            **dict(counts),
            "development_total": len(development_ids),
            "reserved_total": len(reserved_ids),
            "total": len(all_record_ids),
        },
        "fontes": {
            dataset: {
                "caminho": str(source.relative_to(ROOT)).replace("\\", "/"),
                "bytes": source.stat().st_size,
                "sha256": sha256_file(source),
            }
            for dataset, source in inputs.items()
        },
        "validacoes": {
            "sobreposicao_ids": len(development_ids & reserved_ids),
            "sobreposicao_conteudo": len(content_overlap),
            "requisicoes_perdidas": len(all_record_ids - (development_ids | reserved_ids)),
            "replay_recuperavel": True,
            "development_ids_sha256": set_digest(development_ids),
            "reserved_ids_sha256": set_digest(reserved_ids),
        },
        "arquivos": {
            "desenvolvimento": {
                "caminho": str(development_path.relative_to(ROOT)).replace("\\", "/"),
                "bytes": development_path.stat().st_size,
                "sha256": sha256_file(development_path),
            },
            "reservado": {
                "caminho": str(reserved_path.relative_to(ROOT)).replace("\\", "/"),
                "bytes": reserved_path.stat().st_size,
                "sha256": sha256_file(reserved_path),
            },
            "controle": {
                "caminho": str(control_path.relative_to(ROOT)).replace("\\", "/"),
                "bytes": control_path.stat().st_size,
                "sha256": sha256_file(control_path),
            },
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(report_path, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal", type=Path, default=DEFAULT_INPUTS["normal"])
    parser.add_argument("--anomalo", type=Path, default=DEFAULT_INPUTS["anomalo"])
    parser.add_argument("--datasets", type=Path, default=DEFAULT_DATASETS)
    parser.add_argument("--resultados", type=Path, default=DEFAULT_RESULTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = {"normal": args.normal.resolve(), "anomalo": args.anomalo.resolve()}
    for dataset, source in inputs.items():
        if not source.is_file():
            raise FileNotFoundError(f"Fonte {dataset} não encontrada: {source}")
    manifest = build(inputs, args.datasets.resolve(), args.resultados.resolve())
    print(f"Features finais: {manifest['features']['quantidade_finais']}")  # type: ignore[index]
    print(f"Desenvolvimento: {manifest['contagens']['development_total']}")  # type: ignore[index]
    print(f"Reservado: {manifest['contagens']['reserved_total']}")  # type: ignore[index]
    print("Validação concluída sem sobreposição")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
