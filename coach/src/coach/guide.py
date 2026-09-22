"""Headed lesson: the person walks the clickable list and presses Enter."""

from __future__ import annotations

import select
import sys
import threading
import time
from collections.abc import Iterator

from coach.dom_map import PageControls, bind_steps
from coach.lesson import LessonPlan
from coach.observer import PageObserver
from coach.privacy import EgressLog
from coach.session import LearningSession, Speech
from coach.speaker import EdgeSpeaker, Speaker

KEY_LINES = (
    "Mũi tên để đi. Enter để bấm.",
    "Hết danh sách.",
    "Đầu danh sách.",
)


def run_guided(
    *,
    page,
    plan: LessonPlan,
    speaker: Speaker,
    egress: EgressLog,
    llm=None,
    vision_enabled: bool = False,
    poll_seconds: float = 0.35,
    lines: Iterator[str] | None = None,
) -> list[Speech]:
    board = PageControls(page)
    board.install()
    board.set_navigation(True)
    observer = PageObserver(page)
    session = LearningSession(
        plan,
        egress=egress,
        focus=board.move_to,
        click=observer.click_label,
        navigation_mode="coach_list",
        llm=llm,
        vision_enabled=vision_enabled,
    )
    spoken: list[Speech] = []

    def speak(items: list[Speech]) -> None:
        for item in items:
            speaker.say(item.text, egress)
            spoken.append(item)

    speak(session.on_user_text("bắt đầu học tạo bảng ca"))
    if isinstance(speaker, EdgeSpeaker):
        threading.Thread(
            target=speaker.warm,
            args=(list(KEY_LINES), egress),
            name="coach-cue-cache",
            daemon=True,
        ).start()
    source = lines if lines is not None else _stdin_lines(poll_seconds)
    for line in source:
        if session.done:
            break
        if line:
            speak(session.on_user_text(line))
        if session.done:
            break
        detected = board.refresh()
        session.note_bindings(bind_steps(plan, detected))
        state = board.read()
        speak(session.on_page(label=state.label, bump=state.bump, flags=state.flags))
    return spoken


def _stdin_lines(poll_seconds: float) -> Iterator[str]:
    while True:
        ready, _, _ = select.select([sys.stdin], [], [], poll_seconds)
        if not ready:
            yield ""
            continue
        line = sys.stdin.readline()
        if line == "":
            return
        yield line.strip()
