"""Parser e replayer local para a avaliacao externa HTTP CSIC 2010."""

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


NORMAL_FILE = "normalTrafficTraining.txt"
ATTACK_FILE = "anomalousTrafficTest.txt"
DATASET_FILES = {
    "NORMAL": NORMAL_FILE,
    "ATAQUE": ATTACK_FILE,
}
REQUEST_LINE = re.compile(
    rb"^(GET|POST)\s+([^\s]+)\s+HTTP/(1\.[01])\s*$",
    re.IGNORECASE,
)
LOCAL_WAF_SCHEME = "http"
LOCAL_WAF_HOST = "nginx"
LOCAL_WAF_PORT = 80
ALLOWED_QUANTITIES = {20, 100, 500, 1000}
MAX_BODY_BYTES = 256 * 1024
MAX_TARGET_BYTES = 32 * 1024
SEED = 2010


class CSICError(Exception):
    """Erro controlado de parsing, selecao ou replay."""


@dataclass(frozen=True)
class CSICRequest:
    method: str
    target: str
    headers: dict
    body: bytes
    true_label: str


def _safe_header_value(value, limit):
    return "".join(
        character
        for character in value
        if character.isprintable() and character not in "\r\n"
    )[:limit]


def parse_csic_file(path, true_label):
    """Separa requests HTTP brutas sem executar ou interpretar payloads."""
    path = Path(path)
    pending_line = None

    with path.open("rb") as source:
        while True:
            line = pending_line if pending_line is not None else source.readline()
            pending_line = None

            if not line:
                break

            request_match = REQUEST_LINE.match(line.rstrip(b"\r\n"))
            if not request_match:
                continue

            method = request_match.group(1).decode("ascii").upper()
            target_bytes = request_match.group(2)
            if len(target_bytes) > MAX_TARGET_BYTES:
                raise CSICError("Target HTTP excede o limite seguro.")
            target = target_bytes.decode("latin-1")

            headers = {}
            while True:
                header_line = source.readline()
                if not header_line or header_line in (b"\n", b"\r\n"):
                    break

                name, separator, value = header_line.partition(b":")
                if not separator:
                    continue
                header_name = name.decode("latin-1").strip().lower()
                header_value = value.decode("latin-1").strip()
                if header_name:
                    headers[header_name] = header_value

            content_length = None
            raw_length = headers.get("content-length")
            if raw_length is not None:
                try:
                    content_length = int(raw_length)
                except ValueError as error:
                    raise CSICError("Content-Length invalido no dataset.") from error
                if not 0 <= content_length <= MAX_BODY_BYTES:
                    raise CSICError("Body HTTP excede o limite seguro.")

            if content_length is not None:
                body = source.read(content_length)
                if len(body) != content_length:
                    raise CSICError("Body HTTP incompleto no dataset.")
            elif method == "POST":
                body_lines = []
                while True:
                    body_line = source.readline()
                    if not body_line:
                        break
                    if REQUEST_LINE.match(body_line.rstrip(b"\r\n")):
                        pending_line = body_line
                        break
                    body_lines.append(body_line)
                    if sum(map(len, body_lines)) > MAX_BODY_BYTES:
                        raise CSICError("Body HTTP excede o limite seguro.")
                body = b"".join(body_lines).rstrip(b"\r\n")
            else:
                body = b""

            yield CSICRequest(
                method=method,
                target=target,
                headers=headers,
                body=body,
                true_label=true_label,
            )


def reservoir_sample(path, true_label, quantity, seed):
    """Seleciona amostras reprodutiveis sem carregar o dataset inteiro."""
    generator = random.Random(seed)
    sample = []
    seen = 0

    for seen, request in enumerate(parse_csic_file(path, true_label), start=1):
        if len(sample) < quantity:
            sample.append(request)
            continue
        replacement = generator.randrange(seen)
        if replacement < quantity:
            sample[replacement] = request

    if seen < quantity:
        raise CSICError(
            f"Dataset {true_label} possui apenas {seen} requests validas."
        )
    return sample


