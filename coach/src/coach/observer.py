"""Playwright view of a page that may have no accessibility roles."""

from __future__ import annotations

from dataclasses import dataclass

from coach.cues import Box, Point

INSTALL_JS = """
() => {
  if (window.__coachCursorInstalled) return;
  window.__coachCursorInstalled = true;
  window.__coachCursor = { x: null, y: null };
  window.__coachRevision = 0;
  window.__coachFocusRevision = 0;
  const changed = () => { window.__coachRevision += 1; };
  document.addEventListener('mousemove', (event) => {
    window.__coachCursor = { x: event.clientX, y: event.clientY };
  }, true);
  document.addEventListener('focusin', () => { window.__coachFocusRevision += 1; }, true);
  new MutationObserver(changed).observe(document.documentElement, {
    subtree: true,
    childList: true,
    characterData: true,
    attributes: true,
    attributeFilter: [
      'hidden', 'class', 'style', 'role', 'tabindex', 'disabled', 'aria-hidden',
      'aria-label', 'aria-expanded', 'aria-selected', 'aria-checked',
      'aria-activedescendant', 'data-panel', 'data-columns', 'data-saved'
    ],
  });
  for (const name of ['pushState', 'replaceState']) {
    const original = history[name];
    history[name] = function(...args) {
      const result = original.apply(this, args);
      changed();
      return result;
    };
  }
  addEventListener('popstate', changed);
}
"""

SNAPSHOT_JS = r"""
() => {
  const nodes = [];
  const accessibleName = (el) => {
    const aria = (el.getAttribute('aria-label') || '').trim();
    const title = (el.getAttribute('title') || '').trim();
    if (aria) return aria;
    if (el.labels && el.labels.length) {
      const label = [...el.labels].map((item) => item.innerText || '').join(' ').trim();
      if (label) return label;
    }
    const labelledBy = (el.getAttribute('aria-labelledby') || '').trim();
    if (labelledBy) {
      const label = labelledBy.split(/\s+/).map((id) => {
        const node = document.getElementById(id);
        return node ? (node.innerText || '') : '';
      }).join(' ').trim();
      if (label) return label;
    }
    const copy = el.cloneNode(true);
    copy.querySelectorAll?.('[aria-hidden="true"]').forEach((node) => node.remove());
    const text = (copy.textContent || '').trim();
    return text || title || (el.getAttribute('placeholder') || '').trim()
      || (el.getAttribute('name') || '').trim();
  };
  document.querySelectorAll(
    '[data-coach], button, a, input, select, textarea, [role="button"], [role="link"], '
    + '[role="combobox"], [role="checkbox"], [role="option"], [role="switch"]'
  ).forEach((el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    const text = accessibleName(el) || (el.getAttribute('data-coach') || '').trim();
    nodes.push({
      text,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role'),
      tabIndex: el.tabIndex,
      x: rect.x,
      y: rect.y,
      width: rect.width,
      height: rect.height,
    });
  });
  const active = document.activeElement;
  const focusedDescription = (el) => {
    if (!el || el === document.body) return '';
    const activeId = (el.getAttribute('aria-activedescendant') || '').trim();
    if (activeId) {
      const option = document.getElementById(activeId);
      const optionName = option
        ? ((option.innerText || accessibleName(option)).replace(/\s+/g, ' ').trim())
        : '';
      if (optionName) return `Type option, ${optionName}`;
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    const aria = (el.getAttribute('aria-label') || '').trim();
    if (role === 'combobox' && el.tagName === 'BUTTON') {
      // The repair label describes the control; the visible text is the
      // currently selected value that the learner needs to hear.
      const current = (el.innerText || '').replace(/\s+/g, ' ').trim();
      if (current && !aria.toLowerCase().startsWith('schema')) return `Type, hiện tại ${current}`;
    }
    if (role === 'checkbox' && aria.toLowerCase().includes('primary key')) {
      return el.getAttribute('aria-checked') === 'true'
        ? 'Primary, đang chọn'
        : 'Primary, chưa chọn';
    }
    return accessibleName(el) || (el.getAttribute('data-coach') || '').trim();
  };
  const focused = focusedDescription(active);
  const columns = (document.body.dataset.columns || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
  const cursor = window.__coachCursor || { x: null, y: null };
  return {
    revision: window.__coachRevision || 0,
    focus_revision: window.__coachFocusRevision || 0,
    title: document.title || '',
    viewport: { width: innerWidth, height: innerHeight },
    cursor,
    focused_text: focused,
    elements: nodes,
    flags: {
      panel: document.body.dataset.panel || 'closed',
      columns,
      saved: document.body.dataset.saved === 'true',
    },
  };
}
"""

