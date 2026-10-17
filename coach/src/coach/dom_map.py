"""Bind lesson labels to clickable nodes. The model does not name buttons."""

from __future__ import annotations

from dataclasses import dataclass

from coach.cues import Box
from coach.lesson import LessonPlan

NATIVE_TAGS = frozenset({"button", "a", "input", "select", "textarea", "summary"})
POINTER_EVENTS = ("click", "mousedown", "pointerdown")

DETECT_JS = r"""
(() => {
  const native = new Set(["button", "a", "input", "select", "textarea", "summary"]);
  const roles = new Set(["button", "link"]);
  const events = ["click", "mousedown", "pointerdown"];
  const out = [];
  const seen = new Set();
  const accessibleName = (el) => {
    const aria = (el.getAttribute("aria-label") || "").trim();
    const title = (el.getAttribute("title") || "").trim();
    if (aria) return aria;
    if (el.labels && el.labels.length) {
      const label = [...el.labels].map((item) => item.innerText || "").join(" ").trim();
      if (label) return label;
    }
    const labelledBy = (el.getAttribute("aria-labelledby") || "").trim();
    if (labelledBy) {
      const label = labelledBy.split(/\s+/).map((id) => {
        const node = document.getElementById(id);
        return node ? (node.innerText || "") : "";
      }).join(" ").trim();
      if (label) return label;
    }
    const copy = el.cloneNode(true);
    copy.querySelectorAll?.('[aria-hidden="true"]').forEach((node) => node.remove());
    const text = (copy.textContent || "").trim();
    return text || title || (el.getAttribute("placeholder") || "").trim()
      || (el.getAttribute("name") || "").trim();
  };
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
  for (const [domOrder, el] of [...document.querySelectorAll("body *")].entries()) {
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
    const text = accessibleName(el);
    if (!text) continue;
    const key = [tag, text, Math.round(rect.x), Math.round(rect.y)].join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({
      id: controlId(el), text, tag, reason, domOrder,
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
({ enabled, expectedUrl, allowedOrigins }) => {
  const allowed = !allowedOrigins.length || allowedOrigins.some((item) => {
    if (item.startsWith('https://*.')) {
      return location.protocol === 'https:' && location.origin.endsWith(item.slice('https://*'.length));
    }
    return location.origin === item;
  });
  if ((expectedUrl && location.href !== expectedUrl) || !allowed) return false;
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
({ label, expectedUrl, allowedOrigins }) => {
  const allowed = !allowedOrigins.length || allowedOrigins.some((item) => {
    if (item.startsWith('https://*.')) {
      return location.protocol === 'https:' && location.origin.endsWith(item.slice('https://*'.length));
    }
    return location.origin === item;
  });
  if ((expectedUrl && location.href !== expectedUrl) || !allowed) return false;
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
({ id, action, label, expectedUrl, allowedOrigins }) => {
  const allowed = !allowedOrigins.length || allowedOrigins.some((item) => {
    if (item.startsWith('https://*.')) {
      return location.protocol === 'https:' && location.origin.endsWith(item.slice('https://*'.length));
    }
    return location.origin === item;
  });
  if ((expectedUrl && location.href !== expectedUrl) || !allowed) return false;
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
  if (action === "repair") {
    const native = new Set(["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"]);
    if (native.has(target.tagName)) return false;
    if (!target.hasAttribute("role")) target.setAttribute("role", "button");
    if (!target.hasAttribute("tabindex") || Number(target.getAttribute("tabindex")) < 0) {
      target.setAttribute("tabindex", "0");
    }
    if (!target.hasAttribute("aria-label") && label) target.setAttribute("aria-label", label);
    if (!target.dataset.coachKeyboardRepair) {
      target.dataset.coachKeyboardRepair = "1";
      target.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        event.stopPropagation();
        target.click();
      });
    }
    return target.getAttribute("role") === "button" && target.tabIndex === 0;
  }
  return false;
}
"""