def select_requests(data_dir, mode, quantity):
    """Monta os modos NORMAL, ATAQUE e MISTO com seed fixa."""
    mode = mode.upper()
    if mode not in {"NORMAL", "ATAQUE", "MISTO"}:
        raise CSICError("Modo de simulacao invalido.")
    if quantity not in ALLOWED_QUANTITIES:
        raise CSICError("Quantidade de simulacao invalida.")

    if mode == "NORMAL":
        normal_quantity, attack_quantity = quantity, 0
    elif mode == "ATAQUE":
        normal_quantity, attack_quantity = 0, quantity
    else:
        normal_quantity = quantity // 2
        attack_quantity = quantity - normal_quantity

    selected = []
    data_dir = Path(data_dir)
    if normal_quantity:
        selected.extend(reservoir_sample(
            data_dir / NORMAL_FILE,
            "NORMAL",
            normal_quantity,
            SEED,
        ))
    if attack_quantity:
        selected.extend(reservoir_sample(
            data_dir / ATTACK_FILE,
            "ATAQUE",
            attack_quantity,
            SEED + 1,
        ))

    random.Random(SEED).shuffle(selected)
    return selected


def safe_division(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def calculate_metrics(confusion):
    tn = confusion["tn"]
    fp = confusion["fp"]
    fn = confusion["fn"]
    tp = confusion["tp"]
    total = tn + fp + fn + tp
    precision = safe_division(tp, tp + fp)
    recall = safe_division(tp, tp + fn)
    return {
        "accuracy": safe_division(tp + tn, total),
        "precision": precision,
        "recall": recall,
        "f1": safe_division(2 * precision * recall, precision + recall),
        "false_positive_rate": safe_division(fp, fp + tn),
        "false_negative_rate": safe_division(fn, fn + tp),
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LocalWAFReplayer:
    """Envia exclusivamente ao Nginx local, sem proxy e sem redirects."""

    def __init__(self):
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            _NoRedirect(),
        )

    @staticmethod
    def local_resource(target):
        if any(ord(character) < 32 or ord(character) == 127 for character in target):
            raise CSICError("Target contem caracteres de controle.")
        parsed = urllib.parse.urlsplit(target)
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = f"/{path}"
        return urllib.parse.urlunsplit(("", "", path, parsed.query, ""))

    @classmethod
    def build_request(cls, request):
        resource = cls.local_resource(request.target)
        url = (
            f"{LOCAL_WAF_SCHEME}://{LOCAL_WAF_HOST}:"
            f"{LOCAL_WAF_PORT}{resource}"
        )
        parsed_destination = urllib.parse.urlsplit(url)
        if (
            parsed_destination.scheme != LOCAL_WAF_SCHEME
            or parsed_destination.hostname != LOCAL_WAF_HOST
            or parsed_destination.port != LOCAL_WAF_PORT
        ):
            raise CSICError("Destino fora do ambiente local bloqueado.")

        headers = {
            "User-Agent": _safe_header_value(
                request.headers.get("user-agent", "CSIC-2010-Controlled-Evaluation"),
                512,
            ),
            "X-Controlled-Simulation": "csic2010",
            "Connection": "close",
        }
        content_type = _safe_header_value(
            request.headers.get("content-type", ""),
            128,
        )
        if content_type:
            headers["Content-Type"] = content_type

        data = request.body if request.method == "POST" else None
        return urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=request.method,
        )

    def service_available(self):
        try:
            with socket.create_connection(
                (LOCAL_WAF_HOST, LOCAL_WAF_PORT),
                timeout=0.8,
            ):
                return True
        except OSError:
            return False

    def replay(self, request):
        outgoing = self.build_request(request)
        try:
            with self._opener.open(outgoing, timeout=4) as response:
                status = response.status
                response_headers = response.headers
        except urllib.error.HTTPError as error:
            status = error.code
            response_headers = error.headers
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            raise CSICError(f"Falha no WAF local: {error}") from error

        diagnostics = self._diagnostics_from_headers(response_headers)
        if status == 200:
            return "LIBERADA", status, diagnostics
        if status == 403:
            return "BLOQUEADA", status, diagnostics
        raise CSICError(f"Resposta local inesperada: HTTP {status}.")

    @staticmethod
    def _diagnostics_from_headers(headers):
        try:
            names = headers["X-WAF-Feature-Names"].split(",")
            limits = [
                float(value)
                for value in headers["X-WAF-Feature-Limits"].split(",")
            ]
            raw = [
                float(value)
                for value in headers["X-WAF-Features-Raw"].split(",")
            ]
            normalized = [
                float(value)
                for value in headers["X-WAF-Features-Normalized"].split(",")
            ]
            if not len(names) == len(limits) == len(raw) == len(normalized) == 9:
                raise ValueError("Quantidade inesperada de features.")
            features = [
                {
                    "nome": name,
                    "limite": limit,
                    "valor_bruto": raw_value,
                    "valor_normalizado": normalized_value,
                    "clipping": raw_value > limit,
                }
                for name, limit, raw_value, normalized_value in zip(
                    names,
                    limits,
                    raw,
                    normalized,
                )
            ]
            return {
                "risco": float(headers["X-WAF-Risk"]),
                "threshold": float(headers["X-WAF-Threshold"]),
                "features": features,
            }
        except (KeyError, TypeError, ValueError, AttributeError):
            return {"risco": None, "threshold": None, "features": []}


