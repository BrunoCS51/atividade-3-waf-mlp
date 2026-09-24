"""Features HTTP candidatas e independentes de label para o Experimento 2.

Este módulo não normaliza, não seleciona features e não produz um vetor final.
A função pública ``extrair_features_candidatas`` é a implementação única a ser
reutilizada tanto na futura construção do dataset quanto em execução real.
"""

from __future__ import annotations

import ipaddress
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Mapping, Sequence
from urllib.parse import unquote, unquote_plus, urlsplit


PERCENT_RE = re.compile(r"%[0-9A-Fa-f]{2}")
SQL_PATTERNS = (
    re.compile(r"\b(?:select|union|insert|update|delete|drop|alter|create)\b", re.I),
    re.compile(r"\b(?:or|and)\s+[\w'\"]+\s*=\s*[\w'\"]+", re.I),
    re.compile(r"(?:--|/\*|\*/|;\s*(?:select|drop|insert|update|delete))", re.I),
)
XSS_PATTERNS = (
    re.compile(r"<\s*/?\s*(?:script|iframe|svg|img|object|embed)\b", re.I),
    re.compile(r"\bon[a-z]+\s*=", re.I),
    re.compile(r"(?:javascript|data)\s*:", re.I),
)
TRAVERSAL_PATTERNS = (
    re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)"),
    re.compile(r"(?:^|[\\/])\.(?:[\\/]|$)"),
)
SHELL_METACHARS = set(";&|`$<>")
COMMON_HEADER_NAMES = (
    "accept",
    "accept-charset",
    "accept-encoding",
    "accept-language",
    "cache-control",
    "connection",
    "content-length",
    "content-type",
    "cookie",
    "host",
    "pragma",
    "user-agent",
)


@dataclass(frozen=True)
class HTTPRequest:
    method: str
    target: str
    version: str
    headers: Mapping[str, Sequence[str]]
    body: bytes

    @classmethod
    def from_components(
        cls,
        method: str,
        target: str,
        version: str,
        headers: Mapping[str, Sequence[str]],
        body: bytes,
    ) -> "HTTPRequest":
        normalized = {
            str(name).strip().lower(): tuple(str(value) for value in values)
            for name, values in headers.items()
        }
        return cls(method.upper().strip(), target, version.strip(), normalized, bytes(body))


@dataclass(frozen=True)
class FeatureDefinition:
    nome_feature: str
    origem: str
    tipo: str
    descricao: str
    forma_calculo: str
    aplicabilidade: str
    observacoes_limitacoes: str
    contar_distintos: bool = True


FEATURE_DEFINITIONS: dict[str, FeatureDefinition] = {}

# Contrato oficial e ordenado de entrada do futuro modelo do Experimento 2.
# GET é a categoria-base: POST, PUT e outros possuem indicadores explícitos.
FEATURES_EXPERIMENTO_2 = (
    "method_is_post",
    "method_is_put",
    "method_is_other",
    "url_length_raw",
    "url_is_absolute",
    "url_parse_error",
    "url_host_present",
    "url_host_is_ip",
    "url_host_non_ascii_count",
    "url_userinfo_present",
    "url_port_present",
    "url_port_valid",
    "url_fragment_present",
    "path_length_raw",
    "path_percent_encoding_count",
    "path_invalid_percent_count",
    "path_non_ascii_count",
    "path_control_char_count",
    "path_digit_ratio",
    "path_special_ratio",
    "path_sql_pattern_count",
    "path_xss_pattern_count",
    "path_traversal_pattern_count",
    "path_shell_metachar_count",
    "path_segment_count",
    "path_double_slash_count",
    "path_extension_like_segment_count",
    "path_hidden_segment_count",
    "path_nested_extension_transition",
    "path_max_segment_length",
    "path_backslash_count",
    "query_present",
    "query_length_raw",
    "query_percent_encoding_count",
    "query_invalid_percent_count",
    "query_non_ascii_count",
    "query_control_char_count",
    "query_digit_ratio",
    "query_special_ratio",
    "query_sql_pattern_count",
    "query_xss_pattern_count",
    "query_traversal_pattern_count",
    "query_shell_metachar_count",
    "query_parameter_count",
    "query_repeated_parameter_count",
    "query_empty_value_count",
    "query_without_equals_count",
    "query_max_name_length",
    "query_max_value_length",
    "body_present",
    "body_length_raw",
    "body_percent_encoding_count",
    "body_invalid_percent_count",
    "body_non_ascii_count",
    "body_control_char_count",
    "body_digit_ratio",
    "body_special_ratio",
    "body_sql_pattern_count",
    "body_xss_pattern_count",
    "body_traversal_pattern_count",
    "body_shell_metachar_count",
    "body_parameter_count",
    "body_repeated_parameter_count",
    "body_empty_value_count",
    "body_without_equals_count",
    "body_max_name_length",
    "body_max_value_length",
    "header_unique_count",
    "header_duplicate_count",
    "header_has_host",
    "header_has_content_type",
    "content_type_is_form_urlencoded",
    "header_has_content_length",
    "content_length_valid",
    "content_length_delta",
    "host_matches_url_host",
)

