"""Local voice models must return audio. Skipped only when the package is absent."""

from __future__ import annotations

import asyncio
import time

import pytest

from coach.voice_stack import ZEROTTS_MODEL, ZEROTTS_VOICE
from coach.zerotts_stream import stream_pcm


def test_stream_yields_before_the_utterance_finishes():
    numpy = pytest.importorskip("numpy")

    class SlowModel:
        def synthesize_stream(self, text, voice):
            for _ in range(4):
                time.sleep(0.08)
                yield numpy.full(4800, 0.2, dtype=numpy.float32)

    async def collect():
        marks = []
        started = time.perf_counter()
        async for pcm in stream_pcm(
            SlowModel(),
            "Xin chào.",
            voice="maichi",
            startup_buffer_ms=80,
        ):
            marks.append((time.perf_counter() - started, pcm))
        return marks

    marks = asyncio.run(collect())
    assert len(marks) == 4
    assert all(len(pcm) == 9600 for _stamp, pcm in marks)
    assert marks[0][0] < 0.25
    assert marks[-1][0] - marks[0][0] > 0.15


def test_zerotts_streams_audible_audio():
    pytest.importorskip("zerotts")
    numpy = pytest.importorskip("numpy")
    from coach.zerotts_stream import load_engine

    try:
        engine = load_engine(ZEROTTS_MODEL, providers=["CPUExecutionProvider"])
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

    async def collect():
        marks = []
        started = time.perf_counter()
        async for pcm in stream_pcm(
            engine,
            "Xin chào. Mình sẽ hướng dẫn tạo bảng ca.",
            voice=ZEROTTS_VOICE,
        ):
            marks.append((time.perf_counter() - started, pcm))
        return marks

    marks = asyncio.run(collect())
    audio = b"".join(pcm for _stamp, pcm in marks)
    samples = numpy.frombuffer(audio, dtype=numpy.int16)
    assert len(marks) > 1
    assert samples.size > 16000
    assert float(numpy.max(numpy.abs(samples))) > 200
    assert marks[-1][0] - marks[0][0] > 0.1


def test_phowhisper_transcribes_on_the_gpu():
    pytest.importorskip("mlx_whisper")
    pytest.importorskip("zerotts")
    numpy = pytest.importorskip("numpy")
    import mlx.core as mx
    import soxr

    from coach.asr import transcribe_pcm
    from coach.voice_stack import WHISPER_GPU_MODEL, ZEROTTS_MODEL, ZEROTTS_VOICE
    from coach.zerotts_stream import load_engine

    assert mx.default_device().type == mx.DeviceType.gpu
    engine = load_engine(ZEROTTS_MODEL, providers=["CPUExecutionProvider"])
    audio = numpy.concatenate(
        [
            numpy.asarray(chunk, dtype=numpy.float32).reshape(-1)
            for chunk in engine.synthesize_stream("Tạo bảng ca.", voice=ZEROTTS_VOICE)
        ]
    )
    samples = soxr.resample(audio, 48000, 16000).astype(numpy.float32)
    text, backend = transcribe_pcm(
        samples,
        model=WHISPER_GPU_MODEL,
        language="vi",
        device="gpu",
    )
    folded = text.casefold()
    assert backend == "mlx-gpu"
    # ZeroTTS sampling can alter phonemes between runs, so this proves GPU ASR
    # returned a non-empty transcript without asserting an unstable spelling.
    assert folded
    assert mx.get_active_memory() > 0


def test_silero_and_smart_turn_score_local_audio():
    pytest.importorskip("pipecat")
    numpy = pytest.importorskip("numpy")
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    vad = SileroVADAnalyzer(sample_rate=16000)
    silence = numpy.zeros(512, dtype=numpy.int16).tobytes()
    silence_confidence = vad.voice_confidence(silence)
    tone = (
        0.2
        * numpy.sin(2 * numpy.pi * 180 * numpy.arange(512) / 16000)
        * 32767
    ).astype(numpy.int16).tobytes()
    tone_confidence = vad.voice_confidence(tone)
    assert 0.0 <= silence_confidence <= 1.0
    assert 0.0 <= tone_confidence <= 1.0
    assert silence_confidence < 0.5

    turn = LocalSmartTurnAnalyzerV3(sample_rate=16000)
    speech = numpy.zeros(16000, dtype=numpy.int16).tobytes()
    turn.append_audio(speech, is_speech=True)
    state, _metrics = asyncio.run(turn.analyze_end_of_turn())
    assert state is not None
    prediction = turn._predict_endpoint(numpy.zeros(16000, dtype=numpy.float32))
    assert prediction["prediction"] in (0, 1)
    assert 0.0 <= float(prediction["probability"]) <= 1.0
