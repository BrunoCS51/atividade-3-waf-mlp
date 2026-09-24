"""Coordena um único retreinamento em background para o dashboard."""

from __future__ import annotations

import copy
import threading
import time
import uuid
from datetime import datetime

from experimentos.retreinar_modelo import (
    estimate_seconds,
    retrain_model,
    validate_training_request,
)


class TrainingCoordinator:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs = {}
        self._active_id = None

    def start(self, payload, on_success=None):
        validated = validate_training_request(payload)
        with self._lock:
            if self._active_id:
                active = self._jobs.get(self._active_id, {})
                if active.get("status") in {"queued", "running"}:
                    raise RuntimeError("Já existe um treinamento em andamento")
            job_id = uuid.uuid4().hex
            now = datetime.now().astimezone().isoformat()
            total = int(validated["parameters"]["epochs" if validated["algorithm"] == "bp" else "generations"])
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "experiment_id": validated["experiment_id"],
                "algorithm": validated["algorithm"],
                "architecture": validated["architecture"],
                "parameters": validated["parameters"],
                "current": 0,
                "total": total,
                "percent": 0.0,
                "message": "Preparando dataset, split e normalização…",
                "created_at": now,
                "started_at": None,
                "completed_at": None,
                "elapsed_seconds": 0.0,
                "estimated_seconds": estimate_seconds(validated),
                "remaining_seconds": None,
                "result": None,
                "error": None,
            }
            self._active_id = job_id
        thread = threading.Thread(
            target=self._run,
            args=(job_id, payload, on_success),
            name=f"training-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.status(job_id)

    def _run(self, job_id, payload, on_success):
        started = time.perf_counter()
        self._update(job_id, status="running", started_at=datetime.now().astimezone().isoformat())

        def progress(current, total, record):
            elapsed = time.perf_counter() - started
            percent = 100.0 * current / max(total, 1)
            remaining = elapsed * (total - current) / current if current else None
            key = "epoch" if "epoch" in record else "generation"
            validation = record.get("validation_mse")
            message = f"{key.capitalize()} {current} de {total}"
            if validation is not None:
                message += f" · MSE validação {float(validation):.6f}"
            self._update(
                job_id,
                current=current,
                total=total,
                percent=percent,
                message=message,
                elapsed_seconds=elapsed,
                remaining_seconds=remaining,
            )

        try:
            result = retrain_model(payload, progress_callback=progress)
            if on_success:
                on_success()
            elapsed = time.perf_counter() - started
            self._update(
                job_id,
                status="completed",
                current=self._jobs[job_id]["total"],
                percent=100.0,
                message="Treinamento concluído; artefatos e runtime atualizados.",
                elapsed_seconds=elapsed,
                remaining_seconds=0.0,
                completed_at=datetime.now().astimezone().isoformat(),
                result=result,
            )
        except Exception as error:  # Estado controlado e legível para a interface.
            self._update(
                job_id,
                status="failed",
                message="Treinamento interrompido antes da atualização completa.",
                elapsed_seconds=time.perf_counter() - started,
                completed_at=datetime.now().astimezone().isoformat(),
                error=str(error),
            )
        finally:
            with self._lock:
                if self._active_id == job_id:
                    self._active_id = None

    def _update(self, job_id, **values):
        with self._lock:
            self._jobs[job_id].update(values)

    def status(self, job_id):
        with self._lock:
            if job_id not in self._jobs:
                raise ValueError("Treinamento não encontrado")
            return copy.deepcopy(self._jobs[job_id])

    def active(self):
        with self._lock:
            if not self._active_id:
                return None
            return copy.deepcopy(self._jobs[self._active_id])
