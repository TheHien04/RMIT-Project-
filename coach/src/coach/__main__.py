"""Entrypoints. Use coach/.venv so packages stay off the system Python."""

from __future__ import annotations

import argparse
import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from coach.demo_run import run_lesson
from coach.guide import run_guided
from coach.lesson import plan_from_pages
from coach.llm import maybe_llm
from coach.pdf_text import ONBOARDING_PAGES, load_pages, write_lesson_pdf
from coach.privacy import EgressLog
from coach.settings import ROOT, load_settings
from coach.speaker import build_speaker

SANDBOX = ROOT / "sandbox"
FIXTURE = ROOT / "fixtures" / "onboarding.pdf"


def main() -> None:
    parser = argparse.ArgumentParser(description="Voice coach for stage-4 onboarding")
    parser.add_argument("command", choices=("demo", "serve", "live", "speak", "write-fixture"))
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "write-fixture":
        write_lesson_pdf(FIXTURE, ONBOARDING_PAGES)
        print(FIXTURE)
        return
    if args.command == "serve":
        _serve(args.port or settings.sandbox_port)
        return
    if args.command == "demo":
        _demo(settings)
        return
    if args.command == "speak":
        _speak(settings)
        return
    _live(settings, args.port)


def _serve(port: int) -> None:
    server, url = _background_server(port)
    print(url + "/?flow=div")
    server.serve_forever()


def _demo(settings) -> None:
    from playwright.sync_api import sync_playwright

    plan = _plan(settings)
    egress = EgressLog()
    server, url = _background_server(0)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url + "/?flow=div")
            speeches = run_lesson(page, plan, egress=egress)
            browser.close()
    finally:
        server.shutdown()
    for speech in speeches:
        print(f"[{speech.kind}] {speech.text}")
    egress.write_jsonl(settings.egress_log)
    print(f"egress log: {settings.egress_log}")
    if any(event.left_machine for event in egress.events):
        raise SystemExit("demo sent data off the machine")


def _live(settings, port: int | None) -> None:
    if settings.mic_enabled:
        _live_mic(settings)
        return
    from playwright.sync_api import sync_playwright

    plan = _plan(settings)
    speaker = build_speaker(settings)
    egress = EgressLog()
    server, url = _background_server(0 if port is None else port)
    print(url + "/?flow=div")
    if speaker.name == "edge":
        print("TTS edge: mỗi câu nói được gửi tới Microsoft và ghi vào egress log.")
    if maybe_llm(settings):
        print("Câu hỏi mở đi qua OpenAI. Tên nút và Enter nói sẵn.")
    else:
        print("Không gọi OpenAI. Mọi câu nói sẵn.")
    print("Trên trang: mũi tên để đi, Enter để bấm. Terminal: gõ câu rồi Enter. Ctrl-D để dừng.")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=not settings.headed)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(url + "/?flow=div")
            run_guided(
                page=page,
                plan=plan,
                speaker=speaker,
                egress=egress,
                llm=maybe_llm(settings),
                vision_enabled=settings.vision_enabled,
                poll_seconds=settings.cue_poll_seconds,
            )
            browser.close()
    finally:
        server.shutdown()
        egress.write_jsonl(settings.egress_log)
        print(f"egress log: {settings.egress_log}")


def _speak(settings) -> None:
    import asyncio
    import time

    import numpy as np
    import sounddevice as sd

    from coach.voice_stack import ZEROTTS_MODEL, ZEROTTS_VOICE
    from coach.zerotts_stream import load_engine, stream_pcm

    model_name = settings.zerotts_model or ZEROTTS_MODEL
    voice = settings.zerotts_voice or ZEROTTS_VOICE
    text = "Xin chào. Mình sẽ hướng dẫn tạo bảng ca."
    engine = load_engine(model_name)

    async def collect() -> list[bytes]:
        started = time.perf_counter()
        first = None
        chunks: list[bytes] = []
        async for pcm in stream_pcm(engine, text, voice=voice):
            if first is None:
                first = time.perf_counter() - started
            chunks.append(pcm)
        total = time.perf_counter() - started
        samples = sum(len(chunk) // 2 for chunk in chunks)
        print(
            f"zerotts chunks={len(chunks)} first_s={first:.2f} "
            f"audio_s={samples / 48000:.2f} synth_s={total:.2f}"
        )
        return chunks

    audio = b"".join(asyncio.run(collect()))
    samples = np.frombuffer(audio, dtype=np.int16)
    if samples.size < 16000 or float(np.max(np.abs(samples))) < 200:
        raise SystemExit("ZeroTTS did not return audible audio")
    sd.play(samples, samplerate=48000, blocking=True)


def _live_mic(settings) -> None:
    import asyncio

    from coach.browser_bridge import BrowserLessonBridge
    from coach.live import run_live
    from coach.privacy import BrowserAudit
    from coach.session import LearningSession
    from coach.targets import BrowserTarget, TargetManifest

    async def run() -> None:
        egress = EgressLog()
        plan = _plan(settings)
        manifest = TargetManifest.load(settings.target_manifest) if settings.target_manifest else None
        if manifest is not None:
            plan = manifest.apply(plan)
        origins = settings.allowed_origins or (manifest.origins if manifest else ())
        sandbox_mode = not settings.cdp_url
        navigation_mode = "coach_list" if sandbox_mode else settings.navigation_mode
        target = BrowserTarget(
            cdp_url=settings.cdp_url,
            allowed_origins=origins,
            tab_title=settings.target_tab_title,
            navigation_mode=navigation_mode,
            inject_navigation=(True if sandbox_mode else settings.inject_navigation),
            agent_browser_bin=settings.agent_browser_bin,
        )
        if target.external and not target.allowed_origins:
            raise RuntimeError("COACH_ALLOWED_ORIGINS or COACH_TARGET_MANIFEST is required for CDP")
        audit = BrowserAudit()
        session = LearningSession(
            plan,
            egress=egress,
            llm=maybe_llm(settings),
            vision_enabled=settings.vision_enabled,
            navigation_mode=navigation_mode,
        )
        bridge = BrowserLessonBridge(
            plan,
            loop=asyncio.get_running_loop(),
            poll_seconds=settings.cue_poll_seconds,
            headed=settings.headed,
            target=target,
            audit=audit,
        )
        bridge.start()
        session.attach_assist_actions(
            focus=bridge.focus,
            click=bridge.click,
            set_navigation=bridge.set_navigation,
        )
        try:
            await run_live(session, browser_bridge=bridge, settings=settings)
        finally:
            bridge.close()
            egress.write_jsonl(settings.egress_log)
            audit.write_jsonl(settings.browser_audit_log)
            print(f"egress log: {settings.egress_log}")

    try:
        asyncio.run(run())
    except RuntimeError as error:
        raise SystemExit(str(error)) from error


def _plan(settings=None):
    path = settings.lesson_pdf if settings is not None and settings.lesson_pdf else FIXTURE
    if path == FIXTURE and not path.is_file():
        write_lesson_pdf(path, ONBOARDING_PAGES)
    if not path.is_file():
        raise FileNotFoundError(f"COACH_LESSON_PDF does not exist: {path}")
    return plan_from_pages(load_pages(path))


def _background_server(port: int, *, directory=None):
    handler = functools.partial(_QuietHandler, directory=str(directory or SANDBOX))
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound = server.server_address[1]
    return server, f"http://127.0.0.1:{bound}"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


if __name__ == "__main__":
    main()
