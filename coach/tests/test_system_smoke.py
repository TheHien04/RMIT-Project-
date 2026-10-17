from __future__ import annotations

from pathlib import Path

import pytest

from coach.cues import Box
from coach.dom_map import DetectedControl, bind_steps
from coach.lesson import plan_from_pdf
from coach.session import LearningSession
from coach.targets import TargetManifest


@pytest.mark.system
def test_supabase_navigation_lesson_completes_only_on_each_exact_reviewed_path():
    root = Path(__file__).parents[1]
    plan = TargetManifest.load(root / "fixtures" / "lessons" / "supabase-table-editor.json").apply(
        plan_from_pdf(root / "fixtures" / "lessons" / "supabase-table-editor.pdf")
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
        if step.success.kind == "url_path":
            flags = {"url": f"https://supabase.com{step.success.value}"}
        elif step.success.kind == "url_path_prefix":
            flags = {"url": f"https://supabase.com{step.success.value}created-table-id"}
        elif step.success.kind == "url_path_prefix_and_text":
            flags = {
                "url": f"https://supabase.com{step.success.path}created-table-id",
                "dom_probes": [step.success.probe_key],
            }
        elif step.success.kind == "selector_visible":
            flags = {"dom_probes": [step.success.probe_key]}
        elif step.success.kind == "text_visible":
            flags = {"visible_text": [step.success.value]}
        elif step.success.kind == "input_value":
            flags = (
                {"dom_probes": [step.success.probe_key]}
                if step.success.selector
                else {"input_values": [step.success.value]}
            )
        else:
            raise AssertionError(f"unsupported system probe: {step.success.kind}")
        speech = session.on_page(label=step.target_label or "", bump="", flags=flags)
        assert speech

    assert session.done
    assert session.on_user_text("bạn đã xong bài này") == []


@pytest.mark.system
def test_create_a_table_is_keyboard_repaired_and_advances_only_after_form_opens():
    root = Path(__file__).parents[1]
    plan = TargetManifest.load(root / "fixtures" / "lessons" / "supabase-table-editor.json").apply(
        plan_from_pdf(root / "fixtures" / "lessons" / "supabase-table-editor.pdf")
    )
    repaired = []
    session = LearningSession(
        plan,
        keyboard_repair_enabled=True,
        repair=lambda label: repaired.append(label) or True,
    )
    session.start()
    session.on_page(
        label="Table Editor",
        bump="",
        flags={"url": "https://supabase.com/dashboard/project/jpyjehpeqptponceofzt/editor"},
    )
    assert session.step.target_label == "Create a table"

    session.note_bindings(
        bind_steps(
            plan,
            (
                DetectedControl(
                    "Create a table",
                    "div",
                    "click-listener",
                    Box(798, 302, 452, 119),
                ),
            ),
        )
    )
    assert repaired == ["Create a table"]
    session.on_page(label="Create a table", bump="", flags={"visible_text": []})
    assert session.step.target_label == "Create a table"
    session.on_page(
        label="Create a table",
        bump="",
        flags={"dom_probes": [plan.steps[1].success.probe_key]},
    )
    assert session.step.target_label == "Name"
    session.on_page(
        label="Name",
        bump="",
        flags={"dom_probes": [plan.steps[2].success.probe_key]},
    )
    assert session.step.target_label == "Save"
    session.on_page(
        label="Save",
        bump="",
        flags={"url": "https://supabase.com/dashboard/project/jpyjehpeqptponceofzt/editor"},
    )
    assert not session.done
    session.on_page(
        label="Save",
        bump="",
        flags={
            "url": "https://supabase.com/dashboard/project/jpyjehpeqptponceofzt/editor/existing-table"
        },
    )
    assert not session.done
    session.on_page(
        label="Save",
        bump="",
        flags={
            "url": "https://supabase.com/dashboard/project/jpyjehpeqptponceofzt/editor/new-table-id",
            "dom_probes": [plan.steps[3].success.probe_key],
        },
    )
    assert session.done
