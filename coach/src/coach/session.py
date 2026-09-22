"""Lesson state machine. Direction cues are computed, not generated."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from coach.cues import CONFIRM_SECONDS, CueThrottle, Direction, cue_for, cue_line
from coach.dom_map import StepBinding
from coach.lesson import LessonPlan, LessonStep
from coach.observer import Observation
from coach.privacy import EgressLog, consider_icon, llm_payload


@dataclass(frozen=True)
class Speech:
    text: str
    kind: str


class LearningSession:
    def __init__(
        self,
        plan: LessonPlan,
        *,
        egress: EgressLog | None = None,
        focus: Callable[[str], bool] | None = None,
        click: Callable[[str], bool] | None = None,
        set_navigation: Callable[[bool], bool] | None = None,
        navigation_mode: str = "native_focus",
        llm: Optional[Callable[[dict], str]] = None,
        vision_enabled: bool = False,
    ) -> None:
        if not plan.steps:
            raise ValueError("the lesson has no steps")
        self.plan = plan
        self.egress = egress or EgressLog()
        self._focus = focus or (lambda _label: False)
        self._click = click or (lambda _label: False)
        self._set_navigation = set_navigation or (lambda _enabled: False)
        self.navigation_mode = navigation_mode
        self._llm = llm
        self.vision_enabled = vision_enabled
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

    @property
    def step(self) -> LessonStep:
        return self.plan.steps[self.step_index]

    @property
    def done(self) -> bool:
        return self.phase == "done"

    def on_user_text(self, text: str) -> list[Speech]:
        norm = _norm(text)
        if self.phase == "idle":
            if "bắt đầu" in norm or "hoc" in norm or "học" in norm:
                return self.start()
            return [Speech("Nói bắt đầu học để vào bài tạo bảng ca.", "status")]
        if self.phase == "done":
            return []
        if _wants_citation(norm):
            return [self._citation_speech()]
        if "không hiểu" in norm or "khong hieu" in norm:
            return [self._explain(text)]
        if "nhắc lại" in norm or "nhac lai" in norm:
            return [Speech(self.step.instruction, "repeat")]
        navigation = _navigation_request(norm)
        if navigation is not None:
            return self._navigation(navigation)
        assist = _assist_request(norm)
        if assist:
            return self._assist(assist)
        if _done_phrase(norm):
            return self._confirm()
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
        step = self.step
        return [
            Speech(
                f"Mình sẽ hướng dẫn module {step.module_title}. "
                "Bạn tự làm từng bước. Mình không bấm hộ trừ khi bạn nhờ.",
                "brief",
            ),
            Speech(f"Bước {step.number}. {step.instruction}", "step"),
            Speech(self._navigation_instruction(), "step"),
        ]

    def note_bindings(self, bindings: tuple[StepBinding, ...]) -> None:
        self._bindings = {binding.step_number: binding for binding in bindings}

    def attach_assist_actions(
        self,
        *,
        focus: Callable[[str], bool],
        click: Callable[[str], bool],
        set_navigation: Callable[[bool], bool] | None = None,
    ) -> None:
        """Attach the live page only after its browser thread is ready."""

        self._focus = focus
        self._click = click
        if set_navigation is not None:
            self._set_navigation = set_navigation

    def on_page(self, *, label: str, bump: str, flags: dict) -> list[Speech]:
        """Speak the control the person just reached. Do not move them."""

        if self.phase != "guiding":
            return []
        if self.step.success.met(flags):
            return self._advance()
        speeches: list[Speech] = []
        binding = self._bindings.get(self.step.number)
        if binding and binding.status == "unbound" and not self._said_unbound:
            self._said_unbound = True
            speeches.append(Speech(f"Mình không thấy {binding.label} trên trang.", "place"))
        if bump == "end":
            speeches.append(Speech("Hết danh sách.", "place"))
        elif bump == "start":
            speeches.append(Speech("Đầu danh sách.", "place"))
        if label and label != self._place:
            self._place = label
            speeches.append(Speech(self._place_line(label), "place"))
        return speeches

    def on_observation(self, observation: Observation, *, now: float) -> list[Speech]:
        if self.phase != "guiding":
            return []
        speeches: list[Speech] = []
        if observation.focused_text and observation.focused_text != self._last_focused:
            self._last_focused = observation.focused_text
            speeches.append(Speech(f"Đang ở {observation.focused_text}.", "focus"))
        if self.step.success.met(observation.flags):
            speeches.extend(self._advance())
            return speeches
        if self.step.needs_discovery or not self.step.target_label:
            if not self._said_discovery and self._throttle.allow(now):
                self._said_discovery = True
                speeches.append(
                    Speech(
                        "Tài liệu không chỉ nút nào. Mình sẽ không đoán tên control.",
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
        return [Speech("Ảnh control đã được đánh dấu là rời máy.", "vision")]

    def _confirm(self) -> list[Speech]:
        return [
            Speech(
                "Mình chưa thấy bước này xong trên trang. "
                f"Tiếp tục tới {self.step.target_label or 'control trong tài liệu'}.",
                "status",
            )
        ]

    def _advance(self) -> list[Speech]:
        finished = self.step.number
        self._assist_for = None
        self._throttle.reset()
        self._last_direction = None
        self._direction_spoken_at = None
        self._said_missing_cursor = False
        self._said_discovery = False
        self._said_unbound = False
        if self.step_index + 1 >= len(self.plan.steps):
            self.phase = "done"
            return [Speech(f"Xong bước {finished}. Bài học đã hoàn thành.", "done")]
        self.step_index += 1
        step = self.step
        return [
            Speech(f"Xong bước {finished}.", "status"),
            Speech(f"Bước {step.number}. {step.instruction}", "step"),
        ]

    def _assist(self, kind: str) -> list[Speech]:
        label = self.step.target_label
        if not label:
            return [Speech("Tài liệu không chỉ control nào để mình focus.", "assist")]
        self._assist_for = self.step_index
        if kind == "click":
            moved = self._click(label)
            verb = "bấm" if moved else "không bấm được"
            return [Speech(f"Mình đã {verb} {label}. Bước chưa xong cho đến khi trang đổi.", "assist")]
        moved = self._focus(label)
        if not moved:
            return [Speech(f"Mình không tới được {label}.", "assist")]
        self._place = label
        return [Speech(f"Mình đã tới {label}. Bạn tự bấm Enter.", "assist")]

    def _citation_speech(self) -> Speech:
        citation = self.step.citation
        return Speech(f"{citation.quote} Trang {citation.page}.", "citation")

    def _navigation(self, requested: str) -> list[Speech]:
        if requested == "coach_list":
            if not self._set_navigation(True):
                return [Speech("Trang này chỉ hỗ trợ Tab và screen reader, không có danh sách coach.", "status")]
            self.navigation_mode = "coach_list"
            return [
                Speech(
                    "Đi nút. Mũi tên đổi control. Enter để bấm. "
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
            return "Mũi tên để đi. Enter để bấm. Escape để đọc trang."
        if self.navigation_mode == "mouse_cue":
            return "Di chuột theo hướng mình nói. Bạn tự bấm khi tới nơi."
        return "Dùng Tab hoặc screen reader để tới control. Nói đi nút nếu trang không có accessibility layer."

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

        label = self.step.target_label or "control trong tài liệu"
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
        self.egress.record("llm", payload, left_machine=True)
        try:
            spoken = " ".join(self._llm(payload).split())
        except Exception:
            return Speech(canned, "explain")
        return Speech(spoken or canned, "explain")

    def _place_line(self, label: str) -> str:
        binding = self._bindings.get(self.step.number)
        if binding and binding.status == "ambiguous" and label == binding.label:
            return f"{label}. Hai control cùng tên. Mình không chọn hộ."
        if binding and binding.status == "bound" and label == binding.label:
            return f"{label}. Enter."
        return f"{label}."


def _norm(text: str) -> str:
    return " ".join(text.casefold().split())


def _wants_citation(norm: str) -> bool:
    return "tài liệu" in norm or "tai lieu" in norm or "bước này" in norm or "buoc nay" in norm


def _assist_request(norm: str) -> str | None:
    if "focus giúp" in norm or "tập trung giúp" in norm or "focus giup" in norm:
        return "focus"
    if "bấm giúp" in norm or "click giúp" in norm or "bam giup" in norm:
        return "click"
    return None


def _navigation_request(norm: str) -> str | None:
    if "đi nút" in norm or "di nut" in norm:
        return "coach_list"
    if norm in {"đọc", "doc", "đọc trang", "doc trang"}:
        return "native_focus"
    if "dùng chuột" in norm or "dung chuot" in norm:
        return "mouse_cue"
    return None


def _done_phrase(norm: str) -> bool:
    return "tôi bấm rồi" in norm or "bấm rồi" in norm or "toi bam roi" in norm or "xong rồi" in norm