class SimulationManager:
    """Executa uma unica avaliacao por vez em thread de backend."""

    def __init__(self, data_dir, interval=0.04):
        self.data_dir = Path(data_dir)
        self.interval = interval
        self.replayer = LocalWAFReplayer()
        self.lock = threading.Lock()
        self.history = []
        self.next_history_id = 1
        self.state = self._initial_state()

    def _initial_state(self):
        return {
            "status": "idle",
            "mensagem": "Pronto para avaliacao externa controlada.",
            "modo": None,
            "total": 0,
            "processadas": 0,
            "avaliadas": 0,
            "normais_reais": 0,
            "ataques_reais": 0,
            "liberadas": 0,
            "bloqueadas": 0,
            "erros": 0,
            "confusao": {"tn": 0, "fp": 0, "fn": 0, "tp": 0},
            "metricas": calculate_metrics({"tn": 0, "fp": 0, "fn": 0, "tp": 0}),
            "iniciado_em": None,
            "finalizado_em": None,
        }

    def dataset_status(self):
        files = {}
        for label, filename in DATASET_FILES.items():
            path = self.data_dir / filename
            files[label.lower()] = {
                "arquivo": filename,
                "disponivel": path.is_file(),
                "tamanho_bytes": path.stat().st_size if path.is_file() else None,
            }
        return {
            "disponivel": all(item["disponivel"] for item in files.values()),
            "arquivos": files,
        }

    def snapshot(self):
        with self.lock:
            snapshot = json.loads(json.dumps(self.state))
            snapshot["historico_total"] = len(self.history)
            snapshot["exemplos_disponiveis"] = {
                result: sum(
                    item["resultado"] == result
                    for item in self.history
                )
                for result in ("TN", "FP", "FN", "TP")
            }
        snapshot["dataset"] = self.dataset_status()
        snapshot["servico_local_disponivel"] = self.replayer.service_available()
        return snapshot

    def start(self, mode, quantity, monitor_active):
        if monitor_active is not True:
            raise CSICError("Inicie uma sessao do Monitor WAF antes da simulacao.")
        if not self.replayer.service_available():
            raise CSICError("Servico local do WAF indisponivel.")

        if not self.dataset_status()["disponivel"]:
            raise CSICError("Arquivos CSIC 2010 indisponiveis.")

        mode = str(mode).upper()
        quantity = int(quantity)
        if mode not in {"NORMAL", "ATAQUE", "MISTO"}:
            raise CSICError("Modo de simulacao invalido.")
        if quantity not in ALLOWED_QUANTITIES:
            raise CSICError("Quantidade de simulacao invalida.")

        with self.lock:
            if self.state["status"] == "running":
                raise CSICError("Ja existe uma simulacao em andamento.")
            self.state = self._initial_state()
            self.state.update({
                "status": "running",
                "mensagem": "Simulacao em andamento.",
                "modo": mode,
                "total": quantity,
                "iniciado_em": datetime.now().astimezone().isoformat(),
            })
            self.history.clear()
            self.next_history_id = 1

        worker = threading.Thread(
            target=self._run,
            args=(mode, quantity),
            name="csic-controlled-simulation",
            daemon=True,
        )
        worker.start()

    def _run(self, mode, quantity):
        try:
            selected = select_requests(self.data_dir, mode, quantity)
            for request in selected:
                self._process_one(request)
                if self.interval:
                    time.sleep(self.interval)
            with self.lock:
                self.state["status"] = "completed"
                self.state["mensagem"] = "Avaliacao externa controlada concluida."
                self.state["finalizado_em"] = datetime.now().astimezone().isoformat()
        except Exception as error:
            with self.lock:
                self.state["status"] = "error"
                self.state["mensagem"] = str(error)[:240]
                self.state["finalizado_em"] = datetime.now().astimezone().isoformat()

    def _process_one(self, request):
        timestamp = datetime.now().astimezone().isoformat()
        path = urllib.parse.urlsplit(request.target).path or "/"
        path = _safe_header_value(path, 160)
        decision = None
        status_http = None
        result = "ERRO"
        diagnostics = {"risco": None, "threshold": None, "features": []}

        try:
            decision, status_http, diagnostics = self.replayer.replay(request)
            predicted_attack = decision == "BLOQUEADA"
            real_attack = request.true_label == "ATAQUE"
            if real_attack and predicted_attack:
                result = "TP"
            elif real_attack:
                result = "FN"
            elif predicted_attack:
                result = "FP"
            else:
                result = "TN"
        except CSICError:
            pass

        with self.lock:
            self.state["processadas"] += 1
            if request.true_label == "ATAQUE":
                self.state["ataques_reais"] += 1
            else:
                self.state["normais_reais"] += 1

            if result == "ERRO":
                self.state["erros"] += 1
            else:
                self.state["avaliadas"] += 1
                if decision == "BLOQUEADA":
                    self.state["bloqueadas"] += 1
                else:
                    self.state["liberadas"] += 1
                self.state["confusao"][result.lower()] += 1
                self.state["metricas"] = calculate_metrics(
                    self.state["confusao"]
                )

            self.history.append({
                "id": self.next_history_id,
                "data_hora": timestamp,
                "metodo": request.method,
                "caminho": path,
                "rotulo_real": request.true_label,
                "decisao": decision or "ERRO",
                "resultado": result,
                "status_http": status_http,
                "risco": diagnostics["risco"],
                "threshold": diagnostics["threshold"],
                "features": diagnostics["features"],
            })
            self.next_history_id += 1

    @staticmethod
    def _safe_history_item(item, include_features=False):
        safe = {
            key: value
            for key, value in item.items()
            if key != "features"
        }
        if include_features:
            safe["features"] = item.get("features", [])
        return safe

    def history_page(self, page=1, page_size=10):
        page = max(int(page), 1)
        page_size = min(max(int(page_size), 1), 50)
        with self.lock:
            ordered = list(reversed(self.history))
            total = len(ordered)
            pages = max((total + page_size - 1) // page_size, 1)
            page = min(page, pages)
            start = (page - 1) * page_size
            items = [
                self._safe_history_item(item)
                for item in ordered[start:start + page_size]
            ]
            state = json.loads(json.dumps(self.state))
        return {
            "fonte": "csic",
            "pagina": page,
            "por_pagina": page_size,
            "paginas": pages,
            "total": total,
            "itens": items,
            "resumo": {
                "total": state["avaliadas"],
                "liberadas": state["liberadas"],
                "bloqueadas": state["bloqueadas"],
                "risco_medio": (
                    safe_division(
                        sum(item["risco"] for item in ordered if isinstance(item.get("risco"), (int, float))),
                        sum(isinstance(item.get("risco"), (int, float)) for item in ordered),
                    )
                    if any(isinstance(item.get("risco"), (int, float)) for item in ordered)
                    else None
                ),
            },
        }

    def example_list(self, result):
        result = str(result).upper()
        if result not in {"TN", "FP", "FN", "TP"}:
            raise CSICError("Resultado de classificacao invalido.")
        with self.lock:
            items = [
                self._safe_history_item(item)
                for item in reversed(self.history)
                if item["resultado"] == result
            ][:30]
        return {"resultado": result, "itens": items}

    def example(self, history_id):
        history_id = int(history_id)
        with self.lock:
            for item in self.history:
                if item["id"] == history_id:
                    return self._safe_history_item(item, include_features=True)
        raise CSICError("Exemplo de classificacao nao encontrado.")

    def feature_records(self):
        with self.lock:
            return [
                {
                    "rotulo_real": item["rotulo_real"],
                    "features": json.loads(json.dumps(item.get("features", []))),
                }
                for item in self.history
                if item.get("features")
            ]
