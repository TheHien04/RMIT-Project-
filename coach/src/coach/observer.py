"""Playwright view of a page that may have no accessibility roles."""

from __future__ import annotations

from dataclasses import dataclass

from coach.cues import Box, Point

INSTALL_JS = """
() => {
  if (window.__coachCursorInstalled) return;
  window.__coachCursorInstalled = true;
  window.__coachCursor = { x: null, y: null };
  document.addEventListener('mousemove', (event) => {
    window.__coachCursor = { x: event.clientX, y: event.clientY };
  }, true);
}
"""

SNAPSHOT_JS = """
() => {
  const nodes = [];
  document.querySelectorAll('[data-coach], button, a, input, select, textarea, [role="button"], [role="link"]').forEach((el) => {
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    const rect = el.getBoundingClientRect();
    if (rect.width < 1 || rect.height < 1) return;
    const text = (el.innerText || el.getAttribute('data-coach') || '').trim();
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
  const focused = active && active !== document.body
    ? (active.innerText || active.getAttribute('data-coach') || '').trim()
    : '';
  const columns = (document.body.dataset.columns || '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
  const cursor = window.__coachCursor || { x: null, y: null };
  return {
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
        if not self._installed:
            self.install()
        return observation_from_raw(self.page.evaluate(SNAPSHOT_JS))

    def focus_label(self, label: str) -> bool:
        return bool(self.page.evaluate(FOCUS_JS, label))

    def click_label(self, label: str) -> bool:
        return bool(self.page.evaluate(CLICK_JS, label))
