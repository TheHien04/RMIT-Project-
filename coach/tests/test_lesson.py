import dataclasses

from coach.lesson import LessonStep, plan_from_pages, plan_from_pdf
from coach.pdf_text import MISSING_LABEL_PAGES, ONBOARDING_PAGES, load_pages, write_lesson_pdf


def test_pdf_round_trip_keeps_quotes(tmp_path):
    path = tmp_path / "onboarding.pdf"
    write_lesson_pdf(path, ONBOARDING_PAGES)
    pages = load_pages(path)
    plan = plan_from_pages(pages)
    assert plan.title == "Hướng dẫn tạo bảng ca làm"
    assert [step.target_label for step in plan.steps] == ["Tạo bảng", "Thêm cột", "Lưu bảng"]
    assert plan.steps[0].citation.page == 1
    assert plan.steps[1].citation.page == 2
    assert plan.steps[1].success.columns == ("Ca", "Người")
    assert "selector" not in {field.name for field in dataclasses.fields(LessonStep)}
    assert plan_from_pdf(str(path)).steps[2].target_label == "Lưu bảng"


def test_missing_quote_does_not_invent_a_target():
    plan = plan_from_pages(MISSING_LABEL_PAGES)
    step = plan.steps[0]
    assert step.needs_discovery
    assert step.target_label is None
    assert step.instruction == "Tự tìm chỗ tạo bảng trên hệ thống."
