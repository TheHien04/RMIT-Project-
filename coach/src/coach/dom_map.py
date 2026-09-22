"""Bind lesson labels to clickable nodes. The model does not name buttons."""

from __future__ import annotations

from dataclasses import dataclass

from coach.cues import Box
from coach.lesson import LessonPlan

NATIVE_TAGS = frozenset({"button", "a", "input", "select", "textarea", "summary"})
POINTER_EVENTS = ("click", "mousedown", "pointerdown")

DETECT_JS = """
(() => {
  const native = new Set(["button", "a", "input", "select", "textarea", "summary"]);
  const roles = new Set(["button", "link"]);
  const events = ["click", "mousedown", "pointerdown"];
  const out = [];
  const seen = new Set();
  const controlId = (el) => {
    if (el.id) return `id:${el.id}`;
    const parts = [];
    let node = el;
    while (node && node !== document.body) {
      const siblings = [...node.parentElement.children].filter((item) => item.tagName === node.tagName);
      parts.unshift(`${node.tagName.toLowerCase()}:${siblings.indexOf(node)}`);
      node = node.parentElement;
    }
    return `path:${parts.join("/")}`;
  };
  for (const el of document.querySelectorAll("body *")) {
    const style = getComputedStyle(el);
    if (style.display === "none" || style.visibility === "hidden") continue;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) continue;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute("role");
    let reason = "";
    if (native.has(tag)) reason = "native";
    else if (role && roles.has(role)) reason = "role";
    else if (el.hasAttribute("onclick") || el.hasAttribute("onmousedown") || el.hasAttribute("onpointerdown")) {
      reason = "onclick";
    } else {
      let listeners = {};
      try { listeners = getEventListeners(el) || {}; } catch (error) { listeners = {}; }
      if (events.some((name) => listeners[name] && listeners[name].length)) reason = "click-listener";
    }
    if (!reason) continue;
    const text = (el.innerText || el.getAttribute("aria-label") || "").trim();
    if (!text) continue;
    const key = [tag, text, Math.round(rect.x), Math.round(rect.y)].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      id: controlId(el), text, tag, reason,
      x: rect.x, y: rect.y, width: rect.width, height: rect.height,
    });
  }
  return out;
})()
"""

INSTALL_KEYS_JS = """
() => {
  if (window.__coachKeysInstalled) return;
  window.__coachKeysInstalled = true;
  window.__coachKeys = { index: -1, bump: "", enabled: false };
  const style = document.createElement("style");
  style.id = "coach-place-style";
  style.textContent = '[data-coach-current="1"] { outline: 3px solid #0b5; outline-offset: 2px; }';
  document.head.appendChild(style);
  const ordered = () => [...document.querySelectorAll("[data-coach-key]")].sort(
    (a, b) => Number(a.dataset.coachKey) - Number(b.dataset.coachKey)
  );
  const paint = () => {
    const nodes = ordered();
    nodes.forEach((node) => node.removeAttribute("data-coach-current"));
    const keys = window.__coachKeys;
    if (keys.index >= 0 && keys.index < nodes.length) nodes[keys.index].dataset.coachCurrent = "1";
  };
  document.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    if (active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable)) {
      return;
    }
    const keys = window.__coachKeys;
    const nodes = ordered();
    if (!keys.enabled) return;
    if (event.key === "Escape") {
      keys.enabled = false;
      keys.bump = "reading";
    } else if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!nodes.length || keys.index >= nodes.length - 1) {
        keys.bump = "end";
        return;
      }
      keys.index += 1;
      keys.bump = "";
      paint();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (keys.index <= 0) {
        keys.bump = "start";
        return;
      }
      keys.index -= 1;
      keys.bump = "";
      paint();
    } else if ((event.key === "Enter" || event.key === " ") && keys.index >= 0 && nodes[keys.index]) {
      event.preventDefault();
      event.stopPropagation();
      nodes[keys.index].click();
    }
  }, true);
}
"""

SET_NAVIGATION_JS = """
(enabled) => {
  if (!window.__coachKeys) return false;
  window.__coachKeys.enabled = Boolean(enabled);
  window.__coachKeys.bump = "";
  if (!enabled) {
    document.querySelectorAll("[data-coach-current]").forEach((node) => node.removeAttribute("data-coach-current"));
  }
  return true;
}
"""

