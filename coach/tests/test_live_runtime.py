from __future__ import annotations

import asyncio


def test_lesson_completion_waits_for_final_tts_then_ends_runner(monkeypatch):
    from coach.live import _finish_after_final_speech

    events = []

    class Runner:
        async def end(self, reason):
            events.append(("end", reason))

    async def fake_sleep(seconds):
        events.append(("sleep", seconds))

    monkeypatch.setattr("coach.live.asyncio.sleep", fake_sleep)
    asyncio.run(_finish_after_final_speech(Runner()))
    assert events == [("sleep", 4), ("end", "lesson complete")]
