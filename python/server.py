"""WAF HTTP com inferência paralela E1/E2 e decisão operacional configurável."""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, Response, request

from model_runtime import WAFRuntime
from training_jobs import TrainingCoordinator


BASE_DIR = Path(__file__).resolve().parent
HISTORY_FIELDS = (
    "timestamp", "method", "target_path", "primary_model",
    "operational_decision", "e1_algorithm", "e1_score", "e1_decision",
    "e2_algorithm", "e2_score", "e2_decision", "status_http",
)


def safe_path(target: str) -> str:
    try:
        path = urlsplit(target).path or "/"
    except ValueError:
        path = str(target).split("?", 1)[0] or "/"
    return "".join(
        character if character.isprintable() and character not in "\r\n\t" else "?"
        for character in path
    )[:240]


def create_app(runtime: WAFRuntime | None = None, history_path: Path | None = None):
    application = Flask(__name__)
    application.config["WAF_RUNTIME"] = runtime or WAFRuntime(
        primary_model=os.environ.get("WAF_PRIMARY_MODEL", "experimento_1:bp"),
        shadow_e1_algorithm=os.environ.get("WAF_SHADOW_E1_ALGORITHM", "bp"),
        shadow_e2_algorithm=os.environ.get("WAF_SHADOW_E2_ALGORITHM", "bp"),
    )
    application.config["HISTORY_PATH"] = history_path or Path(
        os.environ.get("WAF_HISTORY_PATH", BASE_DIR / "monitor_waf.csv")
    )
    application.config["TRAINING_COORDINATOR"] = TrainingCoordinator()

    def require_training_token():
        expected = os.environ.get("WAF_TRAINING_TOKEN", "local-academic-training")
        received = request.headers.get("X-Training-Token", "")
        if received != expected:
            return Response("Não autorizado", status=403)
        return None

    def reload_runtime():
        current = application.config["WAF_RUNTIME"]
        application.config["WAF_RUNTIME"] = WAFRuntime(
            primary_model=current.primary_model,
            shadow_e1_algorithm=current.shadow_algorithms["experimento_1"],
            shadow_e2_algorithm=current.shadow_algorithms["experimento_2"],
        )

    @application.post("/__training/start")
    def start_training():
        denied = require_training_token()
        if denied:
            return denied
        try:
            payload = request.get_json(force=True)
            job = application.config["TRAINING_COORDINATOR"].start(
                payload, on_success=reload_runtime
            )
            return Response(
                json.dumps(job, ensure_ascii=False),
                status=202,
                content_type="application/json; charset=utf-8",
            )
        except (TypeError, ValueError, RuntimeError) as error:
            return Response(
                json.dumps({"error": str(error)}, ensure_ascii=False),
                status=400,
                content_type="application/json; charset=utf-8",
            )

    @application.get("/__training/status/<job_id>")
    def training_status(job_id):
        denied = require_training_token()
        if denied:
            return denied
        try:
            job = application.config["TRAINING_COORDINATOR"].status(job_id)
            return Response(
                json.dumps(job, ensure_ascii=False),
                content_type="application/json; charset=utf-8",
            )
        except ValueError as error:
            return Response(
                json.dumps({"error": str(error)}, ensure_ascii=False),
                status=404,
                content_type="application/json; charset=utf-8",
            )

    @application.get("/__training/active")
    def active_training():
        denied = require_training_token()
        if denied:
            return denied
        return Response(
            json.dumps(
                application.config["TRAINING_COORDINATOR"].active(),
                ensure_ascii=False,
            ),
            content_type="application/json; charset=utf-8",
        )

    def register(result, method, target, status_http):
        path = Path(application.config["HISTORY_PATH"])
        exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=HISTORY_FIELDS)
            if not exists:
                writer.writeheader()
            writer.writerow({
                "timestamp": datetime.now().astimezone().isoformat(),
                "method": "".join(c for c in method.upper() if c.isalpha())[:16],
                "target_path": safe_path(target),
                "primary_model": result.primary_model,
                "operational_decision": result.operational.decision,
                "e1_algorithm": result.experiment_one.algorithm,
                "e1_score": format(result.experiment_one.score, ".17g"),
                "e1_decision": result.experiment_one.decision,
                "e2_algorithm": result.experiment_two.algorithm,
                "e2_score": format(result.experiment_two.score, ".17g"),
                "e2_decision": result.experiment_two.decision,
                "status_http": status_http,
            })

    @application.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    @application.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def check(path):
        original_uri = request.headers.get("X-Original-URI", request.full_path)
        target = request.headers.get("X-Original-Target", request.url)
        method = request.headers.get("X-Original-Method", request.method)
        client_ip = request.headers.get("X-Real-IP", request.remote_addr or "unknown")
        version = request.environ.get("SERVER_PROTOCOL", "HTTP/1.1")
        result = application.config["WAF_RUNTIME"].evaluate(
            request.headers, target, method, version, request.get_data(), client_ip
        )
        status_http = 403 if result.operational.blocked else 200
        try:
            register(result, method, target, status_http)
        except OSError as error:
            application.logger.error("Não foi possível registrar monitoramento: %s", error)

        headers = {
            "X-WAF-Primary-Model": result.primary_model,
            "X-WAF-Decision": "BLOCKED" if result.operational.blocked else "NORMAL",
            "X-WAF-E1-Algorithm": result.experiment_one.algorithm.upper(),
            "X-WAF-E1-Score": format(result.experiment_one.score, ".8f"),
            "X-WAF-E1-Decision": result.experiment_one.decision,
            "X-WAF-E2-Algorithm": result.experiment_two.algorithm.upper(),
            "X-WAF-E2-Score": format(result.experiment_two.score, ".8f"),
            "X-WAF-E2-Decision": result.experiment_two.decision,
        }
        if result.operational.blocked:
            return Response("Bloqueado pelo WAF", status=403, headers=headers)
        safe_backend_uri = original_uri.replace("\r", "").replace("\n", "")
        headers["X-Accel-Redirect"] = f"/_php_backend{safe_backend_uri}"
        return Response(status=200, headers=headers)

    return application


logging.getLogger("werkzeug").setLevel(logging.ERROR)
app = create_app()


if __name__ == "__main__":
    print(
        f"WAF iniciado; modelo principal={app.config['WAF_RUNTIME'].primary_model}",
        flush=True,
    )
    app.run(host="0.0.0.0", port=5000)
