from dataclasses import replace

from coach.dom_map import DetectedControl, bind_steps
from coach.lesson import LearningDesign, plan_from_pages
from coach.observer import Element, Observation, observation_from_raw
from coach.pdf_text import ONBOARDING_PAGES
from coach.privacy import EgressLog
from coach.progress import AssistanceLevel, ProgressStore
from coach.cues import Box, Point
from coach.session import LearningSession
from coach.scene import PageScene, SceneConfidence
from coach.vision import VisionGuidance


def _plan():
    return plan_from_pages(ONBOARDING_PAGES)


def _obs(**flags):
    return Observation(elements=(), cursor=None, focused_text="", flags=flags)


def test_a_configured_function_is_only_read_on_demand():
    plan = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".'])
    session = LearningSession(
        replace(
            plan,
            functions=(
                (
                    "Table Editor",
                    "Nơi xem và sửa dữ liệu trong bảng.",
                ),
                (
                    "Edge Functions",
                    "Nơi viết hàm chạy trên máy chủ Supabase.",
                ),
            ),
        )
    )
    session.start()
    session.note_bindings(
        bind_steps(session.plan, [DetectedControl("Table Editor", "a", "native", Box(0, 0, 32, 32))])
    )
    heard = session.on_page(label="Table Editor", bump="", flags={})
    assert heard[0].text == "Table Editor. Enter."
    other = session.on_page(label="Edge Functions", bump="", flags={})
    assert other == []
    described = session.on_user_text("cái này là gì")
    assert described[0].text == "Edge Functions. Nơi viết hàm chạy trên máy chủ Supabase."
    plain = session.on_page(label="Database", bump="", flags={})
    assert plain == []


def test_focus_speech_reads_each_new_control_and_marks_the_target():
    plan = plan_from_pages(['Bài\nBước 1. Mở "Create a table".'])
    session = LearningSession(plan, speech_policy="focus")
    session.start()
    session.note_bindings(
        bind_steps(
            session.plan,
            [
                DetectedControl("SQL Editor", "a", "native", Box(0, 0, 32, 32)),
                DetectedControl("Database", "a", "native", Box(0, 40, 32, 32)),
                DetectedControl("Create a table", "div", "role", Box(0, 80, 32, 32)),
            ],
        )
    )

    assert session.on_page(label="SQL Editor", bump="", flags={})[0].text == "SQL Editor."
    assert session.on_page(label="Database", bump="", flags={})[0].text == "Database."
    target = session.on_page(label="Create a table", bump="", flags={})
    assert target[0].text == "Đã tới Create a table. Nhấn Enter."
    assert session.on_page(label="Create a table", bump="", flags={}) == []


def test_focus_speech_tells_the_learner_what_to_type_in_a_target_input():
    plan = plan_from_pages(
        ['Bài\nBước 1. Tại ô "Name", nhập coach_demo_tasks.\n'
         '[xong: đã nhập giá trị "coach_demo_tasks"]']
    )
    session = LearningSession(plan, speech_policy="focus")
    session.start()
    session.note_bindings(
        bind_steps(plan, [DetectedControl("Name", "input", "native", Box(0, 0, 100, 30))])
    )
    speech = session.on_page(label="Name", bump="", flags={})
    assert speech[0].text == "Đã tới Name. Nhập coach_demo_tasks, rồi nhấn Tab."
    assert not session.done
    session.on_page(label="Name", bump="", flags={"input_values": ["coach_demo_tasks"]})
    assert session.done


def test_focus_speech_explains_create_table_column_controls():
    plan = plan_from_pages(['Bài\nBước 1. Mở "Save".'])
    session = LearningSession(plan, speech_policy="focus")
    session.start()

    type_line = session.on_page(label="Type, hiện tại int8", bump="", flags={})[0].text
    assert "mũi tên lên xuống" in type_line
    option_line = session.on_page(
        label="Type option, int4 Signed four-byte integer", bump="", flags={}
    )[0].text
    assert "nhấn Enter để chọn" in option_line
    primary = session.on_page(label="Primary, chưa chọn", bump="", flags={})[0].text
    assert primary == "Primary, chưa chọn. Nhấn Enter để chọn."
    column_name = session.on_page(label="Column name", bump="", flags={})[0].text
    assert column_name == "Column name. Nhập tên cột, rồi nhấn Tab."