TARGETED_REPAIR_JS = """
({ label, expectedUrl, allowedOrigins }) => {
  const allowed = !allowedOrigins.length || allowedOrigins.some((item) => {
    if (item.startsWith('https://*.')) {
      return location.protocol === 'https:' && location.origin.endsWith(item.slice('https://*'.length));
    }
    return location.origin === item;
  });
  if ((expectedUrl && location.href !== expectedUrl) || !allowed) return false;
  const wanted = String(label || "").trim();
  if (!wanted) return false;
  const native = new Set(["BUTTON", "A", "INPUT", "SELECT", "TEXTAREA", "SUMMARY"]);
  const visible = (el) => {
    const style = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden"
      && rect.width >= 1 && rect.height >= 1;
  };
  const exact = [...document.querySelectorAll("body *")].filter(
    (el) => visible(el) && (el.innerText || "").trim() === wanted
  );
  const candidates = new Set();
  for (const leaf of exact) {
    let candidate = null;
    for (let node = leaf; node && node !== document.body; node = node.parentElement) {
      const role = node.getAttribute("role");
      if (native.has(node.tagName) || role === "button" || role === "link") {
        candidate = null;
        break;
      }
      const style = getComputedStyle(node);
      const clickLike = style.cursor === "pointer"
        || node.hasAttribute("onclick")
        || node.hasAttribute("onmousedown")
        || node.hasAttribute("onpointerdown");
      // cursor is inherited, so keep walking to select the outer edge of the
      // click surface rather than turning its heading into a button.
      if (clickLike) candidate = node;
      else if (candidate) break;
    }
    if (candidate) candidates.add(candidate);
  }
  // Never guess when the same reviewed label identifies multiple cards.
  if (candidates.size !== 1) return false;
  const target = [...candidates][0];
  if (!target.hasAttribute("role")) target.setAttribute("role", "button");
  if (!target.hasAttribute("tabindex") || Number(target.getAttribute("tabindex")) < 0) {
    target.setAttribute("tabindex", "0");
  }
  if (!target.hasAttribute("aria-label")) target.setAttribute("aria-label", wanted);
  if (!target.dataset.coachKeyboardRepair) {
    target.dataset.coachKeyboardRepair = "1";
    target.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      event.stopPropagation();
      target.click();
    });
  }
  return target.getAttribute("role") === "button" && target.tabIndex === 0;
}
"""


FORM_ACCESSIBILITY_JS = """
() => {
  // This is a session-only compatibility layer for the reviewed Supabase
  // create-table form. It never fills a value or activates a control without
  // a key pressed by the learner.
  const inCreateTable = () => Boolean(document.querySelector('[data-testid="table-name-input"]'));
  const annotate = () => {
    if (!inCreateTable()) return;
    document.querySelectorAll('button[role="combobox"]').forEach((button) => {
      if (button.hasAttribute('aria-label')) return;
      const current = (button.innerText || '').replace(/\\s+/g, ' ').trim();
      if (current) button.setAttribute('aria-label', `Column type, current ${current}`);
    });
  };
  annotate();
  if (window.__coachFormAccessibilityV2Installed) return true;
  window.__coachFormAccessibilityV2Installed = true;
  window.__coachFormKeyAction = null;
  const focusNewColumnName = (before) => {
    const attempts = [0, 50, 150, 300];
    attempts.forEach((delay) => setTimeout(() => {
      const names = [...document.querySelectorAll('input[aria-label="Column name"]')];
      if (names.length > before && document.activeElement !== names[names.length - 1]) {
        names[names.length - 1].focus();
      }
      annotate();
    }, delay));
  };
  const refocusPrimary = (index) => {
    [0, 50, 150].forEach((delay) => setTimeout(() => {
      const boxes = [...document.querySelectorAll(
        'button[role="checkbox"][aria-label*="primary key"]'
      )];
      if (boxes[index] && document.activeElement !== boxes[index]) boxes[index].focus();
    }, delay));
  };
  window.addEventListener('keydown', (event) => {
    if (!inCreateTable()) return;
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (
      target.matches('button[role="checkbox"]')
      && (target.getAttribute('aria-label') || '').toLowerCase().includes('primary key')
    ) {
      const boxes = [...document.querySelectorAll(
        'button[role="checkbox"][aria-label*="primary key"]'
      )];
      const index = boxes.indexOf(target);
      if (event.key === ' ') {
        refocusPrimary(index);
        return;
      }
      if (event.key !== 'Enter') return;
      event.preventDefault();
      event.stopPropagation();
      window.__coachFormKeyAction = {
        kind: 'primary_enter',
        index,
        sequence: (window.__coachFormKeySequence = (window.__coachFormKeySequence || 0) + 1),
      };
      return;
    }
    if (
      event.key === 'Enter'
      && target.matches('button')
      && (target.innerText || '').trim() === 'Add column'
    ) {
      const before = document.querySelectorAll('input[aria-label="Column name"]').length;
      focusNewColumnName(before);
    }
  }, true);
  new MutationObserver(annotate).observe(document.documentElement, {subtree: true, childList: true});
  return true;
}
"""


