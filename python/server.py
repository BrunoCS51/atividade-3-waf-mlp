import os
import csv
import json  # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
import logging
import urllib.parse  # ALTERADO PARA MONITORAMENTO VISUAL
from datetime import datetime

from flask import Flask, request, Response

from extractor import LIMITES, NOMES_FEATURES, extract_features
from mlp import MLP


app = Flask(__name__)

# O log tecnico sanitizado em CSV substitui o access log HTTP, que poderia
# expor query strings do dataset externo durante a avaliacao controlada.
logging.getLogger("werkzeug").setLevel(logging.ERROR)

mlp = MLP(input_size=9, hidden_size=10, output_size=1)

if os.path.exists("pesos.json"):
    mlp.load("pesos.json")

# ALTERADO PARA SELECAO AUTOMATICA DO MODELO
# Fallback preserva o threshold utilizado anteriormente pelo servidor.
threshold = 0.35

try:
    with open(
        "modelo_selecionado.json",
        "r",
        encoding="utf-8"
    ) as arquivo:
        configuracao_modelo = json.load(arquivo)

    threshold_configurado = float(
        configuracao_modelo["threshold"]
    )

    if not 0.0 <= threshold_configurado <= 1.0:
        raise ValueError("Threshold fora do intervalo [0, 1].")

    threshold = threshold_configurado
except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
    print(
        "Configuracao de modelo ausente ou invalida; "
        "usando threshold 0.35.",
        flush=True
    )


# ALTERADO PARA MONITORAMENTO VISUAL
def registrar_decisao_dashboard(uri, method, risk, decisao, status_http):
    """Registra somente dados tecnicos seguros usados pelo dashboard."""
    caminho = urllib.parse.urlsplit(uri).path or "/"
    caminho = "".join(
        caractere
        if caractere.isprintable() and caractere not in "\r\n\t"
        else "?"
        for caractere in caminho
    )[:200]

    metodo = "".join(
        caractere
        for caractere in method.upper()
        if caractere.isalpha()
    )[:12]

    arquivo = "dashboard_waf.csv"
    arquivo_existe = os.path.exists(arquivo)

    try:
        with open(
            arquivo,
            "a",
            newline="",
            encoding="utf-8"
        ) as registro:
            escritor = csv.writer(registro)

            if not arquivo_existe:
                escritor.writerow([
                    "data_hora",
                    "metodo",
                    "caminho",
                    "risco",
                    "threshold",
                    "decisao",
                    "status_http"
                ])

            escritor.writerow([
                datetime.now().astimezone().isoformat(),
                metodo,
                caminho,
                float(risk),
                threshold,
                decisao,
                status_http
            ])
    except OSError as erro:
        print(
            f"Nao foi possivel registrar monitoramento: {erro}",
            flush=True
        )


def valores_brutos_observados(features_normalizadas, excedentes):
    """Recupera os valores brutos ja calculados, sem nova classificacao."""
    excedentes_por_feature = {
        item["feature"]: item["valor_real"]
        for item in excedentes
    }
    valores = []

    for nome, normalizado, limite in zip(
        NOMES_FEATURES,
        features_normalizadas,
        LIMITES
    ):
        valor = excedentes_por_feature.get(
            nome,
            float(normalizado) * limite
        )
        if abs(valor - round(valor)) < 1e-9:
            valor = int(round(valor))
        valores.append(valor)

    return valores


def headers_diagnostico(risk, features_brutas, features_normalizadas):
    """Expoe somente numeros tecnicos ao replayer local controlado."""
    return {
        "X-WAF-Risk": format(float(risk), ".17g"),
        "X-WAF-Threshold": format(float(threshold), ".17g"),
        "X-WAF-Feature-Names": ",".join(NOMES_FEATURES),
        "X-WAF-Feature-Limits": ",".join(str(valor) for valor in LIMITES),
        "X-WAF-Features-Raw": ",".join(
            format(float(valor), ".17g")
            for valor in features_brutas
        ),
        "X-WAF-Features-Normalized": ",".join(
            format(float(valor), ".17g")
            for valor in features_normalizadas
        )
    }


@app.route(
    "/",
    defaults={"path": ""},
    methods=["GET", "POST", "PUT", "DELETE"]
)
@app.route(
    "/<path:path>",
    methods=["GET", "POST", "PUT", "DELETE"]
)
def check(path):

    uri = request.headers.get("X-Original-URI", request.url)
    method = request.headers.get("X-Original-Method", request.method)
    client_ip = request.headers.get("X-Real-IP", request.remote_addr)
    body = request.get_data(as_text=True)
    simulacao_controlada = (
        request.headers.get("X-Controlled-Simulation", "").lower()
        == "csic2010"
    )
    features, excedentes = extract_features(
        request.headers,
        uri,
        method,
        body,
        client_ip
    )
    features_brutas = valores_brutos_observados(features, excedentes)

    risk = mlp.forward(features)[0]

    # ALTERADO PARA MONITORAMENTO VISUAL
    # A decisao permanece exatamente risk > threshold.
    bloqueada = risk > threshold
    decisao_waf = "BLOQUEADA" if bloqueada else "LIBERADA"
    status_http = 403 if bloqueada else 200
    registrar_decisao_dashboard(
        uri,
        method,
        risk,
        decisao_waf,
        status_http
    )

    if excedentes:

        # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
        decisao = "BLOQUEADO" if bloqueada else "LIBERADO"

        arquivo = "registros_excedentes.csv"
        arquivo_existe = os.path.exists(arquivo)

        # Na avaliacao CSIC, nunca persiste query string do dataset externo.
        uri_registro = (
            urllib.parse.urlsplit(uri).path or "/"
            if simulacao_controlada
            else uri
        )

        with open(
            arquivo,
            "a",
            newline="",
            encoding="utf-8"
        ) as f:

            writer = csv.writer(f)

            if not arquivo_existe:
                writer.writerow([
                    "data_hora",
                    "client_ip",
                    "method",
                    "uri",
                    "feature",
                    "valor_real",
                    "limite",
                    "risk",
                    "decisao"
                ])

            for excedente in excedentes:
                writer.writerow([
                    datetime.now().isoformat(),
                    client_ip,
                    method,
                    uri_registro,
                    excedente["feature"],
                    excedente["valor_real"],
                    excedente["limite"],
                    risk,
                    decisao
                ])

    print(
        f"DEBUG [{method}]: "
        f"Features: {features} | "
        f"Risco: {risk:.4f}",
        flush=True
    )

    headers_observacionais = (
        headers_diagnostico(risk, features_brutas, features)
        if simulacao_controlada
        else {}
    )

    # ALTERADO PARA SELECAO AUTOMATICA DO MODELO
    if bloqueada:
        return Response(
            "Bloqueado pelo WAF",
            status=403,
            headers=headers_observacionais
        )

    # O replay controlado precisa apenas da decisão do WAF. Responder aqui
    # preserva os metadados observacionais que o redirecionamento interno do
    # Nginx descartaria; requisições normais continuam seguindo ao PHP.
    if simulacao_controlada:
        return Response(
            "Liberado pelo WAF",
            status=200,
            headers=headers_observacionais
        )

    headers_observacionais["X-Accel-Redirect"] = f"/_php_backend{uri}"
    return Response(
        status=200,
        headers=headers_observacionais
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )
