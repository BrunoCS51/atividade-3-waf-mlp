"""Núcleo didático do balanceador com Q-Learning tabular, sem frameworks de ML."""

from __future__ import annotations

import random
import math
from copy import deepcopy


STATES = ("carga_baixa", "carga_media", "carga_alta")
ACTIONS = ("node1", "node2", "node3")

ALPHA = 0.25
GAMMA = 0.85
EPSILON_START = 0.30
EPSILON_MIN = 0.02
EPSILON_DECAY = 0.995

NODE_CAPACITY = {"node1": 1.00, "node2": 0.25, "node3": 0.05}
NODE_BASE_LATENCY_MS = {"node1": 8.0, "node2": 35.0, "node3": 90.0}
NODE_LOAD_FACTOR_MS = {"node1": 0.72, "node2": 0.78, "node3": 0.84}
NODE_MAX_CONCURRENT = {"node1": 8, "node2": 2, "node3": 1}
LOAD_DECAY_PER_SECOND = 6.0
REQUEST_LOAD_IMPACT = 1.5
STATE_BASE_LOAD = {"carga_baixa": 20.0, "carga_media": 50.0, "carga_alta": 70.0}


def new_q_table() -> dict[str, dict[str, float]]:
    return {state: {action: 0.0 for action in ACTIONS} for state in STATES}


def select_action(
    q_table: dict[str, dict[str, float]],
    state: str,
    epsilon: float,
    rng: random.Random,
) -> tuple[str, str]:
    """Política ε-greedy: explora com ε; caso contrário usa argmax Q(s,a)."""
    if state not in q_table:
        raise ValueError("Estado desconhecido")
    if not 0.0 <= epsilon <= 1.0:
        raise ValueError("Epsilon deve estar entre 0 e 1")
    if rng.random() < epsilon:
        return rng.choice(ACTIONS), "exploracao"
    values = q_table[state]
    maximum = max(values.values())
    best = [action for action, value in values.items() if value == maximum]
    return rng.choice(best), "explotacao"


def calculate_reward(latency_ms: float, timed_out: bool) -> float:
    """Converte a latência real na recompensa definida pelo professor."""
    if timed_out:
        return -100.0
    if latency_ms < 100.0:
        return 20.0
    if latency_ms < 250.0:
        return 2.0
    return -15.0


def update_q_table(
    q_table: dict[str, dict[str, float]],
    state: str,
    action: str,
    reward: float,
    next_state: str,
    alpha: float = ALPHA,
    gamma: float = GAMMA,
) -> float:
    """Aplica Bellman somente à célula Q(state, action) executada."""
    if state not in q_table or next_state not in q_table or action not in q_table[state]:
        raise ValueError("Transição inválida")
    current_q = q_table[state][action]
    max_future_q = max(q_table[next_state].values())
    td_target = float(reward) + gamma * max_future_q
    td_error = td_target - current_q
    new_q = current_q + alpha * td_error
    q_table[state][action] = new_q
    return new_q


def policy(q_table: dict[str, dict[str, float]]) -> dict[str, str]:
    return {
        state: max(actions, key=actions.get)
        for state, actions in q_table.items()
    }


def state_from_loads(loads: dict[str, float]) -> str:
    """Discretiza a carga média dos três nós no espaço de estados do agente."""
    if set(loads) != set(ACTIONS):
        raise ValueError("Informe a carga dos três servidores")
    average = sum(float(loads[action]) for action in ACTIONS) / len(ACTIONS)
    if not all(0.0 <= float(loads[action]) <= 100.0 for action in ACTIONS):
        raise ValueError("As cargas devem estar entre 0 e 100")
    if average < 34.0:
        return "carga_baixa"
    if average < 67.0:
        return "carga_media"
    return "carga_alta"


def node_telemetry(loads: dict[str, float], active_requests: dict[str, int]) -> dict[str, dict]:
    """Combina carga-base, capacidade e requisições em voo."""
    if set(loads) != set(ACTIONS) or set(active_requests) != set(ACTIONS):
        raise ValueError("Informe carga e concorrência dos três servidores")
    result = {}
    for node in ACTIONS:
        base_load = float(loads[node])
        active = int(active_requests[node])
        if not 0.0 <= base_load <= 100.0 or active < 0:
            raise ValueError("Carga ou concorrência inválida")
        cpu = min(100.0, base_load + active * (10.0 / NODE_CAPACITY[node]))
        result[node] = {
            "base_load": base_load,
            "cpu": cpu,
            "active_requests": active,
            "max_concurrent": NODE_MAX_CONCURRENT[node],
            "saturated": cpu >= 90.0 or active >= NODE_MAX_CONCURRENT[node],
        }
    return result


