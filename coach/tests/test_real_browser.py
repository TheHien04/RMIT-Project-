from __future__ import annotations

import asyncio
import socket
from dataclasses import replace
from pathlib import Path

import pytest

from coach.__main__ import _background_server
from coach.browser_bridge import BrowserLessonBridge
from coach.lesson import SuccessCheck, plan_from_pages
from coach.session import LearningSession
from coach.targets import BrowserTarget


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _partner_plan():
    return plan_from_pages(
        [
            'Cổng đối tác\nBước 1. Mở "Tạo dự án".\n[xong: url chứa page=dashboard]',
        ]
    )


@pytest.mark.integration
def test_cdp_attach_observes_native_control_and_url_probe():
    async def scenario():
        from playwright.async_api import async_playwright

        directory = Path(__file__).parents[1] / "fixtures" / "web" / "partner"
        server, url = _background_server(0, directory=directory)
        port = _port()
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[f"--remote-debugging-port={port}"],
                )
                page = await browser.new_page()
                await page.goto(url + "/index.html")
                # Authentication is user-owned; the test performs it directly,
                # never through the bridge.
                await page.click("#manual-login")
                target = BrowserTarget(
                    cdp_url=f"http://127.0.0.1:{port}",
                    allowed_origins=(url,),
                    tab_title="Cổng đối tác",
                    navigation_mode="native_focus",
                )
                bridge = BrowserLessonBridge(
                    _partner_plan(),
                    loop=asyncio.get_running_loop(),
                    poll_seconds=0.01,
                    headed=False,
                    target=target,
                )
                bridge.start()
                try:
                    update = await asyncio.wait_for(bridge.updates.get(), timeout=5)
                    assert update.blocked_reason == ""
                    assert update.bindings[0].status == "bound"
                    assert update.bindings[0].controls[0].reason == "native"
                    session = LearningSession(_partner_plan())
                    session.start()
                    session.note_bindings(update.bindings)
                    assert session.on_page(
                        label=update.keys.label,
                        bump=update.keys.bump,
                        flags=update.keys.flags,
                    ) == []
                    # The learner performs the native action themselves.
                    await page.click("#create-project")
                    for _ in range(30):
                        update = await asyncio.wait_for(bridge.updates.get(), timeout=2)
                        if "page=dashboard" in update.keys.flags["url"]:
                            break
                    assert "page=dashboard" in update.keys.flags["url"]
                    assert _partner_plan().steps[0].success.met(update.keys.flags)
                    complete = session.on_page(
                        label=update.keys.label,
                        bump=update.keys.bump,
                        flags=update.keys.flags,
                    )
                    assert session.done
                    assert complete[0].text == "Xong bước 1. Bài học đã hoàn thành."
                    assert bridge.audit.events[0]["kind"] == "attached"
                finally:
                    bridge.close()
                await browser.close()
        finally:
            server.shutdown()

    asyncio.run(scenario())


@pytest.mark.integration
def test_cdp_roleless_control_needs_explicit_assist_or_coach_list():
    async def scenario():
        from playwright.async_api import async_playwright

        directory = Path(__file__).parents[1] / "fixtures" / "web" / "partner"
        server, url = _background_server(0, directory=directory)
        port = _port()
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[f"--remote-debugging-port={port}"],
                )
                page = await browser.new_page()
                await page.goto(url + "/roleless.html")
                plan = plan_from_pages(['Trang div-only\nBước 1. Mở "Mở bảng".\n[xong: thấy chữ "Bảng đã mở"]'])
                plan = replace(
                    plan,
                    steps=(
                        replace(
                            plan.steps[0],
                                assist_click_allowed=True,
                            success=SuccessCheck(
                                "text_visible",
                                value="Bảng đã mở",
                                selector="#result",
                            ),
                        ),
                    ),
                )
                bridge = BrowserLessonBridge(
                    plan,
                    loop=asyncio.get_running_loop(),
                    poll_seconds=0.01,
                    headed=False,
                    target=BrowserTarget(
                        cdp_url=f"http://127.0.0.1:{port}",
                        allowed_origins=(url,),
                        tab_title="div-only",
                        navigation_mode="coach_list",
                        inject_navigation=True,
                    ),
                )
                bridge.start()
                try:
                    update = await asyncio.wait_for(bridge.updates.get(), timeout=5)
                    assert update.bindings[0].status == "bound"
                    assert update.bindings[0].controls[0].reason == "click-listener"
                    session = LearningSession(
                        plan,
                        click=bridge.click,
                        set_navigation=bridge.set_navigation,
                        navigation_mode="coach_list",
                    )
                    session.start()
                    assert bridge.set_navigation(True)
                    # A synthetic click must come through the explicit voice
                    # command, never from detecting the div.
                    assert "Mình đã bấm Mở bảng." in session.on_user_text("bấm giúp")[0].text
                    for _ in range(30):
                        update = await asyncio.wait_for(bridge.updates.get(), timeout=2)
                        if plan.steps[0].success.probe_key in update.keys.flags["dom_probes"]:
                            break
                    assert plan.steps[0].success.met(update.keys.flags)
                    session.note_bindings(update.bindings)
                    session.on_page(
                        label=update.keys.label,
                        bump=update.keys.bump,
                        flags=update.keys.flags,
                    )
                    assert session.done
                    assert any(
                        event["summary"].get("action") == "click" and event["summary"]["allowed"]
                        for event in bridge.audit.events
                    )
                finally:
                    bridge.close()
                await browser.close()
        finally:
            server.shutdown()

    asyncio.run(scenario())


@pytest.mark.integration
def test_cdp_bridge_stops_observing_on_an_unapproved_origin():
    async def scenario():
        from playwright.async_api import async_playwright

        directory = Path(__file__).parents[1] / "fixtures" / "web" / "partner"
        server, url = _background_server(0, directory=directory)
        port = _port()
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[f"--remote-debugging-port={port}"],
                )
                page = await browser.new_page()
                await page.goto(url + "/index.html")
                bridge = BrowserLessonBridge(
                    _partner_plan(),
                    loop=asyncio.get_running_loop(),
                    poll_seconds=0.01,
                    headed=False,
                    target=BrowserTarget(
                        cdp_url=f"http://127.0.0.1:{port}",
                        allowed_origins=(url,),
                        tab_title="Cổng đối tác",
                    ),
                )
                bridge.start()
                try:
                    await asyncio.wait_for(bridge.updates.get(), timeout=5)
                    blocked_url = url.replace("127.0.0.1", "localhost") + "/index.html"
                    await page.goto(blocked_url)
                    for _ in range(30):
                        update = await asyncio.wait_for(bridge.updates.get(), timeout=2)
                        if update.blocked_reason:
                            break
                    assert update.blocked_reason == "Trang này không thuộc origin đã phê duyệt."
                    assert any(event["kind"] == "blocked_origin" for event in bridge.audit.events)
                finally:
                    bridge.close()
                await browser.close()
        finally:
            server.shutdown()

    asyncio.run(scenario())