MARK_JS = """
(items) => {
  document.querySelectorAll("[data-coach-key]").forEach((el) => {
    el.removeAttribute("data-coach-key");
    el.removeAttribute("data-coach-current");
  });
  const nodes = [...document.querySelectorAll("body *")];
  items.forEach((item, index) => {
    const el = nodes.find((node) => {
      const rect = node.getBoundingClientRect();
      return node.tagName.toLowerCase() === item.tag
        && Math.abs(rect.x - item.x) < 2
        && Math.abs(rect.y - item.y) < 2;
    });
    if (el) el.dataset.coachKey = String(index);
  });
  const keys = window.__coachKeys;
  if (!keys) return;
  if (keys.index >= items.length) keys.index = items.length - 1;
  const current = document.querySelector(`[data-coach-key="${keys.index}"]`);
  if (current) current.dataset.coachCurrent = "1";
}
"""

READ_JS = """
() => {
  const keys = window.__coachKeys || { index: -1, bump: "" };
  const bump = keys.bump || "";
  keys.bump = "";
  const current = document.querySelector("[data-coach-current]");
  const columns = (document.body.dataset.columns || "").split(",").map((part) => part.trim()).filter(Boolean);
  return {
    label: current ? (current.innerText || "").trim() : "",
    bump,
    index: keys.index,
    enabled: Boolean(keys.enabled),
    flags: {
      panel: document.body.dataset.panel || "closed",
      columns,
      saved: document.body.dataset.saved === "true",
    },
  };
}
"""

MOVE_JS = """
(label) => {
  const el = [...document.querySelectorAll("[data-coach-key]")].find(
    (node) => (node.innerText || "").trim() === label
  );
  if (!el || !window.__coachKeys) return false;
  document.querySelectorAll("[data-coach-current]").forEach((node) => node.removeAttribute("data-coach-current"));
  el.dataset.coachCurrent = "1";
  window.__coachKeys.index = Number(el.dataset.coachKey);
  window.__coachKeys.bump = "";
  return true;
}
"""

CONTROL_ACTION_JS = """
({ id, action }) => {
  const controlId = (el) => {
    if (el.id) return `id:${el.id}`;
    const parts = [];
    let node = el;
    while (node && node !== document.body) {
      const siblings = [...node.parentElement.children].filter((item) => item.tagName === node.tagName);
      parts.unshift(`${node.tagName.toLowerCase()}:${siblings.indexOf(node)}`);
      node = node.parentElement;
    }
    return `path:${parts.join("/")}`;
  };
  const target = [...document.querySelectorAll("body *")].find((node) => controlId(node) === id);
  if (!target) return false;
  if (action === "focus") {
    if (!target.hasAttribute("tabindex")) target.tabIndex = -1;
    target.focus();
    return document.activeElement === target;
  }
  if (action === "click") {
    target.click();
    return true;
  }
  return false;
}
"""


@dataclass(frozen=True)
class DetectedControl:
    text: str
    tag: str
    reason: str
    box: Box
    control_id: str = ""


@dataclass(frozen=True)
class StepBinding:
    step_number: int
    label: str | None
    status: str
    controls: tuple[DetectedControl, ...]


@dataclass(frozen=True)
class KeyState:
    label: str
    bump: str
    index: int
    flags: dict
    enabled: bool = False


def order_controls(controls: tuple[DetectedControl, ...] | list[DetectedControl]) -> tuple[DetectedControl, ...]:
    return tuple(sorted(controls, key=lambda control: (control.box.y, control.box.x)))


def prefer_leaves(controls: tuple[DetectedControl, ...]) -> tuple[DetectedControl, ...]:
    """A parent that wraps a real control is not a second button."""

    kept: list[DetectedControl] = []
    for control in controls:
        wraps_another = any(
            other is not control and other.text != control.text and _contains(control.box, other.box)
            for other in controls
        )
        if not wraps_another:
            kept.append(control)
    return tuple(kept)