# Toda candidata final que pode ser ausente possui um indicador no próprio
# contrato. O valor numérico substituto é 0.0; a combinação com o indicador
# separa ausência legítima, zero observado e invalidade estrutural.
INDICADORES_DE_AUSENCIA = {
    "url_host_is_ip": ("url_host_present",),
    "url_host_non_ascii_count": ("url_host_present",),
    "url_port_valid": ("url_port_present",),
    "content_type_is_form_urlencoded": ("header_has_content_type",),
    "content_length_valid": ("header_has_content_length",),
    "content_length_delta": ("header_has_content_length", "content_length_valid"),
    "host_matches_url_host": ("header_has_host", "url_host_present"),
}
for _component in ("query", "body"):
    for _suffix in (
        "length_raw",
        "percent_encoding_count",
        "invalid_percent_count",
        "non_ascii_count",
        "control_char_count",
        "digit_ratio",
        "special_ratio",
        "sql_pattern_count",
        "xss_pattern_count",
        "traversal_pattern_count",
        "shell_metachar_count",
        "parameter_count",
        "repeated_parameter_count",
        "empty_value_count",
        "without_equals_count",
        "max_name_length",
        "max_value_length",
    ):
        INDICADORES_DE_AUSENCIA[f"{_component}_{_suffix}"] = (f"{_component}_present",)


def _register(
    name: str,
    origin: str,
    kind: str,
    description: str,
    calculation: str,
    applicability: str = "todas as requisições",
    notes: str = "",
    distinct: bool = True,
) -> None:
    if name in FEATURE_DEFINITIONS:
        raise ValueError(f"Feature duplicada: {name}")
    FEATURE_DEFINITIONS[name] = FeatureDefinition(
        name, origin, kind, description, calculation, applicability, notes, distinct
    )