FOCUS_JS = """
(label) => {
  const nodes = [...document.querySelectorAll('[data-coach], button')];
  const el = nodes.find((node) => (node.innerText || '').trim() === label);
  if (!el) return false;
  if (!el.hasAttribute('tabindex')) el.tabIndex = -1;
  el.focus();
  return document.activeElement === el;
}
"""

CLICK_JS = """
(label) => {
  const nodes = [...document.querySelectorAll('[data-coach], button')];
  const el = nodes.find((node) => (node.innerText || '').trim() === label);
  if (!el) return false;
  el.click();
  return true;
}
"""


@dataclass(frozen=True)
class Element:
    text: str
    tag: str
    role: str | None
    tab_index: int
    box: Box


@dataclass(frozen=True)
class Observation:
    elements: tuple[Element, ...]
    cursor: Point | None
    focused_text: str
    flags: dict
    revision: int = 0
    title: str = ""
    viewport: tuple[int, int] = (0, 0)
    focus_revision: int = 0

    def element_named(self, label: str) -> Element | None:
        wanted = label.casefold().strip()
        for element in self.elements:
            if element.text.casefold().strip() == wanted:
                return element
        return None


def observation_from_raw(raw: dict) -> Observation:
    cursor_raw = raw.get("cursor") or {}
    cursor = None
    if cursor_raw.get("x") is not None and cursor_raw.get("y") is not None:
        cursor = Point(float(cursor_raw["x"]), float(cursor_raw["y"]))
    elements = []
    for item in raw.get("elements") or []:
        elements.append(
            Element(
                text=str(item.get("text") or ""),
                tag=str(item.get("tag") or ""),
                role=item.get("role"),
                tab_index=int(item.get("tabIndex") if item.get("tabIndex") is not None else -1),
                box=Box(
                    x=float(item["x"]),
                    y=float(item["y"]),
                    width=float(item["width"]),
                    height=float(item["height"]),
                ),
            )
        )
    flags = dict(raw.get("flags") or {})
    return Observation(
        elements=tuple(elements),
        cursor=cursor,
        focused_text=str(raw.get("focused_text") or ""),
        flags=flags,
        revision=int(raw.get("revision") or 0),
        focus_revision=int(raw.get("focus_revision") or 0),
        title=str(raw.get("title") or ""),
        viewport=(
            int((raw.get("viewport") or {}).get("width") or 0),
            int((raw.get("viewport") or {}).get("height") or 0),
        ),
    )


class PageObserver:
    """Read boxes and the cursor from a Playwright page. Works on unlabeled divs."""

    def __init__(self, page) -> None:
        self.page = page
        self._installed = False

    def install(self) -> None:
        self.page.evaluate(INSTALL_JS)
        self._installed = True

    def snapshot(self) -> Observation:
        if not self._installed or not self.page.evaluate("() => Boolean(window.__coachCursorInstalled)"):
            self.install()
        return observation_from_raw(self.page.evaluate(SNAPSHOT_JS))

    def focus_label(self, label: str) -> bool:
        return bool(self.page.evaluate(FOCUS_JS, label))

    def click_label(self, label: str) -> bool:
        return bool(self.page.evaluate(CLICK_JS, label))
