import io
import json
import signal
import threading
import urllib.error
import urllib.request
from types import SimpleNamespace

from coach.control_app import (
    BrowserReadiness,
    VoiceProcessManager,
    _ControlHandler,
    _ControlServer,
    _plain_log_line,
)
from coach.settings import load_settings


class _FakeProcess:
    pid = 987654

    def __init__(self, lines=()):
        self.stdout = io.StringIO("".join(lines))
        self.return_code = None
        self.signals = []

    def poll(self):
        return self.return_code

    def send_signal(self, value):
        self.signals.append(value)

    def wait(self, timeout=None):
        self.return_code = 0
        return 0

    def terminate(self):
        self.return_code = -15

    def kill(self):
        self.return_code = -9


def _settings(tmp_path):
    env = tmp_path / ".env"
    env.write_text("COACH_MIC=true\n", encoding="utf-8")
    return load_settings(env)


def test_control_app_starts_only_when_the_reviewed_browser_tab_is_ready(tmp_path):
    calls = []
    process = _FakeProcess(["PipelineWorker: pipeline is now ready.\n"])

    def popen(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    manager = VoiceProcessManager(
        _settings(tmp_path),
        popen=popen,
        browser_probe=lambda: BrowserReadiness(True, True, "Tab Supabase đã sẵn sàng."),
    )
    status = manager.start()

    assert status["state"] in {"starting", "listening"}
    assert calls[0][0][0][-3:] == ["-m", "coach", "live"]
    assert calls[0][1]["start_new_session"] is True
    for thread in threading.enumerate():
        if thread.daemon and thread is not threading.current_thread():
            thread.join(timeout=0.05)
    assert manager.status()["state"] == "listening"


def test_control_app_refuses_to_start_without_the_supabase_tab(tmp_path):
    manager = VoiceProcessManager(
        _settings(tmp_path),
        popen=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not launch")),
        browser_probe=lambda: BrowserReadiness(
            True,
            False,
            "Chrome đã mở nhưng chưa có đúng tab Supabase.",
        ),
    )

    try:
        manager.start()
    except RuntimeError as error:
        assert "chưa có đúng tab Supabase" in str(error)
    else:
        raise AssertionError("start must require the reviewed tab")


def test_open_browser_passes_the_reviewed_start_url(tmp_path, monkeypatch):
    calls = []
    process = _FakeProcess()
    manager = VoiceProcessManager(
        _settings(tmp_path),
        popen=lambda *args, **kwargs: calls.append((args, kwargs)) or process,
        browser_probe=lambda: BrowserReadiness(False, False, "Chrome chưa mở."),
    )
    monkeypatch.setattr(manager, "_wait_for_spawned_cdp", lambda _pid: "http://127.0.0.1:49173")

    manager.open_browser()

    args, kwargs = calls[0]
    assert args[0][0] == "sh"
    assert kwargs["env"]["COACH_CDP_PORT"] == "0"
    assert kwargs["env"]["COACH_START_URL"] == "https://supabase.com/dashboard"


def test_control_app_recovers_the_dedicated_chrome_port_after_restart(tmp_path, monkeypatch):
    profile = tmp_path / "coach-profile"
    profile.mkdir()
    (profile / "SingletonLock").symlink_to("test-host-4242")
    env = tmp_path / ".env"
    env.write_text("COACH_ALLOWED_ORIGINS=https://supabase.com\n", encoding="utf-8")
    monkeypatch.setenv("COACH_CHROME_PROFILE", str(profile))
    monkeypatch.setattr(
        "coach.control_app.subprocess.run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=0,
            stdout=(
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome "
                "--remote-debugging-address=127.0.0.1 --remote-debugging-port=53586 "
                f"--user-data-dir={profile.resolve()}"
            ),
        ),
    )

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def urlopen(url, **_kwargs):
        if str(url).endswith("/json/version"):
            return Response({"Browser": "Chrome/155"})
        return Response(
            [{"type": "page", "title": "Coach Demo | Supabase", "url": "https://supabase.com/dashboard/project/demo"}]
        )

    monkeypatch.setattr("coach.control_app.urllib.request.urlopen", urlopen)
    manager = VoiceProcessManager(load_settings(env))

    status = manager.status()
    assert manager._runtime_cdp_url == "http://127.0.0.1:53586"
    assert status["browser"]["tab_ready"] is True


def test_control_app_status_never_exposes_voice_output(tmp_path):
    process = _FakeProcess(["ZeroTTSService: Generating TTS [secret page content]\n"])
    manager = VoiceProcessManager(
        _settings(tmp_path),
        popen=lambda *args, **kwargs: process,
        browser_probe=lambda: BrowserReadiness(True, True, "ready"),
    )
    manager.start()
    status = manager.status()
    serialized = str(status)
    assert "secret page content" not in serialized
    assert set(status) == {"state", "message", "running", "ready", "started_at", "browser"}


