"""API e painel do laboratório isolado de balanceamento por reforço."""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import threading
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, jsonify, request, send_from_directory

from qlearning import (
    ACTIONS,
    ALPHA,
    EPSILON_DECAY,
    EPSILON_MIN,
    EPSILON_START,
    GAMMA,
    STATES,
    calculate_reward,
    new_q_table,
    policy,
    safe_q_table,
    select_action,
    update_q_table,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("RL_DATA_DIR", BASE_DIR / "data"))
PROXY_URL = os.environ.get("RL_PROXY_URL", "http://rl_proxy:8080").rstrip("/")
REQUEST_TIMEOUT = 0.50
DEFAULT_EPISODES = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def atomic_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


class ReinforcementLab:
    def __init__(self):
        self.lock = threading.RLock()
        self.q_table = new_q_table()
        self.job = None
        self.last_training = None
        self.last_comparison = None
        self._load()

    def _load(self):
        try:
            self.q_table = safe_q_table(json.loads((DATA_DIR / "q_table_treinada.json").read_text(encoding="utf-8")))
            self.last_training = json.loads((DATA_DIR / "ultimo_treinamento.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.q_table = new_q_table()
            self.last_training = None
        try:
            self.last_comparison = json.loads((DATA_DIR / "ultima_comparacao.json").read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.last_comparison = None

    def _request_node(self, node: str, state: str) -> dict:
        start = time.perf_counter()
        try:
            response = requests.get(
                f"{PROXY_URL}/{node}",
                headers={"X-Network-State": state},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return {
                "node": node,
                "latency_ms": (time.perf_counter() - start) * 1000.0,
                "timeout": False,
                "error": None,
            }
        except requests.Timeout:
            return {
                "node": node,
                "latency_ms": (time.perf_counter() - start) * 1000.0,
                "timeout": True,
                "error": None,
            }
        except requests.RequestException as error:
            return {
                "node": node,
                "latency_ms": (time.perf_counter() - start) * 1000.0,
                "timeout": True,
                "error": str(error)[:180],
            }

    def infrastructure(self) -> dict:
        nodes = {}
        for node in ACTIONS:
            result = self._request_node(node, "carga_baixa")
            nodes[node] = {
                "online": result["error"] is None,
                "latency_ms": result["latency_ms"],
                "timeout": result["timeout"],
            }
        return {"online": all(item["online"] for item in nodes.values()), "nodes": nodes}

    def status(self) -> dict:
        with self.lock:
            job = deepcopy(self.job) if self.job else None
            return {
                "algorithm": {
                    "name": "Q-Learning tabular off-policy",
                    "alpha": ALPHA,
                    "gamma": GAMMA,
                    "epsilon_start": EPSILON_START,
                    "epsilon_min": EPSILON_MIN,
                    "epsilon_decay": EPSILON_DECAY,
                    "reward": {"lt_100ms": 20, "100_to_249ms": 2, "gte_250ms": -15, "timeout": -100},
                },
                "q_table": deepcopy(self.q_table),
                "policy": policy(self.q_table),
                "training": job,
                "last_training": deepcopy(self.last_training),
                "last_comparison": deepcopy(self.last_comparison),
            }

    def start_training(self, episodes: int, seed: int) -> dict:
        if not 10 <= episodes <= 5000:
            raise ValueError("Episódios devem estar entre 10 e 5000")
        health = self.infrastructure()
        if not health["online"]:
            raise RuntimeError("Infraestrutura RL indisponível. Inicie o profile reforco do Docker Compose.")
        with self.lock:
            if self.job and self.job["status"] in {"queued", "running"}:
                raise RuntimeError("Já existe um treinamento em andamento")
            self.q_table = new_q_table()
            self.job = {
                "status": "queued",
                "episodes": episodes,
                "current_episode": 0,
                "percent": 0.0,
                "epsilon": EPSILON_START,
                "elapsed_seconds": 0.0,
                "remaining_seconds": None,
                "started_at": now_iso(),
                "completed_at": None,
                "message": "Preparando o agente e zerando a Q-Table",
                "curve": [],
                "action_counts": {node: 0 for node in ACTIONS},
                "exploration_count": 0,
                "exploitation_count": 0,
                "timeouts": 0,
                "errors": 0,
                "seed": seed,
            }
        threading.Thread(target=self._train, args=(episodes, seed), daemon=True, name="rl-training").start()
        return self.status()

    def _train(self, episodes: int, seed: int):
        rng = random.Random(seed)
        epsilon = EPSILON_START
        started = time.perf_counter()
        with self.lock:
            self.job["status"] = "running"
            self.job["message"] = "Executando política ε-greedy e atualizações de Bellman"
        try:
            for index in range(episodes):
                episode = index + 1
                state = STATES[index % len(STATES)]
                next_state = STATES[(index + 1) % len(STATES)]
                with self.lock:
                    action, mode = select_action(self.q_table, state, epsilon, rng)
                observation = self._request_node(action, state)
                reward = calculate_reward(observation["latency_ms"], observation["timeout"])
                with self.lock:
                    new_q = update_q_table(self.q_table, state, action, reward, next_state)
                    elapsed = time.perf_counter() - started
                    remaining = elapsed * (episodes - episode) / episode
                    self.job["current_episode"] = episode
                    self.job["percent"] = 100.0 * episode / episodes
                    self.job["epsilon"] = epsilon
                    self.job["elapsed_seconds"] = elapsed
                    self.job["remaining_seconds"] = remaining
                    self.job["action_counts"][action] += 1
                    self.job["exploration_count" if mode == "exploracao" else "exploitation_count"] += 1
                    self.job["timeouts"] += int(observation["timeout"])
                    self.job["errors"] += int(observation["error"] is not None)
                    self.job["message"] = f"Episódio {episode}/{episodes}: {state} → {action}"
                    self.job["curve"].append({
                        "episode": episode,
                        "state": state,
                        "action": action,
                        "mode": mode,
                        "latency_ms": observation["latency_ms"],
                        "timeout": observation["timeout"],
                        "reward": reward,
                        "q_value": new_q,
                        "epsilon": epsilon,
                    })
                epsilon = max(EPSILON_MIN, epsilon * EPSILON_DECAY)
            with self.lock:
                self.job["status"] = "completed"
                self.job["percent"] = 100.0
                self.job["epsilon"] = epsilon
                self.job["remaining_seconds"] = 0.0
                self.job["completed_at"] = now_iso()
                self.job["message"] = "Treinamento concluído e Q-Table persistida"
                self.last_training = deepcopy(self.job)
                atomic_json(DATA_DIR / "q_table_treinada.json", self.q_table)
                atomic_json(DATA_DIR / "ultimo_treinamento.json", self.last_training)
        except Exception as error:
            with self.lock:
                self.job["status"] = "failed"
                self.job["completed_at"] = now_iso()
                self.job["message"] = f"Treinamento interrompido: {error}"

    def reset(self):
        with self.lock:
            if self.job and self.job["status"] in {"queued", "running"}:
                raise RuntimeError("Não é possível limpar durante o treinamento")
            self.q_table = new_q_table()
            self.job = None
            self.last_training = None
            self.last_comparison = None
            for name in ("q_table_treinada.json", "ultimo_treinamento.json", "ultima_comparacao.json"):
                try:
                    (DATA_DIR / name).unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _percentile(values: list[float], fraction: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
        return ordered[index]

    def _burst(self, name: str, schedule: list[str], concurrency: int) -> dict:
        started = time.perf_counter()
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(self._request_node, node, "carga_alta") for node in schedule]
            for future in as_completed(futures):
                results.append(future.result())
        latencies = [item["latency_ms"] for item in results if not item["timeout"]]
        return {
            "policy": name,
            "requests": len(results),
            "concurrency": concurrency,
            "wall_seconds": time.perf_counter() - started,
            "routes": {node: sum(item["node"] == node for item in results) for node in ACTIONS},
            "timeouts": sum(item["timeout"] for item in results),
            "errors": sum(item["error"] is not None for item in results),
            "under_100ms": sum(not item["timeout"] and item["latency_ms"] < 100.0 for item in results),
            "average_latency_ms": statistics.fmean(latencies) if latencies else 0.0,
            "p95_latency_ms": self._percentile(latencies, 0.95),
        }

    def compare(self, request_count: int, concurrency: int, seed: int) -> dict:
        if not 6 <= request_count <= 500:
            raise ValueError("Quantidade deve estar entre 6 e 500")
        if not 1 <= concurrency <= 30:
            raise ValueError("Concorrência deve estar entre 1 e 30")
        health = self.infrastructure()
        if not health["online"]:
            raise RuntimeError("Infraestrutura RL indisponível")
        with self.lock:
            if self.job and self.job["status"] in {"queued", "running"}:
                raise RuntimeError("Aguarde o treinamento terminar antes de comparar")
            learned = policy(self.q_table)["carga_alta"]
            trained = self.last_training is not None
        if not trained:
            raise RuntimeError("Treine o agente antes de executar a comparação")
        rng = random.Random(seed)
        round_robin = [ACTIONS[index % len(ACTIONS)] for index in range(request_count)]
        intelligent = [learned if rng.random() >= EPSILON_MIN else rng.choice(ACTIONS) for _ in range(request_count)]
        comparison = {
            "created_at": now_iso(),
            "trained_q_table": trained,
            "state": "carga_alta",
            "residual_epsilon": EPSILON_MIN,
            "round_robin": self._burst("round_robin", round_robin, concurrency),
            "q_learning": self._burst("q_learning", intelligent, concurrency),
        }
        with self.lock:
            self.last_comparison = comparison
            atomic_json(DATA_DIR / "ultima_comparacao.json", comparison)
        return comparison


app = Flask(__name__, static_folder=str(STATIC_DIR), static_url_path="/static")
lab = ReinforcementLab()


@app.get("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.get("/api/status")
def api_status():
    return jsonify(lab.status())


@app.get("/api/infrastructure")
def api_infrastructure():
    return jsonify(lab.infrastructure())


@app.post("/api/train")
def api_train():
    try:
        payload = request.get_json(force=True) or {}
        return jsonify(lab.start_training(int(payload.get("episodes", DEFAULT_EPISODES)), int(payload.get("seed", 42)))), 202
    except (TypeError, ValueError, RuntimeError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/compare")
def api_compare():
    try:
        payload = request.get_json(force=True) or {}
        return jsonify(lab.compare(int(payload.get("requests", 60)), int(payload.get("concurrency", 6)), int(payload.get("seed", 42))))
    except (TypeError, ValueError, RuntimeError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/reset")
def api_reset():
    try:
        lab.reset()
        return jsonify({"reset": True})
    except RuntimeError as error:
        return jsonify({"error": str(error)}), 409


@app.after_request
def security_headers(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
