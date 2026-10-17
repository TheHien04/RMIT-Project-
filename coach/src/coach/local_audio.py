"""Mic and speaker transport using sounddevice.

Pipecat's local transport imports PyAudio, which needs a system PortAudio
build. sounddevice already ships a PortAudio library and can see the
MacBook microphone and speakers, so the voice pipeline uses that instead.
"""

from __future__ import annotations

import asyncio
import threading

from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame, StartFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameProcessorSetup
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_output import BaseOutputTransport
from pipecat.transports.base_transport import BaseTransport, TransportParams


class SoundDeviceTransport(BaseTransport):
    def __init__(self, params: TransportParams, *, on_audio_started=None):
        super().__init__(name="sounddevice")
        self._params = params
        self._input: _Input | None = None
        self._output: _Output | None = None
        self._on_audio_started = on_audio_started

    def input(self) -> FrameProcessor:
        if self._input is None:
            self._input = _Input(self._params)
        return self._input

    def output(self) -> FrameProcessor:
        if self._output is None:
            self._output = _Output(self._params, on_audio_started=self._on_audio_started)
        return self._output


class _Input(BaseInputTransport):
    def __init__(self, params: TransportParams):
        super().__init__(params)
        self._stream = None

    async def setup(self, setup: FrameProcessorSetup):
        await super().setup(setup)
        import sounddevice as sd

        block = max(int(self.sample_rate / 50), 1)
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=self._params.audio_in_channels,
            dtype="int16",
            blocksize=block,
            callback=self._on_audio,
        )

    async def cleanup(self):
        await self._close_stream()
        await super().cleanup()

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if self._stream is not None:
            self._stream.start()
            await self.set_transport_ready(frame)

    async def stop(self, frame):
        await self._close_stream()
        await super().stop(frame)

    async def cancel(self, frame):
        await self._close_stream()
        await super().cancel(frame)

    async def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.abort()
        except Exception:
            pass
        try:
            stream.close()
        except Exception:
            pass

    def _on_audio(self, indata, frames, time_info, status) -> None:
        pcm = bytes(indata)
        if not pcm:
            return
        loop = self.get_event_loop()
        if loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._push_pcm(pcm), loop)

    async def _push_pcm(self, pcm: bytes) -> None:
        await self.push_audio_frame(
            InputAudioRawFrame(
                audio=pcm,
                sample_rate=self.sample_rate,
                num_channels=self._params.audio_in_channels,
            )
        )


class _Output(BaseOutputTransport):
    def __init__(self, params: TransportParams, *, on_audio_started=None):
        super().__init__(params)
        self._stream = None
        self._pending = bytearray()
        self._pending_lock = threading.Lock()
        self._on_audio_started = on_audio_started
        self._notified_audio = False

    async def setup(self, setup: FrameProcessorSetup):
        await super().setup(setup)
        import sounddevice as sd

        self._stream = sd.RawOutputStream(
            samplerate=self.sample_rate,
            channels=self._params.audio_out_channels,
            dtype="int16",
            blocksize=max(int(self.sample_rate / 50), 1),
            callback=self._on_audio,
        )

    async def cleanup(self):
        stream = self._stream
        self._stream = None
        if stream is not None:
            stream.abort()
            stream.close()
        await super().cleanup()

    async def start(self, frame: StartFrame):
        await super().start(frame)
        if self._stream is not None:
            self._stream.start()
            await self.set_transport_ready(frame)

    async def write_audio_frame(self, frame: OutputAudioRawFrame) -> bool:
        stream = self._stream
        if stream is None or not frame.audio:
            return False
        pcm = _match_rate(frame.audio, frame.sample_rate, self.sample_rate)
        with self._pending_lock:
            self._pending.extend(pcm)
        self._notified_audio = False
        # BaseOutputTransport expects this coroutine to pace audio. The old
        # blocking stream.write() could hang on macOS and hit its 10s timeout.
        duration = len(pcm) / (self.sample_rate * self._params.audio_out_channels * 2)
        await asyncio.sleep(duration)
        return True

    def _on_audio(self, outdata, frames, time_info, status) -> None:
        output = memoryview(outdata).cast("B")
        with self._pending_lock:
            count = min(len(output), len(self._pending))
            if count:
                output[:count] = self._pending[:count]
                del self._pending[:count]
                if not self._notified_audio and self._on_audio_started is not None:
                    self._notified_audio = True
                    self._on_audio_started()
        if count < len(output):
            output[count:] = b"\x00" * (len(output) - count)


def _match_rate(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    if not source_rate or source_rate == target_rate:
        return pcm
    import numpy as np
    import soxr

    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    converted = soxr.resample(samples, source_rate, target_rate)
    return np.clip(converted * 32767.0, -32768, 32767).astype(np.int16).tobytes()
