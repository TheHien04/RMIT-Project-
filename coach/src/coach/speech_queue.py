"""Priority and duplicate policy for speech before it reaches the TTS queue."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from coach.session import SpeechEvent


@dataclass(frozen=True)
class SpeechDecision:
    accepted: bool
    interrupt_current: bool = False


@dataclass
class SpeechQueuePolicy:
    dedupe_seconds: float = 2.0
    _seen: dict[str, float] = field(default_factory=dict)
    _current_priority: int | None = None
    _current_interruptible: bool = True
    _current_kind: str | None = None

    def prepare(
        self,
        event: SpeechEvent,
        *,
        now: float | None = None,
        allow_interrupt: bool = True,
    ) -> SpeechDecision:
        stamp = time.monotonic() if now is None else now
        previous = self._seen.get(event.dedupe_key)
        if previous is not None and stamp - previous < self.dedupe_seconds:
            return SpeechDecision(False)
        self._seen[event.dedupe_key] = stamp
        replaces_stale_focus = (
            event.kind == "place"
            and self._current_kind in {"place", "cue", "focus"}
            and self._current_interruptible
        )
        interrupt = (
            allow_interrupt
            and self._current_priority is not None
            and self._current_interruptible
            and (event.priority > self._current_priority or replaces_stale_focus)
        )
        if self._current_priority is None or allow_interrupt:
            self._current_priority = event.priority
            self._current_interruptible = event.interruptible
            self._current_kind = event.kind
        else:
            # Multiple utterances queued by one state transition are one
            # logical batch. They must not interrupt each other; retain the
            # strongest policy until playback drains.
            self._current_priority = max(self._current_priority, event.priority)
            self._current_interruptible = self._current_interruptible and event.interruptible
        self._expire(stamp)
        return SpeechDecision(True, interrupt)

    def finished(self) -> None:
        self._current_priority = None
        self._current_interruptible = True
        self._current_kind = None

    def _expire(self, now: float) -> None:
        cutoff = now - max(self.dedupe_seconds * 4, 10)
        self._seen = {key: stamp for key, stamp in self._seen.items() if stamp >= cutoff}
