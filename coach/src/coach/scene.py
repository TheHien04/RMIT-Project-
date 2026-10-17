"""Small, privacy-bounded representation of the learner's current web page."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit

from coach.cues import Box


class SceneConfidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class SceneControl:
    label: str
    tag: str
    reason: str
    box: Box


@dataclass(frozen=True)
class PageScene:
    url: str
    title: str
    focused_label: str
    viewport: tuple[int, int]
    controls: tuple[SceneControl, ...]
    visible_probe_values: tuple[str, ...]
    confidence: SceneConfidence
    revision: int = 0
    screenshot: bytes | None = field(default=None, repr=False, compare=False)

    @property
    def path(self) -> str:
        return urlsplit(self.url).path

    def safe_summary(self, *, allowed_labels: tuple[str, ...] = ()) -> dict:
        """Return only reviewed page facts; never arbitrary DOM text."""

        approved = {label.casefold() for label in allowed_labels}
        return {
            "path": self.path,
            "focused_label": (
                self.focused_label[:160]
                if self.focused_label.casefold() in approved
                else ""
            ),
            "viewport": list(self.viewport),
            "controls": [
                {
                    "label": control.label[:160],
                    "tag": control.tag,
                    "reason": control.reason,
                    "box": {
                        "x": round(control.box.x),
                        "y": round(control.box.y),
                        "width": round(control.box.width),
                        "height": round(control.box.height),
                    },
                }
                for control in self.controls
                if control.label.casefold() in approved
            ],
            # Completion probes are local state-machine evidence. Vision does
            # not need them and must not receive page-derived values.
            "visible_probe_values": [],
            "confidence": self.confidence.value,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class VisionRequest:
    scene: PageScene
    question: str
    candidate_labels: tuple[str, ...]
    lesson_labels: tuple[str, ...]
    redaction_count: int
    crop: tuple[int, int, int, int] | None = None
