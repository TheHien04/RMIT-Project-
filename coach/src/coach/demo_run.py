"""Closed-loop lesson. Arrow and Enter are the person's keys, not the coach's."""

from __future__ import annotations

from coach.dom_map import PageControls, bind_steps
from coach.lesson import LessonPlan
from coach.privacy import EgressLog
from coach.session import LearningSession, Speech


def run_lesson(page, plan: LessonPlan, *, egress: EgressLog | None = None) -> list[Speech]:
    board = PageControls(page)
    board.install()
    board.set_navigation(True)
    log = egress or EgressLog()
    clicks: list[str] = []
    session = LearningSession(
        plan,
        egress=log,
        focus=lambda label: False,
        click=lambda label: clicks.append(label) or False,
        navigation_mode="coach_list",
    )
    speeches = session.on_user_text("bắt đầu học tạo bảng ca")
    speeches.extend(session.on_user_text("không hiểu"))
    asked = False
    for _ in range(24):
        if session.done:
            break
        detected = board.refresh()
        session.note_bindings(bind_steps(plan, detected))
        state = board.read()
        speeches.extend(session.on_page(label=state.label, bump=state.bump, flags=state.flags))
        if session.done:
            break
        if session.step_index == 1 and not asked:
            speeches.extend(session.on_user_text("bước này trong tài liệu nói gì"))
            asked = True
        if state.label == session.step.target_label:
            page.keyboard.press("Enter")
        else:
            page.keyboard.press("ArrowDown")
    if clicks:
        raise RuntimeError("practice mode clicked without an explicit request")
    if not session.done:
        raise RuntimeError("the person walked the list and the lesson did not finish")
    return speeches
