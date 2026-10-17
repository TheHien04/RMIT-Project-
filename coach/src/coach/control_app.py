"""Loopback-only control panel for starting and stopping the voice coach."""

from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlparse

from coach.settings import ROOT, Settings
from coach.targets import BrowserTarget

APP_ROOT = ROOT / "control_app"
INSTANCE_FILE = ROOT / "state" / "control-app-instance.json"


@dataclass(frozen=True)
class BrowserReadiness:
    cdp_ready: bool
    tab_ready: bool
    message: str


class VoiceProcessManager:
    """Own exactly one voice subprocess and expose privacy-safe status."""

    def __init__(
        self,
        settings: Settings,
        *,
        popen: Callable[..., subprocess.Popen] = subprocess.Popen,
        browser_probe: Callable[[], BrowserReadiness] | None = None,
    ) -> None:
        self.settings = settings
        self._popen = popen
        self._can_adopt_browser = browser_probe is None
        self._browser_probe = browser_probe or self._probe_browser
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._state = "stopped"
        self._message = "Voice Coach đang tắt."
        self._started_at = ""
        self._stop_requested = False
        self._stop_thread: threading.Thread | None = None
        self._browser_process: subprocess.Popen | None = None
        self._browser_pid: int | None = None
        self._runtime_cdp_url = settings.cdp_url
        self._browser_cache: BrowserReadiness | None = None
        self._browser_checked_at = 0.0
        if self._can_adopt_browser:
            self._adopt_running_coach_chrome()

    def status(self) -> dict[str, object]:
        browser = self._browser_readiness()
        with self._lock:
            self._refresh_process_locked()
            return {
                "state": self._state,
                "message": self._message,
                "running": self._state in {"starting", "listening", "stopping"},
                "ready": self._state == "listening",
                "started_at": self._started_at,
                "browser": {
                    "cdp_ready": browser.cdp_ready,
                    "tab_ready": browser.tab_ready,
                    "message": browser.message,
                },
            }

    def start(self) -> dict[str, object]:
        browser = self._browser_readiness(force=True)
        if not browser.tab_ready:
            raise RuntimeError(browser.message)
        with self._lock:
            self._refresh_process_locked()
            if self._process is not None and self._process.poll() is None:
                return self.status()
            environment = os.environ.copy()
            environment["PYTHONUNBUFFERED"] = "1"
            if self._runtime_cdp_url:
                environment["COACH_CDP_URL"] = self._runtime_cdp_url
            try:
                self._process = self._popen(
                    [sys.executable, "-m", "coach", "live"],
                    cwd=str(ROOT),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
            except OSError as error:
                self._state = "error"
                self._message = "Không thể khởi động Voice Coach."
                raise RuntimeError(self._message) from error
            self._state = "starting"
            self._message = "Đang làm nóng micro và các model giọng nói."
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._stop_requested = False
            thread = threading.Thread(target=self._consume_output, daemon=True)
            thread.start()
            return self.status()

    def stop(self) -> dict[str, object]:
        with self._lock:
            self._refresh_process_locked()
            process = self._process
            if process is None or process.poll() is not None:
                self._state = "stopped"
                self._message = "Voice Coach đang tắt."
                return self.status()
            self._stop_requested = True
            self._state = "stopping"
            self._message = "Đang dừng Voice Coach và giải phóng micro."
            try:
                os.killpg(process.pid, signal.SIGINT)
            except (OSError, ProcessLookupError):
                process.send_signal(signal.SIGINT)
            if self._stop_thread is None or not self._stop_thread.is_alive():
                self._stop_thread = threading.Thread(
                    target=self._wait_for_stop,
                    args=(process,),
                    name="coach-voice-stop",
                )
                self._stop_thread.start()
            return self.status()

    def close(self) -> None:
        """Synchronously release microphone and app-owned browser processes."""

        self.stop()
        with self._lock:
            thread = self._stop_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=15)
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            self._signal_process(process, signal.SIGKILL)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        with self._lock:
            browser_process = self._browser_process
            self._browser_process = None
        if browser_process is not None and browser_process.poll() is None:
            self._signal_process(browser_process, signal.SIGTERM)
            try:
                browser_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._signal_process(browser_process, signal.SIGKILL)
                try:
                    browser_process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        elif self._browser_pid is not None:
            self._stop_adopted_browser()
        self._browser_pid = None

    def open_browser(self) -> dict[str, object]:
        readiness = self._browser_readiness(force=True)
        if readiness.cdp_ready:
            if not readiness.tab_ready:
                self._open_start_tab()
            return self.status()
        if self._can_adopt_browser and self._adopt_running_coach_chrome():
            return self.status()
        script = ROOT / "scripts" / "launch_coach_chrome.sh"
        if not script.is_file():
            raise RuntimeError("Không tìm thấy trình khởi động Chrome dành cho Coach.")
        try:
            environment = os.environ.copy()
            # Chrome owns the ephemeral-port allocation and records it in the
            # owner-only profile, eliminating the bind-close-launch race.
            environment["COACH_CDP_PORT"] = "0"
            environment["COACH_START_URL"] = self.settings.start_url
            self._runtime_cdp_url = ""
            self._browser_cache = None
            self._browser_process = self._popen(
                ["sh", str(script)],
                cwd=str(ROOT),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._browser_pid = self._browser_process.pid
            self._runtime_cdp_url = self._wait_for_spawned_cdp(self._browser_process.pid)
        except (OSError, RuntimeError) as error:
            process = self._browser_process
            if process is not None and process.poll() is None:
                self._signal_process(process, signal.SIGTERM)
            self._browser_process = None
            self._browser_pid = None
            self._runtime_cdp_url = ""
            raise RuntimeError("Không thể mở Chrome dành cho Coach.") from error
        return self.status()

    def _open_start_tab(self) -> None:
        if not self._runtime_cdp_url:
            return
        endpoint = self._runtime_cdp_url.rstrip("/") + "/json/new?" + quote(
            self.settings.start_url,
            safe="",
        )
        request = urllib.request.Request(endpoint, method="PUT")
        try:
            with urllib.request.urlopen(request, timeout=1.0):
                pass
        except (OSError, urllib.error.URLError):
            return
        self._browser_cache = None

    def _wait_for_spawned_cdp(self, expected_pid: int) -> str:
        active_port = self._coach_profile() / "DevToolsActivePort"
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            try:
                lines = active_port.read_text(encoding="utf-8").splitlines()
                port = int(lines[0])
                if not 1 <= port <= 65535:
                    raise ValueError("invalid DevTools port")
                result = subprocess.run(
                    ["ps", "-p", str(expected_pid), "-o", "command="],
                    capture_output=True,
                    text=True,
                    timeout=1,
                    check=False,
                )
                command = result.stdout.strip()
                profile = self._coach_profile()
                if (
                    result.returncode == 0
                    and "Google Chrome" in command
                    and f"--user-data-dir={profile}" in command
                    and "--remote-debugging-address=127.0.0.1" in command
                    and "--remote-debugging-port=0" in command
                ):
                    return f"http://127.0.0.1:{port}"
            except (OSError, ValueError, IndexError, subprocess.SubprocessError):
                pass
            time.sleep(0.05)
        raise RuntimeError("Chrome không công bố cổng DevTools an toàn.")

    @staticmethod
    def _coach_profile() -> Path:
        return Path(
            os.environ.get(
                "COACH_CHROME_PROFILE",
                str(Path.home() / "Library/Application Support/OnboardCoachChrome"),
            )
        ).resolve()

    def _adopt_running_coach_chrome(self) -> bool:
        """Recover a dedicated Chrome left alive after the control app restarted."""

        profile = self._coach_profile()
        lock = profile / "SingletonLock"
        try:
            lock_target = os.readlink(lock)
            pid_match = re.search(r"-(\d+)$", lock_target)
            if pid_match is None:
                return False
            pid = int(pid_match.group(1))
            result = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True,
                text=True,
                timeout=1,
                check=False,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return False
        command = result.stdout.strip()
        port_match = re.search(r"(?:^|\s)--remote-debugging-port=(\d+)(?:\s|$)", command)
        if (
            result.returncode != 0
            or "Google Chrome" not in command
            or f"--user-data-dir={profile}" not in command
            or "--remote-debugging-address=127.0.0.1" not in command
            or port_match is None
        ):
            return False
        port = int(port_match.group(1))
        if port == 0:
            try:
                port = int((profile / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()[0])
            except (OSError, ValueError, IndexError):
                return False
        if not 1 <= port <= 65535:
            return False
        cdp_url = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(cdp_url + "/json/version", timeout=0.7) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            return False
        if not isinstance(payload, dict) or not str(payload.get("Browser", "")).startswith("Chrome/"):
            return False
        self._runtime_cdp_url = cdp_url
        self._browser_pid = pid
        self._browser_cache = None
        return True

    def _stop_adopted_browser(self) -> None:
        pid = self._browser_pid
        if pid is None or not self._adopt_running_coach_chrome() or self._browser_pid != pid:
            return
        try:
            os.killpg(pid, signal.SIGTERM)
        except (OSError, ProcessLookupError):
            try:
                os.kill(pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                return

    def _consume_output(self) -> None:
        with self._lock:
            process = self._process
        if process is None or process.stdout is None:
            return
        for raw_line in process.stdout:
            line = _plain_log_line(raw_line)
            with self._lock:
                if process is not self._process:
                    return
                if "pipeline is now ready" in line.casefold():
                    self._state = "listening"
                    self._message = "Voice Coach đang nghe và sẵn sàng hướng dẫn."
                elif "readiness failed" in line.casefold():
                    self._state = "error"
                    self._message = _safe_runtime_error(line)
        with self._lock:
            self._refresh_process_locked()

    def _wait_for_stop(self, process: subprocess.Popen) -> None:
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            self._signal_process(process, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._signal_process(process, signal.SIGKILL)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        with self._lock:
            if process is self._process:
                self._refresh_process_locked()

    def _refresh_process_locked(self) -> None:
        if self._process is None:
            return
        return_code = self._process.poll()
        if return_code is None:
            return
        if self._stop_requested:
            self._state = "stopped"
            self._message = "Voice Coach đã dừng."
        elif return_code == 0:
            self._state = "completed"
            self._message = "Phiên hướng dẫn đã kết thúc."
        else:
            self._state = "error"
            if "readiness failed" not in self._message.casefold():
                self._message = "Voice Coach đã dừng do lỗi. Hãy kiểm tra Chrome rồi thử lại."
        self._process = None

    @staticmethod
    def _signal_process(process: subprocess.Popen, sig: signal.Signals) -> None:
        try:
            os.killpg(process.pid, sig)
        except (OSError, ProcessLookupError):
            if sig == signal.SIGTERM:
                process.terminate()
            elif sig == signal.SIGKILL:
                process.kill()
            else:
                process.send_signal(sig)

    def _browser_readiness(self, *, force: bool = False) -> BrowserReadiness:
        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._browser_cache is not None
                and now - self._browser_checked_at < 1.0
            ):
                return self._browser_cache
        readiness = self._browser_probe()
        with self._lock:
            self._browser_cache = readiness
            self._browser_checked_at = time.monotonic()
        return readiness

    def _probe_browser(self) -> BrowserReadiness:
        if not self._runtime_cdp_url:
            return BrowserReadiness(True, True, "Coach đang dùng trang thực hành local.")
        endpoint = self._runtime_cdp_url.rstrip("/") + "/json/list"
        try:
            with urllib.request.urlopen(endpoint, timeout=0.7) as response:
                tabs = json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError, urllib.error.URLError):
            return BrowserReadiness(
                False,
                False,
                "Chrome dành cho Coach chưa mở. Hãy chọn Mở Chrome Supabase.",
            )
        target_title = self.settings.target_tab_title.casefold()
        target = BrowserTarget(
            cdp_url=self._runtime_cdp_url,
            allowed_origins=self.settings.allowed_origins,
            tab_title=self.settings.target_tab_title,
        )
        for tab in tabs if isinstance(tabs, list) else []:
            title = str(tab.get("title", "")).casefold()
            url = str(tab.get("url", ""))
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
            title_matches = not target_title or target_title in title
            origin_matches = target.permits(url)
            if tab.get("type", "page") == "page" and title_matches and origin_matches:
                return BrowserReadiness(True, True, "Tab Supabase đã sẵn sàng.")
        return BrowserReadiness(
            True,
            False,
            "Chrome đã mở nhưng chưa có đúng tab Supabase. Hãy đăng nhập và mở project cần học.",
        )


class _ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        handler,
        manager: VoiceProcessManager,
        token: str,
        instance_nonce: str = "",
    ):
        super().__init__(address, handler)
        self.manager = manager
        self.token = token
        self.instance_nonce = instance_nonce
        self._request_slots = threading.BoundedSemaphore(16)

    def process_request(self, request, client_address) -> None:
        if not self._request_slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._request_slots.release()
            raise

    def process_request_thread(self, request, client_address) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._request_slots.release()


class _ControlHandler(SimpleHTTPRequestHandler):
    server: _ControlServer

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP_ROOT), **kwargs)

    def do_GET(self) -> None:
        if not self._valid_host():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Host không hợp lệ."})
            return
        if self.path == "/api/status":
            payload = self.server.manager.status()
            payload["token"] = self.server.token
            self._json(HTTPStatus.OK, payload)
            return
        if self.path == "/":
            self.path = "/index.html"
        if self.path not in {"/index.html", "/styles.css", "/app.js"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if not self._authorized():
            self._json(HTTPStatus.FORBIDDEN, {"error": "Yêu cầu không hợp lệ."})
            return
        actions = {
            "/api/voice/start": self.server.manager.start,
            "/api/voice/stop": self.server.manager.stop,
            "/api/browser/open": self.server.manager.open_browser,
        }
        action = actions.get(self.path)
        if action is None and self.path != "/api/app/quit":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Không tìm thấy thao tác."})
            return
        try:
            if self.path == "/api/app/quit":
                self.server.manager.close()
                payload = self.server.manager.status()
                payload["message"] = "Ứng dụng đã đóng và micro đã được giải phóng."
                self._json(HTTPStatus.OK, payload)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self._json(HTTPStatus.OK, action())
        except RuntimeError as error:
            self._json(HTTPStatus.CONFLICT, {"error": str(error), **self.server.manager.status()})

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        if self.server.instance_nonce:
            self.send_header("X-Coach-Instance", self.server.instance_nonce)
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        return

    def _authorized(self) -> bool:
        token = self.headers.get("X-Coach-Token", "")
        origin = self.headers.get("Origin", "")
        expected_origin = f"http://127.0.0.1:{self.server.server_address[1]}"
        localhost_origin = f"http://localhost:{self.server.server_address[1]}"
        return self._valid_host() and secrets.compare_digest(token, self.server.token) and (
            not origin or origin in {expected_origin, localhost_origin}
        )

    def _valid_host(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in {f"127.0.0.1:{port}", f"localhost:{port}"}

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_control_app(settings: Settings, *, port: int = 8787, open_window: bool = True) -> None:
    """Serve the control panel; a second launch simply reopens the existing UI."""

    url = f"http://127.0.0.1:{port}"
    manager = VoiceProcessManager(settings)
    token = secrets.token_urlsafe(32)
    instance_nonce = secrets.token_urlsafe(32)
    try:
        server = _ControlServer(
            ("127.0.0.1", port),
            _ControlHandler,
            manager,
            token,
            instance_nonce,
        )
    except OSError:
        try:
            expected = _read_instance_nonce(INSTANCE_FILE, port)
            with urllib.request.urlopen(url + "/api/status", timeout=0.8) as response:
                if not expected or not secrets.compare_digest(
                    response.headers.get("X-Coach-Instance", ""),
                    expected,
                ):
                    raise RuntimeError("Cổng Coach đang bị một tiến trình không xác định sử dụng.")
                if open_window:
                    webbrowser.open(url)
                return
        except (OSError, RuntimeError) as error:
            raise RuntimeError(f"Không thể mở Coach Companion tại cổng {port}.") from error
    _write_instance_nonce(INSTANCE_FILE, port, instance_nonce)
    if open_window:
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    finally:
        manager.close()
        server.server_close()
        _remove_instance_nonce(INSTANCE_FILE, port, instance_nonce)


def _write_instance_nonce(path: Path, port: int, nonce: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = -1
            json.dump({"port": port, "nonce": nonce, "pid": os.getpid()}, handle)
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_instance_nonce(path: Path, port: int) -> str:
    try:
        if path.stat().st_mode & 0o077:
            return ""
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("port", -1)) != port:
            return ""
        nonce = str(payload.get("nonce", ""))
        return nonce if len(nonce) >= 32 else ""
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return ""


def _remove_instance_nonce(path: Path, port: int, nonce: str) -> None:
    if secrets.compare_digest(_read_instance_nonce(path, port), nonce):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _plain_log_line(line: str) -> str:
    """Remove terminal color codes without retaining a transcript or DOM dump."""

    output: list[str] = []
    index = 0
    while index < len(line):
        if line[index] == "\x1b" and index + 1 < len(line) and line[index + 1] == "[":
            index += 2
            while index < len(line) and not line[index].isalpha():
                index += 1
            index += 1
            continue
        output.append(line[index])
        index += 1
    return "".join(output).strip()


def _safe_runtime_error(line: str) -> str:
    lowered = line.casefold()
    if "phowhisper" in lowered:
        return "PhoWhisper chưa sẵn sàng."
    if "smart turn" in lowered:
        return "Smart Turn chưa sẵn sàng."
    if "zerotts" in lowered:
        return "ZeroTTS chưa sẵn sàng."
    return "Một backend giọng nói chưa sẵn sàng."
