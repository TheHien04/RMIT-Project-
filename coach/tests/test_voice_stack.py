import pytest

from coach.lesson import plan_from_pages
from coach.pdf_text import ONBOARDING_PAGES
from coach.session import LearningSession
from coach.voice_stack import (
    PIPELINE_STAGES,
    BargeIn,
    SmartTurnDecision,
    TurnState,
    chunk_speech,
    should_emit_mouse_cue,
)


def test_short_chunks_and_barge_in():
    parts = chunk_speech("Một ý ngắn. " + ("rất dài " * 40))
    assert parts[0] == "Một ý ngắn."
    assert all(len(part) <= 120 for part in parts)
    barge = BargeIn()
    assert barge.user_started() is False
    barge.assistant_started()
    assert barge.user_started() is True
    assert barge.user_started() is False


def test_smart_turn_holds_an_incomplete_pause():
    gate = SmartTurnDecision()
    assert gate.on_vad_stop(TurnState.INCOMPLETE, now=0) == "hold"
    assert gate.on_clock(1.0) == "wait"
    assert gate.on_clock(2.0) == "release"
    done = SmartTurnDecision()
    assert done.on_vad_stop(TurnState.COMPLETE, now=0) == "release"


def test_keyboard_navigation_never_emits_static_mouse_cues():
    assert should_emit_mouse_cue("native_focus", mouse_moved=False) is False
    assert should_emit_mouse_cue("native_focus", mouse_moved=True) is False
    assert should_emit_mouse_cue("coach_list", mouse_moved=False) is False
    assert should_emit_mouse_cue("coach_list", mouse_moved=True) is False
    assert should_emit_mouse_cue("mouse_cue", mouse_moved=False) is False
    assert should_emit_mouse_cue("mouse_cue", mouse_moved=True) is True


def test_pipeline_order_and_live_builder_stays_optional():
    import importlib.util

    assert PIPELINE_STAGES[1:4] == ("silero_vad", "smart_turn_gate", "phowhisper_vi")
    assert "zerotts" in PIPELINE_STAGES
    from coach.live import build_live_pipeline

    session = LearningSession(plan_from_pages(ONBOARDING_PAGES))
    voice_installed = importlib.util.find_spec("pipecat") and importlib.util.find_spec("sounddevice")
    if not voice_installed:
        with pytest.raises(RuntimeError):
            build_live_pipeline(session)
        return
    import asyncio

    async def build():
        return build_live_pipeline(session)

    built = asyncio.run(build())
    assert built["stages"] == PIPELINE_STAGES
    assert built["pipeline"] is not None
    assert built["runner"] is not None
