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
from typing import Any

from coach.dom_map import KeyState, PageControls, StepBinding, bind_steps
from coach.agent_browser import AgentBrowserSnapshot
from coach.lesson import LessonPlan
from coach.observer import Observation, PageObserver
from coach.privacy import BrowserAudit
from coach.scene import PageScene, SceneConfidence, SceneControl, VisionRequest
from coach.targets import BrowserTarget, VisionPolicy


_MASK_JS = """
(selectors) => {
  const defaults = [
    'input', 'textarea', 'select', '[contenteditable="true"]', '[role="textbox"]',
    'iframe', 'canvas', 'video'
  ];
  const allSelectors = [...defaults, ...selectors];
  for (const selector of allSelectors) {
    try { document.querySelector(selector); }
    catch (error) { return {ok: false, count: 0, invalid: selector}; }
  }
  const roots = [document];
  for (let index = 0; index < roots.length; index += 1) {
    for (const node of roots[index].querySelectorAll('*')) {
      if (node.shadowRoot) roots.push(node.shadowRoot);
    }
  }
  const selected = [];
  for (const root of roots) {
    for (const selector of allSelectors) selected.push(...root.querySelectorAll(selector));
    let style = root.querySelector('#coach-vision-mask-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'coach-vision-mask-style';
      style.textContent = `
        [data-coach-vision-mask="1"], [data-coach-vision-mask="1"] * {
          visibility: hidden !important;
        }
      `;
      (root === document ? document.head : root).appendChild(style);
    }
  }
  const unique = [...new Set(selected)];
  unique.forEach((node) => node.setAttribute('data-coach-vision-mask', '1'));
  return {ok: true, count: unique.length, invalid: ''};
}
"""

_UNMASK_JS = """
() => {
  const roots = [document];
  for (let index = 0; index < roots.length; index += 1) {
    for (const node of roots[index].querySelectorAll('*')) {
      if (node.shadowRoot) roots.push(node.shadowRoot);
    }
  }
  for (const root of roots) {
    root.querySelectorAll('[data-coach-vision-mask]').forEach(
      (node) => node.removeAttribute('data-coach-vision-mask')
    );
    root.querySelector('#coach-vision-mask-style')?.remove();
  }
}
"""


