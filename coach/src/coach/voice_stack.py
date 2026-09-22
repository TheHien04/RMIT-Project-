"""Voice-path policy that can be tested without loading Pipecat or the models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# Order the live pipeline must build. Cues stay outside the LLM.
PIPELINE_STAGES = (
    "local_audio_input",
    "silero_vad",
    "smart_turn_gate",
    "phowhisper_vi",
    "barge_in",
    "coach",
    "zerotts",
    "local_audio_output",
)

WHISPER_MODEL = "vudang449/PhoWhisper-small-ct2"
WHISPER_GPU_MODEL = "vinai/PhoWhisper-medium"
WHISPER_LANGUAGE = "vi"
ZEROTTS_MODEL = "zeroweight-ai/ZeroTTS"
ZEROTTS_VOICE = "maichi"
TTS_MAX_CHARS = 120


@dataclass(frozen=True)
class VoiceStack:
    vad: str = "silero"
    turn: str = "LocalSmartTurnAnalyzerV3"
    stt_model: str = WHISPER_MODEL
    stt_language: str = WHISPER_LANGUAGE
    tts_model: str = ZEROTTS_MODEL
    tts_voice: str = ZEROTTS_VOICE
    barge_in: bool = True
    transport: str = "local_audio"
    stages: tuple[str, ...] = PIPELINE_STAGES


class TurnState(Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass
class SmartTurnDecision:
    """Hold a raw VAD stop until Smart Turn says the thought is finished."""

    released: bool = False
    holding: bool = False
    deadline: float | None = None

    def on_vad_stop(self, state: TurnState, now: float, *, max_wait_s: float = 2.0) -> str:
        if max_wait_s <= 0:
            raise ValueError("max_wait_s must be positive")
        if state is TurnState.COMPLETE:
            self.released = True
            self.holding = False
            self.deadline = None
            return "release"
        self.holding = True
        self.released = False
        self.deadline = now + max_wait_s
        return "hold"

    def on_clock(self, now: float) -> str:
        if self.holding and self.deadline is not None and now >= self.deadline:
            self.released = True
            self.holding = False
            self.deadline = None
            return "release"
        return "wait"


@dataclass
class BargeIn:
    """Cut assistant speech when the user starts talking."""

    assistant_speaking: bool = False

    def assistant_started(self) -> None:
        self.assistant_speaking = True

    def assistant_finished(self) -> None:
        self.assistant_speaking = False

    def user_started(self) -> bool:
        if not self.assistant_speaking:
            return False
        self.assistant_speaking = False
        return True


def chunk_speech(text: str, *, max_chars: int = TTS_MAX_CHARS) -> list[str]:
    """Split spoken text into short sentences so TTS does not queue a paragraph."""

    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    parts: list[str] = []
    start = 0
    for index, char in enumerate(cleaned):
        if char in ".!?…" and index + 1 < len(cleaned) and cleaned[index + 1] == " ":
            parts.append(cleaned[start : index + 1].strip())
            start = index + 1
    tail = cleaned[start:].strip()
    if tail:
        parts.append(tail)
    limited: list[str] = []
    for part in parts:
        while len(part) > max_chars:
            limited.append(part[:max_chars].strip())
            part = part[max_chars:].strip()
        if part:
            limited.append(part)
    return limited


def should_emit_mouse_cue(navigation_mode: str, mouse_moved: bool) -> bool:
    """Pointer guidance is opt-in and never leaks into keyboard learning."""

    return navigation_mode == "mouse_cue" and mouse_moved
