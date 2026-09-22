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


def test_url_path_probe_does_not_accept_a_child_route():
    plan = plan_from_pages(
        ['Bài\nBước 1. Mở "Project Overview".\n[xong: url là /dashboard/project/demo]']
    )
    success = plan.steps[0].success
    assert success.met({"url": "https://supabase.com/dashboard/project/demo"})
    assert not success.met({"url": "https://supabase.com/dashboard/project/demo/editor"})
