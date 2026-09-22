from coach.dom_map import bind_steps
from coach.lesson import plan_from_pages
from coach.observer import Element, Observation, observation_from_raw
from coach.pdf_text import ONBOARDING_PAGES
from coach.privacy import EgressLog
from coach.cues import Box, Point
from coach.session import LearningSession


def _plan():
    return plan_from_pages(ONBOARDING_PAGES)


def _obs(**flags):
    return Observation(elements=(), cursor=None, focused_text="", flags=flags)


def test_citation_stays_on_the_quoted_sentence():
    session = LearningSession(_plan())
    session.on_user_text("bắt đầu học tạo bảng ca")
    speech = session.on_user_text("bước này trong tài liệu nói gì")[0]
    assert 'Mở mục "Tạo bảng".' in speech.text
    assert "Trang 1" in speech.text


def test_confirm_before_the_page_changes_does_not_advance():
    session = LearningSession(_plan())
    session.start()
    speech = session.on_user_text("tôi bấm rồi")[0]
    assert "chưa thấy" in speech.text.casefold()
    assert session.step_index == 0


def test_assist_focus_does_not_finish_the_step():
    focused = []
    clicked = []
    session = LearningSession(
        _plan(),
        focus=lambda label: focused.append(label) or True,
        click=lambda label: clicked.append(label) or True,
    )
    session.start()
    speech = session.on_user_text("bạn focus giúp")[0]
    assert focused == ["Tạo bảng"]
    assert clicked == []
    assert "Bạn tự bấm Enter" in speech.text
    assert session.step.success.met({"panel": "closed"}) is False

    session.on_user_text("bấm giúp")
    assert clicked == ["Tạo bảng"]
    assert session.step_index == 0


def test_observation_advances_only_when_the_page_matches():
    session = LearningSession(_plan())
    session.start()
    waiting = Observation(
        elements=(Element("Tạo bảng", "div", None, -1, Box(100, 100, 40, 20)),),
        cursor=Point(0, 110),
        focused_text="",
        flags={"panel": "closed", "columns": [], "saved": False},
    )
    cues = session.on_observation(waiting, now=0)
    assert session.step_index == 0
    assert any(speech.kind == "cue" for speech in cues)
    speeches = session.on_observation(_obs(panel="open"), now=1)
    assert session.step.target_label == "Thêm cột"
    assert any("Thêm cột" in speech.text for speech in speeches)


def test_open_questions_use_the_model_and_button_lines_stay_default():
    log = EgressLog()
    local = LearningSession(_plan(), egress=log)
    local.start()
    speech = local.on_user_text("không hiểu")[0]
    assert (
        speech.text
        == "Bước này là Tạo bảng. Dùng Tab hoặc screen reader để tới control. "
        "Nói đi nút nếu trang không có accessibility layer."
    )
    assert log.events[0].left_machine is False

    sent = []
    session = LearningSession(
        _plan(),
        egress=log,
        llm=lambda payload: sent.append(payload) or "Nói ngắn lại.",
    )
    session.start()
    answered = session.on_user_text("không hiểu")[0]
    assert answered.text == "Nói ngắn lại."
    assert sent[-1]["target_label"] == "Tạo bảng"
    assert set(sent[-1]) <= {
        "step_say",
        "target_label",
        "citation_quote",
        "direction",
        "user_text",
    }
    assert log.events[-1].left_machine is True
    assert "dom" not in log.events[-1].summary

    before = len(sent)
    session.note_bindings(bind_steps(session.plan, []))
    session.on_page(
        label="Tạo bảng",
        bump="",
        flags={"panel": "closed", "columns": [], "saved": False},
    )
    assert len(sent) == before


def test_coach_list_is_only_enabled_after_a_spoken_request():
    events = []
    session = LearningSession(
        _plan(),
        set_navigation=lambda enabled: events.append(enabled) or True,
    )
    session.start()
    assert events == []
    speech = session.on_user_text("đi nút")[0]
    assert events == [True]
    assert "Mũi tên đổi control" in speech.text
    speech = session.on_user_text("đọc")[0]
    assert events == [True, False]
    assert "Tab" in speech.text
    speech = session.on_user_text("dùng chuột")[0]
    assert session.navigation_mode == "mouse_cue"
    assert "chỉ nhắc khi bạn di chuyển chuột" in speech.text


def test_completed_lesson_does_not_repeat_completion_for_later_speech():
    session = LearningSession(_plan())
    session.start()
    session.step_index = len(session.plan.steps) - 1
    done = session._advance()
    assert done[0].text == "Xong bước 3. Bài học đã hoàn thành."
    assert session.done
    assert session.on_user_text("bạn đã xong bài này") == []


def test_a_failed_model_call_speaks_the_default_line():
    session = LearningSession(_plan(), llm=lambda _payload: (_ for _ in ()).throw(RuntimeError("down")))
    session.start()
    speech = session.on_user_text("tôi chưa rõ phải làm sao")[0]
    assert speech.text.startswith("Bước này là Tạo bảng.")


def test_a_held_direction_stays_quiet_until_the_confirm_gap():
    session = LearningSession(_plan())
    session.start()
    waiting = Observation(
        elements=(Element("Tạo bảng", "div", None, -1, Box(100, 100, 40, 20)),),
        cursor=Point(0, 110),
        focused_text="",
        flags={"panel": "closed", "columns": [], "saved": False},
    )
    first = session.on_observation(waiting, now=0)
    assert [speech.text for speech in first if speech.kind == "cue"] == ["Đưa chuột qua phải."]
    assert session.on_observation(waiting, now=1) == []
    confirm = session.on_observation(waiting, now=4)
    assert [speech.text for speech in confirm] == ["Qua phải."]

    upward = Observation(
        elements=waiting.elements,
        cursor=Point(120, 0),
        focused_text="",
        flags=waiting.flags,
    )
    changed = session.on_observation(upward, now=4.2)
    assert [speech.text for speech in changed] == ["Đưa chuột xuống dưới."]


def test_unlabeled_div_still_has_a_box():
    raw = {
        "cursor": {"x": 4, "y": 8},
        "focused_text": "",
        "elements": [
            {
                "text": "Tạo bảng",
                "tag": "div",
                "role": None,
                "tabIndex": -1,
                "x": 10,
                "y": 20,
                "width": 80,
                "height": 30,
            }
        ],
        "flags": {"panel": "closed", "columns": [], "saved": False},
    }
    observation = observation_from_raw(raw)
    element = observation.element_named("Tạo bảng")
    assert isinstance(element, Element)
    assert element.tag == "div"
    assert element.role is None
    assert element.box == Box(10, 20, 80, 30)