def _register_definitions() -> None:
    for method in ("get", "post", "put", "other"):
        label = method.upper() if method != "other" else "diferente de GET/POST/PUT"
        _register(
            f"method_is_{method}", "method", "binaria",
            f"Indica se o método é {label}.",
            f"1 quando o método é {label}; 0 caso contrário.",
            notes="Codificação one-hot evita impor ordem entre métodos. PUT pode refletir desenho do corpus e não deve ser tratado automaticamente como ataque.",
        )
    for version, suffix in (("1.0", "1_0"), ("1.1", "1_1"), ("2", "2"), ("other", "other")):
        _register(
            f"http_version_is_{suffix}", "url", "binaria",
            f"Indicador one-hot da versão HTTP {version}.",
            f"1 quando a versão pertence à categoria {version}; 0 caso contrário.",
            notes="Pode ser constante no CSIC e variar no tráfego real.",
        )

    content_metrics = (
        ("length_raw", "contagem", "Comprimento bruto.", "Número de caracteres antes de decodificar."),
        ("length_decoded_once", "contagem", "Comprimento após uma decodificação percentual.", "Número de caracteres após uma aplicação de percent-decoding."),
        ("percent_encoding_count", "contagem", "Quantidade de sequências percent-encoded válidas.", "Contagem de ocorrências %HH."),
        ("invalid_percent_count", "contagem", "Sinais de porcentagem sem par hexadecimal válido.", "Quantidade de '%' menos ocorrências %HH."),
        ("non_ascii_count", "contagem", "Caracteres não ASCII após uma decodificação.", "Contagem de caracteres com código maior que 127."),
        ("control_char_count", "contagem", "Caracteres de controle.", "Contagem de códigos menores que 32 ou iguais a 127."),
        ("alpha_ratio", "continua", "Proporção de caracteres alfabéticos.", "Caracteres alfabéticos / comprimento decodificado."),
        ("digit_ratio", "continua", "Proporção de caracteres numéricos.", "Dígitos / comprimento decodificado."),
        ("special_ratio", "continua", "Proporção de caracteres especiais.", "Caracteres não alfanuméricos e não espaços / comprimento decodificado."),
        ("entropy", "continua", "Entropia de Shannon da composição.", "-Σ p(c)·log2(p(c)) sobre caracteres decodificados."),
        ("max_repeat_run", "contagem", "Maior repetição consecutiva do mesmo caractere.", "Comprimento máximo de uma sequência de caracteres iguais."),
        ("sql_pattern_count", "contagem", "Ocorrências de padrões SQL genéricos.", "Soma de correspondências de expressões regulares SQL após uma decodificação."),
        ("xss_pattern_count", "contagem", "Ocorrências de padrões XSS genéricos.", "Soma de correspondências de tags, handlers e esquemas associados a XSS."),
        ("traversal_pattern_count", "contagem", "Ocorrências de segmentos de navegação relativa.", "Contagem de segmentos '.' e '..' delimitados por barras."),
        ("shell_metachar_count", "contagem", "Metacaracteres comuns de shell/comando.", "Contagem de ; & | ` $ < >."),
    )
    for origin in ("url", "path", "query", "body"):
        applicability = "componente presente" if origin in {"query", "body"} else "todas as requisições"
        for suffix, kind, description, calculation in content_metrics:
            _register(
                f"{origin}_{suffix}", origin, kind,
                f"{description} Aplicada a {origin}.", calculation,
                applicability=applicability,
                notes="Métrica genérica e independente de label. Contagens de padrões dependem da cobertura das expressões e podem produzir falsos positivos.",
                distinct=kind != "continua",
            )

    url_defs = (
        ("url_is_absolute", "binaria", "Target em forma absoluta.", "1 quando scheme e autoridade estão presentes."),
        ("url_parse_error", "binaria", "Falha estrutural no parsing geral da URL.", "1 quando urlsplit não consegue interpretar o target."),
        ("url_scheme_is_http", "binaria", "Scheme HTTP.", "1 quando scheme é http."),
        ("url_scheme_is_https", "binaria", "Scheme HTTPS.", "1 quando scheme é https."),
        ("url_scheme_is_other", "binaria", "Outro scheme explícito.", "1 para scheme presente diferente de HTTP/HTTPS."),
        ("url_scheme_missing", "binaria", "Ausência de scheme.", "1 quando o request-target não contém scheme."),
        ("url_host_present", "binaria", "Host presente no target.", "1 quando a URL contém hostname interpretável."),
        ("url_host_length", "contagem", "Comprimento do hostname.", "Número de caracteres do hostname; ausente quando indisponível."),
        ("url_host_label_count", "contagem", "Quantidade de rótulos no hostname.", "Número de partes não vazias separadas por ponto."),
        ("url_host_is_ip", "binaria", "Hostname é endereço IP.", "1 quando ipaddress reconhece IPv4 ou IPv6; ausente sem host."),
        ("url_host_non_ascii_count", "contagem", "Caracteres não ASCII no hostname.", "Contagem de caracteres do host acima de 127."),
        ("url_userinfo_present", "binaria", "Credenciais/userinfo na autoridade.", "1 quando username ou password aparece na URL."),
        ("url_port_present", "binaria", "Delimitador de porta explícito.", "1 quando a autoridade contém componente de porta."),
        ("url_port_valid", "binaria", "Porta explícita numericamente válida.", "1 para inteiro entre 0 e 65535; 0 para representação inválida; ausente quando não há porta."),
        ("url_port_value", "contagem", "Valor numérico da porta.", "Inteiro da porta; ausente quando não há porta ou ela é inválida."),
        ("url_port_is_standard", "binaria", "Porta HTTP/HTTPS usual.", "1 para 80 ou 443; ausente sem porta válida."),
        ("url_fragment_present", "binaria", "Fragmento presente no target.", "1 quando há componente após #."),
    )
    for item in url_defs:
        applicability = "porta explícita" if item[0] in {"url_port_valid", "url_port_value", "url_port_is_standard"} else "todas as requisições"
        notes = "Falhas de porta ficam separadas de ausência; nunca são convertidas silenciosamente em zero." if item[0].startswith("url_port_") else ""
        _register(item[0], "url", item[1], item[2], item[3], applicability, notes)

    path_defs = (
        ("path_segment_count", "contagem", "Quantidade de segmentos não vazios.", "Partes não vazias separadas por '/'."),
        ("path_depth", "contagem", "Profundidade do path.", "Igual à quantidade de segmentos não vazios."),
        ("path_empty_inner_segment_count", "contagem", "Segmentos vazios internos.", "Partes vazias entre a primeira e a última barra."),
        ("path_double_slash_count", "contagem", "Ocorrências de barras duplas.", "Contagem de '//'."),
        ("path_dot_segment_count", "contagem", "Segmentos exatamente '.' ou '..'.", "Contagem de segmentos de navegação relativa."),
        ("path_segments_with_dot_count", "contagem", "Segmentos que contêm ponto.", "Quantidade de segmentos contendo '.'."),
        ("path_extension_like_segment_count", "contagem", "Segmentos com aparência de extensão.", "Segmentos com ponto interno ou iniciados por ponto e seguidos por caracteres."),
        ("path_max_extensions_in_segment", "contagem", "Maior quantidade de sufixos separados por ponto num segmento.", "Máximo de pontos úteis por segmento."),
        ("path_hidden_segment_count", "contagem", "Segmentos iniciados por ponto.", "Contagem de segmentos cujo primeiro caractere é '.'."),
        ("path_nested_extension_transition", "binaria", "Extensão seguida de outro segmento com aparência de extensão.", "1 quando um segmento com extensão é seguido por segmento iniciado por ponto ou também contendo extensão."),
        ("path_max_segment_length", "contagem", "Maior comprimento de segmento.", "Máximo dos comprimentos dos segmentos decodificados uma vez."),
        ("path_trailing_slash", "binaria", "Path termina com barra.", "1 quando termina em '/'."),
        ("path_backslash_count", "contagem", "Quantidade de barras invertidas.", "Contagem de '\\'."),
    )
    for name, kind, description, calculation in path_defs:
        _register(name, "path", kind, description, calculation, notes="Preserva estrutura sem memorizar nomes concretos de arquivos ou diretórios.")

    parameter_defs = (
        ("present", "binaria", "Presença do componente.", "1 quando o delimitador/componente existe."),
        ("parameter_count", "contagem", "Quantidade de pares de parâmetros.", "Número de partes não vazias separadas por '&'."),
        ("distinct_parameter_name_count", "contagem", "Quantidade de nomes distintos.", "Cardinalidade dos nomes após uma decodificação."),
        ("repeated_parameter_count", "contagem", "Parâmetros repetidos.", "Quantidade de ocorrências além da primeira para cada nome."),
        ("empty_name_count", "contagem", "Parâmetros com nome vazio.", "Contagem de pares cujo nome decodificado é vazio."),
        ("empty_value_count", "contagem", "Parâmetros com valor vazio.", "Contagem de pares cujo valor decodificado é vazio."),
        ("without_equals_count", "contagem", "Partes sem sinal de igual.", "Contagem de fragmentos de parâmetro sem '='."),
        ("mean_name_length", "continua", "Comprimento médio dos nomes.", "Média dos comprimentos dos nomes decodificados."),
        ("max_name_length", "contagem", "Maior nome de parâmetro.", "Máximo dos comprimentos dos nomes decodificados."),
        ("mean_value_length", "continua", "Comprimento médio dos valores.", "Média dos comprimentos dos valores decodificados."),
        ("max_value_length", "contagem", "Maior valor de parâmetro.", "Máximo dos comprimentos dos valores decodificados."),
        ("total_value_length", "contagem", "Comprimento total dos valores.", "Soma dos comprimentos dos valores decodificados."),
    )
    for origin in ("query", "body"):
        for suffix, kind, description, calculation in parameter_defs:
            applicability = "todas as requisições" if suffix == "present" else f"{origin} presente e parametrizável"
            _register(
                f"{origin}_{suffix}", origin, kind,
                f"{description} Aplicada a {origin}.", calculation,
                applicability,
                "Não usa nomes específicos de parâmetros; nomes são apenas agregados por comprimento, repetição e vazio.",
                distinct=kind != "continua",
            )

    for header in COMMON_HEADER_NAMES:
        suffix = header.replace("-", "_")
        _register(
            f"header_has_{suffix}", "headers", "binaria",
            f"Presença do header {header}.",
            f"1 quando existe ao menos uma ocorrência case-insensitive de {header}.",
            notes="Headers constantes no CSIC podem não generalizar para outros clientes e servidores.",
        )
    header_defs = (
        ("header_unique_count", "contagem", "Quantidade de nomes de headers distintos.", "Cardinalidade case-insensitive dos nomes."),
        ("header_value_count", "contagem", "Quantidade total de linhas/valores de headers.", "Soma das ocorrências, incluindo duplicatas."),
        ("header_duplicate_count", "contagem", "Ocorrências duplicadas de headers.", "Total de valores além da primeira ocorrência de cada nome."),
        ("content_type_is_form_urlencoded", "binaria", "Content-Type de formulário URL-encoded.", "1 quando o media type é application/x-www-form-urlencoded; ausente sem Content-Type."),
        ("content_length_valid", "binaria", "Content-Length inteiro não negativo.", "1 quando o valor pode ser convertido para inteiro >= 0; ausente sem header."),
        ("content_length_declared", "contagem", "Comprimento de corpo declarado.", "Valor inteiro do Content-Length; ausente quando inválido ou inexistente."),
        ("body_length_bytes", "contagem", "Comprimento real do body em bytes.", "len(body)."),
        ("content_length_delta", "contagem_assinada", "Diferença entre tamanho real e declarado.", "len(body) - Content-Length; ausente sem declaração válida."),
        ("content_length_matches_body", "binaria", "Coerência entre tamanho declarado e real.", "1 quando Content-Length == len(body); ausente sem declaração válida."),
        ("user_agent_length", "contagem", "Comprimento do primeiro User-Agent.", "Número de caracteres; ausente sem User-Agent."),
        ("user_agent_token_count", "contagem", "Quantidade aproximada de tokens no User-Agent.", "Partes não vazias separadas por espaços."),
        ("user_agent_parenthesis_count", "contagem", "Parênteses no User-Agent.", "Contagem de '(' e ')'."),
        ("host_header_length", "contagem", "Comprimento do primeiro Host.", "Número de caracteres; ausente sem Host."),
        ("host_header_port_present", "binaria", "Porta explícita no header Host.", "1 quando Host contém componente de porta; ausente sem Host."),
        ("host_header_port_valid", "binaria", "Porta válida no header Host.", "1 para porta inteira entre 0 e 65535; ausente sem porta explícita."),
        ("host_matches_url_host", "binaria", "Coerência entre Host e hostname da URL.", "1 quando os hostnames coincidem sem considerar caixa; ausente quando algum não existe."),
        ("cookie_length", "contagem", "Comprimento total dos headers Cookie.", "Soma dos comprimentos; ausente sem Cookie."),
        ("cookie_pair_count", "contagem", "Quantidade aproximada de pares em Cookie.", "Número de partes não vazias separadas por ';'."),
    )
    for name, kind, description, calculation in header_defs:
        applicability = "todas as requisições" if name in {"header_unique_count", "header_value_count", "header_duplicate_count", "body_length_bytes"} else "header/componente correspondente presente"
        notes = "Pode refletir peculiaridades do gerador CSIC; validar em tráfego real." if name.startswith(("user_agent", "cookie")) else ""
        _register(name, "headers", kind, description, calculation, applicability, notes, kind != "continua")


