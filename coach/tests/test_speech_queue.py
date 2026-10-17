from coach.session import SpeechEvent
from coach.speech_queue import SpeechQueuePolicy


def test_speech_queue_dedupes_and_interrupts_only_for_higher_priority():
    policy = SpeechQueuePolicy(dedupe_seconds=2)
    cue = SpeechEvent("Qua phải.", "cue")
    assert policy.prepare(cue, now=0).accepted
    assert not policy.prepare(cue, now=1).accepted
    safety = SpeechEvent("Trang không được phép.", "safety")
    decision = policy.prepare(safety, now=1)
    assert decision.accepted
    assert decision.interrupt_current
    lower = SpeechEvent("Một gợi ý.", "cue", dedupe_key="other")
    assert not policy.prepare(lower, now=1.1).interrupt_current


def test_done_and_safety_speech_are_not_interruptible():
    assert SpeechEvent("Xong.", "done").interruptible is False
    assert SpeechEvent("Dừng.", "safety").interruptible is False


def test_one_logical_speech_batch_does_not_interrupt_itself():
    policy = SpeechQueuePolicy()
    brief = SpeechEvent("Giới thiệu.", "brief")
    step = SpeechEvent("Bước một.", "step")
    assert policy.prepare(brief, now=0).accepted
    decision = policy.prepare(step, now=0.1, allow_interrupt=False)
    assert decision.accepted
    assert decision.interrupt_current is False

    safety = SpeechEvent("Dừng lại.", "safety")
    assert policy.prepare(safety, now=0.2).interrupt_current is True


def test_a_new_focus_place_cancels_an_obsolete_place_announcement():
    policy = SpeechQueuePolicy()
    assert policy.prepare(SpeechEvent("SQL Editor.", "place"), now=0).accepted
    decision = policy.prepare(SpeechEvent("Database.", "place"), now=0.1)
    assert decision.accepted
    assert decision.interrupt_current is True
