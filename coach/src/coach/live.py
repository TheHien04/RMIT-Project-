"""Pipecat local-audio pipeline. Imported only when someone starts live voice.

Depends on the pipecat package (Python 3.11+), not a copy of its source.
Who-Speak-AI stays untouched. Direction cues never go through the LLM.
"""

from __future__ import annotations

import asyncio
import time

from coach.session import LearningSession, Speech
from coach.voice_stack import (
    PIPELINE_STAGES,
    WHISPER_LANGUAGE,
    WHISPER_MODEL,
    ZEROTTS_MODEL,
    ZEROTTS_VOICE,
    BargeIn,
    SmartTurnDecision,
    TurnState,
    chunk_speech,
    should_emit_mouse_cue,
)


def build_live_pipeline(session: LearningSession, *, observer=None, settings=None):
    """Wire Silero, Smart Turn, PhoWhisper, barge-in, and ZeroTTS."""

    if tuple(PIPELINE_STAGES) != (
        "local_audio_input",
        "silero_vad",
        "smart_turn_gate",
        "phowhisper_vi",
        "barge_in",
        "coach",
        "zerotts",
        "local_audio_output",
    ):
        raise RuntimeError("voice pipeline stages drifted from the tested order")

    try:
        from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
        from pipecat.audio.vad.vad_analyzer import VADParams
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.frames.frames import (
            Frame,
            BotStartedSpeakingFrame,
            BotStoppedSpeakingFrame,
            InputAudioRawFrame,
            InterruptionFrame,
            TranscriptionFrame,
            TTSAudioRawFrame,
            TTSSpeakFrame,
            VADUserStartedSpeakingFrame,
            VADUserStoppedSpeakingFrame,
        )
        from pipecat.pipeline.pipeline import Pipeline
        from pipecat.pipeline.worker import PipelineParams, PipelineWorker
        from pipecat.processors.audio.vad_processor import VADProcessor
        from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
        from pipecat.services.settings import STTSettings, TTSSettings
        from pipecat.services.stt_service import SegmentedSTTService
        from pipecat.services.tts_service import TTSService
        from pipecat.transports.base_transport import TransportParams
        from pipecat.workers.runner import WorkerRunner

        from coach.local_audio import SoundDeviceTransport
        from coach.zerotts_stream import load_engine, stream_pcm
    except Exception as error:
        raise RuntimeError(
            "Live voice needs Python 3.12 in coach/.venv312, with pipecat-ai, "
            "faster-whisper, zerotts, and sounddevice. "
            "The scripted demo does not need them."
        ) from error

    whisper_model = settings.whisper_model if settings is not None else WHISPER_MODEL
    whisper_language = settings.whisper_language if settings is not None else WHISPER_LANGUAGE
    whisper_device = settings.whisper_device if settings is not None else "cpu"
    whisper_compute = settings.whisper_compute_type if settings is not None else "int8"
    zerotts_model = settings.zerotts_model if settings is not None else ZEROTTS_MODEL
    zerotts_voice = settings.zerotts_voice if settings is not None else ZEROTTS_VOICE
    barge = BargeIn()
    allow_barge_in = settings.barge_in if settings is not None else False
    vad_min_volume = settings.vad_min_volume if settings is not None else 0.002

    class SpeakerEchoGate(FrameProcessor):
        """Silence the mic while the laptop speakers are playing.

        The built-in microphone hears the coach. That echo was transcribed as
        the user and also cancelled the sentence. COACH_BARGE_IN=true leaves
        the mic open for headphones.
        """

        def __init__(self) -> None:
            super().__init__(name="speaker-echo-gate")
            self._playing = False
            self._quiet_at = 0.0

        def _hearing_speakers(self) -> bool:
            if allow_barge_in:
                return False
            return self._playing or time.monotonic() < self._quiet_at

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, BotStartedSpeakingFrame):
                self._playing = True
                self._quiet_at = 0.0
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._playing = False
                self._quiet_at = time.monotonic() + 0.4
            if (
                self._hearing_speakers()
                and isinstance(frame, InputAudioRawFrame)
                and direction is FrameDirection.DOWNSTREAM
            ):
                frame = InputAudioRawFrame(
                    audio=bytes(len(frame.audio)),
                    sample_rate=frame.sample_rate,
                    num_channels=frame.num_channels,
                )
            await self.push_frame(frame, direction)

    class SmartTurnGate(FrameProcessor):
        def __init__(self) -> None:
            super().__init__(name="smart-turn-gate")
            self._analyzer = LocalSmartTurnAnalyzerV3(sample_rate=16000)
            self._speaking = False
            self._pending = None
            self._decision = SmartTurnDecision()
            self._force_task: asyncio.Task | None = None

        async def _cancel_force(self) -> None:
            task = self._force_task
            self._force_task = None
            if task is not None and not task.done():
                task.cancel()

        async def _release(self, direction: FrameDirection) -> None:
            pending = self._pending
            self._pending = None
            await self._cancel_force()
            self._analyzer.clear()
            if pending is not None:
                await self.push_frame(pending, direction)

        async def _force_release(self, direction: FrameDirection) -> None:
            try:
                await asyncio.sleep(2.0)
            except asyncio.CancelledError:
                return
            if self._decision.on_clock(time.monotonic()) == "release":
                await self._release(direction)

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, InputAudioRawFrame):
                self._analyzer.append_audio(frame.audio, self._speaking)
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, VADUserStartedSpeakingFrame):
                self._speaking = True
                self._pending = None
                self._decision = SmartTurnDecision()
                await self._cancel_force()
                await self.push_frame(frame, direction)
                return
            if isinstance(frame, VADUserStoppedSpeakingFrame):
                self._speaking = False
                self._pending = frame
                state, _metrics = await self._analyzer.analyze_end_of_turn()
                turn = (
                    TurnState.COMPLETE
                    if state is EndOfTurnState.COMPLETE
                    else TurnState.INCOMPLETE
                )
                action = self._decision.on_vad_stop(turn, time.monotonic())
                if action == "release":
                    await self._release(direction)
                else:
                    self._force_task = asyncio.create_task(self._force_release(direction))
                return
            await self.push_frame(frame, direction)

    class PhoWhisperSTT(SegmentedSTTService):
        def __init__(self) -> None:
            super().__init__(
                settings=STTSettings(model=whisper_model, language=whisper_language),
                sample_rate=16000,
            )
            self._whisper = None

        @property
        def wants_wav_segments(self) -> bool:
            return False

        async def run_stt(self, audio: bytes):
            import asyncio

            import numpy as np

            from coach.asr import transcribe_pcm

            samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
            text, _backend = await asyncio.to_thread(
                transcribe_pcm,
                samples,
                model=whisper_model,
                language=whisper_language,
                device=whisper_device,
                compute_type=whisper_compute,
            )
            if text:
                yield TranscriptionFrame(text, "", "", whisper_language)

    class BargeInProcessor(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if (
                allow_barge_in
                and isinstance(frame, VADUserStartedSpeakingFrame)
                and barge.user_started()
            ):
                await self.push_frame(InterruptionFrame(), direction)
            await self.push_frame(frame, direction)

    class CoachProcessor(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame) and frame.text:
                for speech in session.on_user_text(frame.text):
                    for part in chunk_speech(speech.text):
                        barge.assistant_started()
                        await self.push_frame(TTSSpeakFrame(part), direction)
                return
            await self.push_frame(frame, direction)

    class ZeroTTSService(TTSService):
        def __init__(self) -> None:
            super().__init__(
                sample_rate=48000,
                push_start_frame=True,
                push_stop_frames=True,
                settings=TTSSettings(
                    model=zerotts_model,
                    voice=zerotts_voice,
                    language=whisper_language,
                ),
            )
            self._model = None

        def _engine(self):
            if self._model is None:
                self._model = load_engine(zerotts_model)
            return self._model

        async def run_tts(self, text: str, context_id: str):
            async for pcm in stream_pcm(self._engine(), text, voice=zerotts_voice):
                yield TTSAudioRawFrame(pcm, 48000, 1, context_id=context_id)
            barge.assistant_finished()

    transport = SoundDeviceTransport(
        TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_enabled=True,
            audio_out_sample_rate=48000,
        )
    )
    pipeline = Pipeline(
        [
            transport.input(),
            SpeakerEchoGate(),
            VADProcessor(
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(
                        confidence=0.7,
                        start_secs=0.2,
                        stop_secs=0.2,
                        min_volume=vad_min_volume,
                    )
                )
            ),
            SmartTurnGate(),
            PhoWhisperSTT(),
            BargeInProcessor(),
            CoachProcessor(),
            ZeroTTSService(),
            transport.output(),
        ]
    )
    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=48000,
        ),
    )
    runner = WorkerRunner()
    return {
        "pipeline": pipeline,
        "worker": worker,
        "runner": runner,
        "observer": observer,
        "stages": PIPELINE_STAGES,
    }


