import ast
import csv
from collections import Counter, deque
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import statistics
import urllib.parse

from csic_simulator import CSICError, SimulationManager
from feature_diagnostics import build_feature_analysis


DASHBOARD_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("WAF_DATA_DIR", "/data"))
HOST = "0.0.0.0"
PORT = 8000
CSIC_DATA_DIR = Path("/external_data/csic2010")
if not CSIC_DATA_DIR.exists():
    CSIC_DATA_DIR = DASHBOARD_DIR.parent / "external_data" / "csic2010"

EXTRACTOR_PATH = DATA_DIR / "extractor.py"
if not EXTRACTOR_PATH.exists():
    EXTRACTOR_PATH = DASHBOARD_DIR.parent / "python" / "extractor.py"
SIMULATION_MANAGER = SimulationManager(CSIC_DATA_DIR)


def ler_json(nome):
    caminho = DATA_DIR / nome

    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            dados = json.load(arquivo)

        return {
            "disponivel": True,
            "dados": dados,
            "atualizado_em": datetime.fromtimestamp(
                caminho.stat().st_mtime
            ).astimezone().isoformat()
        }
    except (OSError, json.JSONDecodeError, TypeError):
        return {
            "disponivel": False,
            "dados": None,
            "atualizado_em": None
        }


def converter_valor(valor):
    if valor is None or valor == "":
        return None

    try:
        numero = float(valor)
        return int(numero) if numero.is_integer() else numero
    except (TypeError, ValueError):
        return valor


def ler_csv(nome, limite=None):
    caminho = DATA_DIR / nome

    try:
        with caminho.open(
            "r",
            encoding="utf-8",
            newline=""
        ) as arquivo:
            leitor = csv.DictReader(arquivo)

            if limite:
                linhas = deque(leitor, maxlen=limite)
            else:
                linhas = list(leitor)

        return {
            "disponivel": True,
            "linhas": [
                {
                    chave: converter_valor(valor)
                    for chave, valor in linha.items()
                }
                for linha in linhas
            ],
            "atualizado_em": datetime.fromtimestamp(
                caminho.stat().st_mtime
            ).astimezone().isoformat()
        }
    except (OSError, csv.Error):
        return {
            "disponivel": False,
            "linhas": [],
            "atualizado_em": None
        }


def resumo_log_requisicoes():
    caminho = DATA_DIR / "dashboard_waf.csv"
    try:
        return {
            "disponivel": caminho.is_file(),
            "atualizado_em": datetime.fromtimestamp(
                caminho.stat().st_mtime
            ).astimezone().isoformat()
        }
    except OSError:
        return {"disponivel": False, "atualizado_em": None}