def test_vision_requires_per_session_consent_and_never_advances():
    session = LearningSession(_plan(), vision_enabled=True)
    session.start()
    notice = session.on_user_text("mô tả trang")
    assert notice[0].kind == "vision_notice"
    assert "Ảnh không được lưu" in notice[0].text
    request = session.on_user_text("đồng ý")
    assert request[0].kind == "vision_request"
    answer = session.on_vision_guidance(
        VisionGuidance("Trang Supabase.", "Tạo bảng", "Ở thanh bên.", "left", 0.9, False, ())
    )
    assert answer[0].kind == "vision"
    assert session.step_index == 0


def test_vision_is_denied_for_destructive_steps_even_after_consent():
    plan = _plan()
    destructive = replace(plan.steps[0], sensitivity="destructive")
    session = LearningSession(
        replace(plan, steps=(destructive, *plan.steps[1:])),
        vision_enabled=True,
    )
    session.start()
    denied = session.on_user_text("mô tả trang")
    assert denied[0].kind == "vision_notice"
    assert "không gửi ảnh" in denied[0].text
    assert session.on_user_text("đồng ý")[0].kind != "vision_request"


def test_vision_decline_keeps_the_session_dom_only():
    session = LearningSession(_plan(), vision_enabled=True)
    session.start()
    session.on_user_text("mô tả trang")
    declined = session.on_user_text("không gửi ảnh")
    assert "DOM trên máy" in declined[0].text
    assert session.on_user_text("mô tả trang")[0].kind == "vision_notice"


def test_declined_automatic_vision_fallback_does_not_repeat_each_poll():
    session = LearningSession(_plan(), vision_enabled=True)
    session.start()
    empty = bind_steps(session.plan, [])
    session.note_bindings(empty)
    session.note_bindings(empty)
    assert session.on_page(label="", bump="", flags={})[0].kind == "vision_notice"
    session.on_user_text("không gửi ảnh")
    first_dom_fallback = session.on_page(label="", bump="", flags={})
    assert any("không thấy" in item.text for item in first_dom_fallback)
    assert session.on_page(label="", bump="", flags={}) == []


def test_page_version_includes_the_reviewed_completion_selector():
    plan = _plan()
    first = plan.steps[0]
    one = LearningSession(
        replace(
            plan,
            steps=(
                replace(first, success=replace(first.success, selector="#create-one")),
                *plan.steps[1:],
            ),
        )
    )
    two = LearningSession(
        replace(
            plan,
            steps=(
                replace(first, success=replace(first.success, selector="#create-two")),
                *plan.steps[1:],
            ),
        )
    )
    assert one._page_version() != two._page_version()


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


def test_stop_guidance_is_not_treated_as_completion():
    store = ProgressStore()
    session = LearningSession(_plan(), progress=store)
    session.start()

    speech = session.on_user_text("dừng hướng dẫn")

    assert session.stopped
    assert not session.done
    assert session.finished
    assert "chưa hoàn thành" in speech[0].text
    progress = store.get(session._skill_key())
    assert progress.status == "paused"
    assert progress.completion_source == ""


def test_step_completion_requires_explicit_confirmation_when_dom_does_not_match():
    store = ProgressStore()
    session = LearningSession(_plan(), progress=store)
    session.start()

    requested = session.on_user_text("xong bước này")
    assert "tôi xác nhận xong bước này" in requested[0].text
    assert session.step_index == 0

    unrelated = session.on_user_text("ừ")
    assert "đang chờ xác nhận" in unrelated[0].text
    cancelled = session.on_user_text("tiếp tục")
    assert "tiếp tục bài học" in cancelled[0].text
    assert session.step_index == 0


