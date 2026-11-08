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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
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
    NODE_MAX_CONCURRENT,
    STATE_BASE_LOAD,
    STATES,
    add_request_load,
    calculate_operational_reward,
    calculate_reward,
    decay_loads,
    load_wait_ms,
    new_q_table,
    node_telemetry,
    policy,
    safe_q_table,
    select_action,
    select_operational_action,
    state_from_loads,
    update_q_table,
)


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.environ.get("RL_DATA_DIR", BASE_DIR / "data"))
PROXY_URL = os.environ.get("RL_PROXY_URL", "http://rl_proxy:8080").rstrip("/")
REQUEST_TIMEOUT = 0.50
DEFAULT_EPISODES = 500
ENVIRONMENT_VERSION = 4
COMPARISON_VERSION = 2


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
        self.interactive = None
        self._interactive_last_load_update = None
        self._load()

    def _load(self):
        try:
            self.last_training = json.loads((DATA_DIR / "ultimo_treinamento.json").read_text(encoding="utf-8"))
            if self.last_training.get("environment_version") != ENVIRONMENT_VERSION:
                raise ValueError("Treinamento pertence à configuração anterior")
            self.q_table = safe_q_table(json.loads((DATA_DIR / "q_table_treinada.json").read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.q_table = new_q_table()
            self.last_training = None
        try:
            self.last_comparison = json.loads((DATA_DIR / "ultima_comparacao.json").read_text(encoding="utf-8"))
            if (self.last_training is None
                    or self.last_comparison.get("environment_version") != ENVIRONMENT_VERSION
                    or self.last_comparison.get("comparison_version") != COMPARISON_VERSION):
                raise ValueError("Comparação pertence a outro ambiente")
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

    def _training_request(self, node: str, state: str) -> dict:
        """Avalia o treino no mesmo modelo de capacidade usado nas demais etapas."""
        loads = {action: STATE_BASE_LOAD[state] for action in ACTIONS}
        loads = add_request_load(loads, node)
        active = {action: int(action == node) for action in ACTIONS}
        telemetry = node_telemetry(loads, active)[node]
        return self._interactive_request(node, telemetry["cpu"], telemetry["active_requests"])

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
                "interactive": deepcopy(self.interactive),
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
            if self.interactive and self.interactive["status"] == "running":
                raise RuntimeError("Finalize a simulação interativa antes de treinar")
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
                "environment_version": ENVIRONMENT_VERSION,
                "state_base_loads": deepcopy(STATE_BASE_LOAD),
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
                observation = self._training_request(action, state)
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
            if self.interactive and self.interactive["status"] == "running":
                raise RuntimeError("Não é possível limpar durante a simulação interativa")
            self.q_table = new_q_table()
            self.job = None
            self.last_training = None
            self.last_comparison = None
            self.interactive = None
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

    @staticmethod
    def _comparison_verdict(round_robin: dict, q_learning: dict, request_count: int) -> dict:
        """Evita declarar vencedor quando a diferença cabe no ruído da medição."""
        timeout_margin = max(1, math.ceil(request_count * 0.02))
        timeout_difference = round_robin["timeouts"] - q_learning["timeouts"]
        if abs(timeout_difference) >= timeout_margin:
            winner = "q_learning" if timeout_difference > 0 else "round_robin"
            return {
                "winner": winner,
                "equivalent": False,
                "reason": f"diferença de {abs(timeout_difference)} timeout(s)",
            }
        rr_latency = round_robin["average_latency_ms"]
        q_latency = q_learning["average_latency_ms"]
        denominator = max(rr_latency, q_latency, 1.0)
        relative_difference = abs(rr_latency - q_latency) / denominator
        if round_robin["timeouts"] == q_learning["timeouts"] and relative_difference >= 0.05:
            winner = "q_learning" if q_latency < rr_latency else "round_robin"
            return {
                "winner": winner,
                "equivalent": False,
                "reason": f"diferença de latência média de {relative_difference * 100:.1f}%",
            }
        return {
            "winner": None,
            "equivalent": True,
            "reason": "diferenças abaixo das margens de 2% de timeouts e 5% de latência",
        }

    def _burst(self, name: str, schedule: list[dict], concurrency: int) -> dict:
        started = time.perf_counter()
        results = []
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [
                executor.submit(
                    self._interactive_request,
                    item["node"],
                    item["cpu"],
                    item["active_requests"],
                )
                for item in schedule
            ]
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

    @staticmethod
    def _comparison_schedule(strategy: str, request_count: int, concurrency: int, q_table, rng) -> list[dict]:
        """Cria cenários equivalentes; apenas a política de escolha varia."""
        loads = {node: STATE_BASE_LOAD["carga_media"] for node in ACTIONS}
        active = {node: 0 for node in ACTIONS}
        schedule = []
        for index in range(request_count):
            if index and index % concurrency == 0:
                active = {node: 0 for node in ACTIONS}
                loads = decay_loads(loads, 0.25)
            telemetry = node_telemetry(loads, active)
            state = state_from_loads({node: telemetry[node]["cpu"] for node in ACTIONS})
            if strategy == "round_robin":
                selected = ACTIONS[index % len(ACTIONS)]
            else:
                selected, _, _ = select_operational_action(q_table, state, EPSILON_MIN, telemetry, rng)
            loads = add_request_load(loads, selected)
            active[selected] += 1
            selected_telemetry = node_telemetry(loads, active)[selected]
            schedule.append({
                "node": selected,
                "cpu": selected_telemetry["cpu"],
                "active_requests": selected_telemetry["active_requests"],
                "state": state,
            })
        return schedule

    @staticmethod
    def _scenario_concurrency_limit(loads: dict[str, float]) -> int:
        """Número de admissões até todos os nós atingirem seu primeiro limite."""
        limit = 0
        for node in ACTIONS:
            for active_count in range(1, NODE_MAX_CONCURRENT[node] + 1):
                active = {action: 0 for action in ACTIONS}
                active[node] = active_count
                if node_telemetry(loads, active)[node]["saturated"]:
                    limit += active_count
                    break
            else:
                limit += NODE_MAX_CONCURRENT[node]
        return limit

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
            if self.interactive and self.interactive["status"] == "running":
                raise RuntimeError("Aguarde a simulação interativa terminar antes de comparar")
            trained = self.last_training is not None
            comparison_q_table = deepcopy(self.q_table)
        if not trained:
            raise RuntimeError("Treine o agente antes de executar a comparação")
        rng = random.Random(seed)
        comparison_state = "carga_media"
        base_loads = {node: STATE_BASE_LOAD[comparison_state] for node in ACTIONS}
        round_robin = self._comparison_schedule(
            "round_robin", request_count, concurrency, comparison_q_table, rng
        )
        intelligent = self._comparison_schedule(
            "q_learning", request_count, concurrency, comparison_q_table, rng
        )
        execution_order = ["round_robin", "q_learning"]
        if seed % 2:
            execution_order.reverse()
        bursts = {}
        for name in execution_order:
            schedule = round_robin if name == "round_robin" else intelligent
            bursts[name] = self._burst(name, schedule, concurrency)
        verdict = self._comparison_verdict(
            bursts["round_robin"], bursts["q_learning"], request_count
        )
        comparison = {
            "created_at": now_iso(),
            "environment_version": ENVIRONMENT_VERSION,
            "comparison_version": COMPARISON_VERSION,
            "trained_q_table": trained,
            "state": comparison_state,
            "residual_epsilon": EPSILON_MIN,
            "conditions": {
                "requests": request_count,
                "concurrency": concurrency,
                "initial_loads": base_loads,
                "state": comparison_state,
                "same_nodes_and_routes": True,
                "execution_order": execution_order,
                "nominal_concurrency_limit": sum(NODE_MAX_CONCURRENT.values()),
                "scenario_concurrency_limit": self._scenario_concurrency_limit(base_loads),
                "offered_over_capacity": concurrency > self._scenario_concurrency_limit(base_loads),
            },
            "round_robin": bursts["round_robin"],
            "q_learning": bursts["q_learning"],
            "verdict": verdict,
        }
        with self.lock:
            self.last_comparison = comparison
            atomic_json(DATA_DIR / "ultima_comparacao.json", comparison)
        return comparison

    def _interactive_request(self, node: str, load: float, active_requests: int) -> dict:
        wait_ms = load_wait_ms(node, load, active_requests)
        started = time.perf_counter()
        try:
            response = requests.get(
                f"{PROXY_URL}/simulation/{node}",
                params={"wait": f"{wait_ms:.0f}ms"},
                headers={"X-Simulated-Load": f"{load:.1f}"},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return {
                "node": node,
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "configured_wait_ms": wait_ms,
                "timeout": False,
                "error": None,
            }
        except requests.Timeout:
            return {
                "node": node,
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "configured_wait_ms": wait_ms,
                "timeout": True,
                "error": None,
            }
        except requests.RequestException as error:
            return {
                "node": node,
                "latency_ms": (time.perf_counter() - started) * 1000.0,
                "configured_wait_ms": wait_ms,
                "timeout": True,
                "error": str(error)[:180],
            }

    @staticmethod
    def _validated_loads(value) -> dict[str, float]:
        if not isinstance(value, dict):
            raise ValueError("Cargas ausentes")
        loads = {node: float(value.get(node, -1)) for node in ACTIONS}
        state_from_loads(loads)
        return loads

    def _decay_interactive_loads_locked(self, now: float | None = None) -> dict[str, float]:
        """Atualiza a carga residual pelo tempo transcorrido; deve ser chamado com o lock."""
        now = time.perf_counter() if now is None else now
        previous = self._interactive_last_load_update or now
        self.interactive["loads"] = decay_loads(self.interactive["loads"], max(0.0, now - previous))
        self._interactive_last_load_update = now
        return self.interactive["loads"]

    def start_interactive(self, loads, request_count: int, epsilon: float, interval_ms: int, concurrency: int, learning_mode: str, seed: int) -> dict:
        loads = self._validated_loads(loads)
        if not 1 <= request_count <= 500:
            raise ValueError("Quantidade deve estar entre 1 e 500")
        if not 0.0 <= epsilon <= 1.0:
            raise ValueError("Epsilon deve estar entre 0 e 1")
        if not 50 <= interval_ms <= 3000:
            raise ValueError("Intervalo deve estar entre 50 e 3000 ms")
        if not 1 <= concurrency <= 20:
            raise ValueError("Concorrência deve estar entre 1 e 20")
        if learning_mode not in {"fixed", "continuous"}:
            raise ValueError("Modo de aprendizado inválido")
        health = self.infrastructure()
        if not health["online"]:
            raise RuntimeError("Infraestrutura RL indisponível")
        with self.lock:
            if not self.last_training:
                raise RuntimeError("Treine o agente antes da simulação interativa")
            if self.job and self.job["status"] in {"queued", "running"}:
                raise RuntimeError("Aguarde o treinamento terminar")
            if self.interactive and self.interactive["status"] == "running":
                raise RuntimeError("Já existe uma simulação interativa em andamento")
            self.interactive = {
                "status": "running",
                "request_count": request_count,
                "current_request": 0,
                "percent": 0.0,
                "epsilon": epsilon,
                "interval_ms": interval_ms,
                "concurrency": concurrency,
                "learning_mode": learning_mode,
                "seed": seed,
                "loads": loads,
                "active_counts": {node: 0 for node in ACTIONS},
                "cpu_utilization": deepcopy(loads),
                "saturation": {node: False for node in ACTIONS},
                "submitted_requests": 0,
                "initial_loads": deepcopy(loads),
                "q_table": deepcopy(self.q_table),
                "policy": policy(self.q_table),
                "records": [],
                "route_counts": {node: 0 for node in ACTIONS},
                "timeouts": 0,
                "errors": 0,
                "reward_total": 0.0,
                "started_at": now_iso(),
                "completed_at": None,
                "elapsed_seconds": 0.0,
                "message": (
                    "Q-Table fixa: decisões sem atualização de Bellman"
                    if learning_mode == "fixed"
                    else "Aprendizado contínuo sobre uma cópia da Q-Table"
                ),
                "stop_requested": False,
            }
            self._interactive_last_load_update = time.perf_counter()
        threading.Thread(
            target=self._run_interactive,
            args=(request_count, epsilon, interval_ms, concurrency, learning_mode, seed),
            daemon=True,
            name="rl-interactive",
        ).start()
        with self.lock:
            return deepcopy(self.interactive)

    def _run_interactive(self, request_count: int, epsilon: float, interval_ms: int, concurrency: int, learning_mode: str, seed: int):
        """Executa HTTP concorrente e adapta a Q-Table isolada da sessão."""
        rng = random.Random(seed)
        started = time.perf_counter()
        submitted = completed = 0
        next_dispatch = started
        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                pending = {}
                while submitted < request_count or pending:
                    with self.lock:
                        stopping = self.interactive["stop_requested"]
                    now = time.perf_counter()
                    can_dispatch = (not stopping and submitted < request_count
                                    and len(pending) < concurrency and now >= next_dispatch)
                    if can_dispatch:
                        with self.lock:
                            self._decay_interactive_loads_locked(now)
                            loads_before = deepcopy(self.interactive["loads"])
                            telemetry = node_telemetry(loads_before, self.interactive["active_counts"])
                            state = state_from_loads({node: telemetry[node]["cpu"] for node in ACTIONS})
                            action, mode, scores = select_operational_action(
                                self.interactive["q_table"], state, epsilon, telemetry, rng
                            )
                            q_before = self.interactive["q_table"][state][action]
                            self.interactive["loads"] = add_request_load(self.interactive["loads"], action)
                            self.interactive["active_counts"][action] += 1
                            loads_on_arrival = deepcopy(self.interactive["loads"])
                            request_telemetry = node_telemetry(loads_on_arrival, self.interactive["active_counts"])
                            selected = deepcopy(request_telemetry[action])
                            self.interactive["cpu_utilization"] = {node: request_telemetry[node]["cpu"] for node in ACTIONS}
                            self.interactive["saturation"] = {node: request_telemetry[node]["saturated"] for node in ACTIONS}
                            submitted += 1
                            self.interactive["submitted_requests"] = submitted
                            self.interactive["message"] = f"Requisição #{submitted} enviada para {action}"
                        future = executor.submit(self._interactive_request, action, selected["cpu"], selected["active_requests"])
                        pending[future] = {
                            "request": submitted, "state": state, "action": action,
                            "mode": mode, "scores": scores, "q_before": q_before,
                            "loads_before": loads_before,
                            "loads_on_arrival": loads_on_arrival,
                            "cpu_before": {node: request_telemetry[node]["cpu"] for node in ACTIONS},
                            "active_before": {node: request_telemetry[node]["active_requests"] for node in ACTIONS},
                            "selected": selected,
                        }
                        next_dispatch = now + interval_ms / 1000.0
                        continue
                    done, _ = wait(pending, timeout=0.03, return_when=FIRST_COMPLETED) if pending else (set(), set())
                    for future in done:
                        context = pending.pop(future)
                        observation = future.result()
                        with self.lock:
                            action = context["action"]
                            self._decay_interactive_loads_locked()
                            self.interactive["active_counts"][action] -= 1
                            loads_after = deepcopy(self.interactive["loads"])
                            telemetry_after = node_telemetry(loads_after, self.interactive["active_counts"])
                            cpu_after = {node: telemetry_after[node]["cpu"] for node in ACTIONS}
                            next_state = state_from_loads(cpu_after)
                            parts = calculate_operational_reward(
                                observation["latency_ms"], observation["timeout"],
                                context["selected"]["cpu"], context["selected"]["active_requests"],
                                context["selected"]["saturated"],
                            )
                            reward = parts["total"]
                            if learning_mode == "continuous":
                                q_after = update_q_table(
                                    self.interactive["q_table"], context["state"], action, reward, next_state
                                )
                                q_updated = True
                            else:
                                q_after = context["q_before"]
                                q_updated = False
                            epsilon = max(EPSILON_MIN, epsilon * EPSILON_DECAY)
                            completed += 1
                            self.interactive["records"].append({
                                **context, "next_state": next_state, "loads_after": loads_after,
                                "cpu_after": cpu_after, "latency_ms": observation["latency_ms"],
                                "configured_wait_ms": observation["configured_wait_ms"],
                                "timeout": observation["timeout"], "error": observation["error"],
                                "reward": reward, "reward_parts": parts, "q_after": q_after,
                                "q_updated": q_updated, "epsilon": epsilon,
                            })
                            self.interactive["current_request"] = completed
                            self.interactive["percent"] = 100.0 * completed / request_count
                            self.interactive["epsilon"] = epsilon
                            self.interactive["policy"] = policy(self.interactive["q_table"])
                            self.interactive["route_counts"][action] += 1
                            self.interactive["timeouts"] += int(observation["timeout"])
                            self.interactive["errors"] += int(observation["error"] is not None)
                            self.interactive["reward_total"] += reward
                            self.interactive["cpu_utilization"] = cpu_after
                            self.interactive["saturation"] = {node: telemetry_after[node]["saturated"] for node in ACTIONS}
                            self.interactive["elapsed_seconds"] = time.perf_counter() - started
                            latency = "timeout" if observation["timeout"] else f"{observation['latency_ms']:.1f} ms"
                            self.interactive["message"] = f"#{context['request']}: {context['state']} → {action} · {latency} · R={reward:+.1f}"
                    if not pending and (stopping or submitted >= request_count):
                        break
            with self.lock:
                if self.interactive["stop_requested"]:
                    self.interactive["status"] = "stopped"
                    self.interactive["message"] = "Simulação interrompida; requisições em voo foram concluídas"
                else:
                    self.interactive["status"] = "completed"
                    mode_text = "fixa" if learning_mode == "fixed" else "contínua"
                    self.interactive["message"] = f"Simulação {mode_text} concluída; a Q-Table principal foi preservada"
                self.interactive["completed_at"] = now_iso()
                self.interactive["elapsed_seconds"] = time.perf_counter() - started
        except Exception as error:
            with self.lock:
                self.interactive["status"] = "failed"
                self.interactive["message"] = f"Simulação interrompida: {error}"
                self.interactive["completed_at"] = now_iso()

    def update_interactive_loads(self, loads) -> dict:
        loads = self._validated_loads(loads)
        with self.lock:
            if not self.interactive:
                raise RuntimeError("Nenhuma simulação interativa iniciada")
            if self.interactive["status"] != "running":
                raise RuntimeError("A simulação não está em andamento")
            self.interactive["loads"] = loads
            self._interactive_last_load_update = time.perf_counter()
            telemetry = node_telemetry(loads, self.interactive["active_counts"])
            self.interactive["cpu_utilization"] = {node: telemetry[node]["cpu"] for node in ACTIONS}
            self.interactive["saturation"] = {node: telemetry[node]["saturated"] for node in ACTIONS}
            self.interactive["message"] = "Cargas alteradas manualmente; a próxima decisão observará o novo estado"
            return deepcopy(self.interactive)

    def stop_interactive(self) -> dict:
        with self.lock:
            if not self.interactive or self.interactive["status"] != "running":
                raise RuntimeError("Não existe simulação em andamento")
            self.interactive["stop_requested"] = True
            self.interactive["message"] = "Solicitação de parada recebida"
            return deepcopy(self.interactive)


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


@app.get("/api/interactive")
def api_interactive_status():
    with lab.lock:
        return jsonify(deepcopy(lab.interactive))


@app.post("/api/interactive/start")
def api_interactive_start():
    try:
        payload = request.get_json(force=True) or {}
        return jsonify(lab.start_interactive(
            payload.get("loads"),
            int(payload.get("requests", 60)),
            float(payload.get("epsilon", 0.15)),
            int(payload.get("interval_ms", 50)),
            int(payload.get("concurrency", 6)),
            str(payload.get("learning_mode", "continuous")),
            int(payload.get("seed", 42)),
        )), 202
    except (TypeError, ValueError, RuntimeError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/interactive/load")
def api_interactive_load():
    try:
        payload = request.get_json(force=True) or {}
        return jsonify(lab.update_interactive_loads(payload.get("loads")))
    except (TypeError, ValueError, RuntimeError) as error:
        return jsonify({"error": str(error)}), 400


@app.post("/api/interactive/stop")
def api_interactive_stop():
    try:
        return jsonify(lab.stop_interactive())
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
