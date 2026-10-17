"""Speak a cue. Edge TTS is explicit because the sentence leaves the machine."""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from coach.privacy import EgressLog
from coach.settings import Settings


class Speaker:
    name = "print"

    def say(self, text: str, egress: EgressLog) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        print(f"[coach] {cleaned}", flush=True)


class EdgeSpeaker(Speaker):
    name = "edge"

    def __init__(self, voice: str) -> None:
        self.voice = voice
        self._cache: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def say(self, text: str, egress: EgressLog) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        print(f"[coach] {cleaned}", flush=True)
        path = Path(tempfile.mkstemp(suffix=".mp3")[1])
        try:
            path.write_bytes(self.audio(cleaned, egress))
            player = shutil.which("afplay") or shutil.which("ffplay")
            if player and path.stat().st_size > 0:
                subprocess.run([player, str(path)], check=False, capture_output=True)
        except Exception as error:
            print(f"[coach] không nói được: {error}", flush=True)
        finally:
            path.unlink(missing_ok=True)

    def warm(self, lines: list[str], egress: EgressLog) -> None:
        """Fetch the closed cue lines once, so the next move does not wait on the network."""

        for line in lines:
            try:
                self.audio(" ".join(line.split()), egress)
            except Exception as error:
                print(f"[coach] chưa có sẵn câu '{line}': {error}", flush=True)

    def audio(self, text: str, egress: EgressLog) -> bytes:
        with self._lock:
            cached = self._cache.get(text)
            if cached is not None:
                egress.record(
                    "tts",
                    {"provider": "edge-cache", "voice": self.voice, "chars": len(text)},
                    left_machine=False,
                )
                return cached
        path = Path(tempfile.mkstemp(suffix=".mp3")[1])
        try:
            _run_async(_save_edge(text, self.voice, path))
            audio = path.read_bytes()
        finally:
            path.unlink(missing_ok=True)
        if not audio:
            raise RuntimeError("Edge TTS returned no audio.")
        with self._lock:
            self._cache[text] = audio
        egress.record(
            "tts",
            {"provider": "edge", "voice": self.voice, "chars": len(text)},
            left_machine=True,
        )
        return audio


class LocalSpeaker(Speaker):
    name = "zerotts"

    def say(self, text: str, egress: EgressLog) -> None:
        cleaned = " ".join(text.split())
        if not cleaned:
            return
        egress.record(
            "tts",
            {"provider": "zerotts", "chars": len(cleaned)},
            left_machine=False,
        )
        print(f"[coach] {cleaned}", flush=True)


def build_speaker(settings: Settings) -> Speaker:
    if settings.tts == "print":
        return Speaker()
    if settings.tts == "edge":
        _require_edge()
        return EdgeSpeaker(settings.edge_voice)
    if settings.tts == "zerotts":
        return LocalSpeaker()
    if _edge_available():
        return EdgeSpeaker(settings.edge_voice)
    return Speaker()


def _edge_available() -> bool:
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        return False
    return True


def _require_edge() -> None:
    if not _edge_available():
        raise RuntimeError(
            "COACH_TTS=edge needs edge-tts inside coach/.venv: "
            ".venv/bin/python -m pip install edge-tts"
        )


def _run_async(coro) -> None:
    """Run a coroutine even when Playwright already owns the thread's event loop."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    error: list[BaseException] = []

    def worker() -> None:
        try:
            asyncio.run(coro)
        except BaseException as caught:
            error.append(caught)

    thread = threading.Thread(target=worker, name="coach-edge-tts")
    thread.start()
    thread.join()
    if error:
        raise error[0]


async def _save_edge(text: str, voice: str, path: Path) -> None:
    audio = await synthesize_edge(text, voice)
    path.write_bytes(audio)


async def synthesize_edge(text: str, voice: str) -> bytes:
    """Same contract as Who-Speak-AI's EdgeTTSProvider.synthesize: non-empty MP3."""

    if not text.strip():
        raise ValueError("Cannot synthesize empty text.")
    import edge_tts

    output = bytearray()
    communicate = edge_tts.Communicate(text=text, voice=voice)
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            output.extend(chunk["data"])
    if not output:
        raise RuntimeError("Edge TTS returned no audio.")
    return bytes(output)
