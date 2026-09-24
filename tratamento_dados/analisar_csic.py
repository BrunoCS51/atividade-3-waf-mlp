#!/usr/bin/env python3
"""Descoberta estrutural dos arquivos brutos do CSIC 2010.

O programa faz uma única passagem, em modo binário, por cada arquivo. Somente
estatísticas agregadas e até três exemplos sanitizados por campo são mantidos
em memória; nenhuma requisição é copiada para os resultados.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO, Iterable
from urllib.parse import parse_qsl, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUTS = {
    "normal": ROOT / "external_data" / "csic2010" / "normalTrafficTraining.txt",
    "anomalo": ROOT / "external_data" / "csic2010" / "anomalousTrafficTest.txt",
}
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "resultados"
REQUEST_LINE_RE = re.compile(rb"^([^\s]+)\s+(.+?)\s+HTTP/([^\s]+)$")
PERCENT_ENCODING_RE = re.compile(r"%[0-9A-Fa-f]{2}")
INTEGER_RE = re.compile(r"^[+-]?\d+$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.\d*|\d*\.\d+)$")
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def decode(raw: bytes) -> str:
    """Preserva cada byte do corpus sem falhar por codificação."""

    return raw.decode("latin-1")


def safe_name(value: str, maximum: int = 120) -> str:
    value = "".join(ch if ch.isprintable() else "�" for ch in value.strip())
    return value if len(value) <= maximum else value[: maximum - 1] + "…"


def length_band(length: int) -> str:
    if length == 0:
        return "comprimento:0"
    if length <= 8:
        return "comprimento:1-8"
    if length <= 32:
        return "comprimento:9-32"
    if length <= 128:
        return "comprimento:33-128"
    if length <= 512:
        return "comprimento:129-512"
    return "comprimento:>512"


def value_forms(value: str) -> list[str]:
    """Classifica forma/tipo sem atribuir qualidade preditiva ao campo."""

    forms = [length_band(len(value))]
    stripped = value.strip()
    if not stripped:
        forms.append("vazio")
        return forms
    if INTEGER_RE.fullmatch(stripped):
        forms.append("inteiro")
    elif DECIMAL_RE.fullmatch(stripped):
        forms.append("decimal")
    elif stripped.lower() in {"true", "false", "on", "off", "yes", "no"}:
        forms.append("booleano/textual")
    elif EMAIL_RE.fullmatch(stripped):
        forms.append("email")
    elif stripped.startswith(("http://", "https://")):
        forms.append("url-absoluta")
    elif stripped.startswith("/"):
        forms.append("caminho")
    elif stripped.isalnum():
        forms.append("alfanumerico")
    else:
        forms.append("texto/simbolos")

    if PERCENT_ENCODING_RE.search(value):
        forms.append("percent-encoded")
    if any(ch.isspace() for ch in value):
        forms.append("contem-espaco")
    if re.search(r"<[^>]*>", value):
        forms.append("contem-marcacao-angle-brackets")
    if ";" in value:
        forms.append("contem-ponto-e-virgula")
    if any(mark in value for mark in ("'", '"')):
        forms.append("contem-aspas")
    if "(" in value or ")" in value:
        forms.append("contem-parenteses")
    if any(ord(ch) < 32 and ch not in "\t\r\n" for ch in value):
        forms.append("contem-controle")
    if any(ord(ch) > 127 for ch in value):
        forms.append("contem-byte-nao-ascii")
    return forms


def sanitize_cookie(value: str) -> str:
    parts = []
    for item in value.split(";"):
        key = item.split("=", 1)[0].strip()
        if key:
            parts.append(f"{safe_name(key, 40)}=<redigido>")
    return "; ".join(parts) or "<cookie redigido>"


def sanitize_target(value: str) -> str:
    try:
        parsed = urlsplit(value)
        prefix = ""
        if parsed.scheme or parsed.netloc:
            prefix = f"{safe_name(parsed.scheme, 12)}://{safe_name(parsed.netloc, 80)}"
        path = safe_name(parsed.path or "/", 140)
        query_names = [safe_name(key, 50) for key, _ in parse_qsl(
            parsed.query, keep_blank_values=True, encoding="latin-1", errors="replace"
        )]
        if parsed.query and not query_names:
            return f"{prefix}{path}?<query não estruturada>"
        suffix = ""
        if query_names:
            shown = query_names[:8]
            suffix = "?" + "&".join(f"{name}=<valor>" for name in shown)
            if len(query_names) > len(shown):
                suffix += "&…"
        return safe_name(prefix + path + suffix, 300)
    except ValueError:
        return "<target não interpretável; redigido>"


def sanitize_example(field_name: str, value: str) -> str:
    if field_name == "request.target":
        return sanitize_target(value)
    if field_name == "url.query":
        names = [safe_name(key, 50) for key, _ in parse_qsl(
            value, keep_blank_values=True, encoding="latin-1", errors="replace"
        )]
        return "&".join(f"{name}=<valor>" for name in names[:8]) + (
            "&…" if len(names) > 8 else ""
        )
    if field_name == "body":
        return f"<corpo redigido; {len(value)} caracteres>"
    if field_name.startswith(("query_param:", "body_param:")):
        forms = [item for item in value_forms(value) if not item.startswith("comprimento:")]
        form_text = ", ".join(forms) if forms else "valor"
        return f"<{form_text}; {len(value)} caracteres>"
    if field_name == "header:cookie":
        return sanitize_cookie(value)
    if field_name in {"header:authorization", "header:proxy-authorization"}:
        scheme = value.split(None, 1)[0] if value.strip() else "credencial"
        return f"{safe_name(scheme, 30)} <redigido>"
    return safe_name(value.replace("\r", "\\r").replace("\n", "\\n"), 180)


@dataclass
class FieldStats:
    request_count: int = 0
    value_count: int = 0
    methods: Counter[str] = field(default_factory=Counter)
    forms: Counter[str] = field(default_factory=Counter)
    examples: list[str] = field(default_factory=list)

    def observe(self, method: str, values: Iterable[str], name: str) -> None:
        values = list(values)
        self.request_count += 1
        self.value_count += len(values)
        self.methods[method] += 1
        for value in values:
            self.forms.update(value_forms(value))
            example = sanitize_example(name, value)
            if example not in self.examples and len(self.examples) < 3:
                self.examples.append(example)


@dataclass
class MethodStats:
    count: int = 0
    with_query: int = 0
    with_body: int = 0
    with_body_parameters: int = 0
    header_values: int = 0
    query_parameter_values: int = 0
    body_parameter_values: int = 0
    headers: Counter[str] = field(default_factory=Counter)


@dataclass
class ParsedRequest:
    method: str
    target: str
    version: str
    headers: dict[str, list[str]]
    body: bytes
    malformed_headers: list[str]


class DigestReader:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.digest = hashlib.sha256()
        self.bytes_read = 0

    def readline(self) -> bytes:
        data = self.stream.readline()
        self.digest.update(data)
        self.bytes_read += len(data)
        return data

    def read(self, size: int) -> bytes:
        data = self.stream.read(size)
        self.digest.update(data)
        self.bytes_read += len(data)
        return data


def iter_requests(path: Path, parser_info: Counter[str]) -> tuple[Iterable[ParsedRequest], DigestReader]:
    """Cria iterador streaming e expõe o leitor para o hash ao final."""

    raw_file = path.open("rb")
    reader = DigestReader(raw_file)

    def generate() -> Iterable[ParsedRequest]:
        try:
            pending = b""
            while True:
                line = pending or reader.readline()
                pending = b""
                if not line:
                    break
                stripped = line.rstrip(b"\r\n")
                if not stripped:
                    continue
                match = REQUEST_LINE_RE.match(stripped)
                if not match:
                    parser_info["linhas_fora_de_requisicao"] += 1
                    continue

                method, target, version = (decode(part) for part in match.groups())
                headers: dict[str, list[str]] = defaultdict(list)
                malformed_headers: list[str] = []
                last_header = ""
                while True:
                    header_line = reader.readline()
                    if not header_line:
                        parser_info["fim_durante_headers"] += 1
                        break
                    header_raw = header_line.rstrip(b"\r\n")
                    if not header_raw:
                        break
                    if header_raw[:1] in {b" ", b"\t"} and last_header:
                        headers[last_header][-1] += " " + decode(header_raw).strip()
                        parser_info["headers_continuados"] += 1
                        continue
                    if b":" not in header_raw:
                        malformed_headers.append(decode(header_raw))
                        last_header = ""
                        continue
                    raw_name, raw_value = header_raw.split(b":", 1)
                    name = safe_name(decode(raw_name).lower(), 120)
                    headers[name].append(decode(raw_value).strip())
                    last_header = name

                content_length = 0
                if "content-length" in headers:
                    try:
                        content_length = int(headers["content-length"][-1].strip())
                        if content_length < 0:
                            raise ValueError
                    except ValueError:
                        parser_info["content_length_invalido"] += 1
                        content_length = 0
                body = reader.read(content_length) if content_length else b""
                if len(body) != content_length:
                    parser_info["corpo_truncado"] += 1

                yield ParsedRequest(
                    method=safe_name(method.upper(), 40),
                    target=target,
                    version=safe_name(version, 30),
                    headers=dict(headers),
                    body=body,
                    malformed_headers=malformed_headers,
                )
        finally:
            raw_file.close()

    return generate(), reader


class DatasetAnalyzer:
    def __init__(self, label: str, path: Path):
        self.label = label
        self.path = path
        self.total = 0
        self.methods: Counter[str] = Counter()
        self.versions: Counter[str] = Counter()
        self.target_forms: Counter[str] = Counter()
        self.fields: dict[str, FieldStats] = defaultdict(FieldStats)
        self.by_method: dict[str, MethodStats] = defaultdict(MethodStats)
        self.parser_info: Counter[str] = Counter()
        self.malformed_header_examples: list[str] = []
        self.digest = ""
        self.bytes_read = 0

    def observe_field(self, name: str, method: str, values: Iterable[str]) -> None:
        values = list(values)
        if values:
            self.fields[name].observe(method, values, name)

    def analyze(self) -> None:
        requests, reader = iter_requests(self.path, self.parser_info)
        for request in requests:
            self.total += 1
            method = request.method
            self.methods[method] += 1
            self.versions[request.version] += 1
            method_stats = self.by_method[method]
            method_stats.count += 1

            self.observe_field("request.method", method, [method])
            self.observe_field("request.target", method, [request.target])
            self.observe_field("request.http_version", method, [request.version])

            try:
                parsed = urlsplit(request.target)
                target_form = "absoluta" if parsed.scheme and parsed.netloc else "origem"
                if request.target == "*":
                    target_form = "asterisco"
                elif method == "CONNECT" and not parsed.path.startswith("/"):
                    target_form = "autoridade"
                self.target_forms[target_form] += 1
                if parsed.scheme:
                    self.observe_field("url.scheme", method, [parsed.scheme])
                if parsed.hostname:
                    self.observe_field("url.host", method, [parsed.hostname])
                try:
                    if parsed.port is not None:
                        self.observe_field("url.port", method, [str(parsed.port)])
                except ValueError:
                    self.parser_info["porta_url_invalida"] += 1
                self.observe_field("url.path", method, [parsed.path or "/"])
                if parsed.query:
                    self.observe_field("url.query", method, [parsed.query])
                    self.observe_field("query.parameters", method, ["presente"])
                    method_stats.with_query += 1
                    grouped_query: dict[str, list[str]] = defaultdict(list)
                    for key, value in parse_qsl(
                        parsed.query,
                        keep_blank_values=True,
                        encoding="latin-1",
                        errors="replace",
                    ):
                        grouped_query[safe_name(key or "<nome-vazio>")].append(value)
                    for key, values in grouped_query.items():
                        self.observe_field(f"query_param:{key}", method, values)
                        method_stats.query_parameter_values += len(values)
            except ValueError:
                self.parser_info["url_nao_interpretavel"] += 1

            if request.headers:
                self.observe_field("headers", method, [str(len(request.headers))])
            for name, values in request.headers.items():
                self.observe_field(f"header:{name}", method, values)
                method_stats.headers[name] += 1
                method_stats.header_values += len(values)

            if request.malformed_headers:
                self.observe_field(
                    "headers.malformed",
                    method,
                    ["linha sem separador ':'"] * len(request.malformed_headers),
                )
                for value in request.malformed_headers:
                    example = safe_name(value, 120)
                    if example not in self.malformed_header_examples and len(self.malformed_header_examples) < 3:
                        self.malformed_header_examples.append(example)

            if request.body:
                body_text = decode(request.body)
                self.observe_field("body", method, [body_text])
                method_stats.with_body += 1
                content_types = request.headers.get("content-type", [])
                is_form = any(
                    item.lower().split(";", 1)[0].strip()
                    == "application/x-www-form-urlencoded"
                    for item in content_types
                )
                looks_like_form = "=" in body_text and "\x00" not in body_text
                if is_form or looks_like_form:
                    grouped_body: dict[str, list[str]] = defaultdict(list)
                    for key, value in parse_qsl(
                        body_text,
                        keep_blank_values=True,
                        encoding="latin-1",
                        errors="replace",
                    ):
                        grouped_body[safe_name(key or "<nome-vazio>")].append(value)
                    if grouped_body:
                        self.observe_field("body.parameters", method, ["presente"])
                        method_stats.with_body_parameters += 1
                    for key, values in grouped_body.items():
                        self.observe_field(f"body_param:{key}", method, values)
                        method_stats.body_parameter_values += len(values)

        self.digest = reader.digest.hexdigest()
        self.bytes_read = reader.bytes_read

    def field_dict(self, name: str, stats: FieldStats) -> dict:
        all_methods = sorted(self.methods)
        methods = sorted(stats.methods)
        return {
            "requisicoes_com_campo": stats.request_count,
            "percentual_requisicoes": percentage(stats.request_count, self.total),
            "total_valores": stats.value_count,
            "presenca": "todas" if stats.request_count == self.total else "parte",
            "metodos": methods,
            "somente_em_determinados_metodos": methods != all_methods,
            "por_metodo": {
                method: {
                    "ocorrencias": stats.methods.get(method, 0),
                    "percentual": percentage(stats.methods.get(method, 0), self.methods[method]),
                }
                for method in all_methods
            },
            "formas_valores": dict(stats.forms.most_common()),
            "exemplos_sanitizados": stats.examples,
        }

    def to_dict(self) -> dict:
        return {
            "rotulo": self.label,
            "arquivo": str(self.path.relative_to(ROOT)).replace("\\", "/"),
            "tamanho_bytes": self.path.stat().st_size,
            "bytes_lidos": self.bytes_read,
            "sha256": self.digest,
            "total_requisicoes": self.total,
            "metodos": dict(self.methods.most_common()),
            "versoes_http": dict(self.versions.most_common()),
            "formas_request_target": dict(self.target_forms.most_common()),
            "parser": dict(self.parser_info),
            "headers_malformados_exemplos": self.malformed_header_examples,
            "campos": {
                name: self.field_dict(name, stats)
                for name, stats in sorted(self.fields.items())
            },
            "analise_por_metodo": {
                method: method_dict(stats, self.methods[method])
                for method, stats in sorted(self.by_method.items())
            },
        }


def percentage(value: int, total: int) -> float:
    return round(100.0 * value / total, 4) if total else 0.0


def average(value: int, total: int) -> float:
    return round(value / total, 4) if total else 0.0


def method_dict(stats: MethodStats, total: int) -> dict:
    return {
        "requisicoes": total,
        "com_query": stats.with_query,
        "percentual_com_query": percentage(stats.with_query, total),
        "com_body": stats.with_body,
        "percentual_com_body": percentage(stats.with_body, total),
        "com_parametros_body": stats.with_body_parameters,
        "percentual_com_parametros_body": percentage(stats.with_body_parameters, total),
        "media_headers_por_requisicao": average(stats.header_values, total),
        "media_parametros_query_por_requisicao": average(stats.query_parameter_values, total),
        "media_parametros_body_por_requisicao": average(stats.body_parameter_values, total),
        "headers_por_presenca": dict(stats.headers.most_common()),
    }


def field_category(name: str) -> str:
    if name.startswith("header:"):
        return "header"
    if name.startswith("query_param:"):
        return "parametro_query"
    if name.startswith("body_param:"):
        return "parametro_body"
    return "estrutura"


def compact_forms(field_data: dict | None) -> str:
    if not field_data:
        return ""
    forms = field_data["formas_valores"]
    return "; ".join(f"{name}={count}" for name, count in list(forms.items())[:12])


def field_interpretation(normal: dict | None, anomalous: dict | None) -> str:
    if normal and anomalous:
        difference = anomalous["percentual_requisicoes"] - normal["percentual_requisicoes"]
        if math.isclose(difference, 0.0, abs_tol=0.05):
            return "presença equivalente"
        return "mais frequente no anômalo" if difference > 0 else "mais frequente no normal"
    return "somente no normal" if normal else "somente no anômalo"


def write_field_comparison(output: Path, summaries: dict[str, dict]) -> None:
    normal_fields = summaries["normal"]["campos"]
    anomalous_fields = summaries["anomalo"]["campos"]
    fieldnames = [
        "categoria",
        "campo",
        "normal_ocorrencias",
        "normal_percentual",
        "anomalo_ocorrencias",
        "anomalo_percentual",
        "diferenca_anomalo_menos_normal_pp",
        "normal_metodos",
        "anomalo_metodos",
        "normal_formas_valores",
        "anomalo_formas_valores",
        "comparacao",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        for name in sorted(set(normal_fields) | set(anomalous_fields)):
            normal = normal_fields.get(name)
            anomalous = anomalous_fields.get(name)
            normal_pct = normal["percentual_requisicoes"] if normal else 0.0
            anomalous_pct = anomalous["percentual_requisicoes"] if anomalous else 0.0
            writer.writerow({
                "categoria": field_category(name),
                "campo": name,
                "normal_ocorrencias": normal["requisicoes_com_campo"] if normal else 0,
                "normal_percentual": normal_pct,
                "anomalo_ocorrencias": anomalous["requisicoes_com_campo"] if anomalous else 0,
                "anomalo_percentual": anomalous_pct,
                "diferenca_anomalo_menos_normal_pp": round(anomalous_pct - normal_pct, 4),
                "normal_metodos": "|".join(normal["metodos"]) if normal else "",
                "anomalo_metodos": "|".join(anomalous["metodos"]) if anomalous else "",
                "normal_formas_valores": compact_forms(normal),
                "anomalo_formas_valores": compact_forms(anomalous),
                "comparacao": field_interpretation(normal, anomalous),
            })


def write_method_comparison(output: Path, summaries: dict[str, dict]) -> None:
    columns = [
        "metodo",
        "normal_requisicoes",
        "normal_percentual",
        "anomalo_requisicoes",
        "anomalo_percentual",
        "diferenca_anomalo_menos_normal_pp",
        "normal_percentual_com_query",
        "anomalo_percentual_com_query",
        "normal_percentual_com_body",
        "anomalo_percentual_com_body",
        "normal_media_headers",
        "anomalo_media_headers",
        "normal_media_parametros_query",
        "anomalo_media_parametros_query",
        "normal_media_parametros_body",
        "anomalo_media_parametros_body",
    ]
    methods = sorted(set(summaries["normal"]["metodos"]) | set(summaries["anomalo"]["metodos"]))
    with output.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for method in methods:
            normal_count = summaries["normal"]["metodos"].get(method, 0)
            anomalous_count = summaries["anomalo"]["metodos"].get(method, 0)
            normal = summaries["normal"]["analise_por_metodo"].get(method, {})
            anomalous = summaries["anomalo"]["analise_por_metodo"].get(method, {})
            normal_pct = percentage(normal_count, summaries["normal"]["total_requisicoes"])
            anomalous_pct = percentage(anomalous_count, summaries["anomalo"]["total_requisicoes"])
            writer.writerow({
                "metodo": method,
                "normal_requisicoes": normal_count,
                "normal_percentual": normal_pct,
                "anomalo_requisicoes": anomalous_count,
                "anomalo_percentual": anomalous_pct,
                "diferenca_anomalo_menos_normal_pp": round(anomalous_pct - normal_pct, 4),
                "normal_percentual_com_query": normal.get("percentual_com_query", 0),
                "anomalo_percentual_com_query": anomalous.get("percentual_com_query", 0),
                "normal_percentual_com_body": normal.get("percentual_com_body", 0),
                "anomalo_percentual_com_body": anomalous.get("percentual_com_body", 0),
                "normal_media_headers": normal.get("media_headers_por_requisicao", 0),
                "anomalo_media_headers": anomalous.get("media_headers_por_requisicao", 0),
                "normal_media_parametros_query": normal.get("media_parametros_query_por_requisicao", 0),
                "anomalo_media_parametros_query": anomalous.get("media_parametros_query_por_requisicao", 0),
                "normal_media_parametros_body": normal.get("media_parametros_body_por_requisicao", 0),
                "anomalo_media_parametros_body": anomalous.get("media_parametros_body_por_requisicao", 0),
            })


def md_table(headers: list[str], rows: Iterable[Iterable[object]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return lines


def names_by_prefix(summary: dict, prefix: str) -> list[str]:
    return sorted(name[len(prefix):] for name in summary["campos"] if name.startswith(prefix))


def pct_text(value: float) -> str:
    return f"{value:.2f}%".replace(".", ",")


def write_report(output: Path, summaries: dict[str, dict]) -> None:
    normal = summaries["normal"]
    anomalous = summaries["anomalo"]
    all_methods = sorted(set(normal["metodos"]) | set(anomalous["metodos"]))
    normal_fields = normal["campos"]
    anomalous_fields = anomalous["campos"]
    shared = sorted(set(normal_fields) & set(anomalous_fields))
    normal_only = sorted(set(normal_fields) - set(anomalous_fields))
    anomalous_only = sorted(set(anomalous_fields) - set(normal_fields))

    lines = [
        "# Relatório de descoberta estrutural — CSIC 2010",
        "",
        "> Esta etapa descreve o conteúdo observado. Não seleciona features, não define limites, "
        "não normaliza dados e não treina modelos.",
        "",
        "## Escopo e método",
        "",
        "Os dois arquivos foram percorridos integralmente em modo binário e sequencial. "
        "As contagens representam presença por requisição; `total_valores` no JSON também "
        "registra repetições do mesmo header ou parâmetro. Os exemplos são limitados a três "
        "por campo, truncados e têm cookies, credenciais e valores de parâmetros redigidos.",
        "",
        "## Quantidade de requisições",
        "",
        *md_table(
            ["Dataset", "Arquivo", "Requisições", "Bytes lidos", "SHA-256"],
            [
                ["Normal", normal["arquivo"], normal["total_requisicoes"], normal["bytes_lidos"], f"`{normal['sha256']}`"],
                ["Anômalo", anomalous["arquivo"], anomalous["total_requisicoes"], anomalous["bytes_lidos"], f"`{anomalous['sha256']}`"],
            ],
        ),
        "",
        "## Métodos HTTP encontrados",
        "",
        *md_table(
            ["Método", "Normal", "% normal", "Anômalo", "% anômalo"],
            [
                [
                    method,
                    normal["metodos"].get(method, 0),
                    pct_text(percentage(normal["metodos"].get(method, 0), normal["total_requisicoes"])),
                    anomalous["metodos"].get(method, 0),
                    pct_text(percentage(anomalous["metodos"].get(method, 0), anomalous["total_requisicoes"])),
                ]
                for method in all_methods
            ],
        ),
        "",
        "## Informações extraíveis de uma requisição",
        "",
        "A estrutura observada permite extrair: método; target/URL original; versão HTTP; "
        "scheme, host, porta, path e query; nomes e valores dos parâmetros da query; conjunto "
        "de headers e seus valores; corpo; tipo e comprimento declarado do corpo; e nomes e "
        "valores de parâmetros de corpos `application/x-www-form-urlencoded`. A lista completa "
        "de campos, frequência, métodos, formas de valores e exemplos sanitizados está em "
        "`resumo_estrutura.json` e `comparacao_campos.csv`.",
        "",
        "### Headers encontrados",
        "",
        *md_table(
            ["Dataset", "Headers"],
            [
                ["Normal", ", ".join(names_by_prefix(normal, "header:"))],
                ["Anômalo", ", ".join(names_by_prefix(anomalous, "header:"))],
            ],
        ),
        "",
        "### Parâmetros encontrados",
        "",
        *md_table(
            ["Origem", "Normal", "Anômalo"],
            [
                ["Query", ", ".join(names_by_prefix(normal, "query_param:")), ", ".join(names_by_prefix(anomalous, "query_param:"))],
                ["Body", ", ".join(names_by_prefix(normal, "body_param:")), ", ".join(names_by_prefix(anomalous, "body_param:"))],
            ],
        ),
        "",
        "## Campos comuns e variáveis",
        "",
    ]

    for title, dataset in (("Normal", normal), ("Anômalo", anomalous)):
        universal = [name for name, data in dataset["campos"].items() if data["presenca"] == "todas"]
        partial = [name for name, data in dataset["campos"].items() if data["presenca"] == "parte"]
        lines.extend([
            f"### {title}",
            "",
            f"Presentes em todas as requisições ({len(universal)}): " + ", ".join(f"`{name}`" for name in universal) + ".",
            "",
            f"Presentes somente em parte ({len(partial)}): " + ", ".join(f"`{name}`" for name in partial) + ".",
            "",
        ])

    lines.extend([
        "## Comparação normal × anômalo",
        "",
        f"Há **{len(shared)} campos** observados nos dois conjuntos, **{len(normal_only)} somente no normal** "
        f"e **{len(anomalous_only)} somente no anômalo**. Exclusivos do normal: "
        f"{', '.join(f'`{name}`' for name in normal_only) or 'nenhum'}. Exclusivos do anômalo: "
        f"{', '.join(f'`{name}`' for name in anomalous_only) or 'nenhum'}.",
        "",
        "As maiores diferenças de presença (em pontos percentuais) são:",
        "",
    ])
    differences = []
    for name in shared:
        n_pct = normal_fields[name]["percentual_requisicoes"]
        a_pct = anomalous_fields[name]["percentual_requisicoes"]
        differences.append((abs(a_pct - n_pct), name, n_pct, a_pct))
    lines.extend(md_table(
        ["Campo", "% normal", "% anômalo", "Diferença anômalo − normal"],
        [
            [f"`{name}`", pct_text(n_pct), pct_text(a_pct), f"{a_pct - n_pct:+.2f} pp"]
            for _, name, n_pct, a_pct in sorted(differences, reverse=True)[:15]
        ],
    ))
    lines.extend(["", "## Estrutura por método", ""])

    for method in all_methods:
        n = normal["analise_por_metodo"].get(method)
        a = anomalous["analise_por_metodo"].get(method)
        lines.extend([f"### {method}", ""])
        rows = []
        for label, values in (("Normal", n), ("Anômalo", a)):
            if not values:
                rows.append([label, 0, "—", "—", "—", "—", "—"])
            else:
                rows.append([
                    label,
                    values["requisicoes"],
                    pct_text(values["percentual_com_query"]),
                    pct_text(values["percentual_com_body"]),
                    pct_text(values["percentual_com_parametros_body"]),
                    values["media_headers_por_requisicao"],
                    f"{values['media_parametros_query_por_requisicao']} / {values['media_parametros_body_por_requisicao']}",
                ])
        lines.extend(md_table(
            ["Dataset", "Requisições", "Com query", "Com body", "Body parametrizado", "Média headers", "Média params query/body"],
            rows,
        ))
        lines.append("")

    lines.extend([
        "## Observações do parser",
        "",
        "O arquivo normal não produziu ocorrências de parsing. No arquivo anômalo, "
        f"**{anomalous['parser'].get('porta_url_invalida', 0)} targets** continham uma "
        "representação de porta que não pôde ser convertida em número. Esses targets "
        "continuaram contabilizados, com método, URL original, path, query, headers e body "
        "preservados na análise; somente o componente numérico `url.port` ficou ausente.",
        "",
        "## Observações metodológicas",
        "",
        "- A comparação é estrutural entre o conjunto normal de treinamento e o conjunto anômalo de teste fornecidos; ela não demonstra, por si só, que uma diferença seja útil para classificação.",
        "- As formas de valores no JSON são marcadores não exclusivos: um mesmo valor pode ser, por exemplo, textual, percent-encoded e conter bytes não ASCII.",
        "- O parser usa `Content-Length` para ler corpos e Latin-1 para preservar a correspondência de um byte por caractere do corpus.",
        "- Nenhuma requisição original foi modificada e nenhum conteúdo integral foi exportado.",
        "",
    ])
    output.write_text("\n".join(lines), encoding="utf-8")


def build_summary(analyzers: dict[str, DatasetAnalyzer]) -> dict:
    datasets = {key: analyzer.to_dict() for key, analyzer in analyzers.items()}
    normal_fields = set(datasets["normal"]["campos"])
    anomalous_fields = set(datasets["anomalo"]["campos"])
    return {
        "metadados": {
            "gerado_em_utc": datetime.now(timezone.utc).isoformat(),
            "objetivo": "descoberta estrutural; sem seleção de features, normalização ou treinamento",
            "leitura": "streaming binário; arquivos originais somente leitura",
            "limite_exemplos_sanitizados_por_campo": 3,
        },
        "datasets": datasets,
        "comparacao": {
            "campos_em_ambos": sorted(normal_fields & anomalous_fields),
            "campos_somente_normal": sorted(normal_fields - anomalous_fields),
            "campos_somente_anomalo": sorted(anomalous_fields - normal_fields),
            "metodos_em_ambos": sorted(set(datasets["normal"]["metodos"]) & set(datasets["anomalo"]["metodos"])),
            "metodos_somente_normal": sorted(set(datasets["normal"]["metodos"]) - set(datasets["anomalo"]["metodos"])),
            "metodos_somente_anomalo": sorted(set(datasets["anomalo"]["metodos"]) - set(datasets["normal"]["metodos"])),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--normal", type=Path, default=DEFAULT_INPUTS["normal"])
    parser.add_argument("--anomalo", type=Path, default=DEFAULT_INPUTS["anomalo"])
    parser.add_argument("--saida", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs = {"normal": args.normal.resolve(), "anomalo": args.anomalo.resolve()}
    for label, path in inputs.items():
        if not path.is_file():
            raise FileNotFoundError(f"Arquivo {label} não encontrado: {path}")

    output = args.saida.resolve()
    output.mkdir(parents=True, exist_ok=True)
    analyzers = {label: DatasetAnalyzer(label, path) for label, path in inputs.items()}
    for analyzer in analyzers.values():
        analyzer.analyze()

    summary = build_summary(analyzers)
    summary_path = output / "resumo_estrutura.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    datasets = summary["datasets"]
    write_field_comparison(output / "comparacao_campos.csv", datasets)
    write_method_comparison(output / "comparacao_metodos.csv", datasets)
    write_report(output / "relatorio_estrutura.md", datasets)

    for label, dataset in datasets.items():
        print(f"{label}: {dataset['total_requisicoes']} requisições; métodos={dataset['metodos']}")
    print(f"Resultados gravados em: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
