import pytest

from coach.cues import Box
from coach.dom_map import DetectedControl, bind_steps, prefer_leaves, resolve
from coach.lesson import plan_from_pages
from coach.pdf_text import ONBOARDING_PAGES
from coach.session import LearningSession


def _control(text: str, *, x: float = 0, y: float = 0, reason: str = "click-listener") -> DetectedControl:
    return DetectedControl(text, "div", reason, Box(x, y, 40, 20))


def test_binding_matches_visible_text_and_refuses_a_made_up_choice():
    plan = plan_from_pages(ONBOARDING_PAGES)
    create = _control("Tạo bảng", y=0)
    duplicate_a = _control("Lưu bảng", y=20)
    duplicate_b = _control("Lưu bảng", y=40)
    bindings = bind_steps(plan, [duplicate_b, create, duplicate_a, _control("Thêm cột", y=10)])
    by_step = {binding.step_number: binding for binding in bindings}
    assert by_step[1].status == "bound"
    assert by_step[1].controls == (create,)
    assert by_step[2].status == "bound"
    assert by_step[3].status == "ambiguous"
    assert [control.box.y for control in by_step[3].controls] == [20, 40]
    with pytest.raises(ValueError):
        resolve(by_step[3], _control("Nút bịa"))
    chosen = resolve(by_step[3], duplicate_a)
    assert chosen.status == "bound"
    assert chosen.controls == (duplicate_a,)


def test_a_wrapping_box_is_not_its_own_button():
    parent = DetectedControl("Tạo bảng Thêm cột", "div", "click-listener", Box(0, 0, 200, 80))
    child = _control("Tạo bảng", x=10, y=10)
    assert prefer_leaves((parent, child)) == (child,)


def test_the_person_must_move_before_enter_is_spoken():
    session = LearningSession(plan_from_pages(ONBOARDING_PAGES))
    session.start()
    session.note_bindings(bind_steps(session.plan, [_control("Tạo bảng"), _control("Thêm cột", y=30)]))
    flags = {"panel": "closed", "columns": [], "saved": False}
    assert session.on_page(label="", bump="", flags=flags) == []
    heard = session.on_page(label="Thêm cột", bump="", flags=flags)
    assert heard[0].text == "Thêm cột."
    assert session.on_page(label="Thêm cột", bump="", flags=flags) == []
    hit = session.on_page(label="Tạo bảng", bump="", flags=flags)
    assert hit[0].text == "Tạo bảng. Enter."
    opened = session.on_page(label="Tạo bảng", bump="", flags={**flags, "panel": "open"})
    assert session.step.target_label == "Thêm cột"
    assert "Enter" not in opened[-1].text
    stayed = session.on_page(label="Tạo bảng", bump="", flags={**flags, "panel": "open"})
    assert stayed == []
