"""Reviewed per-site lesson metadata for real browser targets.

The PDF remains the authority for what the learner is taught. A manifest only
adds reviewed local evidence for *where* a quoted target exists and *how* the
coach can verify the page changed. It is never generated from the DOM or an
LLM response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from coach.lesson import LessonPlan, LessonStep, SuccessCheck


@dataclass(frozen=True)
class BrowserTarget:
    cdp_url: str = ""
    allowed_origins: tuple[str, ...] = ()
    tab_title: str = ""
    navigation_mode: str = "native_focus"
    inject_navigation: bool = False
    agent_browser_bin: str = ""

    @property
    def external(self) -> bool:
        return bool(self.cdp_url)

    def permits(self, url: str) -> bool:
        if not self.allowed_origins:
            return not self.external
        parsed = urlsplit(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        return any(_origin_matches(origin, allowed) for allowed in self.allowed_origins)


@dataclass(frozen=True)
class ManifestStep:
    number: int
    target_label: str | None = None
    completion: SuccessCheck | None = None
    sensitivity: str = "normal"


@dataclass(frozen=True)
class TargetManifest:
    origins: tuple[str, ...]
    steps: tuple[ManifestStep, ...]

    @classmethod
    def load(cls, path: str | Path) -> "TargetManifest":
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        origins = tuple(str(value).rstrip("/") for value in raw.get("origins", []) if str(value).strip())
        if not origins:
            raise ValueError("target manifest must list at least one approved origin")
        steps: list[ManifestStep] = []
        for raw_step in raw.get("steps", []):
            completion = raw_step.get("completion")
            success = None
            if completion is not None:
                success = SuccessCheck(
                    kind=str(completion["kind"]),
                    value=str(completion.get("value", "")),
                )
            steps.append(
                ManifestStep(
                    number=int(raw_step["number"]),
                    target_label=(str(raw_step["target_label"]).strip() if raw_step.get("target_label") else None),
                    completion=success,
                    sensitivity=str(raw_step.get("sensitivity", "normal")),
                )
            )
        return cls(origins=origins, steps=tuple(steps))

    def apply(self, plan: LessonPlan) -> LessonPlan:
        by_number = {step.number: step for step in self.steps}
        updated: list[LessonStep] = []
        for step in plan.steps:
            reviewed = by_number.get(step.number)
            if reviewed is None:
                updated.append(step)
                continue
            label = reviewed.target_label or step.target_label
            if label and label not in step.citation.quote:
                raise ValueError(
                    f"manifest step {step.number} target must be copied from its PDF citation"
                )
            updated.append(
                replace(
                    step,
                    target_label=label,
                    needs_discovery=label is None,
                    success=reviewed.completion or step.success,
                )
            )
        return replace(plan, steps=tuple(updated))


def _origin_matches(origin: str, allowed: str) -> bool:
    if allowed.startswith("https://*."):
        suffix = allowed.removeprefix("https://*")
        return origin.endswith(suffix) and origin.startswith("https://")
    return origin == allowed
