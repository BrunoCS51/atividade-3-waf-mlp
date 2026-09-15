import os
import csv
from datetime import datetime

from flask import Flask, request, Response

from extractor import extract_features
from mlp import MLP


app = Flask(__name__)

mlp = MLP(input_size=9, hidden_size=10, output_size=1)

if os.path.exists("pesos.json"):
    mlp.load("pesos.json")


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

    features, excedentes = extract_features(
        request.headers,
        uri,
        method,
        body,
        client_ip
    )

    risk = mlp.forward(features)[0]

    if excedentes:

        decisao = "BLOQUEADO" if risk > 0.35 else "LIBERADO"

        arquivo = "registros_excedentes.csv"
        arquivo_existe = os.path.exists(arquivo)

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
                    uri,
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

    if risk > 0.35:
        return Response(
            "Bloqueado pelo WAF",
            status=403
        )

    return Response(
        status=200,
        headers={
            "X-Accel-Redirect": f"/_php_backend{uri}"
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000
    )