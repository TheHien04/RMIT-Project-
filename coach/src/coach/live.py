"""Pipecat local-audio pipeline. Imported only when someone starts live voice.

Depends on the pipecat package (Python 3.11+), not a copy of its source.
Who-Speak-AI stays untouched. Direction cues never go through the LLM.
"""

from __future__ import annotations

import asyncio
import itertools
import time
from collections import deque

from coach.session import LearningSession, Speech
from coach.latency import LatencyLog, LatencyTrace
from coach.speech_queue import SpeechQueuePolicy
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
        from coach.zerotts_stream import float32_to_s16, load_engine, stream_pcm
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
    speech_queue = SpeechQueuePolicy()
    latency_log = LatencyLog(settings.latency_log) if settings is not None else None
    event_loop = asyncio.get_running_loop()
    trace_ids = itertools.count(1)
    latency_traces: dict[str, LatencyTrace] = {}
    tts_trace_contexts: deque[tuple[str, LatencyTrace | None]] = deque()
    audio_traces: deque[LatencyTrace] = deque()
    playback_idle = asyncio.Event()
    playback_idle.set()

    if settings is not None:
        try:
            import numpy as np

            from coach.asr import transcribe_pcm

            transcribe_pcm(
                np.zeros(3200, dtype=np.float32),
                model=whisper_model,
                language=whisper_language,
                device=whisper_device,
                compute_type=whisper_compute,
            )
        except Exception as error:
            raise RuntimeError(f"PhoWhisper readiness failed: {error}") from error

    def start_latency(kind: str, origin: str, at: float | None = None) -> LatencyTrace:
        trace = LatencyTrace(f"{kind}-{next(trace_ids)}", kind)
        trace.mark(origin, at)
        latency_traces[kind] = trace
        return trace

    def current_latency(kind: str) -> LatencyTrace | None:
        return latency_traces.get(kind)

    def mark_latency(name: str, context: str | LatencyTrace | None = None) -> None:
        trace = latency_traces.get(context) if isinstance(context, str) else context
        if trace is not None and name not in trace.marks:
            trace.mark(name)

    def queue_tts_trace(text: str, trace: LatencyTrace | None) -> None:
        while len(tts_trace_contexts) >= 128:
            tts_trace_contexts.popleft()
        tts_trace_contexts.append((text, trace))

    def mark_tts_first_pcm(trace: LatencyTrace | None) -> None:
        if trace is None:
            return
        if "tts_first_pcm" in trace.marks:
            return
        trace.mark("tts_first_pcm")
        audio_traces.append(trace)

    def audio_started() -> None:
        if not audio_traces:
            return
        trace = audio_traces.popleft()
        trace.mark("audio_started")
        if latency_traces.get(trace.kind) is trace:
            latency_traces.pop(trace.kind, None)
        if latency_log is not None:
            event_loop.call_soon_threadsafe(
                lambda finished=trace: asyncio.create_task(
                    asyncio.to_thread(latency_log.write, finished)
                )
            )

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
                playback_idle.clear()
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._playing = False
                self._quiet_at = time.monotonic() + 0.4
                playback_idle.set()
                barge.assistant_finished()
                speech_queue.finished()
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
            try:
                self._analyzer = LocalSmartTurnAnalyzerV3(sample_rate=16000)
                # This analyzer is hosted inside our custom processor instead
                # of Pipecat's turn strategy, so Pipecat will not initialize
                # its effective sample rate for us.
                self._analyzer.set_sample_rate(16000)
            except Exception as error:
                raise RuntimeError(f"Smart Turn readiness failed: {error}") from error
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
                start_latency("voice", "vad_stop")
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
        def __init__(self) -> None:
            super().__init__(name="coach")
            self.event_handler = None

        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, TranscriptionFrame) and frame.text:
                mark_latency("asr_final", "voice")
                events = session.on_user_text(frame.text)
                if self.event_handler is not None:
                    await self.event_handler(events)
                else:
                    for speech in events:
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
            try:
                self._model = load_engine(zerotts_model) if settings is not None else None
            except Exception as error:
                raise RuntimeError(f"ZeroTTS readiness failed: {error}") from error
            self._cache: dict[str, tuple[bytes, ...]] = {}
            self._cacheable = {
                "Để mình xem trang.",
                *(
                    line
                    for step in session.plan.steps
                    for line in (
                        f"Bước {step.number}. {step.instruction}",
                        f"{step.target_label}. Enter." if step.target_label else "",
                    )
                    if line
                ),
            }
            if self._model is not None:
                try:
                    for line in self._cacheable:
                        chunks = tuple(
                            pcm
                            for raw in self._model.synthesize_stream(line, voice=zerotts_voice)
                            if (pcm := float32_to_s16(raw))
                        )
                        if chunks:
                            self._cache[line] = chunks
                except Exception as error:
                    raise RuntimeError(f"ZeroTTS warmup failed: {error}") from error

        def _engine(self):
            if self._model is None:
                self._model = load_engine(zerotts_model)
            return self._model

        async def run_tts(self, text: str, context_id: str):
            trace = None
            queued = next((item for item in tts_trace_contexts if item[0] == text), None)
            if queued is not None:
                tts_trace_contexts.remove(queued)
                trace = queued[1]
            cached = self._cache.get(text)
            if cached is not None:
                for index, pcm in enumerate(cached):
                    if index == 0:
                        mark_tts_first_pcm(trace)
                    yield TTSAudioRawFrame(pcm, 48000, 1, context_id=context_id)
                return
            chunks: list[bytes] | None = [] if text in self._cacheable else None
            first = True
            async for pcm in stream_pcm(self._engine(), text, voice=zerotts_voice):
                if chunks is not None:
                    chunks.append(pcm)
                if first:
                    mark_tts_first_pcm(trace)
                    first = False
                yield TTSAudioRawFrame(pcm, 48000, 1, context_id=context_id)
            if chunks:
                self._cache[text] = tuple(chunks)

    transport = SoundDeviceTransport(
        TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_enabled=True,
            audio_out_sample_rate=48000,
        ),
        on_audio_started=audio_started,
    )
    coach_processor = CoachProcessor()
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
            coach_processor,
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
        "coach_processor": coach_processor,
        "speech_queue": speech_queue,
        "barge": barge,
        "mark_latency": mark_latency,
        "start_latency": start_latency,
        "current_latency": current_latency,
        "queue_tts_trace": queue_tts_trace,
        "tts_trace_contexts": tts_trace_contexts,
        "playback_idle": playback_idle,
    }