def test_terminal_color_codes_are_removed_from_readiness_lines():
    assert _plain_log_line("\x1b[32mPipeline ready\x1b[0m\r\n") == "Pipeline ready"


def test_control_app_close_reaps_the_voice_process(tmp_path, monkeypatch):
    process = _FakeProcess()
    manager = VoiceProcessManager(
        _settings(tmp_path),
        popen=lambda *args, **kwargs: process,
        browser_probe=lambda: BrowserReadiness(True, True, "ready"),
    )
    monkeypatch.setattr(
        "coach.control_app.os.killpg",
        lambda *_args: (_ for _ in ()).throw(ProcessLookupError()),
    )
    manager.start()
    manager.close()
    assert signal.SIGINT in process.signals
    assert process.poll() == 0
    assert manager.status()["running"] is False


def test_control_readiness_uses_wildcard_origin_matching(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(
        "COACH_CDP_URL=http://127.0.0.1:9222\n"
        "COACH_ALLOWED_ORIGINS=https://*.example.com\n"
        "COACH_START_URL=https://app.example.com/project\n",
        encoding="utf-8",
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                [{"type": "page", "title": "Demo", "url": "https://app.example.com/project"}]
            ).encode("utf-8")

    monkeypatch.setattr("coach.control_app.urllib.request.urlopen", lambda *_a, **_k: Response())
    manager = VoiceProcessManager(load_settings(env))
    assert manager.status()["browser"]["tab_ready"] is True


class _StubManager:
    def status(self):
        return {
            "state": "stopped",
            "message": "Voice Coach đang tắt.",
            "running": False,
            "ready": False,
            "started_at": "",
            "browser": {
                "cdp_ready": True,
                "tab_ready": True,
                "message": "Tab Supabase đã sẵn sàng.",
            },
        }

    def start(self):
        raise RuntimeError("Hãy mở đúng tab Supabase trước.")

    def stop(self):
        return self.status()

    def open_browser(self):
        return self.status()


def _control_server():
    server = _ControlServer(("127.0.0.1", 0), _ControlHandler, _StubManager(), "test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_control_api_rejects_dns_rebinding_host_header():
    server, url = _control_server()
    try:
        request = urllib.request.Request(url + "/api/status", headers={"Host": "attacker.test"})
        try:
            urllib.request.urlopen(request, timeout=2)
        except urllib.error.HTTPError as error:
            assert error.code == 403
        else:
            raise AssertionError("an untrusted Host header must be rejected")
    finally:
        server.shutdown()
        server.server_close()


def test_control_ui_is_semantic_and_responsive(browser):
    server, url = _control_server()
    page = browser.new_page(viewport={"width": 375, "height": 812})
    try:
        page.goto(url)
        page.get_by_role("button", name="Bắt đầu hướng dẫn").wait_for()
        assert page.get_by_role("heading", level=1).count() == 1
        assert page.locator('[role="status"]').count() == 1
        assert page.get_by_role("button", name="Bắt đầu hướng dẫn").get_attribute("aria-pressed") == "false"
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        box = page.get_by_role("button", name="Bắt đầu hướng dẫn").bounding_box()
        assert box is not None and box["height"] >= 100 and box["width"] >= 300
        page.get_by_role("button", name="Thoát ứng dụng").click()
        dialog = page.get_by_role("dialog", name="Thoát Coach Companion?")
        assert dialog.is_visible()
        assert page.get_by_role("button", name="Thoát an toàn").is_visible()
        page.get_by_role("button", name="Ở lại").click()
        assert dialog.is_hidden()
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_primary_voice_action_is_visible_above_the_desktop_fold(browser):
    server, url = _control_server()
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    try:
        page.goto(url)
        button = page.get_by_role("button", name="Bắt đầu hướng dẫn")
        button.wait_for()
        box = button.bounding_box()
        assert box is not None
        assert box["y"] >= 0
        assert box["y"] + box["height"] <= 900
        assert page.locator("#session-duration").is_hidden()
    finally:
        page.close()
        server.shutdown()
        server.server_close()


def test_action_error_remains_visible_across_status_polling(browser):
    server, url = _control_server()
    page = browser.new_page(viewport={"width": 1024, "height": 800})
    try:
        page.goto(url)
        page.get_by_role("button", name="Bắt đầu hướng dẫn").click()
        error = page.get_by_role("alert")
        error.wait_for(state="visible")
        assert "đúng tab Supabase" in error.text_content()
        page.wait_for_timeout(1500)
        assert error.is_visible()
    finally:
        page.close()
        server.shutdown()
        server.server_close()
