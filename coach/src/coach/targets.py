"""Reviewed per-site lesson metadata for real browser targets.

The PDF remains the authority for what the learner is taught. A manifest only
adds reviewed local evidence for *where* a quoted target exists and *how* the
coach can verify the page changed. Optional learning-design copy is also local,
reviewed curriculum metadata. Neither kind is generated from the DOM or an LLM.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlsplit

from coach.lesson import LearningDesign, LessonPlan, LessonStep, SuccessCheck


_BLOOM_LEVELS = {"remember", "understand", "apply", "analyze", "evaluate", "create"}


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
class ControlFunction:
    label: str
    function: str
    region: str = ""
    role: str = ""


@dataclass(frozen=True)
class VisionPolicy:
    allowed: bool = False
    overview_allowed: bool = False
    sensitive_selectors: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccessibilityPolicy:
    keyboard_repair_allowed: bool = False


@dataclass(frozen=True)
class ManifestStep:
    number: int
    target_label: str | None = None
    completion: SuccessCheck | None = None
    sensitivity: str = "normal"
    assist_click_allowed: bool = False


@dataclass(frozen=True)
class TargetManifest:
    origins: tuple[str, ...]
    steps: tuple[ManifestStep, ...]
    controls: tuple[ControlFunction, ...] = ()
    vision: VisionPolicy = VisionPolicy()
    accessibility: AccessibilityPolicy = AccessibilityPolicy()
    learning: LearningDesign | None = None

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
                    selector=str(completion.get("selector", "")),
                    path=str(completion.get("path", "")),
                )
            sensitivity = str(raw_step.get("sensitivity", "normal"))
            if sensitivity not in {"normal", "destructive"}:
                raise ValueError("manifest step sensitivity must be normal or destructive")
            steps.append(
                ManifestStep(
                    number=int(raw_step["number"]),
                    target_label=(str(raw_step["target_label"]).strip() if raw_step.get("target_label") else None),
                    completion=success,
                    sensitivity=sensitivity,
                    assist_click_allowed=_json_bool(raw_step, "assist_click_allowed", False),
                )
            )
        return cls(
            origins=origins,
            steps=tuple(steps),
            controls=_control_functions(raw.get("controls", [])),
            vision=_vision_policy(raw.get("vision")),
            accessibility=_accessibility_policy(raw.get("accessibility")),
            learning=_learning_design(raw.get("learning")),
        )

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
                    sensitivity=reviewed.sensitivity,
                    assist_click_allowed=reviewed.assist_click_allowed,
                )
            )
        return replace(
            plan,
            steps=tuple(updated),
            functions=tuple((item.label, item.function) for item in self.controls),
            control_hints=tuple((item.label, item.region, item.role) for item in self.controls),
            learning=self.learning or plan.learning,
        )


def _control_functions(raw_controls) -> tuple[ControlFunction, ...]:
    controls: list[ControlFunction] = []
    seen: set[str] = set()
    for raw_control in raw_controls:
        label = " ".join(str(raw_control.get("label", "")).split())
        function = " ".join(str(raw_control.get("function", "")).split())
        if not label or not function:
            raise ValueError("each control function needs a label and a function")
        key = label.casefold()
        if key in seen:
            raise ValueError(f"duplicate control function: {label}")
        seen.add(key)
        controls.append(
            ControlFunction(
                label=label,
                function=function,
                region=" ".join(str(raw_control.get("region", "")).split()),
                role=" ".join(str(raw_control.get("role", "")).split()),
            )
        )
    return tuple(controls)


def _vision_policy(raw) -> VisionPolicy:
    if raw is None:
        return VisionPolicy()
    if not isinstance(raw, dict):
        raise ValueError("vision policy must be an object")
    selectors = tuple(
        selector.strip()
        for value in raw.get("sensitive_selectors", [])
        if (selector := str(value).strip())
    )
    return VisionPolicy(
        allowed=_json_bool(raw, "allowed", False),
        overview_allowed=_json_bool(raw, "overview_allowed", False),
        sensitive_selectors=selectors,
    )


def _accessibility_policy(raw) -> AccessibilityPolicy:
    if raw is None:
        return AccessibilityPolicy()
    if not isinstance(raw, dict):
        raise ValueError("accessibility policy must be an object")
    return AccessibilityPolicy(
        keyboard_repair_allowed=_json_bool(raw, "keyboard_repair_allowed", False)
    )


def _learning_design(raw) -> LearningDesign | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("learning design must be an object")
    bloom_level = _clean_learning_text(raw.get("bloom_level", ""))
    if bloom_level and bloom_level not in _BLOOM_LEVELS:
        raise ValueError("learning bloom_level is not supported")
    evidence = raw.get("success_evidence", [])
    if not isinstance(evidence, list):
        raise ValueError("learning success_evidence must be a list")
    return LearningDesign(
        objective=_clean_learning_text(raw.get("objective", "")),
        bloom_level=bloom_level,
        authentic_scenario=_clean_learning_text(raw.get("authentic_scenario", "")),
        reflection_prompt=_clean_learning_text(raw.get("reflection_prompt", "")),
        concept_summary=_clean_learning_text(raw.get("concept_summary", "")),
        transfer_task=_clean_learning_text(raw.get("transfer_task", "")),
        success_evidence=tuple(
            cleaned for value in evidence if (cleaned := _clean_learning_text(value))
        ),
    )


def _clean_learning_text(value) -> str:
    text = " ".join(str(value).split())
    if len(text) > 500:
        raise ValueError("learning design text must be at most 500 characters")
    return text


def _json_bool(raw: dict, key: str, default: bool) -> bool:
    if key not in raw:
        return default
    value = raw[key]
    if type(value) is not bool:
        raise ValueError(f"{key} must be a JSON boolean")
    return value


def _origin_matches(origin: str, allowed: str) -> bool:
    if allowed.startswith("https://*."):
        suffix = allowed.removeprefix("https://*")
        return origin.endswith(suffix) and origin.startswith("https://")
    return origin == allowed
