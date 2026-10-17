"""Deterministic pointer cues. These never call a language model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    LEFT = "qua trái"
    RIGHT = "qua phải"
    UP = "lên trên"
    DOWN = "xuống dưới"
    ARRIVED = "tới rồi"


# Closed phrases. Navigation speaks one of these and never waits on a model.
# A direction change gets the imperative. A held direction, much later, gets the short word.
CONFIRM_SECONDS = 4.0


def cue_line(direction: Direction, *, repeat: bool) -> str:
    if direction is Direction.ARRIVED:
        return "Tới rồi."
    words = direction.value
    if repeat:
        return words[0].upper() + words[1:] + "."
    return f"Đưa chuột {words}."


CUE_LINES = [
    cue_line(direction, repeat=False)
    for direction in Direction
    if direction is not Direction.ARRIVED
] + [
    cue_line(direction, repeat=True)
    for direction in Direction
    if direction is not Direction.ARRIVED
] + ["Tới rồi.", "Đưa chuột vào trang."]


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> Point:
        return Point(self.x + self.width / 2, self.y + self.height / 2)

    def contains(self, point: Point) -> bool:
        return (
            self.x <= point.x <= self.x + self.width
            and self.y <= point.y <= self.y + self.height
        )


def cue_for(cursor: Point, box: Box, *, arrive_px: float = 24) -> Direction:
    """Map a cursor and a target box to one spoken direction.

    Screen Y grows downward. Horizontal wins only when it is strictly larger
    than the vertical gap, so a tie is spoken as up or down.
    """

    if arrive_px < 0:
        raise ValueError("arrive_px must not be negative")
    if box.contains(cursor):
        return Direction.ARRIVED
    center = box.center
    dx = center.x - cursor.x
    dy = center.y - cursor.y
    if abs(dx) <= arrive_px and abs(dy) <= arrive_px:
        return Direction.ARRIVED
    if abs(dx) > abs(dy):
        return Direction.RIGHT if dx > 0 else Direction.LEFT
    return Direction.DOWN if dy > 0 else Direction.UP


class CueThrottle:
    """Drop cues that would talk over the previous one."""

    def __init__(self, interval_s: float = 0.8) -> None:
        if interval_s < 0:
            raise ValueError("interval_s must not be negative")
        self.interval_s = interval_s
        self._last_at: float | None = None

    def allow(self, now: float) -> bool:
        if self._last_at is not None and now - self._last_at < self.interval_s:
            return False
        self._last_at = now
        return True

    def reset(self) -> None:
        self._last_at = None
