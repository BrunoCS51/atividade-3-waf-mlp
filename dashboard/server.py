"""Servidor estático e API somente-leitura do dashboard final."""

from __future__ import annotations

import csv
import base64
import http.client
import json
import os
import random
import socket
import threading
import urllib.parse
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


DASHBOARD_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WAF_DATA_DIR", "/data"))
if not DATA_DIR.exists():
    DATA_DIR = DASHBOARD_DIR.parent / "python"
HOST = "0.0.0.0"
PORT = 8000
RESERVED_DATA_PATH = Path(os.environ.get(
    "CSIC_RESERVED_PATH",
    "/tratamento_dados/datasets/csic_experimento2_reservado.jsonl",
))
if not RESERVED_DATA_PATH.is_file():
    RESERVED_DATA_PATH = (
        DASHBOARD_DIR.parent
        / "tratamento_dados"
        / "datasets"
        / "csic_experimento2_reservado.jsonl"
    )
_RESERVED_INDEX = None
_RESERVED_INDEX_LOCK = threading.Lock()
_RANDOM = random.SystemRandom()


def read_json(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def read_diagnostic(path: Path):
    with path.open("r", encoding="utf-8", newline="") as stream:
        return [
            {key: number(value) for key, value in row.items()}
            for row in csv.DictReader(stream)
        ]


def number(value):
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
        return int(numeric) if numeric.is_integer() else numeric
    except (TypeError, ValueError):
        return value


def _history_model_summary(result):
    """Expõe somente os dados necessários para comparação, nunca pesos."""
    return {
        "architecture": result.get("architecture", []),
        "parameter_count": result.get("parameter_count"),
        "parameters": result.get("parameters", {}),
        "threshold": result.get("threshold"),
        "training": result.get("training", {}),
        "metrics": {
            split: result.get("metrics", {}).get(split, {})
            for split in ("validacao", "teste")
        },
        "retrained_at": result.get("retrained_at"),
    }


def retraining_history(experiment_id, algorithm, current_result):
    """Reconstrói cada retreino comparando a versão anterior com a resultante."""
    root = DATA_DIR / "experimentos" / experiment_id / "historico_treinamentos"
    archived = []
    if root.is_dir():
        for directory in sorted(root.glob(f"*-{algorithm}")):
            result_path = directory / algorithm / "resultado.json"
            if not result_path.is_file():
                continue
            try:
                archived.append((directory.name, read_json(result_path)))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    if not archived:
        return []
    versions = [result for _, result in archived] + [current_result]
    events = []
    for index in range(len(versions) - 1):
        previous = versions[index]
        resulting = versions[index + 1]
        archive_name = archived[index][0]
        events.append({
            "sequence": index + 1,
            "completed_at": resulting.get("retrained_at") or archive_name[:22],
            "previous": _history_model_summary(previous),
            "result": _history_model_summary(resulting),
        })
    return list(reversed(events[-20:]))


def experiment_payload(experiment_id):
    artifacts = DATA_DIR / "experimentos" / experiment_id / "artefatos"
    result = read_json(artifacts / "resultados.json")
    result["configuration"] = read_json(artifacts / "configuracao.json")
    result["features"] = read_json(artifacts / "features.json")
    result["normalization"] = read_json(artifacts / "normalizacao.json")
    for algorithm in ("bp", "ag"):
        result["models"][algorithm]["diagnostic"]["series"] = read_diagnostic(
            artifacts / algorithm / "diagnostico.csv"
        )
        result["models"][algorithm]["retraining_history"] = retraining_history(
            experiment_id, algorithm, result["models"][algorithm]
        )
    return result


def waf_online():
    try:
        with socket.create_connection(("python_waf", 5000), timeout=0.4):
            return True
    except OSError:
        try:
            with socket.create_connection(("127.0.0.1", 5000), timeout=0.2):
                return True
        except OSError:
            return False


def build_data():
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "waf": {
            "online": waf_online(),
            "primary_model": os.environ.get("WAF_PRIMARY_MODEL", "experimento_1:bp"),
            "shadow_e1_algorithm": os.environ.get("WAF_SHADOW_E1_ALGORITHM", "bp"),
            "shadow_e2_algorithm": os.environ.get("WAF_SHADOW_E2_ALGORITHM", "bp"),
        },
        "experiments": {
            "experimento_1": experiment_payload("experimento_1"),
            "experimento_2": experiment_payload("experimento_2"),
        },
    }


