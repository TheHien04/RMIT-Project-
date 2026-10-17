from __future__ import annotations

import asyncio

from coach.browser_bridge import BrowserLessonBridge
from coach.cues import Box, Point
from coach.scene import PageScene, SceneConfidence, SceneControl
from coach.lesson import plan_from_pages, SuccessCheck
from coach.observer import Observation
from coach.pdf_text import ONBOARDING_PAGES
from coach.targets import VisionPolicy
from coach.targets import BrowserTarget


def test_browser_bridge_binds_div_controls_and_only_assists_on_request():
    async def run():
        plan = plan_from_pages(ONBOARDING_PAGES)
        bridge = BrowserLessonBridge(
            plan,
            loop=asyncio.get_running_loop(),
            poll_seconds=0.01,
            headed=False,
            vision_policy=VisionPolicy(allowed=True, overview_allowed=True),
        )
        bridge.start()
        try:
            update = await asyncio.wait_for(bridge.updates.get(), timeout=5)
            assert [binding.status for binding in update.bindings] == ["bound", "bound", "bound"]
            assert update.keys.index == -1
            assert update.keys.flags["panel"] == "closed"
            capture = bridge.capture_vision("Mô tả trang")
            assert capture is not None
            assert capture.scene.screenshot.startswith(b"\x89PNG")
            assert capture.candidate_labels == ("Tạo bảng", "Thêm cột", "Lưu bảng")

            # A focus request explicitly moves the coach marker; it does not click.
            assert bridge.focus("Tạo bảng")
            await asyncio.sleep(0.03)
            assert bridge.click("Tạo bảng")
            for _ in range(20):
                update = await asyncio.wait_for(bridge.updates.get(), timeout=2)
                if update.keys.flags["panel"] == "open":
                    break
            assert update.keys.flags["panel"] == "open"
            assert any(event["kind"] == "vision_capture" for event in bridge.audit.events)
        finally:
            bridge.close()

    asyncio.run(run())


def test_mouse_cues_only_start_after_a_real_pointer_move():
    async def run():
        bridge = BrowserLessonBridge(
            plan_from_pages(ONBOARDING_PAGES),
            loop=asyncio.get_running_loop(),
            poll_seconds=0.01,
            headed=False,
        )
        still = Observation(elements=(), cursor=Point(10, 10), focused_text="", flags={})
        moved = Observation(elements=(), cursor=Point(12, 10), focused_text="", flags={})
        assert bridge._mouse_moved(still) is False
        assert bridge._mouse_moved(still) is False
        assert bridge._mouse_moved(moved) is True

    asyncio.run(run())


def test_vision_capture_masks_sensitive_fields_and_does_not_log_content(page):
    page.set_content(
        '<input value="super-secret"><img class="private" '
        'src="data:image/svg+xml,<svg xmlns=\'http://www.w3.org/2000/svg\'></svg>">'
        '<button>Table Editor</button><button>private-table-name</button>'
    )
    plan = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".'])
    loop = asyncio.new_event_loop()
    try:
        bridge = BrowserLessonBridge(
            plan,
            loop=loop,
            poll_seconds=0.1,
            headed=False,
            vision_policy=VisionPolicy(
                allowed=True,
                overview_allowed=True,
                sensitive_selectors=("img.private",),
            ),
        )
        scene = PageScene(
            url=page.url,
            title="Supabase",
            focused_label="private-table-name",
            viewport=(1280, 800),
            controls=(
                SceneControl("Table Editor", "button", "native", Box(1, 2, 3, 4)),
                SceneControl("private-table-name", "button", "native", Box(5, 6, 7, 8)),
            ),
            visible_probe_values=(),
            confidence=SceneConfidence.MEDIUM,
        )
        capture = bridge._capture(page, scene, "Mô tả trang")
        assert capture.redaction_count == 2
        assert capture.scene.screenshot.startswith(b"\x89PNG")
        assert capture.candidate_labels == ("Table Editor",)
        assert capture.scene.focused_label == ""
        assert "private-table-name" not in str(
            capture.scene.safe_summary(allowed_labels=capture.candidate_labels)
        )
        assert page.locator("[data-coach-vision-mask]").count() == 0
        assert "super-secret" not in str(bridge.audit.events)
    finally:
        loop.close()