def decay_loads(loads: dict[str, float], elapsed_seconds: float) -> dict[str, float]:
    """Libera gradualmente a carga residual conforme o tempo de processamento passa."""
    if set(loads) != set(ACTIONS) or elapsed_seconds < 0:
        raise ValueError("Cargas ou intervalo de tempo inválidos")
    released = LOAD_DECAY_PER_SECOND * float(elapsed_seconds)
    return {node: max(0.0, float(loads[node]) - released) for node in ACTIONS}


def add_request_load(loads: dict[str, float], node: str) -> dict[str, float]:
    """Acrescenta ao nó o trabalho residual de uma nova requisição recebida."""
    if set(loads) != set(ACTIONS) or node not in ACTIONS:
        raise ValueError("Carga ou servidor inválido")
    result = {action: float(loads[action]) for action in ACTIONS}
    # O efeito residual cresce nos nós menores, mas pela raiz da capacidade para
    # evitar saltos artificiais de dezenas de pontos em uma única requisição.
    result[node] = min(100.0, result[node] + REQUEST_LOAD_IMPACT / math.sqrt(NODE_CAPACITY[node]))
    return result


def select_operational_action(q_table, state, epsilon, telemetry, rng):
    """ε-greedy com proteção operacional baseada na telemetria instantânea."""
    if state not in q_table or set(telemetry) != set(ACTIONS):
        raise ValueError("Estado ou telemetria inválida")
    if not 0.0 <= epsilon <= 1.0:
        raise ValueError("Epsilon deve estar entre 0 e 1")
    available = [node for node in ACTIONS if not telemetry[node]["saturated"]] or list(ACTIONS)
    q_values = q_table[state]
    q_min, q_max = min(q_values.values()), max(q_values.values())
    # A vantagem aprendida é normalizada para não dominar indefinidamente sinais
    # operacionais em outra escala. A ordenação da Q-Table é preservada.
    learned_scores = {
        node: (10.0 * (q_values[node] - q_min) / (q_max - q_min) if q_max != q_min else 0.0)
        for node in ACTIONS
    }
    scores = {
        node: learned_scores[node]
        - 0.20 * float(telemetry[node]["cpu"])
        - 3.00 * int(telemetry[node]["active_requests"])
        - (40.0 if telemetry[node]["saturated"] else 0.0)
        for node in ACTIONS
    }
    if rng.random() < epsilon:
        return rng.choice(available), "exploracao", scores
    maximum = max(scores[node] for node in available)
    best = [node for node in available if scores[node] == maximum]
    return rng.choice(best), "explotacao", scores


def calculate_operational_reward(latency_ms, timed_out, cpu, active_requests, saturated):
    """Preserva a recompensa de latência e acrescenta penalidades operacionais."""
    latency_reward = calculate_reward(latency_ms, timed_out)
    cpu_penalty = max(0.0, float(cpu) - 70.0) * 0.25
    concurrency_penalty = max(0, int(active_requests) - 1) * 1.5
    saturation_penalty = 25.0 if saturated else 0.0
    return {
        "total": latency_reward - cpu_penalty - concurrency_penalty - saturation_penalty,
        "latency_reward": latency_reward,
        "cpu_penalty": cpu_penalty,
        "concurrency_penalty": concurrency_penalty,
        "saturation_penalty": saturation_penalty,
    }


def load_wait_ms(node: str, load_percentage: float, active_requests: int = 1) -> float:
    """Transforma carga e capacidade do nó em atraso aplicado ao HTTP real."""
    if node not in ACTIONS:
        raise ValueError("Servidor desconhecido")
    load = float(load_percentage)
    if not 0.0 <= load <= 100.0:
        raise ValueError("Carga deve estar entre 0 e 100")
    active = int(active_requests)
    if active < 1:
        raise ValueError("Deve existir ao menos uma requisição ativa")
    concurrency_delay = (max(0, active - 1) ** 2) * (7.0 / NODE_CAPACITY[node])
    saturation_delay = 180.0 if load >= 90.0 or active >= NODE_MAX_CONCURRENT[node] else 0.0
    return NODE_BASE_LATENCY_MS[node] + load * NODE_LOAD_FACTOR_MS[node] + concurrency_delay + saturation_delay


def safe_q_table(value) -> dict[str, dict[str, float]]:
    """Valida uma Q-Table persistida antes de reutilizá-la."""
    if not isinstance(value, dict) or set(value) != set(STATES):
        raise ValueError("Q-Table persistida inválida")
    result = new_q_table()
    for state in STATES:
        if not isinstance(value[state], dict) or set(value[state]) != set(ACTIONS):
            raise ValueError("Ações persistidas inválidas")
        for action in ACTIONS:
            result[state][action] = float(value[state][action])
    return deepcopy(result)