def request_page(page=1, per_page=15):
    path = DATA_DIR / "monitor_waf.csv"
    page = max(int(page), 1)
    per_page = min(max(int(per_page), 1), 50)
    rows = []
    if path.is_file():
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = [
                {key: number(value) for key, value in row.items()}
                for row in csv.DictReader(stream)
            ]
    rows.reverse()
    total = len(rows)
    pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, pages)
    offset = (page - 1) * per_page
    blocked = sum(row.get("operational_decision") == "BLOQUEIA" for row in rows)
    disagreements = sum(row.get("e1_decision") != row.get("e2_decision") for row in rows)
    return {
        "page": page,
        "per_page": per_page,
        "pages": pages,
        "total": total,
        "items": rows[offset:offset + per_page],
        "summary": {
            "total": total,
            "allowed": total - blocked,
            "blocked": blocked,
            "disagreements": disagreements,
        },
        "updated_at": (
            datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
            if path.is_file() else None
        ),
    }


def clear_request_history():
    """Limpa exclusivamente o histórico de runtime; artefatos são somente leitura lógica."""
    path = DATA_DIR / "monitor_waf.csv"
    if path.is_file():
        with path.open("w", encoding="utf-8", newline=""):
            pass
    return {"cleared": True}


def reserved_index():
    """Indexa apenas offsets/IDs; o arquivo bruto permanece imutável."""
    global _RESERVED_INDEX
    if _RESERVED_INDEX is not None:
        return _RESERVED_INDEX
    with _RESERVED_INDEX_LOCK:
        if _RESERVED_INDEX is not None:
            return _RESERVED_INDEX
        groups = {}
        records = {}
        offset = 0
        for line in RESERVED_DATA_PATH.read_bytes().splitlines(keepends=True):
            record = json.loads(line)
            label = int(record["label"])
            method = str(record["method"]).upper()
            record_id = str(record["record_id"])
            groups.setdefault((label, method), []).append(offset)
            records[record_id] = offset
            offset += len(line)
        _RESERVED_INDEX = {"groups": groups, "records": records}
    return _RESERVED_INDEX


def read_reserved_offset(offset):
    with RESERVED_DATA_PATH.open("rb") as stream:
        stream.seek(offset)
        return json.loads(stream.readline())


def read_reserved_offsets(offsets):
    records = []
    with RESERVED_DATA_PATH.open("rb") as stream:
        for offset in offsets:
            stream.seek(offset)
            records.append(json.loads(stream.readline()))
    return records


def reserved_public_record(record):
    body = base64.b64decode(record.get("body_base64", "")).decode("latin-1")
    return {
        "record_id": record["record_id"],
        "source_sequence": record["source_sequence"],
        "expected_class": "ATAQUE" if int(record["label"]) else "NORMAL",
        "expected_decision": "BLOQUEIA" if int(record["label"]) else "LIBERA",
        "method": record["method"],
        "target": record["target"],
        "path": record["path"],
        "query": record["query"],
        "content_type": record.get("content_type"),
        "body_preview": body[:1000],
        "body_truncated": len(body) > 1000,
    }


def reserved_samples(label, method="", limit=20):
    label = int(label)
    if label not in (0, 1):
        raise ValueError("Classe reservada inválida")
    method = str(method).upper().strip()
    limit = min(max(int(limit), 1), 30)
    index = reserved_index()
    methods = sorted({key_method for key_label, key_method in index["groups"] if key_label == label})
    offsets = []
    for available_method in methods:
        if not method or available_method == method:
            offsets.extend(index["groups"][(label, available_method)])
    if method and method not in methods:
        raise ValueError("Método não disponível para esta classe")
    chosen = _RANDOM.sample(offsets, min(limit, len(offsets)))
    return {
        "source": "CSIC 2010 — conjunto reservado externo aos experimentos",
        "label": label,
        "expected_class": "ATAQUE" if label else "NORMAL",
        "available_methods": methods,
        "available_count": len(offsets),
        "items": [reserved_public_record(record) for record in read_reserved_offsets(chosen)],
    }