def test_user_can_explicitly_confirm_a_step_without_dom_evidence():
    store = ProgressStore()
    session = LearningSession(_plan(), progress=store)
    session.start()
    first_key = session._skill_key()

    session.on_user_text("xong bước này")
    speech = session.on_user_text("tôi xác nhận xong bước này")

    assert session.step_index == 1
    assert speech[0].text == "Xong bước 1."
    progress = store.get(first_key)
    assert progress.status == "completed"
    assert progress.completion_source == "user_confirmed"
    assert progress.successful_without_hint == 0


def test_step_completion_advances_immediately_when_dom_matches():
    store = ProgressStore()
    session = LearningSession(_plan(), progress=store)
    session.start()
    first_key = session._skill_key()
    session.on_page(label="", bump="", flags={"panel": "open"})

    assert session.step_index == 1
    assert store.get(first_key).completion_source == "dom_verified"


def test_whole_lesson_completion_has_a_separate_explicit_confirmation():
    store = ProgressStore()
    session = LearningSession(_plan(), progress=store)
    session.start()

    requested = session.on_user_text("tôi đã hoàn thành bài học")
    assert "tôi xác nhận hoàn thành bài học" in requested[0].text
    assert not session.done

    speech = session.on_user_text("tôi xác nhận hoàn thành bài học")
    assert session.done
    assert session.finished
    assert "chưa được DOM xác minh" in speech[0].text
    for step in session.plan.steps:
        key = ProgressStore.skill_key(session.plan.title, step)
        progress = store.get(key)
        assert progress.status == "completed"
        assert progress.completion_source == "user_confirmed"
        assert progress.successful_without_hint == 0


