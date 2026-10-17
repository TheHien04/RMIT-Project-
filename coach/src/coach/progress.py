"""Local, per-skill learning progress for adaptive coaching.

This store contains no transcript, DOM, URL, credential, or screenshot.  It is
deliberately separate from the accessibility runtime: learned proficiency may
reduce instructional speech, but it never disables keyboard access support.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from coach.lesson import LessonStep


class AssistanceLevel(str, Enum):
    ORIENTATION = "orientation"
    GUIDED = "guided"
    PRACTICE = "practice"
    ON_DEMAND = "on_demand"
    SILENT = "silent"


@dataclass
class SkillProgress:
    attempts: int = 0
    successful_without_hint: int = 0
    independent_success_streak: int = 0
    highest_hint_level: int = 0
    focus_loops: int = 0
    help_requests: int = 0
    last_success: float | None = None
    time_to_complete: float | None = None
    page_version: str = ""
    assistance_level: str = AssistanceLevel.ORIENTATION.value
    suggested_level: str = ""
    status: str = "not_started"
    completion_source: str = ""
    reflection_prompts: int = 0
    transfer_tasks_offered: int = 0


class ProgressStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._skills: dict[str, SkillProgress] = {}
        self._attempt_hints: dict[str, int] = {}
        self._attempt_started_at: dict[str, float] = {}
        if path is not None and path.is_file():
            self._load()

    @staticmethod
    def skill_key(module_title: str, step: LessonStep) -> str:
        target = step.target_label or f"step-{step.number}"
        return f"{module_title}::{step.number}::{target}"

    def level_for(self, key: str) -> AssistanceLevel:
        raw = self.get(key).assistance_level
        try:
            return AssistanceLevel(raw)
        except ValueError:
            return AssistanceLevel.ORIENTATION

    def recommended_level_for(self, key: str) -> AssistanceLevel:
        successes = self.get(key).independent_success_streak
        if successes == 0:
            return AssistanceLevel.ORIENTATION
        if successes == 1:
            return AssistanceLevel.GUIDED
        if successes == 2:
            return AssistanceLevel.PRACTICE
        return AssistanceLevel.ON_DEMAND

    def get(self, key: str) -> SkillProgress:
        return self._skills.setdefault(key, SkillProgress())

    def start_attempt(self, key: str, *, page_version: str) -> None:
        progress = self.get(key)
        if progress.page_version and progress.page_version != page_version:
            # A changed lesson/page contract lowers confidence without erasing
            # the learner's history.
            progress.successful_without_hint = max(0, progress.successful_without_hint - 1)
            progress.independent_success_streak = 0
            safer_level = self.recommended_level_for(key)
            if _level_index(safer_level) < _level_index(self.level_for(key)):
                progress.assistance_level = safer_level.value
            progress.suggested_level = ""
        progress.page_version = page_version
        progress.attempts += 1
        progress.status = "in_progress"
        progress.completion_source = ""
        self._attempt_hints[key] = 0
        self._attempt_started_at[key] = time.monotonic()
        self._save()

    def record_hint(self, key: str, level: int) -> None:
        progress = self.get(key)
        progress.help_requests += 1
        progress.highest_hint_level = max(progress.highest_hint_level, level)
        self._attempt_hints[key] = max(self._attempt_hints.get(key, 0), level)
        progress.independent_success_streak = 0
        self._save()

    def record_focus_loop(self, key: str) -> None:
        progress = self.get(key)
        progress.focus_loops += 1
        progress.independent_success_streak = 0
        # A loop is evidence that the attempt was not yet independent, even
        # when the learner did not explicitly ask for a hint.
        self._attempt_hints[key] = max(self._attempt_hints.get(key, 0), 1)
        self._save()

    def complete(self, key: str, *, source: str = "dom_verified") -> None:
        if source not in {"dom_verified", "user_confirmed"}:
            raise ValueError("completion source must be dom_verified or user_confirmed")
        progress = self.get(key)
        if source == "dom_verified" and self._attempt_hints.get(key, 0) == 0:
            progress.successful_without_hint += 1
            progress.independent_success_streak += 1
        else:
            progress.independent_success_streak = 0
        progress.last_success = time.time()
        progress.status = "completed"
        progress.completion_source = source
        started_at = self._attempt_started_at.pop(key, None)
        if started_at is not None:
            progress.time_to_complete = max(0.0, time.monotonic() - started_at)
        recommendation = self.recommended_level_for(key)
        if _level_index(recommendation) > _level_index(self.level_for(key)):
            progress.suggested_level = recommendation.value
        self._save()

    def record_learning_followup(self, key: str, *, reflection: bool, transfer: bool) -> None:
        progress = self.get(key)
        if reflection:
            progress.reflection_prompts += 1
        if transfer:
            progress.transfer_tasks_offered += 1
        self._save()

    def pause(self, key: str) -> None:
        progress = self.get(key)
        progress.status = "paused"
        progress.completion_source = ""
        self._save()

    def suggested_level_for(self, key: str) -> AssistanceLevel | None:
        raw = self.get(key).suggested_level
        try:
            return AssistanceLevel(raw) if raw else None
        except ValueError:
            return None

    def accept_level(self, key: str, level: AssistanceLevel) -> None:
        progress = self.get(key)
        progress.assistance_level = level.value
        progress.suggested_level = ""
        self._save()

    def decline_suggestion(self, key: str) -> None:
        self.get(key).suggested_level = ""
        self._save()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path else {}
            for key, value in raw.get("skills", {}).items():
                if isinstance(value, dict):
                    loaded = SkillProgress(
                        **{name: value[name] for name in SkillProgress.__dataclass_fields__ if name in value}
                    )
                    if "independent_success_streak" not in value:
                        loaded.independent_success_streak = loaded.successful_without_hint
                    self._skills[str(key)] = loaded
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            self._skills = {}

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 3, "skills": {key: asdict(value) for key, value in self._skills.items()}}
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)


def _level_index(level: AssistanceLevel) -> int:
    return list(AssistanceLevel).index(level)
