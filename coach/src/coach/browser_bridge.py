"""Threaded headed-browser bridge for the local voice lesson.

Playwright's sync API owns its thread. Pipecat owns the asyncio event loop.
This bridge is the narrow boundary between them: browser state flows to the
voice loop, and explicit assist requests flow back to the browser. The coach
never moves the learner's current control unless they explicitly ask.
"""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path

from coach.dom_map import KeyState, PageControls, StepBinding, bind_steps
from coach.agent_browser import AgentBrowserSnapshot
from coach.lesson import LessonPlan
from coach.observer import Observation, PageObserver
from coach.privacy import BrowserAudit
from coach.targets import BrowserTarget


@dataclass(frozen=True)
class BrowserUpdate:
    bindings: tuple[StepBinding, ...]
    keys: KeyState
    observation: Observation
    blocked_reason: str = ""
    mouse_moved: bool = False


class BrowserLessonBridge:
    """Host the sandbox and exchange page state with Pipecat safely."""

    def __init__(
        self,
        plan: LessonPlan,
        *,
        loop: asyncio.AbstractEventLoop,
        poll_seconds: float,
        headed: bool,
        target: BrowserTarget | None = None,
        audit: BrowserAudit | None = None,
    ) -> None:
        self._plan = plan
        self._loop = loop
        self._poll_seconds = poll_seconds
        self._headed = headed
        self._target = target or BrowserTarget()
        self.audit = audit or BrowserAudit()
        self.updates: asyncio.Queue[BrowserUpdate] = asyncio.Queue()
        self._commands: queue.Queue[tuple[str, str, queue.Queue[bool]]] = queue.Queue()
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._last_cursor: tuple[float, float] | None = None
        self._thread = threading.Thread(target=self._run, name="coach-browser", daemon=True)

    def start(self) -> None:
        self._thread.start()
        if not self._ready.wait(timeout=15):
            raise RuntimeError("browser coach did not start")
        if self._error is not None:
            raise RuntimeError("browser coach failed to start") from self._error

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=5)

    def focus(self, label: str) -> bool:
        return self._request("focus", label)

    def click(self, label: str) -> bool:
        return self._request("click", label)

    def set_navigation(self, enabled: bool) -> bool:
        return self._request("navigation", "on" if enabled else "off")

    def _request(self, action: str, label: str) -> bool:
        if self._stop.is_set():
            return False
        reply: queue.Queue[bool] = queue.Queue(maxsize=1)
        self._commands.put((action, label, reply))
        try:
            return reply.get(timeout=2)
        except queue.Empty:
            return False

    def _publish(self, update: BrowserUpdate) -> None:
        if not self._stop.is_set():
            self._loop.call_soon_threadsafe(self.updates.put_nowait, update)

    def _run(self) -> None:
        server = None
        try:
            from playwright.sync_api import sync_playwright

            from coach.__main__ import _background_server

            with sync_playwright() as playwright:
                if self._target.external:
                    browser = playwright.chromium.connect_over_cdp(self._target.cdp_url)
                    page = self._select_page(browser)
                    self.audit.record("attached", origin=_origin(page.url), external=True)
                    semantic = AgentBrowserSnapshot(
                        self._target.cdp_url,
                        target_id=self._target_id(page),
                        binary=self._target.agent_browser_bin,
                    )
                else:
                    server, url = _background_server(0)
                    browser = playwright.chromium.launch(headless=not self._headed)
                    page = browser.new_page(viewport={"width": 1280, "height": 800})
                    page.goto(url + "/?flow=div")
                    self.audit.record("attached", origin=_origin(page.url), external=False)
                    semantic = None
                page.bring_to_front()
                controls = PageControls(
                    page,
                    inject_navigation=(not self._target.external or self._target.inject_navigation),
                )
                if controls.inject_navigation:
                    controls.install()
                observer = PageObserver(page)
                observer.install()
                self._ready.set()
                while not self._stop.is_set():
                    if not self._target.permits(page.url):
                        self.audit.record("blocked_origin", origin=_origin(page.url))
                        self._publish(
                            BrowserUpdate(
                                bindings=(),
                                keys=KeyState("", "", -1, {"url": page.url}),
                                observation=observer.snapshot(),
                                blocked_reason="Trang này không thuộc origin đã phê duyệt.",
                            )
                        )
                        self._stop.wait(self._poll_seconds)
                        continue
                    self._handle_commands(controls)
                    detected = controls.refresh()
                    if semantic is not None:
                        detected = self._semantic_controls(detected, semantic)
                    observation = observer.snapshot()
                    raw_keys = controls.read()
                    flags = dict(observation.flags)
                    flags.update(
                        {
                            "url": page.url,
                            "focused": observation.focused_text,
                            "visible_text": self._visible_completion_text(page, detected),
                        }
                    )
                    keys = KeyState(
                        label=raw_keys.label if raw_keys.enabled else observation.focused_text,
                        bump=raw_keys.bump,
                        index=raw_keys.index,
                        flags=flags,
                        enabled=raw_keys.enabled,
                    )
                    self._publish(
                        BrowserUpdate(
                            bindings=bind_steps(self._plan, detected),
                            keys=keys,
                            observation=observation,
                            mouse_moved=self._mouse_moved(observation),
                        )
                    )
                    self._stop.wait(self._poll_seconds)
        except BaseException as error:
            self._error = error
            self._ready.set()
        finally:
            if server is not None:
                server.shutdown()

    def _select_page(self, browser):
        pages = [
            page
            for context in browser.contexts
            for page in context.pages
            if self._target.permits(page.url)
            and (not self._target.tab_title or self._target.tab_title.casefold() in page.title().casefold())
        ]
        if len(pages) != 1:
            raise RuntimeError(
                "Select exactly one approved authenticated tab before connecting the coach"
            )
        return pages[0]

    @staticmethod
    def _target_id(page) -> str:
        client = page.context.new_cdp_session(page)
        return str(client.send("Target.getTargetInfo")["targetInfo"]["targetId"])

    def _semantic_controls(self, detected, semantic: AgentBrowserSnapshot):
        accessible = {
            item.name.casefold()
            for item in semantic.controls()
            if item.role.casefold() in {"button", "link", "textbox", "combobox", "checkbox"}
        }
        if not accessible:
            self.audit.record("semantic_snapshot_unavailable", backend="agent-browser")
            return detected
        annotated = []
        for control in detected:
            if control.text.casefold() in accessible:
                annotated.append(replace(control, reason="accessibility"))
            elif control.reason in {"click-listener", "onclick"}:
                annotated.append(control)
        self.audit.record(
            "semantic_snapshot",
            backend="agent-browser",
            accessible_controls=len(accessible),
            fallback_controls=len(annotated) - sum(item.reason == "accessibility" for item in annotated),
        )
        return tuple(annotated)

    def _visible_completion_text(self, page, detected) -> list[str]:
        """Check only reviewed probe strings locally; never retain full page text."""

        reviewed = tuple(
            step.success.value
            for step in self._plan.steps
            if step.success.kind == "text_visible" and step.success.value
        )
        if not reviewed:
            return [control.text for control in detected]
        return list(
            page.evaluate(
                """(values) => {
                    const text = document.body.innerText || "";
                    return values.filter((value) => text.includes(value));
                }""",
                list(reviewed),
            )
        )

    def _mouse_moved(self, observation: Observation) -> bool:
        cursor = observation.cursor
        if cursor is None:
            self._last_cursor = None
            return False
        current = (cursor.x, cursor.y)
        previous = self._last_cursor
        self._last_cursor = current
        return previous is not None and current != previous

    def _handle_commands(self, controls: PageControls) -> None:
        while True:
            try:
                action, label, reply = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                if action == "focus":
                    result = controls.move_to(label)
                elif action == "click":
                    result = controls.click_label(label)
                elif action == "navigation":
                    result = controls.set_navigation(label == "on")
                else:
                    result = False
            except Exception:
                result = False
            self.audit.record("explicit_assist", action=action, label=label, allowed=result)
            reply.put(result)


def _origin(url: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"