def reserved_record(record_id):
    offset = reserved_index()["records"].get(str(record_id))
    if offset is None:
        raise ValueError("Requisição reservada não encontrada")
    return read_reserved_offset(offset)


def replay_reserved(record_id):
    record = reserved_record(record_id)
    body = base64.b64decode(record.get("body_base64", ""))
    raw_path = record.get("path") or "/"
    if record.get("query"):
        raw_path = f"{raw_path}?{record['query']}"
    path = urllib.parse.quote_from_bytes(
        raw_path.encode("latin-1"), safe="/?&=;%:+,$@!()*'~-._"
    )
    allowed_headers = {
        "user-agent", "pragma", "cache-control", "accept", "accept-charset",
        "accept-language", "cookie", "content-type",
    }
    headers = {}
    for name, values in record.get("headers", {}).items():
        value = ", ".join(str(item) for item in values)
        if name.lower() in allowed_headers and "\r" not in value and "\n" not in value:
            headers[name] = value
    headers["Host"] = "localhost:8080"
    hosts = [
        (os.environ.get("WAF_GATEWAY_HOST", "nginx"), int(os.environ.get("WAF_GATEWAY_PORT", "80"))),
        ("127.0.0.1", 8080),
    ]
    last_error = None
    for host, port in hosts:
        connection = http.client.HTTPConnection(host, port, timeout=8)
        try:
            connection.request(record["method"], path, body=body or None, headers=headers)
            response = connection.getresponse()
            response.read()
            return {
                "record": reserved_public_record(record),
                "status_http": response.status,
            }
        except OSError as error:
            last_error = error
        finally:
            connection.close()
    raise OSError(f"WAF indisponível para replay reservado: {last_error}")


def training_api(method, path, payload=None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {
        "X-Training-Token": os.environ.get("WAF_TRAINING_TOKEN", "local-academic-training"),
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    hosts = [
        (os.environ.get("WAF_API_HOST", "python_waf"), int(os.environ.get("WAF_API_PORT", "5000"))),
        ("127.0.0.1", 5000),
    ]
    last_error = None
    for host, port in hosts:
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            data = json.loads(response_body) if response_body else {}
            return data, response.status
        except OSError as error:
            last_error = error
        finally:
            connection.close()
    raise OSError(f"Serviço de treinamento indisponível: {last_error}")


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/api/data":
                return self.send_json(build_data())
            if parsed.path == "/api/requests":
                return self.send_json(request_page(
                    query.get("page", [1])[0], query.get("per_page", [15])[0]
                ))
            if parsed.path == "/api/reserved":
                return self.send_json(reserved_samples(
                    query.get("label", [0])[0],
                    query.get("method", [""])[0],
                    query.get("limit", [20])[0],
                ))
            if parsed.path == "/api/training/status":
                job_id = query.get("job_id", [""])[0]
                if not job_id.isalnum():
                    raise ValueError("Identificador de treinamento inválido")
                data, status = training_api("GET", f"/__training/status/{job_id}")
                return self.send_json(data, status=status)
            if parsed.path == "/api/training/active":
                data, status = training_api("GET", "/__training/active")
                return self.send_json(data, status=status)
            if parsed.path == "/api/health":
                return self.send_json({"status": "ok"})
        except (OSError, ValueError, TypeError, json.JSONDecodeError, csv.Error) as error:
            return self.send_json({"error": str(error)}, status=500)
        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if parsed.path == "/api/requests/clear":
                return self.send_json(clear_request_history())
            if parsed.path not in {"/api/reserved/execute", "/api/training/start"}:
                return self.send_json({"error": "Endpoint não encontrado"}, status=404)
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                raise ValueError("Corpo da requisição inválido")
            payload = json.loads(self.rfile.read(length))
            if parsed.path == "/api/training/start":
                data, status = training_api("POST", "/__training/start", payload)
                return self.send_json(data, status=status)
            return self.send_json(replay_reserved(payload.get("record_id", "")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            return self.send_json({"error": str(error)}, status=400)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()


if __name__ == "__main__":
    print(f"Dashboard disponível na porta {PORT}", flush=True)
    ThreadingHTTPServer((HOST, PORT), DashboardHandler).serve_forever()