READ_FORM_ACCESSIBILITY_ACTION_JS = """
() => {
  const action = window.__coachFormKeyAction || null;
  window.__coachFormKeyAction = null;
  return action;
}
"""


@dataclass(frozen=True)
class DetectedControl:
    text: str
    tag: str
    reason: str
    box: Box
    control_id: str = ""
    dom_order: int = -1


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
    if controls and all(control.dom_order >= 0 for control in controls):
        return tuple(sorted(controls, key=lambda control: control.dom_order))
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
    for index, item in enumerate(raw):
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
                dom_order=int(item.get("domOrder", index)),
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

    def install_form_accessibility(self) -> bool:
        """Install session-only keyboard and naming fixes for reviewed forms."""

        return bool(self.page.evaluate(FORM_ACCESSIBILITY_JS))

    def process_form_accessibility_action(self) -> str:
        """Translate a learner's Enter into the native key the widget supports."""

        action = self.page.evaluate(READ_FORM_ACCESSIBILITY_ACTION_JS)
        if not isinstance(action, dict) or action.get("kind") != "primary_enter":
            return ""
        self.page.keyboard.press("Space")
        return "primary_enter"

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

    def move_to(
        self,
        label: str,
        *,
        expected_url: str = "",
        allowed_origins: tuple[str, ...] = (),
    ) -> bool:
        """Assist focus only. The person still performs a native activation."""

        control = self._control_named(label)
        if control is None:
            return False
        if self.inject_navigation:
            return bool(
                self.page.evaluate(
                    MOVE_JS,
                    {
                        "label": label,
                        "expectedUrl": expected_url,
                        "allowedOrigins": list(allowed_origins),
                    },
                )
            )
        return self._action(
            control,
            "focus",
            expected_url=expected_url,
            allowed_origins=allowed_origins,
        )

    def click_label(
        self,
        label: str,
        *,
        expected_url: str = "",
        allowed_origins: tuple[str, ...] = (),
    ) -> bool:
        control = self._control_named(label)
        return bool(
            control
            and self._action(
                control,
                "click",
                expected_url=expected_url,
                allowed_origins=allowed_origins,
            )
        )

    def repair_label(
        self,
        label: str,
        *,
        expected_url: str = "",
        allowed_origins: tuple[str, ...] = (),
    ) -> bool:
        """Make one exact reviewed click-only target keyboard operable.

        This never focuses or activates the target. The learner still reaches
        it with Tab and activates it with Enter or Space.
        """

        control = self._control_named(label)
        if control is not None and control.reason in {"onclick", "click-listener"}:
            return self._action(
                control,
                "repair",
                label=label,
                expected_url=expected_url,
                allowed_origins=allowed_origins,
            )
        # React commonly delegates clicks to the document, so DevTools cannot
        # see a listener on the visual card itself. For an otherwise unbound
        # reviewed target, repair one uniquely named pointer surface only.
        return bool(
            self.page.evaluate(
                TARGETED_REPAIR_JS,
                {
                    "label": label,
                    "expectedUrl": expected_url,
                    "allowedOrigins": list(allowed_origins),
                },
            )
        )

    def set_navigation(
        self,
        enabled: bool,
        *,
        expected_url: str = "",
        allowed_origins: tuple[str, ...] = (),
    ) -> bool:
        if not self.inject_navigation:
            return False
        if not expected_url:
            self.install()
        return bool(
            self.page.evaluate(
                SET_NAVIGATION_JS,
                {
                    "enabled": enabled,
                    "expectedUrl": expected_url,
                    "allowedOrigins": list(allowed_origins),
                },
            )
        )

    def _control_named(self, label: str) -> DetectedControl | None:
        matches = [control for control in self.detect() if control.text.strip() == label.strip()]
        return matches[0] if len(matches) == 1 else None

    def _action(
        self,
        control: DetectedControl,
        action: str,
        *,
        label: str = "",
        expected_url: str = "",
        allowed_origins: tuple[str, ...] = (),
    ) -> bool:
        if not control.control_id:
            return False
        return bool(
            self.page.evaluate(
                CONTROL_ACTION_JS,
                {
                    "id": control.control_id,
                    "action": action,
                    "label": label,
                    "expectedUrl": expected_url,
                    "allowedOrigins": list(allowed_origins),
                },
            )
        )

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