async def run_live(session: LearningSession, *, observer=None, browser_bridge=None, settings=None) -> None:
    from pipecat.frames.frames import InterruptionFrame, TTSSpeakFrame

    from coach.vision import VisionClient

    event_loop = asyncio.get_running_loop()
    built = build_live_pipeline(session, observer=observer, settings=settings)
    worker = built["worker"]
    runner = built["runner"]
    speech_queue = built["speech_queue"]
    barge = built["barge"]
    mark_latency = built["mark_latency"]
    start_latency = built["start_latency"]
    current_latency = built["current_latency"]
    queue_tts_trace = built["queue_tts_trace"]
    tts_trace_contexts = built["tts_trace_contexts"]
    playback_idle = built["playback_idle"]
    vision = VisionClient(settings, session.egress) if settings is not None else None
    completion_task: asyncio.Task | None = None

    async def queue_speech(
        speech: Speech,
        *,
        allow_interrupt: bool = True,
        trace: LatencyTrace | None = None,
    ) -> bool:
        decision = speech_queue.prepare(speech, allow_interrupt=allow_interrupt)
        if not decision.accepted:
            return False
        if decision.interrupt_current:
            tts_trace_contexts.clear()
            await worker.queue_frame(InterruptionFrame())
        mark_latency("agent_first_token", trace)
        barge.assistant_started()
        playback_idle.clear()
        for part in chunk_speech(speech.text):
            queue_tts_trace(part, trace)
            await worker.queue_frame(TTSSpeakFrame(part, append_to_context=False))
        return True

    async def say(items, *, trace: LatencyTrace | None = None) -> None:
        first_in_batch = True

        async def queue_batch_item(item: Speech) -> None:
            nonlocal first_in_batch
            accepted = await queue_speech(
                item,
                allow_interrupt=first_in_batch,
                trace=trace,
            )
            if accepted:
                first_in_batch = False

        for speech in items:
            if speech.kind == "llm_request":
                clauses: asyncio.Queue[Speech | BaseException | None] = asyncio.Queue()

                def produce() -> None:
                    try:
                        for clause in session.stream_llm(speech.text):
                            asyncio.run_coroutine_threadsafe(clauses.put(clause), event_loop).result()
                    except BaseException as error:
                        asyncio.run_coroutine_threadsafe(clauses.put(error), event_loop).result()
                    finally:
                        asyncio.run_coroutine_threadsafe(clauses.put(None), event_loop).result()

                producer = asyncio.create_task(asyncio.to_thread(produce))
                emitted = False
                try:
                    while True:
                        item = await asyncio.wait_for(clauses.get(), timeout=1.3 if not emitted else 2.0)
                        if item is None:
                            break
                        if isinstance(item, BaseException):
                            raise item
                        emitted = True
                        await queue_batch_item(item)
                except Exception:
                    if not emitted:
                        await queue_batch_item(session.local_explanation())
                finally:
                    if not producer.done():
                        producer.cancel()
                continue
            if speech.kind != "vision_request":
                await queue_batch_item(speech)
                continue
            await queue_batch_item(Speech("Để mình xem trang.", "vision_notice"))
            if browser_bridge is None or vision is None or not vision.available:
                await say(session.on_vision_error(), trace=trace)
                continue
            capture = await asyncio.to_thread(browser_bridge.capture_vision, speech.text)
            if capture is None:
                await say(session.on_vision_error(), trace=trace)
                continue
            try:
                guidance = await asyncio.wait_for(
                    asyncio.to_thread(vision.describe, capture),
                    timeout=settings.vision_timeout_seconds + 0.25,
                )
                await say(session.on_vision_guidance(guidance), trace=trace)
            except Exception:
                await say(session.on_vision_error(), trace=trace)
            finally:
                capture = None

    async def say_voice(items) -> None:
        nonlocal completion_task
        await say(items, trace=current_latency("voice"))
        if session.finished and completion_task is None:
            completion_task = asyncio.create_task(
                _finish_after_final_speech(runner, playback_idle),
                name="coach-session-finished",
            )

    built["coach_processor"].event_handler = say_voice

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
            scene_speech = session.note_scene(update.scene)
            if scene_speech:
                await say(scene_speech)
            session.note_bindings(update.bindings)
            page_speech = session.on_page(
                    label=update.keys.label,
                    bump=update.keys.bump,
                    flags=update.keys.flags,
                )
            if page_speech:
                trace = start_latency("browser", "browser_event", update.observed_at or None)
                await say(page_speech, trace=trace)
            if session.finished:
                if completion_task is None:
                    completion_task = asyncio.create_task(
                        _finish_after_final_speech(runner, playback_idle),
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


async def _finish_after_final_speech(
    runner,
    playback_idle: asyncio.Event,
    *,
    timeout: float = 30.0,
    settle_seconds: float = 0.35,
) -> None:
    """End only after output reports a stable drained state."""

    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        try:
            await asyncio.wait_for(playback_idle.wait(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        await asyncio.sleep(settle_seconds)
        if playback_idle.is_set():
            break
    await runner.end("lesson complete")