async def run_live(session: LearningSession, *, observer=None, browser_bridge=None, settings=None) -> None:
    from pipecat.frames.frames import TTSSpeakFrame

    built = build_live_pipeline(session, observer=observer, settings=settings)
    worker = built["worker"]
    runner = built["runner"]
    completion_task: asyncio.Task | None = None

    async def say(items) -> None:
        for speech in items:
            for part in chunk_speech(speech.text):
                await worker.queue_frame(TTSSpeakFrame(part, append_to_context=False))

    async def observe_browser() -> None:
        """Turn Layer 1.5 browser updates into speech on the Pipecat loop."""

        nonlocal completion_task
        last_blocked = ""
        while True:
            update = await browser_bridge.updates.get()
            if update.blocked_reason:
                if update.blocked_reason != last_blocked:
                    await say([Speech(update.blocked_reason, "safety")])
                    last_blocked = update.blocked_reason
                continue
            last_blocked = ""
            session.note_bindings(update.bindings)
            await say(
                session.on_page(
                    label=update.keys.label,
                    bump=update.keys.bump,
                    flags=update.keys.flags,
                )
            )
            if session.done:
                if completion_task is None:
                    completion_task = asyncio.create_task(
                        _finish_after_final_speech(runner),
                        name="coach-lesson-complete",
                    )
                continue
            # Keyboard and screen-reader modes never emit pointer cues. In
            # mouse mode a static cursor is also silent: a cue means the
            # learner just moved the pointer, not merely clicked the page.
            if should_emit_mouse_cue(session.navigation_mode, update.mouse_moved):
                await say(session.on_observation(update.observation, now=time.monotonic()))

    @worker.event_handler("on_pipeline_started")
    async def _greet(_worker, _frame):
        if session.phase == "idle":
            await worker.queue_frame(
                TTSSpeakFrame(
                    "Nói bắt đầu học để mình hướng dẫn theo lesson hiện tại.",
                    append_to_context=False,
                )
            )

    await runner.add_workers(worker)
    browser_task = (
        asyncio.create_task(observe_browser(), name="coach-browser-observer")
        if browser_bridge is not None
        else None
    )
    try:
        await runner.run()
    finally:
        if completion_task is not None:
            completion_task.cancel()
        if browser_task is not None:
            browser_task.cancel()
            try:
                await browser_task
            except asyncio.CancelledError:
                pass


async def _finish_after_final_speech(runner) -> None:
    """Give the final ZeroTTS sentence time to drain, then release the mic."""

    await asyncio.sleep(4)
    await runner.end("lesson complete")