_register_definitions()


def parse_raw_http_request(raw: bytes) -> HTTPRequest:
    """Interpreta uma única requisição bruta sem depender de label ou contexto temporal."""

    separator = b"\r\n\r\n" if b"\r\n\r\n" in raw else b"\n\n"
    head, found, body = raw.partition(separator)
    if not found:
        head, body = raw, b""
    lines = head.replace(b"\r\n", b"\n").split(b"\n")
    if not lines or not lines[0].strip():
        raise ValueError("Requisição sem linha inicial")
    request_line = lines[0].strip()
    first_space = request_line.find(b" ")
    last_space = request_line.rfind(b" ")
    if first_space <= 0 or last_space <= first_space:
        raise ValueError("Linha inicial inválida")
    method = request_line[:first_space].decode("latin-1")
    target = request_line[first_space + 1:last_space].decode("latin-1")
    version_token = request_line[last_space + 1:].decode("latin-1")
    version = version_token[5:] if version_token.upper().startswith("HTTP/") else version_token
    headers: dict[str, list[str]] = defaultdict(list)
    last_header = ""
    for raw_line in lines[1:]:
        if raw_line[:1] in {b" ", b"\t"} and last_header:
            headers[last_header][-1] += " " + raw_line.decode("latin-1").strip()
            continue
        if b":" not in raw_line:
            continue
        name, value = raw_line.split(b":", 1)
        last_header = name.decode("latin-1").strip().lower()
        headers[last_header].append(value.decode("latin-1").strip())
    return HTTPRequest.from_components(method, target, version, headers, body)


