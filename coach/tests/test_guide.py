from pathlib import Path

from coach.guide import run_guided
from coach.lesson import plan_from_pages
from coach.pdf_text import ONBOARDING_PAGES
from coach.privacy import EgressLog
from coach.speaker import EdgeSpeaker, Speaker


def test_guided_session_speaks_the_first_step_without_leaving(page, sandbox_url):
    page.goto(sandbox_url + "/?flow=div")
    log = EgressLog()

    def lines():
        page.keyboard.press("ArrowDown")
        yield "không hiểu"

    spoken = run_guided(
        page=page,
        plan=plan_from_pages(ONBOARDING_PAGES),
        speaker=Speaker(),
        egress=log,
        poll_seconds=0.01,
        lines=lines(),
    )
    text = " ".join(item.text for item in spoken)
    assert "Mũi tên để đi. Enter để bấm. Escape để đọc trang." in text
    assert "Tạo bảng. Enter." in text
    assert all(not event.left_machine for event in log.events)


def test_edge_speaker_runs_while_playwright_owns_the_loop(page, sandbox_url, monkeypatch):
    async def fake_save(text, voice, path):
        Path(path).write_bytes(b"mp3")

    monkeypatch.setattr("coach.speaker._save_edge", fake_save)
    monkeypatch.setattr("coach.speaker.shutil.which", lambda name: None)
    page.goto(sandbox_url + "/?flow=div")
    log = EgressLog()
    spoken = run_guided(
        page=page,
        plan=plan_from_pages(ONBOARDING_PAGES),
        speaker=EdgeSpeaker("vi-VN-HoaiMyNeural"),
        egress=log,
        poll_seconds=0.01,
        lines=iter([""]),
    )
    assert spoken[0].text.startswith("Mình sẽ hướng dẫn")
    assert log.events[0].left_machine is True
    assert log.events[0].kind == "tts"