def test_assist_focus_does_not_finish_the_step():
    focused = []
    clicked = []
    plan = _plan()
    plan = replace(plan, steps=(replace(plan.steps[0], assist_click_allowed=True), *plan.steps[1:]))
    session = LearningSession(
        plan,
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


def test_destructive_step_never_allows_voice_synthetic_click():
    clicked = []
    plan = _plan()
    plan = replace(
        plan,
        steps=(replace(plan.steps[0], sensitivity="destructive"), *plan.steps[1:]),
    )
    session = LearningSession(plan, click=lambda label: clicked.append(label) or True)
    session.start()

    speech = session.on_user_text("bấm giúp")

    assert clicked == []
    assert speech[0].kind == "safety"
    assert "không bấm hộ" in speech[0].text


def test_unreviewed_step_denies_voice_synthetic_click_by_default():
    clicked = []
    session = LearningSession(_plan(), click=lambda label: clicked.append(label) or True)
    session.start()

    speech = session.on_user_text("bấm giúp")

    assert clicked == []
    assert speech[0].kind == "safety"
    assert "chưa cấp quyền" in speech[0].text


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
        == "Bước này là Tạo bảng. Dùng Tab hoặc screen reader để đi qua các nút và liên kết. "
        "Khi nghe đúng mục, nhấn Enter. Nếu bị kẹt, nói mở danh sách điều khiển."
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
    assert "Bạn có đồng ý" in answered.text
    answered = session.on_user_text("đồng ý")[0]
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
    assert "Mũi tên đổi nút hoặc liên kết" in speech.text
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
    session.on_user_text("tôi chưa rõ phải làm sao")
    speech = session.on_user_text("đồng ý")[0]
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


def test_open_answer_streams_checked_clauses_before_completion():
    class FakeLLM:
        def stream(self, payload):
            assert payload["target_label"] == "Tạo bảng"
            yield "Đi tới Tạo bảng."
            yield "Sau đó nhấn Enter."

    log = EgressLog()
    session = LearningSession(_plan(), llm=FakeLLM(), egress=log, defer_llm=True)
    session.start()
    notice = session.on_user_text("giải thích giúp")[0]
    assert "Bạn có đồng ý" in notice.text
    request = session.on_user_text("đồng ý")[0]
    assert request.kind == "llm_request"
    clauses = list(session.stream_llm(request.text))
    assert [item.text for item in clauses] == [
        "Đi tới Tạo bảng.",
        "Sau đó nhấn Enter.",
    ]
    assert log.events[-1].left_machine is True


def test_cloud_answer_decline_stays_local_for_the_session():
    sent = []
    log = EgressLog()
    session = LearningSession(
        _plan(),
        llm=lambda payload: sent.append(payload) or "cloud",
        egress=log,
    )
    session.start()
    assert "Bạn có đồng ý" in session.on_user_text("giải thích giúp")[0].text

    declined = session.on_user_text("không gửi")
    later = session.on_user_text("giải thích lại")

    assert sent == []
    assert any("không rời máy" in item.text for item in declined)
    assert later[0].text.startswith("Bước này là")
    assert log.events[-1].left_machine is False


def test_adaptive_coaching_fades_but_stays_available_on_demand():
    store = ProgressStore()
    first = LearningSession(_plan(), progress=store, assistance_level="adaptive")
    first.start()
    first.on_page(label="", bump="", flags={"panel": "open"})

    expected = ("chỉ nhắc mục tiêu", "tự luyện", "chỉ hướng dẫn khi bạn hỏi")
    session = first
    for index, proposal in enumerate(expected):
        session = LearningSession(_plan(), progress=store, assistance_level="adaptive")
        opening = session.start()
        assert proposal in opening[0].text
        accepted = session.on_user_text("đồng ý")
        if index < len(expected) - 1:
            session.on_page(label="", bump="", flags={"panel": "open"})

    assert any("chỉ hướng dẫn khi bạn hỏi" in item.text for item in accepted)
    assert store.level_for(session._skill_key()) is AssistanceLevel.ON_DEMAND
    hint = session.on_user_text("cho tôi một gợi ý")
    assert "Tạo bảng" in hint[0].text


def test_user_can_control_how_much_the_companion_speaks():
    session = LearningSession(_plan())
    session.start()
    assert "hướng dẫn vừa đủ" in session.on_user_text("nói ít hơn")[0].text
    assert "đồng hành im lặng" in session.on_user_text("đừng tự nhắc")[0].text
    assert "hướng dẫn chi tiết" in session.on_user_text("hướng dẫn chi tiết")[0].text
    assert "hướng dẫn vừa đủ" in session.on_user_text("quay lại chế độ học")[0].text


def test_hint_ladder_uses_reviewed_region_role_and_function():
    plan = replace(
        _plan(),
        functions=(("Tạo bảng", "Mở biểu mẫu tạo bảng."),),
        control_hints=(("Tạo bảng", "vùng nội dung chính", "nút"),),
    )
    session = LearningSession(plan)
    session.start()
    assert session.on_user_text("gợi ý")[0].text == "Bạn cần tìm Tạo bảng."
    assert "vùng nội dung chính" in session.on_user_text("gợi ý")[0].text
    third = session.on_user_text("gợi ý")[0].text
    assert "nút" in third and "Mở biểu mẫu tạo bảng" in third


def test_keyboard_repair_is_target_only_and_never_activates_for_the_user():
    repaired = []
    focused = []
    clicked = []
    session = LearningSession(
        _plan(),
        keyboard_repair_enabled=True,
        repair=lambda label: repaired.append(label) or True,
        focus=lambda label: focused.append(label) or True,
        click=lambda label: clicked.append(label) or True,
    )
    session.start()
    binding = bind_steps(
        session.plan,
        [DetectedControl("Tạo bảng", "div", "click-listener", Box(0, 0, 32, 32))],
    )
    session.note_bindings(binding)
    speech = session.on_page(label="", bump="", flags={})
    assert repaired == ["Tạo bảng"]
    assert focused == [] and clicked == []
    assert "Bạn vẫn là người tự di chuyển và nhấn Enter" in speech[0].text


def test_unbound_target_gets_exact_label_repair_after_two_stable_snapshots():
    repaired = []
    session = LearningSession(
        _plan(),
        keyboard_repair_enabled=True,
        repair=lambda label: repaired.append(label) or True,
    )
    session.start()
    empty = bind_steps(session.plan, [])

    session.note_bindings(empty)
    assert repaired == []
    session.note_bindings(empty)
    speech = session.on_page(label="", bump="", flags={})

    assert repaired == ["Tạo bảng"]
    assert speech[0].kind == "accessibility"
    assert all("không thấy" not in item.text for item in speech)


def test_recovery_appears_after_a_focus_loop_but_respects_explicit_silence():
    session = LearningSession(_plan(), assistance_level="on_demand")
    session.start()
    session.on_page(label="SQL Editor", bump="", flags={})
    session.on_page(label="Database", bump="", flags={})
    recovery = session.on_page(label="SQL Editor", bump="", flags={})
    assert any("đang đi vòng" in item.text for item in recovery)

    quiet = LearningSession(_plan())
    quiet.start()
    quiet.on_user_text("đừng tự nhắc")
    quiet.on_page(label="SQL Editor", bump="", flags={})
    quiet.on_page(label="Database", bump="", flags={})
    assert quiet.on_page(label="SQL Editor", bump="", flags={}) == []


def test_always_describe_new_pages_uses_the_existing_vision_consent_flow():
    session = LearningSession(_plan(), vision_enabled=True)
    session.start()
    first = PageScene(
        "https://supabase.com/dashboard/project/demo/editor",
        "Table Editor",
        "",
        (1280, 800),
        (),
        (),
        SceneConfidence.HIGH,
    )
    second = replace(first, url="https://supabase.com/dashboard/project/demo/settings", title="Settings")
    session.note_scene(first)
    session.on_user_text("luôn mô tả trang mới")
    notice = session.note_scene(second)
    assert notice[0].kind == "vision_notice"
    assert session.on_user_text("đồng ý")[0].kind == "vision_request"


def test_location_and_read_step_remain_available_in_silent_mode():
    session = LearningSession(_plan())
    session.start()
    session.on_user_text("đừng tự nhắc")
    session.on_page(label="SQL Editor", bump="", flags={})
    assert session.on_user_text("tôi đang ở đâu")[0].text == "Bạn đang ở SQL Editor."
    assert session.on_user_text("đọc lại bước")[0].text == session.step.instruction


def test_learning_design_is_available_on_demand_and_after_completion():
    plan = replace(
        _plan(),
        learning=LearningDesign(
            objective="Tự tạo bảng bằng bàn phím.",
            bloom_level="apply",
            authentic_scenario="Bạn cần tạo bảng công việc cho nhóm.",
            concept_summary="Bạn đã dùng một mẫu thao tác có thể lặp lại.",
            reflection_prompt="Bạn đã dùng phím nào để chọn control?",
            transfer_task="Tự tạo một bảng khác với ít gợi ý hơn.",
            success_evidence=("Tự hoàn thành không cần gợi ý.",),
        ),
    )
    store = ProgressStore()
    session = LearningSession(plan, progress=store)
    opening = session.start()
    assert "Mục tiêu: Tự tạo bảng bằng bàn phím" in opening[0].text
    assert session.on_user_text("mục tiêu bài học")[0].text.endswith("Tự tạo bảng bằng bàn phím.")
    assert "bảng công việc" in session.on_user_text("bài này để làm gì")[0].text
    assert "phím nào" in session.on_user_text("nhìn lại bài học")[0].text
    assert "ít gợi ý hơn" in session.on_user_text("bài tự luyện")[0].text

    session.step_index = len(plan.steps) - 1
    final_key = session._skill_key()
    completion = session._advance()
    assert [item.kind for item in completion] == ["done", "reflection", "reflection", "transfer"]
    assert store.get(final_key).reflection_prompts == 1
    assert store.get(final_key).transfer_tasks_offered == 1
    assert "ít gợi ý hơn" in session.on_user_text("bài tự luyện")[0].text
    assert "không cần gợi ý" in session.on_user_text("tiêu chí hoàn thành")[0].text
