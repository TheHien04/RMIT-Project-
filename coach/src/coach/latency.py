"""Append-only latency traces without transcript or page content."""

from __future__ import annotations

import json
import time
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from coach.privacy import _write_private


@dataclass
class LatencyTrace:
    trace_id: str
    kind: str
    marks: dict[str, float] = field(default_factory=dict)

    def mark(self, name: str, at: float | None = None) -> None:
        self.marks[name] = time.monotonic() if at is None else at

    def durations_ms(self) -> dict[str, float]:
        origin = (
            self.marks.get("vad_stop")
            or self.marks.get("browser_event")
            or self.marks.get("vision_request")
        )
        if origin is None:
            return {}
        return {
            name: round((stamp - origin) * 1000, 2)
            for name, stamp in self.marks.items()
            if stamp >= origin and name not in {"vad_stop", "browser_event", "vision_request"}
        }


class LatencyLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write(self, trace: LatencyTrace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trace_id": trace.trace_id,
            "kind": trace.kind,
            "durations_ms": trace.durations_ms(),
        }
        _write_private(
            self.path,
            json.dumps(payload, ensure_ascii=False) + "\n",
            append=True,
        )


def summarize(values: list[float]) -> dict[str, float]:
    if not values:
        raise ValueError("latency sample is empty")
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "p50": round(statistics.median(ordered), 2),
        "p95": round(ordered[p95_index], 2),
        "max": round(ordered[-1], 2),
    }


def assert_slo(values: list[float], *, p95_limit_ms: float) -> dict[str, float]:
    summary = summarize(values)
    if summary["p95"] > p95_limit_ms:
        raise AssertionError(
            f"latency p95 {summary['p95']}ms exceeds {p95_limit_ms}ms"
        )
    return summary


_SLO_METRICS = {
    "voice": ("audio_started", 1500.0),
    "browser": ("audio_started", 250.0),
    "vision": ("guidance_ready", 3000.0),
}


def report_file(path: Path, *, kind: str, min_samples: int = 100) -> dict[str, float]:
    """Summarize one warm-run metric from the privacy-safe JSONL trace."""

    if kind not in _SLO_METRICS:
        raise ValueError(f"unknown latency kind: {kind}")
    metric, limit = _SLO_METRICS[kind]
    values: list[float] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            value = item.get("durations_ms", {}).get(metric)
            if item.get("kind") == kind and value is not None:
                values.append(float(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    if len(values) < min_samples:
        raise ValueError(
            f"{kind} needs at least {min_samples} samples; found {len(values)}"
        )
    result = assert_slo(values, p95_limit_ms=limit)
    return {"samples": len(values), "limit_ms": limit, **result}
