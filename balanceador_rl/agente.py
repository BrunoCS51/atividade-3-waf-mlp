"""Cliente de terminal para iniciar e acompanhar o agente exibido no painel."""

from __future__ import annotations

import argparse
import json
import os
import time

import requests


API_URL = os.environ.get("RL_AGENT_API_URL", "http://localhost:8091").rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Treina o balanceador Q-Learning pela API local")
    parser.add_argument("--episodios", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    response = requests.post(
        f"{API_URL}/api/train",
        json={"episodes": args.episodios, "seed": args.seed},
        timeout=10,
    )
    response.raise_for_status()
    previous = -1
    while True:
        status = requests.get(f"{API_URL}/api/status", timeout=5).json()
        job = status["training"]
        current = int(job["current_episode"])
        if current <= 5 or current == args.episodios or current // 25 != previous // 25:
            print(
                f"Episódio {current:03d}/{args.episodios} | "
                f"{job['percent']:6.2f}% | ε={job['epsilon']:.4f} | "
                f"timeouts={job['timeouts']} | {job['message']}"
            )
        previous = current
        if job["status"] not in {"queued", "running"}:
            if job["status"] != "completed":
                raise RuntimeError(job["message"])
            print("\nPolítica final:")
            print(json.dumps(status["policy"], ensure_ascii=False, indent=2))
            print("\nQ-Table:")
            print(json.dumps(status["q_table"], ensure_ascii=False, indent=2))
            break
        time.sleep(0.8)


if __name__ == "__main__":
    main()
