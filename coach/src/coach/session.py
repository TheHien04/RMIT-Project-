"""Lesson state machine. Direction cues are computed, not generated."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator
from typing import Callable, Optional

from coach.cues import CONFIRM_SECONDS, CueThrottle, Direction, cue_for, cue_line
from coach.dom_map import StepBinding
from coach.lesson import LessonPlan, LessonStep
from coach.observer import Observation
from coach.privacy import EgressLog, consider_icon, llm_payload
from coach.progress import AssistanceLevel, ProgressStore
from coach.scene import PageScene
from coach.vision import VisionGuidance


_SPEECH_PRIORITY = {
    "safety": 100,
    "done": 90,
    "stop": 90,
    "step": 80,
    "status": 70,
    "navigation": 70,
    "assist": 70,
    "accessibility": 85,
    "vision_notice": 65,
    "privacy_notice": 65,
    "vision": 60,
    "explain": 60,
    "citation": 55,
    "repeat": 55,
    "place": 45,
    "reflection": 45,
    "transfer": 40,
    "cue": 30,
    "focus": 20,
}


@dataclass(frozen=True)
class SpeechEvent:
    text: str
    kind: str
    priority: int = -1
    interruptible: bool = True
    dedupe_key: str = ""

    def __post_init__(self) -> None:
        if self.priority < 0:
            object.__setattr__(self, "priority", _SPEECH_PRIORITY.get(self.kind, 50))
        if not self.dedupe_key:
            object.__setattr__(self, "dedupe_key", f"{self.kind}:{self.text}")
        if self.kind in {"safety", "done", "stop"}:
            object.__setattr__(self, "interruptible", False)


# Backwards-compatible name used by the existing guide and tests.
Speech = SpeechEvent


class LearningSession:
    def __init__(
        self,
        plan: LessonPlan,
        *,
        egress: EgressLog | None = None,
        focus: Callable[[str], bool] | None = None,
        click: Callable[[str], bool] | None = None,
        repair: Callable[[str], bool] | None = None,
        set_navigation: Callable[[bool], bool] | None = None,
        navigation_mode: str = "native_focus",
        navigation_available: bool = True,
        keyboard_repair_enabled: bool = False,
        progress: ProgressStore | None = None,
        assistance_level: str = "orientation",
        llm: Optional[Callable[[dict], str]] = None,
        vision_enabled: bool = False,
        speech_policy: str = "quiet",
        defer_llm: bool = False,
    ) -> None:
        if not plan.steps:
            raise ValueError("the lesson has no steps")
        self.plan = plan
        self.egress = egress or EgressLog()
        self._focus = focus or (lambda _label: False)
        self._click = click or (lambda _label: False)
        self._repair = repair or (lambda _label: False)
        self._set_navigation = set_navigation or (lambda _enabled: False)
        self.navigation_mode = navigation_mode
        self._navigation_available = navigation_available
        self._keyboard_repair_enabled = keyboard_repair_enabled
        self._progress = progress
        self._configured_level = assistance_level
        self._level_override: AssistanceLevel | None = None
        self._llm = llm
        self.vision_enabled = vision_enabled
        self.speech_policy = speech_policy
        self._defer_llm = defer_llm
        self.step_index = 0
        self.phase = "idle"
        self._assist_for: int | None = None
        self._throttle = CueThrottle()
        self._last_direction: str | None = None
        self._direction_spoken_at: float | None = None
        self._last_focused = ""
        self._said_missing_cursor = False
        self._said_discovery = False
        self._said_unbound = False
        self._place = ""
        self._bindings: dict[int, StepBinding] = {}
        self._binding_seen: dict[tuple[int, str, str | None], int] = {}
        self._vision_consent: bool | None = None
        self._pending_vision_question = ""
        self._llm_consent: bool | None = None
        self._pending_llm_question = ""
        self._vision_requested_steps: set[int] = set()
        self._describe_new_pages = False
        self._hint_level = 0
        self._focus_visits: dict[str, int] = {}
        self._focus_loop_recorded = False
        self._started_steps: set[int] = set()
        self._repaired_steps: set[int] = set()
        self._pending_binding_speech: list[Speech] = []
        self._pending_level_suggestion: tuple[str, AssistanceLevel] | None = None
        self._scene: PageScene | None = None
        self._last_scene_path = ""
        self._last_flags: dict = {}
        self._pending_completion: str | None = None

    @property
    def step(self) -> LessonStep:
        return self.plan.steps[self.step_index]

    @property
    def done(self) -> bool:
        return self.phase == "done"

    @property
    def stopped(self) -> bool:
        return self.phase == "stopped"

    @property
    def finished(self) -> bool:
        return self.phase in {"done", "stopped"}

    def on_user_text(self, text: str) -> list[Speech]:
        norm = _norm(text)
        if self.phase == "idle":
            if "bắt đầu" in norm or "hoc" in norm or "học" in norm:
                return self.start()
            return [Speech("Nói bắt đầu học để vào bài tạo bảng ca.", "status")]
        if self.phase in {"done", "stopped"}:
            if self.phase == "done":
                if _wants_learning_goal(norm):
                    return self._learning_goal()
                if _wants_learning_reason(norm):
                    return self._learning_reason()
                if _wants_reflection(norm):
                    return self._reflection_prompt()
                if _wants_transfer_task(norm):
                    return self._transfer_task()
                if _wants_success_evidence(norm):
                    return self._success_evidence()
            return []
        if _stop_guidance_intent(norm):
            return self._stop_guidance()
        if self._pending_completion is not None:
            return self._handle_completion_confirmation(norm)
        # Completion intents must precede broad helpers such as citation
        # detection, which also recognizes the words "bước này".
        if _lesson_done_intent(norm):
            return self._request_lesson_completion()
        if _step_done_intent(norm):
            return self._request_step_completion()
        if self._pending_level_suggestion and _accepts_vision(norm):
            key, level = self._pending_level_suggestion
            if self._progress is not None:
                self._progress.accept_level(key, level)
            self._pending_level_suggestion = None
            return [Speech("Đã giảm lời hướng dẫn theo lựa chọn của bạn.", "status"), *self._step_speech()]
        if self._pending_level_suggestion and _declines_vision(norm):
            key, _level = self._pending_level_suggestion
            if self._progress is not None:
                self._progress.decline_suggestion(key)
            self._pending_level_suggestion = None
            return [Speech("Được. Mình giữ nguyên mức hướng dẫn.", "status"), *self._step_speech()]
        if self._pending_vision_question and _accepts_vision(norm):
            self._vision_consent = True
            question = self._pending_vision_question
            self._pending_vision_question = ""
            return self._request_vision(question)
        if self._pending_vision_question and _declines_vision(norm):
            self._vision_consent = False
            self._pending_vision_question = ""
            return [Speech("Được. Mình tiếp tục chỉ dùng thông tin DOM trên máy.", "vision_notice")]
        if self._pending_llm_question and _accepts_vision(norm):
            self._llm_consent = True
            question = self._pending_llm_question
            self._pending_llm_question = ""
            if self._defer_llm:
                return [Speech(question, "llm_request", priority=60)]
            return [self.complete_llm(question)]
        if self._pending_llm_question and _declines_vision(norm):
            self._llm_consent = False
            self._pending_llm_question = ""
            return [
                Speech(
                    "Được. Câu hỏi và lời nói của bạn sẽ không rời máy. "
                    "Mình tiếp tục bằng hướng dẫn local.",
                    "explain",
                ),
                self.local_explanation(),
            ]
        assistance = self._assistance_request(norm)
        if assistance is not None:
            return assistance
        if _wants_hint(norm):
            return self._next_hint()
        if _wants_learning_goal(norm):
            return self._learning_goal()
        if _wants_learning_reason(norm):
            return self._learning_reason()
        if _wants_reflection(norm):
            return self._reflection_prompt()
        if _wants_transfer_task(norm):
            return self._transfer_task()
        if _wants_success_evidence(norm):
            return self._success_evidence()
        if _wants_page_description(norm):
            return self._request_vision(text)
        if _wants_location(norm):
            if self._place:
                return [Speech(f"Bạn đang ở {self._place}.", "explain")]
            if self._scene is not None:
                return [Speech(f"Bạn đang ở trang {self._scene.title}.", "explain")]
            return [Speech("Mình chưa xác định được vị trí hiện tại.", "status")]
        if _wants_destination(norm):
            label = self.step.target_label or "mục được ghi trong tài liệu"
            return [Speech(f"Bạn cần tới {self._named(label, detail=True)}", "explain")]
        if _wants_current_description(norm):
            if self._place and self._function_for(self._place):
                return [Speech(self._named(self._place, detail=True), "explain")]
            return self._request_vision(text)
        if _wants_citation(norm):
            return [self._citation_speech()]
        if "không hiểu" in norm or "khong hieu" in norm:
            return [self._explain(text)]
        if "nhắc lại" in norm or "nhac lai" in norm or "đọc lại bước" in norm or "doc lai buoc" in norm:
            return [Speech(self.step.instruction, "repeat")]
        navigation = _navigation_request(norm)
        if navigation is not None:
            return self._navigation(navigation)
        assist = _assist_request(norm)
        if assist:
            return self._assist(assist)
        return [self._explain(text)]

    def start(self) -> list[Speech]:
        self.phase = "guiding"
        if self.navigation_mode == "coach_list":
            self._set_navigation(True)
        self.step_index = 0
        self._assist_for = None
        self._throttle.reset()
        self._last_direction = None
        self._direction_spoken_at = None
        self._place = ""
        self._said_unbound = False
        self._begin_step()
        if self._configured_level == "adaptive" and self._progress is not None:
            suggested = self._progress.suggested_level_for(self._skill_key())
            if suggested is not None:
                self._pending_level_suggestion = (self._skill_key(), suggested)
                names = {
                    AssistanceLevel.GUIDED: "chỉ nhắc mục tiêu và khu vực",
                    AssistanceLevel.PRACTICE: "chỉ giao mục tiêu để bạn tự luyện",
                    AssistanceLevel.ON_DEMAND: "chỉ hướng dẫn khi bạn hỏi",
                    AssistanceLevel.SILENT: "đồng hành im lặng",
                }
                return [
                    Speech(
                        f"Bạn đã hoàn thành kỹ năng này không cần gợi ý. "
                        f"Lần này mình {names.get(suggested, 'nói ít hơn')}, được không? "
                        "Nói đồng ý hoặc giữ nguyên.",
                        "status",
                    )
                ]
        return self._step_speech(initial=True)

    def note_bindings(self, bindings: tuple[StepBinding, ...]) -> None:
        self._bindings = {binding.step_number: binding for binding in bindings}
        binding = self._bindings.get(self.step.number)
        if binding is not None:
            key = (binding.step_number, binding.status, binding.label)
            self._binding_seen[key] = self._binding_seen.get(key, 0) + 1
        if (
            self.phase != "guiding"
            or not self._keyboard_repair_enabled
            or self.step_index in self._repaired_steps
            or binding is None
        ):
            return
        repairable_bound = (
            binding.status == "bound"
            and len(binding.controls) == 1
            and binding.controls[0].reason in {"onclick", "click-listener"}
        )
        # An unbound target must be stable across two observations before the
        # bridge tries the exact-label pointer-card fallback.
        key = (binding.step_number, binding.status, binding.label)
        repairable_unbound = binding.status == "unbound" and self._binding_seen.get(key, 0) >= 2
        if not (repairable_bound or repairable_unbound):
            return
        if not self._repair(self.step.target_label or ""):
            return
        self._repaired_steps.add(self.step_index)
        if self._level() in {AssistanceLevel.ORIENTATION, AssistanceLevel.GUIDED}:
            text = (
                f"{self.step.target_label} không nhận phím Tab theo mặc định. "
                "Mình đã bổ sung khả năng nhận focus và phím Enter cho đúng mục này. "
                "Bạn vẫn là người tự di chuyển và nhấn Enter."
            )
        else:
            text = f"Đã bổ sung bàn phím cho {self.step.target_label}. Bạn tự nhấn Enter."
        self._pending_binding_speech.append(
            Speech(text, "accessibility", priority=85, interruptible=False)
        )

    def note_scene(self, scene: PageScene | None) -> list[Speech]:
        if scene is None:
            return []
        previous = self._last_scene_path
        self._scene = scene
        self._last_scene_path = scene.path
        if not previous or previous == scene.path or not self._describe_new_pages:
            return []
        return self._request_vision(f"Mô tả trang mới {scene.title} và các vùng chính.")

    def attach_assist_actions(
        self,
        *,
        focus: Callable[[str], bool],
        click: Callable[[str], bool],
        repair: Callable[[str], bool] | None = None,
        set_navigation: Callable[[bool], bool] | None = None,
    ) -> None:
        """Attach the live page only after its browser thread is ready."""

        self._focus = focus
        self._click = click
        if repair is not None:
            self._repair = repair
        if set_navigation is not None:
            self._set_navigation = set_navigation

    def on_page(self, *, label: str, bump: str, flags: dict) -> list[Speech]:
        """Speak the control the person just reached. Do not move them."""

        if self.phase != "guiding":
            return []
        self._last_flags = dict(flags)
        if self.step.success.met(flags):
            return self._advance()
        speeches = self._drain_binding_speech()
        binding = self._bindings.get(self.step.number)
        repaired = self.step_index in self._repaired_steps
        if binding and not repaired and binding.status in {"unbound", "ambiguous"} and self._needs_vision(binding):
            return self._request_vision(
                f"Hãy mô tả vùng trang và giúp nhận biết {binding.label or 'target của bước này'}."
            )
        if binding and not repaired and binding.status == "unbound" and not self._said_unbound:
            self._said_unbound = True
            speeches.append(Speech(f"Mình không thấy {binding.label} trên trang.", "place"))
        if bump == "end":
            speeches.append(Speech("Hết danh sách.", "place"))
        elif bump == "start":
            speeches.append(Speech("Đầu danh sách.", "place"))
        if label and label != self._place:
            self._place = label
            recovery = self._note_focus_visit(label)
            if recovery is not None:
                speeches.append(recovery)
            line = self._place_line(label)
            if line:
                speeches.append(Speech(line, "place"))
        return speeches

    def on_observation(self, observation: Observation, *, now: float) -> list[Speech]:
        if self.phase != "guiding":
            return []
        self._last_flags = dict(observation.flags)
        speeches: list[Speech] = []
        if observation.focused_text and observation.focused_text != self._last_focused:
            self._last_focused = observation.focused_text
            self._place = observation.focused_text
            recovery = self._note_focus_visit(observation.focused_text)
            if recovery is not None:
                speeches.append(recovery)
            if observation.focused_text == self.step.target_label and self._announces_target():
                speeches.append(Speech(f"{observation.focused_text}. Enter.", "place"))
        if self.step.success.met(observation.flags):
            speeches.extend(self._advance())
            return speeches
        if self.step.needs_discovery or not self.step.target_label:
            if not self._said_discovery and self._throttle.allow(now):
                self._said_discovery = True
                speeches.append(
                    Speech(
                        "Tài liệu không chỉ nút nào. Mình sẽ không đoán tên mục.",
                        "discovery",
                    )
                )
            return speeches
        element = observation.element_named(self.step.target_label)
        if element is None or observation.cursor is None:
            if observation.cursor is None and not self._said_missing_cursor and self._throttle.allow(now):
                self._said_missing_cursor = True
                speeches.append(Speech("Đưa chuột vào trang.", "cue"))
            return speeches
        speeches.extend(self._direction_cue(cue_for(observation.cursor, element.box), now))
        return speeches

    def on_unlabeled_icon(self, png: bytes) -> list[Speech]:
        allowed = consider_icon(png, vision_enabled=self.vision_enabled, egress=self.egress)
        if not allowed:
            return [Speech("Control này không có chữ. Mình không gửi ảnh ra ngoài.", "vision")]
        return [Speech("Ảnh của mục này đã được đánh dấu là rời máy.", "vision")]

    def on_vision_guidance(self, guidance: VisionGuidance) -> list[Speech]:
        """Vision is advisory speech only; it never advances the lesson."""

        text = guidance.spoken_text()
        if not text:
            return [Speech("Mình chưa đọc được thêm thông tin từ ảnh.", "vision")]
        if guidance.target_label:
            function = _spoken(self._function_for(guidance.target_label))
            if function:
                text = f"{text} {function}"
        return [Speech(text, "vision")]

    def on_vision_error(self) -> list[Speech]:
        return [
            Speech(
                "Mình chưa phân tích được ảnh. Mình sẽ tiếp tục dùng thông tin DOM trên máy.",
                "vision",
            )
        ]

    def _stop_guidance(self) -> list[Speech]:
        if self._progress is not None:
            self._progress.pause(self._skill_key())
        self._pending_completion = None
        self.phase = "stopped"
        return [
            Speech(
                "Đã dừng hướng dẫn. Tiến độ hiện tại được giữ là chưa hoàn thành.",
                "stop",
            )
        ]

    def _request_step_completion(self) -> list[Speech]:
        if self.step.success.met(self._last_flags):
            return self._advance(source="dom_verified")
        self._pending_completion = "step"
        return [
            Speech(
                "Mình chưa thấy bước này hoàn tất trên trang. "
                "Nếu bạn chắc chắn đã xong, nói: tôi xác nhận xong bước này. "
                "Hoặc nói: tiếp tục.",
                "status",
                interruptible=False,
            )
        ]

    def _request_lesson_completion(self) -> list[Speech]:
        if self.step_index == len(self.plan.steps) - 1 and self.step.success.met(self._last_flags):
            return self._advance(source="dom_verified")
        self._pending_completion = "lesson"
        return [
            Speech(
                "Mình chưa thấy toàn bộ bài học hoàn tất trên trang. "
                "Nếu bạn muốn tự xác nhận, nói: tôi xác nhận hoàn thành bài học. "
                "Hoặc nói: tiếp tục.",
                "status",
                interruptible=False,
            )
        ]

    def _handle_completion_confirmation(self, norm: str) -> list[Speech]:
        pending = self._pending_completion
        if _declines_completion(norm):
            self._pending_completion = None
            return [Speech("Được. Mình tiếp tục bài học hiện tại.", "status")]
        if pending == "step" and _confirms_step_completion(norm):
            self._pending_completion = None
            return self._advance(source="user_confirmed")
        if pending == "lesson" and _confirms_lesson_completion(norm):
            self._pending_completion = None
            return self._complete_lesson_by_user()
        requested = (
            "tôi xác nhận xong bước này"
            if pending == "step"
            else "tôi xác nhận hoàn thành bài học"
        )
        return [Speech(f"Mình đang chờ xác nhận. Nói {requested}, hoặc nói tiếp tục.", "status")]

    def _complete_lesson_by_user(self) -> list[Speech]:
        if self._progress is not None:
            for index in range(self.step_index, len(self.plan.steps)):
                step = self.plan.steps[index]
                key = ProgressStore.skill_key(self.plan.title, step)
                if index not in self._started_steps:
                    success = step.success
                    columns = ",".join(success.columns)
                    version = f"{step.target_label or ''}|{success.kind}|{success.value}|{columns}"
                    self._progress.start_attempt(key, page_version=version)
                self._progress.complete(key, source="user_confirmed")
        self.phase = "done"
        speeches = [
            Speech(
                "Đã ghi nhận bài học hoàn thành theo xác nhận của bạn. "
                "Kết quả này chưa được DOM xác minh.",
                "done",
            )
        ]
        speeches.extend(self._learning_followup())
        return speeches

    def _advance(self, *, source: str = "dom_verified") -> list[Speech]:
        finished = self.step.number
        if self._progress is not None:
            self._progress.complete(self._skill_key(), source=source)
        self._assist_for = None
        self._throttle.reset()
        self._last_direction = None
        self._direction_spoken_at = None
        self._said_missing_cursor = False
        self._said_discovery = False
        self._said_unbound = False
        self._hint_level = 0
        self._focus_visits = {}
        self._focus_loop_recorded = False
        if self.step_index + 1 >= len(self.plan.steps):
            self.phase = "done"
            suffix = "" if source == "dom_verified" else " theo xác nhận của bạn"
            speeches = [Speech(f"Xong bước {finished}. Bài học đã hoàn thành{suffix}.", "done")]
            speeches.extend(self._learning_followup())
            return speeches
        self.step_index += 1
        self._begin_step()
        return [Speech(f"Xong bước {finished}.", "status"), *self._step_speech()]

    def _assist(self, kind: str) -> list[Speech]:
        label = self.step.target_label
        if not label:
            return [Speech("Tài liệu không chỉ mục nào để mình đưa focus tới.", "assist")]
        self._assist_for = self.step_index
        self._record_hint(6 if kind == "focus" else 7)
        if kind == "click":
            if self.step.sensitivity == "destructive":
                return [
                    Speech(
                        f"{label} sẽ ghi thay đổi thật vào hệ thống. Mình không bấm hộ bước này. "
                        "Bạn hãy kiểm tra thông tin rồi tự nhấn Enter.",
                        "safety",
                    )
                ]
            if not self.step.assist_click_allowed:
                return [
                    Speech(
                        f"Mình không bấm hộ {label} vì bài học chưa cấp quyền cho thao tác này. "
                        "Bạn vẫn là người tự nhấn Enter.",
                        "safety",
                    )
                ]
            moved = self._click(label)
            verb = "bấm" if moved else "không bấm được"
            return [Speech(f"Mình đã {verb} {label}. Bước chưa xong cho đến khi trang đổi.", "assist")]
        moved = self._focus(label)
        if not moved:
            return [Speech(f"Mình không tới được {label}.", "assist")]
        self._place = label
        return [Speech(f"Mình đã tới {self._named(label)} Bạn tự bấm Enter.", "assist")]

    def _citation_speech(self) -> Speech:
        citation = self.step.citation
        return Speech(f"{citation.quote} Trang {citation.page}.", "citation")

    def _navigation(self, requested: str) -> list[Speech]:
        if requested == "coach_list":
            if not self._navigation_available:
                return [
                    Speech(
                        "Danh sách điều khiển riêng chưa được bật trên trang này. "
                        "Tiếp tục dùng Tab, hoặc nói focus giúp nếu bạn bị kẹt.",
                        "status",
                    )
                ]
            if not self._set_navigation(True):
                return [Speech("Không mở được danh sách điều khiển. Tiếp tục dùng Tab.", "status")]
            self.navigation_mode = "coach_list"
            return [
                Speech(
                    "Đã mở danh sách điều khiển. Mũi tên đổi nút hoặc liên kết. Enter để bấm. "
                    "Nói đọc hoặc nhấn Escape để quay lại đọc trang.",
                    "navigation",
                )
            ]
        if requested == "mouse_cue":
            self._set_navigation(False)
            self.navigation_mode = "mouse_cue"
            return [Speech("Dùng chuột. Mình chỉ nhắc khi bạn di chuyển chuột.", "navigation")]
        self._set_navigation(False)
        self.navigation_mode = "native_focus"
        return [Speech("Đọc trang. Tab và screen reader điều hướng bình thường.", "navigation")]

    def _navigation_instruction(self) -> str:
        if self.navigation_mode == "coach_list":
            return "Mũi tên đổi nút hoặc liên kết. Enter để bấm. Escape để trở lại trang."
        if self.navigation_mode == "mouse_cue":
            return "Di chuột theo hướng mình nói. Bạn tự bấm khi tới nơi."
        text = "Dùng Tab hoặc screen reader để đi qua các nút và liên kết. Khi nghe đúng mục, nhấn Enter."
        if self._navigation_available:
            text += " Nếu bị kẹt, nói mở danh sách điều khiển."
        return text

    def _level(self) -> AssistanceLevel:
        if self._level_override is not None:
            return self._level_override
        if self._configured_level != "adaptive":
            try:
                return AssistanceLevel(self._configured_level)
            except ValueError:
                return AssistanceLevel.ORIENTATION
        if self._progress is None:
            return AssistanceLevel.ORIENTATION
        return self._progress.level_for(self._skill_key())

    def _skill_key(self) -> str:
        return ProgressStore.skill_key(self.plan.title, self.step)

    def _page_version(self) -> str:
        success = self.step.success
        columns = ",".join(success.columns)
        return (
            f"{self.step.target_label or ''}|{success.kind}|{success.selector}|"
            f"{success.value}|{columns}"
        )

    def _begin_step(self) -> None:
        if self.step_index in self._started_steps:
            return
        self._started_steps.add(self.step_index)
        if self._progress is not None:
            self._progress.start_attempt(self._skill_key(), page_version=self._page_version())

    def _step_speech(self, *, initial: bool = False) -> list[Speech]:
        step = self.step
        level = self._level()
        speeches: list[Speech] = []
        if initial and level in {AssistanceLevel.ORIENTATION, AssistanceLevel.GUIDED}:
            objective = self.plan.learning.objective
            speeches.append(
                Speech(
                    f"Mình sẽ hướng dẫn module {step.module_title}. "
                    + (f"Mục tiêu: {objective} " if objective else "")
                    + "Bạn tự làm từng bước; hỗ trợ sẽ giảm khi bạn đã quen.",
                    "brief",
                )
            )
        if level is AssistanceLevel.ORIENTATION:
            speeches.append(Speech(f"Bước {step.number}. {step.instruction}", "step"))
            region, role = self._hint_for(step.target_label)
            context = ". ".join(value for value in (region, role) if value)
            if context:
                speeches.append(Speech(f"{step.target_label} ở {context}.", "step"))
            speeches.append(Speech(self._navigation_instruction(), "step"))
        elif level is AssistanceLevel.GUIDED:
            speeches.append(Speech(f"Bước {step.number}. {step.instruction}", "step"))
            region, _role = self._hint_for(step.target_label)
            if region:
                speeches.append(Speech(f"Mục này ở {region}.", "step"))
        elif level is AssistanceLevel.PRACTICE:
            speeches.append(Speech(f"Hãy tự hoàn thành bước {step.number}: {step.instruction}", "step"))
        elif level is AssistanceLevel.ON_DEMAND:
            speeches.append(
                Speech(
                    f"Mục tiêu bước {step.number}: {step.target_label or step.instruction}. "
                    "Mình sẽ chỉ hướng dẫn khi bạn hỏi.",
                    "step",
                )
            )
        elif initial:
            speeches.append(
                Speech(
                    "Đang ở chế độ đồng hành im lặng. Mình vẫn theo dõi an toàn và sẵn sàng khi bạn hỏi.",
                    "status",
                )
            )
        return speeches

    def _learning_goal(self) -> list[Speech]:
        learning = self.plan.learning
        if not learning.objective:
            return [Speech("Bài học chưa khai báo mục tiêu học tập riêng.", "explain")]
        return [Speech(f"Mục tiêu bài học: {learning.objective}", "explain")]

    def _learning_reason(self) -> list[Speech]:
        learning = self.plan.learning
        text = learning.authentic_scenario or learning.concept_summary
        if not text:
            return [Speech("Bài học chưa có tình huống thực tế để giải thích thêm.", "explain")]
        return [Speech(text, "explain")]

    def _reflection_prompt(self) -> list[Speech]:
        prompt = self.plan.learning.reflection_prompt
        if not prompt:
            return [Speech("Bài học chưa có câu hỏi nhìn lại.", "explain")]
        return [Speech(prompt, "reflection")]

    def _transfer_task(self) -> list[Speech]:
        task = self.plan.learning.transfer_task
        if not task:
            return [Speech("Bài học chưa có bài tự luyện tiếp theo.", "explain")]
        return [Speech(f"Bài tự luyện: {task}", "transfer")]

    def _success_evidence(self) -> list[Speech]:
        evidence = self.plan.learning.success_evidence
        if not evidence:
            return [Speech("Bài học chưa khai báo bằng chứng thành công.", "explain")]
        return [Speech("Bằng chứng thành công: " + "; ".join(evidence), "explain")]

    def _learning_followup(self) -> list[Speech]:
        learning = self.plan.learning
        speeches: list[Speech] = []
        if learning.concept_summary:
            speeches.append(Speech(learning.concept_summary, "reflection"))
        if learning.reflection_prompt:
            speeches.append(Speech(learning.reflection_prompt, "reflection"))
        if learning.transfer_task:
            speeches.append(
                Speech("Khi muốn luyện tiếp, hãy nói: bài tự luyện.", "transfer")
            )
        if self._progress is not None and (learning.reflection_prompt or learning.transfer_task):
            self._progress.record_learning_followup(
                self._skill_key(),
                reflection=bool(learning.reflection_prompt),
                transfer=bool(learning.transfer_task),
            )
        return speeches

    def _hint_for(self, label: str | None) -> tuple[str, str]:
        folded = " ".join((label or "").casefold().split())
        for name, region, role in self.plan.control_hints:
            if " ".join(name.casefold().split()) == folded:
                return region, role
        return "", ""

    def _record_hint(self, level: int) -> None:
        if self._progress is not None:
            self._progress.record_hint(self._skill_key(), level)

    def _next_hint(self) -> list[Speech]:
        self._hint_level = min(5, self._hint_level + 1)
        self._record_hint(self._hint_level)
        label = self.step.target_label or "mục được nêu trong tài liệu"
        region, role = self._hint_for(self.step.target_label)
        function = _spoken(self._function_for(label))
        if self._hint_level == 1:
            text = f"Bạn cần tìm {label}."
        elif self._hint_level == 2:
            text = f"{label} nằm ở {region}." if region else f"Tìm vùng chứa {label} trên trang."
        elif self._hint_level == 3:
            details = " ".join(part for part in (f"Đó là {role}." if role else "", function) if part)
            text = details or f"Đây là mục có nhãn {label}."
        elif self._hint_level == 4:
            text = f"Nhấn Tab từng lần cho đến khi nghe {label}, rồi nhấn Enter."
        elif self.step_index in self._repaired_steps:
            text = f"Khả năng nhận Tab và Enter đã được bổ sung cho {label}. Bạn hãy tự nhấn Enter."
        elif self._navigation_available:
            text = "Bạn có thể nói mở danh sách điều khiển, rồi dùng phím mũi tên để tìm mục."
        else:
            text = "Nếu vẫn bị kẹt, nói focus giúp. Mình chỉ đưa focus tới mục; bạn tự nhấn Enter."
        return [Speech(text, "explain")]

    def _assistance_request(self, norm: str) -> list[Speech] | None:
        if "luôn mô tả trang mới" in norm or "luon mo ta trang moi" in norm:
            self._describe_new_pages = True
            return [Speech("Được. Khi sang trang mới, mình sẽ đề nghị mô tả trang nếu vision được phép.", "status")]
        if "hướng dẫn chi tiết" in norm or "huong dan chi tiet" in norm:
            self._level_override = AssistanceLevel.ORIENTATION
        elif "quay lại chế độ học" in norm or "quay lai che do hoc" in norm:
            self._level_override = AssistanceLevel.GUIDED
        elif "chỉ báo khi tôi sai" in norm or "chi bao khi toi sai" in norm:
            self._level_override = AssistanceLevel.ON_DEMAND
        elif "đừng tự nhắc" in norm or "dung tu nhac" in norm:
            self._level_override = AssistanceLevel.SILENT
        elif "nói ít hơn" in norm or "noi it hon" in norm:
            levels = list(AssistanceLevel)
            current = self._level()
            self._level_override = levels[min(levels.index(current) + 1, len(levels) - 1)]
        else:
            return None
        labels = {
            AssistanceLevel.ORIENTATION: "hướng dẫn chi tiết",
            AssistanceLevel.GUIDED: "hướng dẫn vừa đủ",
            AssistanceLevel.PRACTICE: "tự luyện tập",
            AssistanceLevel.ON_DEMAND: "chỉ hướng dẫn khi cần",
            AssistanceLevel.SILENT: "đồng hành im lặng",
        }
        if self._progress is not None and self._level_override is not None:
            self._progress.accept_level(self._skill_key(), self._level_override)
        return [Speech(f"Đã chuyển sang chế độ {labels[self._level_override]}.", "status")]

    def _announces_target(self) -> bool:
        return self._level() not in {AssistanceLevel.ON_DEMAND, AssistanceLevel.SILENT}

    def _note_focus_visit(self, label: str) -> Speech | None:
        if label == self.step.target_label:
            return None
        folded = " ".join(label.casefold().split())
        self._focus_visits[folded] = self._focus_visits.get(folded, 0) + 1
        if self._focus_visits[folded] < 2 or self._focus_loop_recorded:
            return None
        self._focus_loop_recorded = True
        if self._progress is not None:
            self._progress.record_focus_loop(self._skill_key())
        if self._level_override is AssistanceLevel.SILENT:
            return None
        return Speech(
            f"Có vẻ bạn đang đi vòng. Mục tiêu là {self.step.target_label or 'mục trong tài liệu'}. "
            "Nếu muốn thêm trợ giúp, nói gợi ý.",
            "assist",
        )

    def _drain_binding_speech(self) -> list[Speech]:
        speeches = self._pending_binding_speech
        self._pending_binding_speech = []
        return speeches

    def _direction_cue(self, direction: Direction, now: float) -> list[Speech]:
        """One local phrase. Same heading stays quiet until the confirm gap."""

        if direction is Direction.ARRIVED:
            if self._last_direction == direction.value:
                return []
            self._last_direction = direction.value
            self._direction_spoken_at = now
            return [Speech(cue_line(direction, repeat=False), "cue")]
        repeat = self._last_direction == direction.value
        if repeat:
            spoken_at = self._direction_spoken_at
            if spoken_at is None or now - spoken_at < CONFIRM_SECONDS:
                return []
            self._direction_spoken_at = now
            return [Speech(cue_line(direction, repeat=True), "cue")]
        if not self._throttle.allow(now):
            return []
        self._last_direction = direction.value
        self._direction_spoken_at = now
        return [Speech(cue_line(direction, repeat=False), "cue")]

    def _explain(self, user_text: str) -> Speech:
        """Open questions go to the model. The canned line is the default."""

        label = self.step.target_label or "mục trong tài liệu"
        canned = f"Bước này là {label}. {self._navigation_instruction()}"
        payload = llm_payload(
            step_say=self.step.instruction,
            target_label=self.step.target_label,
            citation_quote=self.step.citation.quote,
            direction=self._place or self._last_direction,
            user_text=user_text,
        )
        if self._llm is None:
            self.egress.record("llm", payload, left_machine=False)
            return Speech(canned, "explain")
        if self._llm_consent is not True:
            if self._llm_consent is False:
                self.egress.record("llm", payload, left_machine=False)
                return Speech(canned, "explain")
            self._pending_llm_question = user_text
            return Speech(
                "Để trả lời câu hỏi mở, mình cần gửi câu bạn vừa nói cùng nội dung bước hiện tại "
                "tới dịch vụ AI OpenAI. Không gửi audio, DOM, mật khẩu hay ảnh. "
                "Bạn có đồng ý cho phiên này không? Nói đồng ý hoặc không gửi.",
                "privacy_notice",
                interruptible=False,
                dedupe_key="llm-consent",
            )
        if self._defer_llm:
            return Speech(user_text, "llm_request", priority=60)
        return self.complete_llm(user_text)

    def complete_llm(self, user_text: str) -> Speech:
        """Run the optional cloud explanation off the realtime audio loop."""

        label = self.step.target_label or "mục trong tài liệu"
        canned = f"Bước này là {label}. {self._navigation_instruction()}"
        payload = llm_payload(
            step_say=self.step.instruction,
            target_label=self.step.target_label,
            citation_quote=self.step.citation.quote,
            direction=self._place or self._last_direction,
            user_text=user_text,
        )
        if self._llm is None or self._llm_consent is not True:
            self.egress.record("llm", payload, left_machine=False)
            return Speech(canned, "explain")
        self.egress.record("llm", payload, left_machine=True)
        try:
            spoken = " ".join(self._llm(payload).split())
        except Exception:
            return Speech(canned, "explain")
        return Speech(spoken or canned, "explain")

    def stream_llm(self, user_text: str) -> Iterator[Speech]:
        """Yield checked clauses when the configured LLM supports SSE streaming."""

        payload = llm_payload(
            step_say=self.step.instruction,
            target_label=self.step.target_label,
            citation_quote=self.step.citation.quote,
            direction=self._place or self._last_direction,
            user_text=user_text,
        )
        if self._llm is None or self._llm_consent is not True:
            self.egress.record("llm", payload, left_machine=False)
            yield self.local_explanation()
            return
        streamer = getattr(self._llm, "stream", None)
        if streamer is None:
            yield self.complete_llm(user_text)
            return
        self.egress.record("llm", payload, left_machine=True)
        emitted = False
        try:
            for clause in streamer(payload):
                spoken = " ".join(str(clause).split())
                if spoken:
                    emitted = True
                    yield Speech(spoken, "explain", dedupe_key=f"llm:{spoken}")
        except Exception:
            if emitted:
                return
        if not emitted:
            yield self.local_explanation()

    def local_explanation(self) -> Speech:
        label = self.step.target_label or "mục trong tài liệu"
        return Speech(f"Bước này là {label}. {self._navigation_instruction()}", "explain")

    def _function_for(self, label: str) -> str:
        folded = " ".join(label.casefold().split())
        if not folded:
            return ""
        for name, function in self.plan.functions:
            if " ".join(name.casefold().split()) == folded:
                return function
        return ""

    def _named(self, label: str, *, detail: bool = False) -> str:
        """The control name, plus its prewritten meaning when one is configured."""

        function = _spoken(self._function_for(label)) if detail else ""
        if function:
            return f"{label}. {function}"
        return f"{label}."

    def _place_line(self, label: str) -> str:
        spoken = self._named(label)
        if self.speech_policy == "focus":
            if label.startswith("Type, hiện tại "):
                return (
                    f"{label}. Nhấn Enter để mở. Sau đó dùng mũi tên lên xuống, "
                    "nghe từng loại, rồi nhấn Enter để chọn."
                )
            if label.startswith("Type option, "):
                return f"{label}. Dùng mũi tên lên xuống; nhấn Enter để chọn loại này."
            if label == "Primary, đang chọn":
                return "Primary, đang chọn. Nhấn Enter để bỏ chọn."
            if label == "Primary, chưa chọn":
                return "Primary, chưa chọn. Nhấn Enter để chọn."
            if label == "Column name":
                return "Column name. Nhập tên cột, rồi nhấn Tab."
        binding = self._bindings.get(self.step.number)
        if binding and binding.status == "ambiguous" and label == binding.label:
            return f"{spoken} Có hai mục cùng tên. Mình không chọn hộ."
        if binding and binding.status == "bound" and label == binding.label and self._announces_target():
            if self.speech_policy == "focus":
                if binding.controls and binding.controls[0].tag in {"input", "textarea"}:
                    if self.step.success.kind == "input_value":
                        return f"Đã tới {label}. Nhập {self.step.success.value}, rồi nhấn Tab."
                    return f"Đã tới {label}. Làm theo hướng dẫn của bước này."
                return f"Đã tới {label}. Nhấn Enter."
            return f"{spoken} Enter."
        if self.speech_policy != "focus" or not self._announces_target():
            return ""
        return spoken

    def _needs_vision(self, binding: StepBinding) -> bool:
        key = (binding.step_number, binding.status, binding.label)
        return (
            self.vision_enabled
            and self._vision_consent is not False
            and self._binding_seen.get(key, 0) >= 2
            and self.step.number not in self._vision_requested_steps
        )

    def _request_vision(self, question: str) -> list[Speech]:
        if not self.vision_enabled:
            return [Speech("Vision đang tắt. Mình chỉ dùng thông tin DOM trên máy.", "vision_notice")]
        if self.step.sensitivity == "destructive":
            return [
                Speech(
                    "Mình không gửi ảnh ở bước có thao tác thay đổi dữ liệu. "
                    "Mình sẽ tiếp tục dùng DOM trên máy.",
                    "vision_notice",
                    interruptible=False,
                )
            ]
        if self._vision_consent is False:
            return [Speech("Bạn đã chọn không gửi ảnh. Mình tiếp tục dùng DOM trên máy.", "vision_notice")]
        if self._vision_consent is None:
            if self._pending_vision_question:
                return []
            self._pending_vision_question = question
            return [
                Speech(
                    "Mình cần gửi một ảnh màn hình đã che vùng nhạy cảm để mô tả trang. "
                    "Ảnh không được lưu. Nói đồng ý hoặc không gửi ảnh.",
                    "vision_notice",
                    interruptible=False,
                )
            ]
        self._vision_requested_steps.add(self.step.number)
        return [Speech(question, "vision_request", priority=65)]


def _spoken(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    if not cleaned:
        return ""
    if cleaned[-1] not in ".!?…":
        cleaned += "."
    return cleaned


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _wants_citation(norm: str) -> bool:
    return "tài liệu" in norm or "tai lieu" in norm or "bước này" in norm or "buoc nay" in norm


def _wants_learning_goal(norm: str) -> bool:
    return norm in {
        "mục tiêu bài học", "muc tieu bai hoc", "bài này học gì",
        "bai nay hoc gi", "tôi sẽ học gì", "toi se hoc gi",
    }


def _wants_learning_reason(norm: str) -> bool:
    return norm in {
        "tại sao học bài này", "tai sao hoc bai nay",
        "học cái này để làm gì", "hoc cai nay de lam gi",
        "bài này để làm gì", "bai nay de lam gi",
    }


def _wants_reflection(norm: str) -> bool:
    return norm in {
        "nhìn lại bài học", "nhin lai bai hoc", "tôi vừa học gì",
        "toi vua hoc gi", "câu hỏi nhìn lại", "cau hoi nhin lai",
    }


def _wants_transfer_task(norm: str) -> bool:
    return norm in {
        "bài tự luyện", "bai tu luyen", "luyện thêm", "luyen them",
        "tôi luyện gì tiếp", "toi luyen gi tiep",
    }


def _wants_success_evidence(norm: str) -> bool:
    return norm in {
        "làm sao biết tôi đã học được", "lam sao biet toi da hoc duoc",
        "bằng chứng thành công", "bang chung thanh cong",
        "tiêu chí hoàn thành", "tieu chi hoan thanh",
    }


def _wants_page_description(norm: str) -> bool:
    return "mô tả trang" in norm or "mo ta trang" in norm or "mô tả màn hình" in norm or "mo ta man hinh" in norm


def _wants_current_description(norm: str) -> bool:
    return norm in {"cái này là gì", "cai nay la gi", "đây là gì", "day la gi"}


def _wants_destination(norm: str) -> bool:
    return "tôi cần đi đâu" in norm or "toi can di dau" in norm or "đi đâu" == norm or "di dau" == norm


def _wants_location(norm: str) -> bool:
    return "tôi đang ở đâu" in norm or "toi dang o dau" in norm or norm in {"đang ở đâu", "dang o dau"}


def _accepts_vision(norm: str) -> bool:
    return norm in {"đồng ý", "dong y", "cho phép", "cho phep", "được", "duoc"}


def _declines_vision(norm: str) -> bool:
    return "không gửi" in norm or "khong gui" in norm or norm in {
        "không",
        "khong",
        "từ chối",
        "tu choi",
        "giữ nguyên",
        "giu nguyen",
    }


def _assist_request(norm: str) -> str | None:
    if "focus giúp" in norm or "tập trung giúp" in norm or "focus giup" in norm:
        return "focus"
    if "bấm giúp" in norm or "click giúp" in norm or "bam giup" in norm:
        return "click"
    return None


def _navigation_request(norm: str) -> str | None:
    if (
        "đi nút" in norm
        or "di nut" in norm
        or "mở danh sách điều khiển" in norm
        or "mo danh sach dieu khien" in norm
    ):
        return "coach_list"
    if norm in {"đọc", "doc", "đọc trang", "doc trang"}:
        return "native_focus"
    if "dùng chuột" in norm or "dung chuot" in norm:
        return "mouse_cue"
    return None


def _stop_guidance_intent(norm: str) -> bool:
    return norm in {
        "dừng",
        "dung",
        "dừng lại",
        "dung lai",
        "dừng hướng dẫn",
        "dung huong dan",
        "dừng và lưu tiến độ",
        "dung va luu tien do",
    }


def _lesson_done_intent(norm: str) -> bool:
    return norm in {
        "tôi đã hoàn thành bài học",
        "toi da hoan thanh bai hoc",
        "tôi hoàn thành bài học",
        "toi hoan thanh bai hoc",
        "hoàn thành bài học",
        "hoan thanh bai hoc",
    }


def _step_done_intent(norm: str) -> bool:
    return norm in {
        "xong bước này",
        "xong buoc nay",
        "tôi đã xong bước này",
        "toi da xong buoc nay",
        "tôi bấm rồi",
        "toi bam roi",
        "bấm rồi",
        "bam roi",
        "xong rồi",
        "xong roi",
    }


def _confirms_step_completion(norm: str) -> bool:
    return norm in {
        "tôi xác nhận xong bước này",
        "toi xac nhan xong buoc nay",
        "xác nhận xong bước này",
        "xac nhan xong buoc nay",
    }


def _confirms_lesson_completion(norm: str) -> bool:
    return norm in {
        "tôi xác nhận hoàn thành bài học",
        "toi xac nhan hoan thanh bai hoc",
        "xác nhận hoàn thành bài học",
        "xac nhan hoan thanh bai hoc",
    }


def _declines_completion(norm: str) -> bool:
    return norm in {
        "tiếp tục",
        "tiep tuc",
        "không",
        "khong",
        "chưa",
        "chua",
        "quay lại",
        "quay lai",
    }


def _wants_hint(norm: str) -> bool:
    return (
        "gợi ý" in norm
        or "goi y" in norm
        or "tôi không tới được" in norm
        or "toi khong toi duoc" in norm
    )
