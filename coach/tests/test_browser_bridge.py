from __future__ import annotations

import asyncio

from coach.browser_bridge import BrowserLessonBridge
from coach.cues import Point
from coach.lesson import plan_from_pages
from coach.observer import Observation
from coach.pdf_text import ONBOARDING_PAGES


def test_browser_bridge_binds_div_controls_and_only_assists_on_request():
    async def run():
        plan = plan_from_pages(ONBOARDING_PAGES)
        bridge = BrowserLessonBridge(
            plan,
            loop=asyncio.get_running_loop(),
            poll_seconds=0.01,
            headed=False,
        )
        bridge.start()
        try:
            update = await asyncio.wait_for(bridge.updates.get(), timeout=5)
            assert [binding.status for binding in update.bindings] == ["bound", "bound", "bound"]
            assert update.keys.index == -1
            assert update.keys.flags["panel"] == "closed"

            # A focus request explicitly moves the coach marker; it does not click.
            assert bridge.focus("Tạo bảng")
            await asyncio.sleep(0.03)
            assert bridge.click("Tạo bảng")
            for _ in range(20):
                update = await asyncio.wait_for(bridge.updates.get(), timeout=2)
                if update.keys.flags["panel"] == "open":
                    break
            assert update.keys.flags["panel"] == "open"
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
