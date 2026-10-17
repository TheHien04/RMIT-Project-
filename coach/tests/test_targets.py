from __future__ import annotations

import json

import pytest

from coach.lesson import plan_from_pages
from coach.targets import BrowserTarget, TargetManifest


def test_external_target_requires_an_approved_exact_origin():
    target = BrowserTarget(
        cdp_url="http://127.0.0.1:9222",
        allowed_origins=("https://demo.supabase.com",),
    )
    assert target.permits("https://demo.supabase.com/project")
    assert not target.permits("https://evil.example/project")
    assert not BrowserTarget(cdp_url="http://127.0.0.1:9222").permits("https://demo.supabase.com")


def test_manifest_can_only_use_target_labels_quoted_in_the_pdf(tmp_path):
    plan = plan_from_pages(['Bài\nBước 1. Mở "Tạo dự án".'])
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "origins": ["https://demo.supabase.com"],
                "steps": [
                    {
                        "number": 1,
                        "target_label": "Tạo dự án",
                        "completion": {"kind": "url_contains", "value": "/project"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    applied = TargetManifest.load(path).apply(plan)
    assert applied.steps[0].success.met({"url": "https://demo.supabase.com/project"})

    path.write_text(
        json.dumps(
            {
                "origins": ["https://demo.supabase.com"],
                "steps": [{"number": 1, "target_label": "Xóa toàn bộ"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="copied from its PDF citation"):
        TargetManifest.load(path).apply(plan)


def test_new_completion_checks_are_local_and_exact():
    plan = plan_from_pages(
        [
            'Bài\n'
            'Bước 1. Mở "Tạo dự án".\n'
            '[xong: thấy chữ "Dự án đã tạo"]\n'
            'Bước 2. Mở "Tạo dự án".\n'
            '[xong: focus ở "Tạo dự án"]'
        ]
    )
    assert plan.steps[0].success.met({"visible_text": ["Dự án đã tạo"]})
    assert not plan.steps[0].success.met({"visible_text": ["dự án đã tạo khác"]})
    assert plan.steps[1].success.met({"focused": "Tạo dự án"})


def test_supabase_sidebar_meanings_are_preconfigured():
    from pathlib import Path

    from coach.lesson import plan_from_pdf

    root = Path(__file__).parents[1]
    manifest = TargetManifest.load(root / "fixtures" / "lessons" / "supabase-table-editor.json")
    plan = manifest.apply(
        plan_from_pdf(root / "fixtures" / "lessons" / "supabase-table-editor.pdf")
    )
    assert manifest.vision.allowed
    assert manifest.vision.overview_allowed
    assert manifest.accessibility.keyboard_repair_allowed
    assert plan.learning.bloom_level == "apply"
    assert "Tự điều hướng" in plan.learning.objective
    assert plan.learning.reflection_prompt
    assert plan.learning.transfer_task
    assert len(plan.learning.success_evidence) == 4
    assert "input" in manifest.vision.sensitive_selectors
    assert [label for label, _function in plan.functions] == [
        "Project Overview",
        "Table Editor",
        "Create a table",
        "Name",
        "Save",
        "SQL Editor",
        "Database",
        "Authentication",
        "Storage",
        "Edge Functions",
        "Realtime",
        "Advisors",
        "Observability",
        "Logs",
        "Integrations",
        "Project Settings",
    ]
    assert ("Table Editor", "thanh điều hướng project", "liên kết") in plan.control_hints
    assert (
        "Create a table",
        "vùng nội dung chính của Table Editor",
        "nút",
    ) in plan.control_hints
    assert [step.target_label for step in plan.steps] == [
        "Table Editor",
        "Create a table",
        "Name",
        "Save",
    ]
    assert plan.steps[1].success.kind == "selector_visible"
    assert plan.steps[1].success.selector == "[data-testid='table-name-input']"
    assert plan.steps[2].success.kind == "input_value"
    assert plan.steps[2].success.value == "coach_demo_tasks"
    assert plan.steps[2].success.selector == "[data-testid='table-name-input']"
    assert plan.steps[3].success.kind == "url_path_prefix_and_text"
    assert plan.steps[3].success.value == "coach_demo_tasks"
    assert plan.steps[3].success.path.endswith("/editor/")
    assert plan.steps[3].sensitivity == "destructive"
    assert all(not step.assist_click_allowed for step in plan.steps)


def test_url_path_probe_does_not_accept_a_child_route():
    plan = plan_from_pages(
        ['Bài\nBước 1. Mở "Project Overview".\n[xong: url là /dashboard/project/demo]']
    )
    success = plan.steps[0].success
    assert success.met({"url": "https://supabase.com/dashboard/project/demo"})
    assert not success.met({"url": "https://supabase.com/dashboard/project/demo/editor"})


@pytest.mark.parametrize("section,key", [("vision", "allowed"), ("accessibility", "keyboard_repair_allowed")])
def test_manifest_rejects_string_policy_booleans(tmp_path, section, key):
    raw = {
        "origins": ["https://demo.supabase.com"],
        section: {key: "false"},
        "steps": [],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON boolean"):
        TargetManifest.load(path)


def test_manifest_rejects_unknown_bloom_level(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "origins": ["https://demo.supabase.com"],
                "learning": {"bloom_level": "become-a-genius"},
                "steps": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="bloom_level"):
        TargetManifest.load(path)


def test_manifest_click_capability_is_explicit_and_defaults_closed(tmp_path):
    plan = plan_from_pages(['Bài\nBước 1. Mở "Tạo dự án".'])
    path = tmp_path / "manifest.json"
    base = {
        "origins": ["https://demo.supabase.com"],
        "steps": [{"number": 1, "target_label": "Tạo dự án"}],
    }
    path.write_text(json.dumps(base), encoding="utf-8")
    assert not TargetManifest.load(path).apply(plan).steps[0].assist_click_allowed

    base["steps"][0]["assist_click_allowed"] = True
    path.write_text(json.dumps(base), encoding="utf-8")
    assert TargetManifest.load(path).apply(plan).steps[0].assist_click_allowed