def _decode_once(value: str, plus_as_space: bool = False) -> str:
    function = unquote_plus if plus_as_space else unquote
    return function(value, encoding="latin-1", errors="replace")


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = Counter(value)
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _max_repeat(value: str) -> int:
    if not value:
        return 0
    maximum = current = 1
    for previous, character in zip(value, value[1:]):
        current = current + 1 if character == previous else 1
        maximum = max(maximum, current)
    return maximum


def _content_metrics(value: str, plus_as_space: bool = False) -> dict[str, float]:
    decoded = _decode_once(value, plus_as_space)
    length = len(decoded)
    valid_percent = len(PERCENT_RE.findall(value))
    sql_count = sum(len(pattern.findall(decoded)) for pattern in SQL_PATTERNS)
    xss_count = sum(len(pattern.findall(decoded)) for pattern in XSS_PATTERNS)
    normalized_path = decoded.replace("\\", "/")
    traversal_count = sum(len(pattern.findall(normalized_path)) for pattern in TRAVERSAL_PATTERNS)
    return {
        "length_raw": float(len(value)),
        "length_decoded_once": float(length),
        "percent_encoding_count": float(valid_percent),
        "invalid_percent_count": float(max(0, value.count("%") - valid_percent)),
        "non_ascii_count": float(sum(ord(character) > 127 for character in decoded)),
        "control_char_count": float(sum(ord(character) < 32 or ord(character) == 127 for character in decoded)),
        "alpha_ratio": sum(character.isalpha() for character in decoded) / length if length else 0.0,
        "digit_ratio": sum(character.isdigit() for character in decoded) / length if length else 0.0,
        "special_ratio": sum(not character.isalnum() and not character.isspace() for character in decoded) / length if length else 0.0,
        "entropy": _entropy(decoded),
        "max_repeat_run": float(_max_repeat(decoded)),
        "sql_pattern_count": float(sql_count),
        "xss_pattern_count": float(xss_count),
        "traversal_pattern_count": float(traversal_count),
        "shell_metachar_count": float(sum(character in SHELL_METACHARS for character in decoded)),
    }


