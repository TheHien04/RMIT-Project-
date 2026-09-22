from __future__ import annotations

from pathlib import Path

import pytest

from coach.lesson import plan_from_pdf
from coach.session import LearningSession
from coach.targets import TargetManifest


@pytest.mark.system
def test_supabase_navigation_lesson_completes_only_on_each_exact_reviewed_path():
    root = Path(__file__).parents[1]
    plan = TargetManifest.load(root / "fixtures" / "supabase-table-editor.json").apply(
        plan_from_pdf(root / "fixtures" / "supabase-table-editor.pdf")
    )
    session = LearningSession(plan)
    session.start()

    for index, step in enumerate(plan.steps):
        # A parent project URL is deliberately insufficient for every child
        # route, preventing a false pass when moving between Supabase sections.
        if index:
            wrong_path = "https://supabase.com/dashboard/project/jpyjehpeqptponceofzt/not-the-step"
            before = session.step_index
            session.on_page(label=step.target_label or "", bump="", flags={"url": wrong_path})
            assert session.step_index == before
        speech = session.on_page(
            label=step.target_label or "",
            bump="",
            flags={"url": f"https://supabase.com{step.success.value}"},
        )
        assert speech

    assert session.done
    assert session.on_user_text("bạn đã xong bài này") == []