@dataclass(frozen=True)
class BrowserUpdate:
    bindings: tuple[StepBinding, ...]
    keys: KeyState
    observation: Observation
    scene: PageScene | None = None
    blocked_reason: str = ""
    mouse_moved: bool = False
    observed_at: float = 0.0


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
        vision_policy: VisionPolicy | None = None,
        keyboard_repair: bool = False,
    ) -> None:
        self._plan = plan
        self._loop = loop
        self._poll_seconds = poll_seconds
        self._headed = headed
        self._target = target or BrowserTarget()
        self.audit = audit or BrowserAudit()
        self._vision_policy = vision_policy or VisionPolicy()
        self._keyboard_repair = keyboard_repair
        self.updates: asyncio.Queue[BrowserUpdate] = asyncio.Queue()
        self._commands: queue.Queue[tuple[str, str, queue.Queue[Any]]] = queue.Queue()
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

    def capture_vision(self, question: str) -> VisionRequest | None:
        result = self._request("capture", question, timeout=4)
        return result if isinstance(result, VisionRequest) else None

    def repair(self, label: str) -> bool:
        if not self._keyboard_repair:
            self.audit.record("accessibility_repair", label=label, allowed=False)
            return False
        return bool(self._request("repair", label))

    def _request(self, action: str, label: str, *, timeout: float = 2) -> Any:
        if self._stop.is_set():
            return False
        reply: queue.Queue[Any] = queue.Queue(maxsize=1)
        self._commands.put((action, label, reply))
        try:
            return reply.get(timeout=timeout)
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
                if self._keyboard_repair:
                    controls.install_form_accessibility()
                cached_detected = ()
                cached_scene_key = None
                self._ready.set()
                while not self._stop.is_set():
                    if not self._target.permits(page.url):
                        self.audit.record("blocked_origin", origin=_origin(page.url))
                        self._publish(
                            BrowserUpdate(
                                bindings=(),
                                keys=KeyState("", "", -1, {"url": page.url}),
                                # Do not evaluate or retain any DOM state after
                                # the tab leaves its approved origin.
                                observation=Observation((), None, "", {}),
                                blocked_reason="Trang này không thuộc origin đã phê duyệt.",
                                observed_at=time.monotonic(),
                            )
                        )
                        self._stop.wait(self._poll_seconds)
                        continue
                    try:
                        if self._keyboard_repair:
                            controls.install_form_accessibility()
                            remapped = controls.process_form_accessibility_action()
                            if remapped:
                                self.audit.record(
                                    "accessibility_key_remap",
                                    action=remapped,
                                    persisted=False,
                                    initiated_by="learner",
                                )
                        observation = observer.snapshot()
                    except Exception as error:
                        # A navigation can destroy the JavaScript execution
                        # context between the origin check and snapshot. Retry
                        # so the next iteration can enforce the new origin.
                        self.audit.record("browser_poll_retry", error=type(error).__name__)
                        self._stop.wait(self._poll_seconds)
                        continue
                    if not self._target.permits(page.url):
                        continue
                    scene_key = (page.url, observation.revision)
                    if scene_key != cached_scene_key:
                        cached_detected = controls.refresh()
                        if semantic is not None:
                            cached_detected = self._semantic_controls(cached_detected, semantic)
                        cached_scene_key = scene_key
                    detected = cached_detected
                    raw_keys = controls.read()
                    flags = dict(observation.flags)
                    flags.update(
                        {
                            "url": page.url,
                            "focused": observation.focused_text,
                            "dom_probes": self._reviewed_dom_probes(page),
                        }
                    )
                    keys = KeyState(
                        label=raw_keys.label if raw_keys.enabled else observation.focused_text,
                        bump=raw_keys.bump,
                        index=raw_keys.index,
                        flags=flags,
                        enabled=raw_keys.enabled,
                    )
                    scene = self._scene(page, observation, detected, ())
                    self._handle_commands(controls, page, scene)
                    self._publish(
                        BrowserUpdate(
                            bindings=bind_steps(self._plan, detected),
                            keys=keys,
                            observation=observation,
                            scene=scene,
                            mouse_moved=self._mouse_moved(observation),
                            observed_at=time.monotonic(),
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

    def _reviewed_dom_probes(self, page) -> list[str]:
        """Evaluate only manifest-scoped selectors and return opaque check keys."""

        checks = [
            {
                "key": step.success.probe_key,
                "kind": step.success.kind,
                "selector": step.success.selector,
                "value": step.success.value,
            }
            for step in self._plan.steps
            if step.success.selector
            and step.success.kind in {
                "selector_visible",
                "text_visible",
                "input_value",
                "url_path_prefix_and_text",
            }
        ]
        if not checks:
            return []
        return list(
            page.evaluate(
                """(checks) => {
                    const visible = (node) => {
                      const style = getComputedStyle(node);
                      const rect = node.getBoundingClientRect();
                      return style.display !== 'none' && style.visibility !== 'hidden'
                        && rect.width > 0 && rect.height > 0;
                    };
                    const normalizedText = (node) =>
                      String(node.innerText || node.textContent || '').replace(/\\s+/g, ' ').trim();
                    const matched = [];
                    for (const check of checks) {
                      let nodes = [];
                      try { nodes = [...document.querySelectorAll(check.selector)]; }
                      catch (_error) { continue; }
                      const ok = nodes.some((node) => {
                        if (!visible(node)) return false;
                        if (check.kind === 'selector_visible') return true;
                        if (check.kind === 'input_value') {
                          return !node.disabled && String(node.value || '') === check.value;
                        }
                        return normalizedText(node) === check.value;
                      });
                      if (ok) matched.push(check.key);
                    }
                    return matched;
                }""",
                checks,
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

    def _scene(self, page, observation, detected, visible_text) -> PageScene:
        bound_labels = {
            binding.label
            for binding in bind_steps(self._plan, detected)
            if binding.status == "bound" and binding.label
        }
        if not detected:
            confidence = SceneConfidence.LOW
        elif bound_labels:
            confidence = SceneConfidence.HIGH
        else:
            confidence = SceneConfidence.MEDIUM
        return PageScene(
            url=page.url,
            title=observation.title,
            focused_label=observation.focused_text,
            viewport=observation.viewport,
            controls=tuple(
                SceneControl(control.text, control.tag, control.reason, control.box)
                for control in detected
            ),
            visible_probe_values=tuple(str(value) for value in visible_text),
            confidence=confidence,
            revision=observation.revision,
        )

    def _capture(self, page, scene: PageScene, question: str) -> VisionRequest | None:
        if page.url != scene.url or not self._target.permits(page.url):
            self.audit.record("vision_denied", reason="stale_or_unapproved_page")
            return None
        lesson_labels = tuple(
            step.target_label for step in self._plan.steps if step.target_label
        )
        approved = {label.casefold() for label in lesson_labels}
        safe_scene = replace(
            scene,
            focused_label=(
                scene.focused_label if scene.focused_label.casefold() in approved else ""
            ),
            controls=tuple(
                control for control in scene.controls if control.label.casefold() in approved
            ),
        )
        crop = _crop_for_question(safe_scene, question)
        if not self._vision_policy.allowed or (crop is None and not self._vision_policy.overview_allowed):
            self.audit.record("vision_denied", reason="manifest_policy", path=safe_scene.path)
            return None
        if _vision_blocked(safe_scene.path):
            self.audit.record("vision_denied", reason="sensitive_route", path=safe_scene.path)
            return None
        redactions = 0
        try:
            mask_result = page.evaluate(_MASK_JS, list(self._vision_policy.sensitive_selectors))
            if not isinstance(mask_result, dict) or not mask_result.get("ok"):
                self.audit.record(
                    "vision_denied",
                    reason="invalid_sensitive_selector",
                    selector_chars=len(str((mask_result or {}).get("invalid", ""))),
                )
                return None
            redactions = int(mask_result.get("count", 0))
            if page.url != safe_scene.url or not self._target.permits(page.url):
                self.audit.record("vision_denied", reason="page_changed_during_redaction")
                return None
            clip = None
            if crop is not None:
                clip = {"x": crop[0], "y": crop[1], "width": crop[2], "height": crop[3]}
            png = page.screenshot(type="png", full_page=False, clip=clip)
            if page.url != safe_scene.url or not self._target.permits(page.url):
                self.audit.record("vision_denied", reason="page_changed_during_capture")
                return None
        finally:
            try:
                page.evaluate(_UNMASK_JS)
            except Exception:
                pass
        self.audit.record(
            "vision_capture",
            path=safe_scene.path,
            bytes=len(png),
            redactions=redactions,
            persisted=False,
        )
        return VisionRequest(
            scene=replace(safe_scene, screenshot=png),
            question=question,
            candidate_labels=tuple(control.label for control in safe_scene.controls),
            lesson_labels=lesson_labels,
            redaction_count=redactions,
            crop=crop,
        )

    def _handle_commands(self, controls: PageControls, page, scene: PageScene) -> None:
        while True:
            try:
                action, label, reply = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                current_allowed = page.url == scene.url and self._target.permits(page.url)
                if action != "capture" and not current_allowed:
                    self.audit.record(
                        "command_denied",
                        action=action,
                        reason="stale_or_unapproved_page",
                        origin=_origin(page.url),
                    )
                    result = False
                elif action == "focus":
                    result = controls.move_to(
                        label,
                        expected_url=scene.url,
                        allowed_origins=self._target.allowed_origins,
                    )
                elif action == "click":
                    result = controls.click_label(
                        label,
                        expected_url=scene.url,
                        allowed_origins=self._target.allowed_origins,
                    )
                elif action == "navigation":
                    result = controls.set_navigation(
                        label == "on",
                        expected_url=scene.url,
                        allowed_origins=self._target.allowed_origins,
                    )
                elif action == "capture":
                    result = self._capture(page, scene, label)
                elif action == "repair":
                    result = controls.repair_label(
                        label,
                        expected_url=scene.url,
                        allowed_origins=self._target.allowed_origins,
                    )
                else:
                    result = False
            except Exception:
                result = False
            if action == "repair":
                self.audit.record(
                    "accessibility_repair",
                    label=label,
                    allowed=bool(result),
                    persisted=False,
                    activated=False,
                )
            elif action != "capture":
                self.audit.record("explicit_assist", action=action, label=label, allowed=bool(result))
            reply.put(result)


def _origin(url: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _vision_blocked(path: str) -> bool:
    folded = path.casefold()
    return any(
        marker in folded
        for marker in (
            "/login",
            "/sign-in",
            "/auth/users",
            "/billing",
            "/members",
            "/settings/api",
            "/settings/team",
        )
    )


def _crop_for_question(scene: PageScene, question: str) -> tuple[int, int, int, int] | None:
    folded = question.casefold()
    matches = [control.box for control in scene.controls if control.label.casefold() in folded]
    if not matches:
        return None
    padding = 24
    left = max(0, int(min(box.x for box in matches) - padding))
    top = max(0, int(min(box.y for box in matches) - padding))
    right = min(scene.viewport[0], int(max(box.x + box.width for box in matches) + padding))
    bottom = min(scene.viewport[1], int(max(box.y + box.height for box in matches) + padding))
    if right <= left or bottom <= top:
        return None
    return left, top, right - left, bottom - top