def _parse_data_iso(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.timestamp()


def pagina_log_requisicoes(inicio, fim, pagina=1, por_pagina=10):
    caminho = DATA_DIR / "dashboard_waf.csv"
    pagina = max(int(pagina), 1)
    por_pagina = min(max(int(por_pagina), 1), 50)
    inicio_timestamp = _parse_data_iso(inicio)
    fim_timestamp = _parse_data_iso(fim) if fim else float("inf")

    if inicio_timestamp is None:
        return {
            "fonte": "waf",
            "pagina": 1,
            "por_pagina": por_pagina,
            "paginas": 1,
            "total": 0,
            "itens": [],
            "resumo": {
                "total": 0,
                "liberadas": 0,
                "bloqueadas": 0,
                "risco_medio": None,
            },
            "atualizado_em": None,
        }

    rows = []
    if caminho.is_file():
        with caminho.open("r", encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                timestamp = _parse_data_iso(row.get("data_hora"))
                if timestamp is None or not inicio_timestamp <= timestamp <= fim_timestamp:
                    continue
                rows.append({
                    key: converter_valor(value)
                    for key, value in row.items()
                    if key is not None
                })

    rows.reverse()
    total = len(rows)
    paginas = max((total + por_pagina - 1) // por_pagina, 1)
    pagina = min(pagina, paginas)
    offset = (pagina - 1) * por_pagina
    items = rows[offset:offset + por_pagina]
    blocked = sum(row.get("decisao") == "BLOQUEADA" for row in rows)
    risks = [
        float(row["risco"])
        for row in rows
        if isinstance(row.get("risco"), (int, float))
    ]
    return {
        "fonte": "waf",
        "pagina": pagina,
        "por_pagina": por_pagina,
        "paginas": paginas,
        "total": total,
        "itens": items,
        "resumo": {
            "total": total,
            "liberadas": total - blocked,
            "bloqueadas": blocked,
            "risco_medio": statistics.fmean(risks) if risks else None,
        },
        "atualizado_em": (
            datetime.fromtimestamp(caminho.stat().st_mtime).astimezone().isoformat()
            if caminho.is_file()
            else None
        ),
    }


def ler_configuracao_treinamento(nome, campos):
    caminho = DATA_DIR / nome

    try:
        arvore = ast.parse(
            caminho.read_text(encoding="utf-8"),
            filename=nome
        )
    except (OSError, SyntaxError, UnicodeError):
        return {}

    valores = {}

    for no in arvore.body:
        if not isinstance(no, ast.Assign) or len(no.targets) != 1:
            continue

        alvo = no.targets[0]
        if not isinstance(alvo, ast.Name) or alvo.id not in campos:
            continue

        try:
            valores[alvo.id] = ast.literal_eval(no.value)
        except (ValueError, TypeError):
            continue

    return valores


def resumo_diagnostico(nome, eixo):
    diagnostico = ler_csv(nome)
    linhas = diagnostico["linhas"]

    if not linhas:
        return {
            **diagnostico,
            "final": None,
            "ultima_melhoria": None,
            "tempo_total": None,
            "cpu_total": None
        }

    campo_sem_melhoria = (
        "epocas_sem_melhoria"
        if eixo == "epoca"
        else "geracoes_sem_melhoria"
    )
    ultima_melhoria = linhas[0].get(eixo)

    for linha in linhas[1:]:
        melhoria = linha.get("melhoria")
        if isinstance(melhoria, (int, float)) and melhoria > 1e-6:
            ultima_melhoria = linha.get(eixo)

    prefixo = "epoca" if eixo == "epoca" else "geracao"
    campo_tempo = f"tempo_parede_{prefixo}_segundos"
    campo_cpu = f"tempo_cpu_{prefixo}_segundos"
    tempos = [
        linha.get(campo_tempo)
        for linha in linhas
        if isinstance(linha.get(campo_tempo), (int, float))
    ]
    cpus = [
        linha.get(campo_cpu)
        for linha in linhas
        if isinstance(linha.get(campo_cpu), (int, float))
    ]

    return {
        **diagnostico,
        "final": linhas[-1],
        "ultima_melhoria": ultima_melhoria,
        "sem_melhoria": linhas[-1].get(campo_sem_melhoria),
        "tempo_total": sum(tempos) if tempos else None,
        "tempo_medio": (
            sum(tempos) / len(tempos)
            if tempos else None
        ),
        "cpu_total": sum(cpus) if cpus else None,
        "cpu_media": (
            sum(cpus) / len(cpus)
            if cpus else None
        )
    }


def resumo_dataset():
    caminho = DATA_DIR / "requisicoes.csv"
    rotulos = []

    try:
        with caminho.open("r", encoding="utf-8") as arquivo:
            for linha in csv.reader(arquivo):
                if linha:
                    rotulos.append(int(float(linha[9])))
    except (OSError, csv.Error, ValueError, IndexError):
        return {"disponivel": False}

    classes = Counter(rotulos)
    treino = sum(int(quantidade * 0.70) for quantidade in classes.values())
    validacao = sum(
        int(quantidade * 0.15)
        for quantidade in classes.values()
    )

    return {
        "disponivel": True,
        "total": len(rotulos),
        "treino": treino,
        "validacao": validacao,
        "teste": len(rotulos) - treino - validacao,
        "classes": dict(classes)
    }


def resumo_rede():
    pesos = ler_json("pesos.json")

    if not pesos["disponivel"]:
        return {"disponivel": False}

    rede = pesos["dados"].get("rede")
    if not isinstance(rede, list) or len(rede) < 2:
        return {"disponivel": False}

    quantidade_pesos = sum(
        (rede[indice] + 1) * rede[indice + 1]
        for indice in range(len(rede) - 1)
    )

    return {
        "disponivel": True,
        "arquitetura": rede,
        "entradas": rede[0],
        "ocultos": rede[1] if len(rede) > 2 else None,
        "saidas": rede[-1],
        "quantidade_pesos": quantidade_pesos,
        "bias": pesos["dados"].get("bias")
    }


def resumo_pesos(nome):
    arquivo = ler_json(nome)
    if not arquivo["disponivel"]:
        return {"disponivel": False}

    dados = arquivo["dados"]
    rede = dados.get("rede")
    matriz = dados.get("pesos")

    if not isinstance(rede, list) or not isinstance(matriz, list):
        return {"disponivel": False}

    camadas = []
    todos = []

    try:
        for camada in range(len(rede) - 1):
            valores = [
                float(matriz[linha][coluna][camada])
                for linha in range(rede[camada] + 1)
                for coluna in range(rede[camada + 1])
            ]
            todos.extend(valores)
            camadas.append({
                "magnitude_media": statistics.fmean(
                    abs(valor) for valor in valores
                ),
                "media": statistics.fmean(valores),
                "desvio": statistics.pstdev(valores),
                "menor": min(valores),
                "maior": max(valores)
            })
    except (IndexError, TypeError, ValueError, statistics.StatisticsError):
        return {"disponivel": False}

    return {
        "disponivel": True,
        "quantidade": len(todos),
        "magnitude_media": statistics.fmean(
            abs(valor) for valor in todos
        ),
        "desvio": statistics.pstdev(todos),
        "menor": min(todos),
        "maior": max(todos),
        "camadas": camadas
    }


def waf_online():
    try:
        with socket.create_connection(("python_waf", 5000), timeout=0.4):
            return True
    except OSError:
        return False


def montar_dados():
    configuracao_bp = ler_configuracao_treinamento(
        "train_bp.py",
        {"rede", "taxa", "epocas"}
    )
    configuracao_ag = ler_configuracao_treinamento(
        "train_ga.py",
        {
            "rede",
            "npop",
            "geracoes",
            "tipo_selecao",
            "tipo_crossover",
            "tipo_mutacao",
            "rmin",
            "rmax"
        }
    )

    simulacao = SIMULATION_MANAGER.snapshot()
    analise_features = build_feature_analysis(
        EXTRACTOR_PATH,
        DATA_DIR / "requisicoes.csv",
        SIMULATION_MANAGER.feature_records(),
    )

    return {
        "gerado_em": datetime.now().astimezone().isoformat(),
        "waf": {"online": waf_online()},
        "implantacao": ler_json("modelo_selecionado.json"),
        "rede": resumo_rede(),
        "pesos": {
            "bp": resumo_pesos("pesos_bp.json"),
            "ag": resumo_pesos("pesos_ag.json")
        },
        "dataset": resumo_dataset(),
        "treinamento": {
            "bp": configuracao_bp,
            "ag": configuracao_ag
        },
        "diagnosticos": {
            "bp": resumo_diagnostico("diagnostico_bp.csv", "epoca"),
            "ag": resumo_diagnostico("diagnostico_ag.csv", "geracao")
        },
        "avaliacao": ler_json("avaliacao_modelos.json"),
        "requisicoes": resumo_log_requisicoes(),
        "simulacao": simulacao,
        "analise_features": analise_features
    }


class DashboardHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(
            *args,
            directory=str(DASHBOARD_DIR),
            **kwargs
        )

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        caminho = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if caminho == "/api/data":
            self.enviar_json(montar_dados())
            return

        if caminho == "/api/health":
            self.enviar_json({"status": "ok"})
            return

        try:
            if caminho == "/api/requests":
                self.enviar_json(pagina_log_requisicoes(
                    query.get("inicio", [None])[0],
                    query.get("fim", [None])[0],
                    query.get("pagina", [1])[0],
                    query.get("por_pagina", [10])[0],
                ))
                return

            if caminho == "/api/simulation/history":
                self.enviar_json(SIMULATION_MANAGER.history_page(
                    query.get("pagina", [1])[0],
                    query.get("por_pagina", [10])[0],
                ))
                return

            if caminho == "/api/simulation/examples":
                self.enviar_json(SIMULATION_MANAGER.example_list(
                    query.get("resultado", [""])[0]
                ))
                return

            if caminho == "/api/simulation/example":
                self.enviar_json(SIMULATION_MANAGER.example(
                    query.get("id", [""])[0]
                ))
                return
        except (CSICError, OSError, ValueError, TypeError, csv.Error) as erro:
            self.enviar_json({"erro": str(erro)}, status=400)
            return

        super().do_GET()

    def do_POST(self):
        caminho = self.path.split("?", 1)[0]
        if caminho != "/api/simulation/start":
            self.send_error(404)
            return

        try:
            tamanho = int(self.headers.get("Content-Length", "0"))
            if not 0 < tamanho <= 4096:
                raise ValueError("Corpo JSON ausente ou muito grande.")
            payload = json.loads(self.rfile.read(tamanho).decode("utf-8"))
            SIMULATION_MANAGER.start(
                payload.get("modo"),
                payload.get("quantidade"),
                payload.get("monitor_ativo") is True,
            )
            self.enviar_json(
                SIMULATION_MANAGER.snapshot(),
                status=202,
            )
        except (CSICError, ValueError, TypeError, json.JSONDecodeError) as erro:
            self.enviar_json(
                {"erro": str(erro)},
                status=400,
            )

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "frame-ancestors 'none'"
        )
        super().end_headers()

    def enviar_json(self, dados, status=200):
        corpo = json.dumps(
            dados,
            ensure_ascii=False,
            allow_nan=False
        ).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, formato, *args):
        print(
            f"[{self.log_date_time_string()}] {formato % args}",
            flush=True
        )


if __name__ == "__main__":
    servidor = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    print(
        f"Dashboard disponivel na porta {PORT}",
        flush=True
    )
    servidor.serve_forever()