def test_vision_capture_rejects_a_stale_page_scene(page):
    page.set_content("<button>Table Editor</button>")
    plan = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".'])
    loop = asyncio.new_event_loop()
    try:
        bridge = BrowserLessonBridge(
            plan,
            loop=loop,
            poll_seconds=0.1,
            headed=False,
            vision_policy=VisionPolicy(allowed=True, overview_allowed=True),
        )
        stale = PageScene(
            url="https://supabase.com/dashboard/project/old",
            title="Old",
            focused_label="",
            viewport=(1280, 800),
            controls=(),
            visible_probe_values=(),
            confidence=SceneConfidence.MEDIUM,
        )
        assert bridge._capture(page, stale, "Mô tả trang") is None
        assert bridge.audit.events[-1]["summary"]["reason"] == "stale_or_unapproved_page"
    finally:
        loop.close()


def test_vision_capture_fails_closed_on_an_invalid_sensitive_selector(page):
    page.set_content("<button>Table Editor</button>")
    plan = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".'])
    loop = asyncio.new_event_loop()
    try:
        bridge = BrowserLessonBridge(
            plan,
            loop=loop,
            poll_seconds=0.1,
            headed=False,
            vision_policy=VisionPolicy(
                allowed=True,
                overview_allowed=True,
                sensitive_selectors=("[",),
            ),
        )
        scene = PageScene(
            url=page.url,
            title="Supabase",
            focused_label="",
            viewport=(1280, 800),
            controls=(SceneControl("Table Editor", "button", "native", Box(1, 2, 3, 4)),),
            visible_probe_values=(),
            confidence=SceneConfidence.MEDIUM,
        )
        assert bridge._capture(page, scene, "Mô tả trang") is None
        assert bridge.audit.events[-1]["summary"]["reason"] == "invalid_sensitive_selector"
        assert page.locator("[data-coach-vision-mask]").count() == 0
    finally:
        loop.close()


def test_dom_completion_probe_is_scoped_to_the_reviewed_selector(page):
    plan = plan_from_pages(['Bài\nBước 1. Mở "Name".'])
    plan = type(plan)(
        title=plan.title,
        steps=(
            type(plan.steps[0])(
                **{
                    **plan.steps[0].__dict__,
                    "success": SuccessCheck(
                        "selector_visible",
                        selector="[data-testid='table-name-input']",
                    ),
                }
            ),
        ),
    )
    loop = asyncio.new_event_loop()
    try:
        bridge = BrowserLessonBridge(plan, loop=loop, poll_seconds=0.1, headed=False)
        page.set_content("<p>Name</p>")
        assert bridge._reviewed_dom_probes(page) == []
        page.set_content('<input data-testid="table-name-input">')
        assert bridge._reviewed_dom_probes(page) == [plan.steps[0].success.probe_key]
    finally:
        loop.close()


def test_every_browser_command_fails_closed_when_scene_is_stale():
    class Page:
        url = "https://evil.example/redirected"

    class Controls:
        def __getattr__(self, _name):
            raise AssertionError("a stale command must not touch page controls")

    plan = plan_from_pages(['Bài\nBước 1. Mở "Table Editor".'])
    loop = asyncio.new_event_loop()
    try:
        bridge = BrowserLessonBridge(
            plan,
            loop=loop,
            poll_seconds=0.1,
            headed=False,
            target=BrowserTarget(
                cdp_url="http://127.0.0.1:9222",
                allowed_origins=("https://supabase.com",),
            ),
        )
        scene = PageScene(
            url="https://supabase.com/dashboard/project/demo",
            title="Supabase",
            focused_label="",
            viewport=(1280, 800),
            controls=(),
            visible_probe_values=(),
            confidence=SceneConfidence.HIGH,
        )
        for action in ("focus", "click", "navigation", "repair"):
            reply = __import__("queue").Queue(maxsize=1)
            bridge._commands.put((action, "Table Editor", reply))
            bridge._handle_commands(Controls(), Page(), scene)
            assert reply.get_nowait() is False
        assert [event["kind"] for event in bridge.audit.events].count("command_denied") == 4
    finally:
        loop.close()
