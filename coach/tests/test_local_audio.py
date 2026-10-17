from __future__ import annotations

import asyncio

import pytest


def test_output_callback_drains_pcm_without_blocking_transport(monkeypatch):
    pytest.importorskip("pipecat")
    from pipecat.frames.frames import OutputAudioRawFrame
    from pipecat.transports.base_transport import TransportParams

    from coach.local_audio import _Output

    output = _Output(
        TransportParams(
            audio_out_enabled=True,
            audio_out_sample_rate=48000,
            audio_out_channels=1,
        )
    )
    output._sample_rate = 48000
    output._stream = object()
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("coach.local_audio.asyncio.sleep", fake_sleep)
    frame = OutputAudioRawFrame(b"\x01\x00\x02\x00", 48000, 1)
    assert asyncio.run(output.write_audio_frame(frame)) is True
    assert sleeps == [2 / 48000]

    outdata = bytearray(8)
    output._on_audio(outdata, 4, None, None)
    assert bytes(outdata) == b"\x01\x00\x02\x00\x00\x00\x00\x00"
