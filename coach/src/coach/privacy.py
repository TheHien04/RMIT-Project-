"""Record anything that could leave the machine. Vision is off unless asked."""

from __future__ import annotations

import json
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


ALLOWED_LLM_KEYS = frozenset(
    {"step_say", "target_label", "citation_quote", "direction", "user_text"}
)


@dataclass(frozen=True)
class EgressEvent:
    kind: str
    left_machine: bool
    summary: dict[str, Any]


@dataclass
class EgressLog:
    events: list[EgressEvent] = field(default_factory=list)

    def record(self, kind: str, summary: Mapping[str, Any], *, left_machine: bool) -> EgressEvent:
        event = EgressEvent(
            kind=kind,
            left_machine=left_machine,
            summary=_egress_summary(summary),
        )
        self.events.append(event)
        return event

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            json.dumps(
                {
                    "kind": event.kind,
                    "left_machine": event.left_machine,
                    "summary": event.summary,
                },
                ensure_ascii=False,
            )
            for event in self.events
        ]
        _write_private(path, "\n".join(lines) + ("\n" if lines else ""), append=False)


@dataclass
class BrowserAudit:
    """Local, redacted record of browser attachment and explicit assistance."""

    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, kind: str, **summary: Any) -> None:
        redacted = {
            key: _redact(value)
            for key, value in summary.items()
            if key not in {"html", "dom", "cookie", "token", "password", "screenshot"}
        }
        self.events.append({"kind": kind, "summary": redacted})

    def write_jsonl(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in self.events)
        if text:
            _write_private(path, text, append=True)


def _egress_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Keep audit value without persisting speech or prompt content."""

    safe: dict[str, Any] = {}
    for key, value in summary.items():
        if key in {"html", "dom", "cookie", "token", "password", "screenshot"}:
            continue
        if key in {"user_text", "step_say", "citation_quote"}:
            text = str(value or "")
            safe[f"{key}_chars"] = len(text)
            safe[f"{key}_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            continue
        safe[key] = _redact(value)
    return safe


def _write_private(path: Path, text: str, *, append: bool) -> None:
    """Create privacy logs as owner-only files, including existing paths."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if append else os.O_TRUNC)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a" if append else "w", encoding="utf-8") as handle:
            descriptor = -1
            handle.write(text)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        lowered = value.casefold()
        if any(word in lowered for word in ("token=", "apikey=", "api_key=", "password=")):
            return "[redacted]"
        return value[:300]
    return value


def llm_payload(
    *,
    step_say: str,
    target_label: str | None,
    citation_quote: str,
    direction: str | None,
    user_text: str,
) -> dict[str, Any]:
    payload = {
        "step_say": step_say,
        "target_label": target_label,
        "citation_quote": citation_quote,
        "direction": direction,
        "user_text": user_text,
    }
    extra = set(payload) - ALLOWED_LLM_KEYS
    if extra:
        raise ValueError(f"LLM payload has forbidden keys: {sorted(extra)}")
    return payload


def consider_icon(
    png: bytes,
    *,
    vision_enabled: bool,
    egress: EgressLog,
) -> bool:
    """Return whether a screenshot may be sent out. Default is no."""

    if not png:
        raise ValueError("png must not be empty")
    if not vision_enabled:
        egress.record(
            "vision",
            {"bytes": len(png), "reason": "vision disabled"},
            left_machine=False,
        )
        return False
    egress.record("vision", {"bytes": len(png)}, left_machine=True)
    return True
