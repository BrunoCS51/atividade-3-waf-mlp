"""Cliente de terminal para comparar Round-Robin e a política Q-Learning."""

from __future__ import annotations

import argparse
import json
import os

import requests


API_URL = os.environ.get("RL_AGENT_API_URL", "http://localhost:8091").rstrip("/")


def main() -> None:
    parser = argparse.ArgumentParser(description="Executa rajadas comparativas no laboratório RL")
    parser.add_argument("--requisicoes", type=int, default=60)
    parser.add_argument("--concorrencia", type=int, default=6)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    response = requests.post(
        f"{API_URL}/api/compare",
        json={
            "requests": args.requisicoes,
            "concurrency": args.concorrencia,
            "seed": args.seed,
        },
        timeout=120,
    )
    response.raise_for_status()
    result = response.json()
    print("=" * 72)
    print("ROUND-ROBIN × Q-LEARNING")
    print("=" * 72)
    for key, label in (("round_robin", "Round-Robin"), ("q_learning", "Q-Learning")):
        item = result[key]
        print(f"\n{label}")
        print(f"  Rotas: {json.dumps(item['routes'], ensure_ascii=False)}")
        print(f"  Latência média: {item['average_latency_ms']:.2f} ms")
        print(f"  P95: {item['p95_latency_ms']:.2f} ms")
        print(f"  < 100 ms: {item['under_100ms']}/{item['requests']}")
        print(f"  Timeouts: {item['timeouts']}/{item['requests']}")
        print(f"  Tempo total: {item['wall_seconds']:.2f} s")


if __name__ == "__main__":
    main()
