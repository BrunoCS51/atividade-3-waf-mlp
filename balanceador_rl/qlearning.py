"""Núcleo didático do balanceador com Q-Learning tabular, sem frameworks de ML."""

from __future__ import annotations

import random
from copy import deepcopy


STATES = ("carga_baixa", "carga_media", "carga_alta")
ACTIONS = ("node1", "node2", "node3")

ALPHA = 0.25
GAMMA = 0.85
EPSILON_START = 0.30
EPSILON_MIN = 0.02
EPSILON_DECAY = 0.995


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