def _raw_authority(target: str) -> str:
    match = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]*)", target)
    return match.group(1) if match else ""


def _port_information(authority: str) -> tuple[bool, bool | None, int | None]:
    if not authority:
        return False, None, None
    host_port = authority.rsplit("@", 1)[-1]
    port_text: str | None = None
    if host_port.startswith("["):
        close = host_port.find("]")
        if close >= 0 and host_port[close + 1:].startswith(":"):
            port_text = host_port[close + 2:]
    elif ":" in host_port:
        port_text = host_port.rsplit(":", 1)[1]
    if port_text is None:
        return False, None, None
    try:
        port = int(port_text)
    except ValueError:
        return True, False, None
    return True, 0 <= port <= 65535, port if 0 <= port <= 65535 else None


def _parameter_metrics(raw: str) -> dict[str, float]:
    parts = [part for part in raw.split("&") if part != ""]
    names: list[str] = []
    values: list[str] = []
    without_equals = 0
    for part in parts:
        if "=" in part:
            name, value = part.split("=", 1)
        else:
            name, value = part, ""
            without_equals += 1
        names.append(_decode_once(name, True))
        values.append(_decode_once(value, True))
    name_counts = Counter(names)
    name_lengths = [len(name) for name in names]
    value_lengths = [len(value) for value in values]
    return {
        "parameter_count": float(len(parts)),
        "distinct_parameter_name_count": float(len(name_counts)),
        "repeated_parameter_count": float(sum(max(0, count - 1) for count in name_counts.values())),
        "empty_name_count": float(sum(not name for name in names)),
        "empty_value_count": float(sum(not value for value in values)),
        "without_equals_count": float(without_equals),
        "mean_name_length": sum(name_lengths) / len(name_lengths) if name_lengths else 0.0,
        "max_name_length": float(max(name_lengths, default=0)),
        "mean_value_length": sum(value_lengths) / len(value_lengths) if value_lengths else 0.0,
        "max_value_length": float(max(value_lengths, default=0)),
        "total_value_length": float(sum(value_lengths)),
    }


def _path_metrics(path: str) -> dict[str, float]:
    decoded = _decode_once(path)
    raw_segments = decoded.split("/")
    segments = [segment for segment in raw_segments if segment]
    inner = raw_segments[1:-1] if len(raw_segments) > 2 else []

    def extension_count(segment: str) -> int:
        stripped = segment[1:] if segment.startswith(".") else segment
        return stripped.count(".") + (1 if segment.startswith(".") and len(segment) > 1 else 0)

    ext_counts = [extension_count(segment) for segment in segments]
    extension_like = [count > 0 for count in ext_counts]
    nested_transition = any(
        extension_like[index] and (
            segments[index + 1].startswith(".") or extension_like[index + 1]
        )
        for index in range(max(0, len(segments) - 1))
    )
    return {
        "path_segment_count": float(len(segments)),
        "path_depth": float(len(segments)),
        "path_empty_inner_segment_count": float(sum(segment == "" for segment in inner)),
        "path_double_slash_count": float(decoded.count("//")),
        "path_dot_segment_count": float(sum(segment in {".", ".."} for segment in segments)),
        "path_segments_with_dot_count": float(sum("." in segment for segment in segments)),
        "path_extension_like_segment_count": float(sum(extension_like)),
        "path_max_extensions_in_segment": float(max(ext_counts, default=0)),
        "path_hidden_segment_count": float(sum(segment.startswith(".") for segment in segments)),
        "path_nested_extension_transition": float(nested_transition),
        "path_max_segment_length": float(max((len(segment) for segment in segments), default=0)),
        "path_trailing_slash": float(decoded.endswith("/")),
        "path_backslash_count": float(decoded.count("\\")),
    }


def _first(headers: Mapping[str, Sequence[str]], name: str) -> str | None:
    values = headers.get(name, ())
    return str(values[0]) if values else None


def _host_and_port(value: str) -> tuple[str, bool, bool | None]:
    value = value.strip()
    if value.startswith("["):
        close = value.find("]")
        host = value[1:close] if close >= 0 else value
        suffix = value[close + 1:] if close >= 0 else ""
        present = suffix.startswith(":")
        port_text = suffix[1:] if present else ""
    elif ":" in value:
        host, port_text = value.rsplit(":", 1)
        present = True
    else:
        host, port_text, present = value, "", False
    if not present:
        return host, False, None
    try:
        port = int(port_text)
    except ValueError:
        return host, True, False
    return host, True, 0 <= port <= 65535