def bind_steps(plan: LessonPlan, controls: tuple[DetectedControl, ...] | list[DetectedControl]) -> tuple[StepBinding, ...]:
    ordered = prefer_leaves(order_controls(tuple(controls)))
    bindings: list[StepBinding] = []
    for step in plan.steps:
        if step.needs_discovery or not step.target_label:
            bindings.append(StepBinding(step.number, None, "discovery", ()))
            continue
        matches = tuple(control for control in ordered if control.text.strip() == step.target_label)
        if len(matches) == 1:
            status = "bound"
        elif not matches:
            status = "unbound"
        else:
            status = "ambiguous"
        bindings.append(StepBinding(step.number, step.target_label, status, matches))
    return tuple(bindings)


def resolve(binding: StepBinding, chosen: DetectedControl) -> StepBinding:
    """Pick one detected control. A name that was not on the page cannot win."""

    if binding.status != "ambiguous":
        raise ValueError("only an ambiguous binding can be resolved")
    if chosen not in binding.controls:
        raise ValueError("the choice must be one of the detected controls")
    return StepBinding(binding.step_number, binding.label, "bound", (chosen,))


def controls_from_raw(raw: list[dict]) -> tuple[DetectedControl, ...]:
    controls = []
    for item in raw:
        controls.append(
            DetectedControl(
                text=str(item.get("text") or "").strip(),
                tag=str(item.get("tag") or ""),
                reason=str(item.get("reason") or ""),
                box=Box(
                    x=float(item["x"]),
                    y=float(item["y"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                ),
                control_id=str(item.get("id") or ""),
            )
        )
    return prefer_leaves(order_controls(controls))


class PageControls:
    """List clickable nodes and let the person walk them. Nothing moves until a key."""

    def __init__(self, page, *, inject_navigation: bool = True) -> None:
        self.page = page
        self.inject_navigation = inject_navigation
        self._cdp = None

    def install(self) -> None:
        self.page.evaluate(INSTALL_KEYS_JS)
        self.refresh()

    def refresh(self) -> tuple[DetectedControl, ...]:
        controls = self.detect()
        if not self.inject_navigation:
            return controls
        self.page.evaluate(
            MARK_JS,
            [
                {
                    "text": control.text,
                    "tag": control.tag,
                    "id": control.control_id,
                    "x": control.box.x,
                    "y": control.box.y,
                }
                for control in controls
            ],
        )
        return controls

    def detect(self) -> tuple[DetectedControl, ...]:
        client = self._client()
        payload = client.send(
            "Runtime.evaluate",
            {
                "expression": DETECT_JS,
                "includeCommandLineAPI": True,
                "returnByValue": True,
            },
        )
        result = payload.get("result") or {}
        if result.get("subtype") == "error":
            raise RuntimeError(result.get("description") or "DOM detect failed")
        return controls_from_raw(list(result.get("value") or []))

    def read(self) -> KeyState:
        raw = self.page.evaluate(READ_JS)
        return KeyState(
            label=str(raw.get("label") or ""),
            bump=str(raw.get("bump") or ""),
            index=int(raw.get("index")),
            flags=dict(raw.get("flags") or {}),
            enabled=bool(raw.get("enabled")),
        )

    def move_to(self, label: str) -> bool:
        """Assist focus only. The person still performs a native activation."""

        control = self._control_named(label)
        if control is None:
            return False
        if self.inject_navigation:
            return bool(self.page.evaluate(MOVE_JS, label))
        return self._action(control, "focus")

    def click_label(self, label: str) -> bool:
        control = self._control_named(label)
        return bool(control and self._action(control, "click"))

    def set_navigation(self, enabled: bool) -> bool:
        if not self.inject_navigation:
            return False
        self.install()
        return bool(self.page.evaluate(SET_NAVIGATION_JS, enabled))

    def _control_named(self, label: str) -> DetectedControl | None:
        matches = [control for control in self.detect() if control.text.strip() == label.strip()]
        return matches[0] if len(matches) == 1 else None

    def _action(self, control: DetectedControl, action: str) -> bool:
        if not control.control_id:
            return False
        return bool(self.page.evaluate(CONTROL_ACTION_JS, {"id": control.control_id, "action": action}))

    def _client(self):
        if self._cdp is None:
            self._cdp = self.page.context.new_cdp_session(self.page)
        return self._cdp


def _contains(outer: Box, inner: Box) -> bool:
    return (
        outer.x <= inner.x
        and outer.y <= inner.y
        and outer.x + outer.width >= inner.x + inner.width
        and outer.y + outer.height >= inner.y + inner.height
        and (outer.width > inner.width or outer.height > inner.height)
    )
