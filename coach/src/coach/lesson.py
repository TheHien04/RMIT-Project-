"""Turn an onboarding PDF into a lesson whose labels are copied from the text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from coach.pdf_text import load_pages

_STEP_RE = re.compile(r"^Bước\s+(\d+)\.\s*(.+)$")
_DONE_RE = re.compile(r"^\[xong:\s*(.+)\]$")
_QUOTE_RE = re.compile(r"[\"“](.+?)[\"”]")


@dataclass(frozen=True)
class Citation:
    page: int
    quote: str


@dataclass(frozen=True)
class SuccessCheck:
    kind: str
    columns: tuple[str, ...] = ()
    value: str = ""

    def met(self, flags: dict) -> bool:
        if self.kind == "panel_open":
            return flags.get("panel") == "open"
        if self.kind == "saved":
            return bool(flags.get("saved"))
        if self.kind == "columns":
            have = {str(name) for name in flags.get("columns") or []}
            return set(self.columns).issubset(have)
        if self.kind == "url_contains":
            return self.value in str(flags.get("url") or "")
        if self.kind == "url_path":
            return urlsplit(str(flags.get("url") or "")).path == self.value
        if self.kind == "text_visible":
            return self.value.casefold() in {
                str(text).casefold() for text in flags.get("visible_text") or []
            }
        if self.kind == "focused_label":
            return self.value.casefold() == str(flags.get("focused") or "").casefold()
        return False


@dataclass(frozen=True)
class LessonStep:
    number: int
    instruction: str
    citation: Citation
    target_label: str | None
    needs_discovery: bool
    success: SuccessCheck
    module_title: str

    def __post_init__(self) -> None:
        if self.target_label and self.target_label not in self.citation.quote:
            raise ValueError("target label must be copied from the cited sentence")
        if self.needs_discovery and self.target_label:
            raise ValueError("a discovery step cannot carry a target label")


@dataclass(frozen=True)
class LessonPlan:
    title: str
    steps: tuple[LessonStep, ...]


def plan_from_pages(pages: list[str]) -> LessonPlan:
    if not pages:
        raise ValueError("the document has no pages")
    title = _module_title(pages)
    steps: list[LessonStep] = []
    for page_number, page in enumerate(pages, start=1):
        steps.extend(_steps_on_page(page, page_number, title))
    if not steps:
        raise ValueError("the document has no numbered steps")
    plan = LessonPlan(title=title, steps=tuple(steps))
    assert_grounded(plan, pages)
    return plan


def plan_from_pdf(path: str) -> LessonPlan:
    return plan_from_pages(load_pages(path))


def assert_grounded(plan: LessonPlan, pages: list[str]) -> None:
    blob = _normalize_grounding("\n".join(pages))
    for step in plan.steps:
        if _normalize_grounding(step.citation.quote) not in blob:
            raise ValueError(f"step {step.number} quotes text that is not in the document")
        if step.target_label and step.target_label not in step.citation.quote:
            raise ValueError(f"step {step.number} invented a target label")


def _normalize_grounding(text: str) -> str:
    """PDF extraction often wraps a visual sentence over multiple lines."""

    return " ".join(text.split())


def _module_title(pages: list[str]) -> str:
    for page in pages:
        for line in page.splitlines():
            cleaned = line.strip()
            if cleaned and not _STEP_RE.match(cleaned) and not _DONE_RE.match(cleaned):
                return cleaned
    return "Bài onboarding"


def _steps_on_page(page: str, page_number: int, title: str) -> list[LessonStep]:
    steps: list[LessonStep] = []
    instruction: list[str] = []
    number: int | None = None
    success: SuccessCheck | None = None

    def flush() -> None:
        nonlocal instruction, number, success
        if number is None:
            return
        quote = " ".join(part.strip() for part in instruction if part.strip())
        if not quote:
            raise ValueError(f"step {number} has no instruction")
        label = _first_quote(quote)
        steps.append(
            LessonStep(
                number=number,
                instruction=quote,
                citation=Citation(page=page_number, quote=quote),
                target_label=label,
                needs_discovery=label is None,
                success=success or SuccessCheck(kind="unverified"),
                module_title=title,
            )
        )
        instruction = []
        number = None
        success = None

    for raw in page.splitlines():
        line = raw.strip()
        if not line:
            continue
        step_match = _STEP_RE.match(line)
        if step_match:
            flush()
            number = int(step_match.group(1))
            instruction = [step_match.group(2).strip()]
            continue
        done_match = _DONE_RE.match(line)
        if done_match:
            if number is None:
                raise ValueError("a completion check appeared before its step")
            success = _parse_success(done_match.group(1).strip())
            continue
        if number is None:
            continue
        instruction.append(line)
    flush()
    return steps


def _first_quote(text: str) -> str | None:
    match = _QUOTE_RE.search(text)
    if not match:
        return None
    label = match.group(1).strip()
    return label or None


def _parse_success(text: str) -> SuccessCheck:
    if text == "panel tạo bảng đang mở":
        return SuccessCheck(kind="panel_open")
    if text == "bảng đã lưu":
        return SuccessCheck(kind="saved")
    prefix = "bảng có cột "
    if text.startswith(prefix):
        names = tuple(part.strip() for part in text[len(prefix) :].split(" và ") if part.strip())
        if not names:
            raise ValueError("column check does not name any column")
        return SuccessCheck(kind="columns", columns=names)
    url_prefix = "url chứa "
    if text.startswith(url_prefix):
        value = text[len(url_prefix) :].strip()
        if value:
            return SuccessCheck(kind="url_contains", value=value)
    exact_url_prefix = "url là "
    if text.startswith(exact_url_prefix):
        value = text[len(exact_url_prefix) :].strip()
        if value.startswith("/"):
            return SuccessCheck(kind="url_path", value=value)
    text_prefix = "thấy chữ "
    if text.startswith(text_prefix):
        value = text[len(text_prefix) :].strip().strip('"“”')
        if value:
            return SuccessCheck(kind="text_visible", value=value)
    focus_prefix = "focus ở "
    if text.startswith(focus_prefix):
        value = text[len(focus_prefix) :].strip().strip('"“”')
        if value:
            return SuccessCheck(kind="focused_label", value=value)
    raise ValueError(f"the document uses an unknown completion check: {text}")
