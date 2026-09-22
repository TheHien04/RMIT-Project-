"""Load each speech backend and check that it returns audio, or say why it cannot.

Who-Speak-AI's voice tests mock ZeroTTS and only assert PCM conversion. The
Edge contract they use is reused here: stream chunks until the buffer is
non-empty. ZeroTTS and PhoWhisper are skipped until those packages are in
this venv.
"""

from __future__ import annotations

import asyncio

import pytest

from coach.speaker import synthesize_edge


def test_edge_tts_returns_audio():
    audio = asyncio.run(synthesize_edge("Xin chào.", "vi-VN-HoaiMyNeural"))
    assert isinstance(audio, bytes)
    assert len(audio) > 100


def test_zerotts_package_can_be_imported():
    pytest.importorskip("zerotts")
    from zerotts import ZeroTTS

    try:
        model = ZeroTTS.from_pretrained("zeroweight-ai/ZeroTTS", providers=["CPUExecutionProvider"])
    except Exception as error:
        message = str(error)
        broken_runtime = (
            "ArgMax" in message
            or "NOT_IMPLEMENTED" in message
            or "too many values to unpack" in message
        )
        if broken_runtime:
            pytest.skip(
                "ZeroTTS needs Python 3.12, onnxruntime >= 1.22, and zerotts 0.1.5: "
                + message.splitlines()[-1]
            )
        raise
    voices = model.list_voices()
    assert "maichi" in voices
    chunk = next(iter(model.synthesize_stream("Xin chào.", voice="maichi")), None)
    assert chunk is not None


def test_phowhisper_transcribes_silence_without_crashing():
    pytest.importorskip("faster_whisper")
    import numpy as np
    from faster_whisper import WhisperModel

    model = WhisperModel("vudang449/PhoWhisper-small-ct2", device="cpu", compute_type="int8")
    silence = np.zeros(16000, dtype=np.float32)
    segments, _info = model.transcribe(silence, language="vi")
    text = " ".join(segment.text.strip() for segment in segments)
    assert isinstance(text, str)
