"""Stream ZeroTTS audio as it is produced.

The synthesizer is synchronous. A worker thread pulls frames so the event
loop stays free, and a bounded queue stops a slow consumer from holding the
whole utterance in memory. The first yield waits for a short startup buffer,
then each later chunk is yielded immediately. A line that finishes before
that buffer is still spoken.
"""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator


def float32_to_s16(raw) -> bytes:
    import numpy as np

    samples = np.clip(np.asarray(raw, dtype=np.float32).reshape(-1), -1.0, 1.0)
    return (samples * 32767.0).astype(np.int16).tobytes()


def preferred_providers() -> list[str]:
    """CPU. CoreML is present on this M4, but ZeroTTS crashes inside it.

    onnxruntime reports CoreMLExecutionProvider, then fails at runtime with
    "Unable to compute the prediction using a neural network model". CPU on
    the M4 Pro already synthesizes faster than realtime.
    """

    return ["CPUExecutionProvider"]


def load_engine(model_name: str, *, providers: list[str] | None = None):
    from zerotts import ZeroTTS

    return ZeroTTS.from_pretrained(model_name, providers=list(providers or preferred_providers()))


async def stream_pcm(
    model,
    text: str,
    *,
    voice: str,
    sample_rate: int = 48_000,
    startup_buffer_ms: float = 250.0,
    queue_max_chunks: int = 8,
) -> AsyncIterator[bytes]:
    """Yield 16-bit mono PCM at ``sample_rate`` while synthesis is still running."""

    if not text.strip():
        return
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    if startup_buffer_ms < 0:
        raise ValueError("startup_buffer_ms must not be negative")
    if queue_max_chunks <= 0:
        raise ValueError("queue_max_chunks must be positive")

    output: queue.Queue[object] = queue.Queue(maxsize=queue_max_chunks)
    stop = threading.Event()
    sentinel = object()
    errors: list[BaseException] = []

    def produce() -> None:
        try:
            for raw in model.synthesize_stream(text, voice=voice):
                if stop.is_set():
                    break
                pcm = float32_to_s16(raw)
                if not pcm:
                    continue
                while not stop.is_set():
                    try:
                        output.put(pcm, timeout=0.1)
                        break
                    except queue.Full:
                        continue
        except BaseException as error:
            errors.append(error)
        finally:
            while not stop.is_set():
                try:
                    output.put(sentinel, timeout=0.1)
                    break
                except queue.Full:
                    continue

    worker = asyncio.get_running_loop().run_in_executor(None, produce)
    startup_bytes = int(sample_rate * 2 * startup_buffer_ms / 1000)
    pending: list[bytes] = []
    pending_bytes = 0
    started = startup_bytes <= 0
    try:
        while True:
            try:
                item = output.get_nowait()
            except queue.Empty:
                if worker.done() and output.empty():
                    for chunk in pending:
                        yield chunk
                    pending.clear()
                    break
                await asyncio.sleep(0.005)
                continue
            if item is sentinel:
                for chunk in pending:
                    yield chunk
                pending.clear()
                break
            chunk = item
            if not isinstance(chunk, bytes):
                continue
            if not started:
                pending.append(chunk)
                pending_bytes += len(chunk)
                if pending_bytes < startup_bytes:
                    continue
                started = True
                for buffered in pending:
                    yield buffered
                pending.clear()
                pending_bytes = 0
                continue
            yield chunk
        await worker
        if errors:
            raise errors[0]
    finally:
        stop.set()
