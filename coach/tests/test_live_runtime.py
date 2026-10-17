from __future__ import annotations

import asyncio


def test_lesson_completion_waits_for_final_tts_then_ends_runner():
    from coach.live import _finish_after_final_speech

    events = []

    class Runner:
        async def end(self, reason):
            events.append(("end", reason))

    async def scenario():
        playback_idle = asyncio.Event()
        task = asyncio.create_task(
            _finish_after_final_speech(Runner(), playback_idle, settle_seconds=0)
        )
        await asyncio.sleep(0)
        assert events == []
        playback_idle.set()
        await task

    asyncio.run(scenario())
    assert events == [("end", "lesson complete")]


def test_lesson_completion_has_a_bounded_audio_drain_fallback():
    from coach.live import _finish_after_final_speech

    events = []

    class Runner:
        async def end(self, reason):
            events.append(reason)

    async def scenario():
        await _finish_after_final_speech(
            Runner(),
            asyncio.Event(),
            timeout=0.001,
            settle_seconds=0,
        )

    asyncio.run(scenario())
    assert events == ["lesson complete"]