def extrair_features_candidatas(source: HTTPRequest | bytes) -> dict[str, float | None]:
    """Transforma uma requisição em candidatas numéricas, sem label/request_rate."""

    request = parse_raw_http_request(source) if isinstance(source, bytes) else source
    method = request.method.upper()
    values: dict[str, float | None] = {}
    for candidate in ("get", "post", "put"):
        values[f"method_is_{candidate}"] = float(method == candidate.upper())
    values["method_is_other"] = float(method not in {"GET", "POST", "PUT"})

    version = request.version.upper().removeprefix("HTTP/")
    values["http_version_is_1_0"] = float(version == "1.0")
    values["http_version_is_1_1"] = float(version == "1.1")
    values["http_version_is_2"] = float(version in {"2", "2.0"})
    values["http_version_is_other"] = float(version not in {"1.0", "1.1", "2", "2.0"})

    target = request.target
    parse_error = False
    try:
        parsed = urlsplit(target)
        scheme = parsed.scheme.lower()
        path = parsed.path or "/"
        query = parsed.query
        fragment = parsed.fragment
        try:
            hostname = parsed.hostname or ""
        except ValueError:
            hostname = ""
            parse_error = True
        userinfo_present = parsed.username is not None or parsed.password is not None
    except ValueError:
        parsed = None
        scheme = ""
        path = target.split("?", 1)[0] or "/"
        query = target.split("?", 1)[1].split("#", 1)[0] if "?" in target else ""
        fragment = target.split("#", 1)[1] if "#" in target else ""
        hostname = ""
        userinfo_present = False
        parse_error = True

    for suffix, metric in _content_metrics(target).items():
        values[f"url_{suffix}"] = metric
    values["url_is_absolute"] = float(bool(scheme and _raw_authority(target)))
    values["url_parse_error"] = float(parse_error)
    values["url_scheme_is_http"] = float(scheme == "http")
    values["url_scheme_is_https"] = float(scheme == "https")
    values["url_scheme_is_other"] = float(bool(scheme) and scheme not in {"http", "https"})
    values["url_scheme_missing"] = float(not scheme)
    values["url_host_present"] = float(bool(hostname))
    values["url_host_length"] = float(len(hostname)) if hostname else None
    values["url_host_label_count"] = float(len([part for part in hostname.split(".") if part])) if hostname else None
    if hostname:
        try:
            ipaddress.ip_address(hostname)
            is_ip = True
        except ValueError:
            is_ip = False
        values["url_host_is_ip"] = float(is_ip)
        values["url_host_non_ascii_count"] = float(sum(ord(character) > 127 for character in hostname))
    else:
        values["url_host_is_ip"] = None
        values["url_host_non_ascii_count"] = None
    values["url_userinfo_present"] = float(userinfo_present)
    port_present, port_valid, port_value = _port_information(_raw_authority(target))
    values["url_port_present"] = float(port_present)
    values["url_port_valid"] = float(port_valid) if port_valid is not None else None
    values["url_port_value"] = float(port_value) if port_value is not None else None
    values["url_port_is_standard"] = float(port_value in {80, 443}) if port_value is not None else None
    values["url_fragment_present"] = float(bool(fragment))

    for suffix, metric in _content_metrics(path).items():
        values[f"path_{suffix}"] = metric
    values.update(_path_metrics(path))

    query_delimiter_present = "?" in target.split("#", 1)[0]
    values["query_present"] = float(query_delimiter_present)
    if query_delimiter_present:
        for suffix, metric in _content_metrics(query, True).items():
            values[f"query_{suffix}"] = metric
        values.update({f"query_{name}": metric for name, metric in _parameter_metrics(query).items()})
    else:
        for suffix in (
            "length_raw", "length_decoded_once", "percent_encoding_count", "invalid_percent_count",
            "non_ascii_count", "control_char_count", "alpha_ratio", "digit_ratio", "special_ratio",
            "entropy", "max_repeat_run", "sql_pattern_count", "xss_pattern_count",
            "traversal_pattern_count", "shell_metachar_count",
            "parameter_count", "distinct_parameter_name_count", "repeated_parameter_count",
            "empty_name_count", "empty_value_count", "without_equals_count", "mean_name_length",
            "max_name_length", "mean_value_length", "max_value_length", "total_value_length",
        ):
            values[f"query_{suffix}"] = None

    body_text = request.body.decode("latin-1")
    body_present = bool(request.body)
    content_type = _first(request.headers, "content-type")
    body_is_form = bool(
        content_type is not None
        and content_type.lower().split(";", 1)[0].strip()
        == "application/x-www-form-urlencoded"
    )
    values["body_present"] = float(body_present)
    if body_present:
        for suffix, metric in _content_metrics(body_text, True).items():
            values[f"body_{suffix}"] = metric
        if body_is_form:
            values.update({f"body_{name}": metric for name, metric in _parameter_metrics(body_text).items()})
        else:
            for suffix in (
                "parameter_count", "distinct_parameter_name_count", "repeated_parameter_count",
                "empty_name_count", "empty_value_count", "without_equals_count", "mean_name_length",
                "max_name_length", "mean_value_length", "max_value_length", "total_value_length",
            ):
                values[f"body_{suffix}"] = None
    else:
        for suffix in (
            "length_raw", "length_decoded_once", "percent_encoding_count", "invalid_percent_count",
            "non_ascii_count", "control_char_count", "alpha_ratio", "digit_ratio", "special_ratio",
            "entropy", "max_repeat_run", "sql_pattern_count", "xss_pattern_count",
            "traversal_pattern_count", "shell_metachar_count",
            "parameter_count", "distinct_parameter_name_count", "repeated_parameter_count",
            "empty_name_count", "empty_value_count", "without_equals_count", "mean_name_length",
            "max_name_length", "mean_value_length", "max_value_length", "total_value_length",
        ):
            values[f"body_{suffix}"] = None

    headers = request.headers
    for header in COMMON_HEADER_NAMES:
        values[f"header_has_{header.replace('-', '_')}"] = float(bool(headers.get(header)))
    header_value_count = sum(len(header_values) for header_values in headers.values())
    values["header_unique_count"] = float(len(headers))
    values["header_value_count"] = float(header_value_count)
    values["header_duplicate_count"] = float(header_value_count - len(headers))

    values["content_type_is_form_urlencoded"] = (
        float(content_type.lower().split(";", 1)[0].strip() == "application/x-www-form-urlencoded")
        if content_type is not None else None
    )
    content_length = _first(headers, "content-length")
    declared_length: int | None = None
    valid_length: bool | None = None
    if content_length is not None:
        try:
            candidate_length = int(content_length.strip())
            valid_length = candidate_length >= 0
            declared_length = candidate_length if valid_length else None
        except ValueError:
            valid_length = False
    values["content_length_valid"] = float(valid_length) if valid_length is not None else None
    values["content_length_declared"] = float(declared_length) if declared_length is not None else None
    actual_length = len(request.body)
    values["body_length_bytes"] = float(actual_length)
    values["content_length_delta"] = float(actual_length - declared_length) if declared_length is not None else None
    values["content_length_matches_body"] = float(actual_length == declared_length) if declared_length is not None else None

    user_agent = _first(headers, "user-agent")
    values["user_agent_length"] = float(len(user_agent)) if user_agent is not None else None
    values["user_agent_token_count"] = float(len(user_agent.split())) if user_agent is not None else None
    values["user_agent_parenthesis_count"] = float(user_agent.count("(") + user_agent.count(")")) if user_agent is not None else None

    host_header = _first(headers, "host")
    values["host_header_length"] = float(len(host_header)) if host_header is not None else None
    if host_header is not None:
        host_name, host_port_present, host_port_valid = _host_and_port(host_header)
        values["host_header_port_present"] = float(host_port_present)
        values["host_header_port_valid"] = float(host_port_valid) if host_port_valid is not None else None
        values["host_matches_url_host"] = float(host_name.lower() == hostname.lower()) if hostname else None
    else:
        values["host_header_port_present"] = None
        values["host_header_port_valid"] = None
        values["host_matches_url_host"] = None

    cookie_values = headers.get("cookie", ())
    if cookie_values:
        values["cookie_length"] = float(sum(len(value) for value in cookie_values))
        values["cookie_pair_count"] = float(sum(len([part for part in value.split(";") if part.strip()]) for value in cookie_values))
    else:
        values["cookie_length"] = None
        values["cookie_pair_count"] = None

    missing = set(FEATURE_DEFINITIONS) - set(values)
    unexpected = set(values) - set(FEATURE_DEFINITIONS)
    if missing or unexpected:
        raise RuntimeError(f"Contrato de features inconsistente; ausentes={sorted(missing)}, extras={sorted(unexpected)}")
    return values


def catalogo_features() -> tuple[FeatureDefinition, ...]:
    return tuple(FEATURE_DEFINITIONS.values())


def extrair_features_experimento_2(source: HTTPRequest | bytes) -> tuple[float, ...]:
    """Retorna o vetor final, numérico e ordenado, ainda sem normalização.

    ``None`` é convertido deterministicamente para 0.0 somente em features que
    possuem indicadores explícitos de presença/validade no contrato final.
    """

    candidates = extrair_features_candidatas(source)
    vector: list[float] = []
    for name in FEATURES_EXPERIMENTO_2:
        value = candidates[name]
        if value is None:
            if name not in INDICADORES_DE_AUSENCIA:
                raise ValueError(f"Feature final ausente sem política documentada: {name}")
            numeric = 0.0
        else:
            numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"Feature final não finita: {name}={numeric}")
        vector.append(numeric)
    return tuple(vector)
