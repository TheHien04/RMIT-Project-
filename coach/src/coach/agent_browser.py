"""Read-only adapter for Vercel agent-browser's accessibility snapshot.

The coach never gives this process navigation or interaction commands. It is
used only to label controls that the browser already exposes accessibly. Plain
JavaScript divs are intentionally handled by the local CDP fallback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AccessibleControl:
    ref: str
    role: str
    name: str


class AgentBrowserSnapshot:
    def __init__(self, cdp_url: str, *, target_id: str = "", binary: str = "") -> None:
        self._cdp_url = cdp_url
        self._target_id = target_id
        self._binary = binary or shutil.which("agent-browser") or ""
        self._bound = False

    @property
    def available(self) -> bool:
        return bool(self._binary)

    def controls(self) -> tuple[AccessibleControl, ...]:
        if not self.available:
            return ()
        if self._target_id and not self._bound and not self._bind_target():
            return ()
        result = subprocess.run(
            [
                self._binary,
                "--cdp",
                _cdp_argument(self._cdp_url),
                "--session",
                "coach-observer",
                "--pin-tab",
                "snapshot",
                "-i",
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        if result.returncode != 0:
            return ()
        try:
            payload = json.loads(result.stdout)
            refs = payload.get("data", {}).get("refs", {})
        except (json.JSONDecodeError, AttributeError):
            return ()
        values: list[AccessibleControl] = []
        for ref, item in refs.items():
            name = str(item.get("name") or "").strip()
            role = str(item.get("role") or "").strip()
            if name and role:
                values.append(AccessibleControl(str(ref), role, name))
        return tuple(values)

    def _bind_target(self) -> bool:
        """Pin a preselected CDP target without ever opening or navigating tabs."""

        result = subprocess.run(
            [
                self._binary,
                "--cdp",
                _cdp_argument(self._cdp_url),
                "--session",
                "coach-observer",
                "tab",
                self._target_id,
                "--json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        self._bound = result.returncode == 0
        return self._bound


def _cdp_argument(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.hostname in {"127.0.0.1", "localhost"} and parsed.port:
        return str(parsed.port)
    return url
