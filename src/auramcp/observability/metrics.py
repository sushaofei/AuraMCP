from __future__ import annotations

from collections import defaultdict


class Metrics:
    def __init__(self) -> None:
        self.counters: dict[str, int] = defaultdict(int)
        self.latency_sum_ms: dict[str, float] = defaultdict(float)

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] += amount

    def observe_ms(self, name: str, value: float) -> None:
        self.counters[f"{name}_count"] += 1
        self.latency_sum_ms[name] += value

    def snapshot(self) -> dict[str, float | int]:
        payload: dict[str, float | int] = dict(self.counters)
        for name, total in self.latency_sum_ms.items():
            count = self.counters.get(f"{name}_count", 0)
            payload[f"{name}_avg_ms"] = total / count if count else 0.0
        return payload
