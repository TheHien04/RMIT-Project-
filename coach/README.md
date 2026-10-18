# Coach Companion runtime

**Developer and operator guide for the local-first Vietnamese voice coaching runtime.**

---

The runtime combines a reviewed lesson, browser observation, adaptive coaching policy, local speech models, and explicit accessibility assistance. The learner remains responsible for navigation, data entry, and destructive actions.

For the product overview, screenshots, and architecture diagrams, start with the [repository README](../README.md).

## Install

All dependencies stay inside `coach/.venv312`; nothing is installed into the system Python.

```bash
cd coach
uv venv .venv312 --python 3.12
uv pip install --python .venv312/bin/python -e ".[dev,voice]"
.venv312/bin/python -m playwright install chromium
cp .env.example .env
chmod 600 .env
```

`coach/.env` is ignored by Git. Startup rejects an environment file containing `OPENAI_API_KEY` when that file is readable by other users.

## Run the app

Build the local macOS app once, then open it from Finder whenever it is needed:

```bash
sh scripts/build_macos_app.sh
open "Coach Companion.app"
```

The app opens a loopback-only control panel at `http://127.0.0.1:8787`. It can start and stop the voice process, open the dedicated Supabase Chrome profile, report readiness, and release the microphone and app-owned Chrome process on exit.

For development, run the control panel directly:

```bash
.venv312/bin/python -m coach app
```

The generated `.app` bundle is intentionally ignored. A local build receives an ad-hoc integrity signature. Distribution requires an Apple Developer ID signature and notarization.

## Configure the Supabase lesson

The supplied target manifest is reviewed for the current staging lesson. Update its project-specific URL paths before using another project.

Recommended local voice settings:

```dotenv
COACH_MIC=true
COACH_TTS=zerotts
COACH_SPEECH_POLICY=focus
COACH_ASSISTANCE_LEVEL=adaptive
COACH_NAV_MODE=native_focus
COACH_INJECT_NAVIGATION=false
COACH_KEYBOARD_REPAIR=target_only

COACH_START_URL=https://supabase.com/dashboard
COACH_TARGET_MANIFEST=fixtures/lessons/supabase-table-editor.json
COACH_LESSON_PDF=fixtures/lessons/supabase-table-editor.pdf
```

Keep these values disabled for a fully local session:

```dotenv
COACH_LLM=false
COACH_VISION=false
```

When cloud text answers or vision are enabled, separate audible consent is still required in every session. Audio is never sent to OpenAI.

## Use a real staging tab

The recommended path is the **Open Supabase to learn** button in Coach Companion. It launches Chrome with:

- a dedicated user-data directory;
- DevTools bound to `127.0.0.1`;
- a random lifecycle-bound port;
- manual authentication by the learner;
- exact origin and tab selection checks.

For development only, Chrome can be launched manually:

```bash
COACH_CDP_PORT=49173 sh scripts/launch_coach_chrome.sh
```

Then set the matching endpoint for that run:

```dotenv
COACH_CDP_URL=http://127.0.0.1:49173
```

Do not expose credentials, MFA, API keys, billing, member management, production accounts, or unrelated personal tabs to the coaching profile. Chrome DevTools access is equivalent to control of that isolated browser profile while the session is active.

## Voice and keyboard behaviour

The default real-web mode is `native_focus`:

- Tab and Shift+Tab remain owned by the page and the learner's screen reader.
- Focus changes are observed, not generated.
- In `focus` speech policy, the coach announces each newly focused control.
- On the reviewed target, the coach says that the learner has arrived and prompts them to press Enter.
- A new focus event cancels stale, low-priority speech.

`COACH_KEYBOARD_REPAIR=target_only` can repair a reviewed target that has a click listener but no keyboard semantics. It adds runtime `role`, `tabindex`, and Enter/Space handling to that exact DOM node. It does not modify the website source, move focus, or click the control. The target manifest must also declare `accessibility.keyboard_repair_allowed=true`.

`coach_list` is a fallback for role-less training pages. It is enabled only after an explicit learner request, and Escape returns arrow keys to the page or screen reader.

Synthetic focus or click assistance requires `focus giúp` or `bấm giúp`, is locally audited, and never counts as lesson completion. Destructive steps reject synthetic activation.

## Learning lifecycle

Accessibility support and teaching support have separate lifecycles. Keyboard access remains available; instructional speech fades per skill through:

1. `orientation`
2. `guided`
3. `practice`
4. `on_demand`

The coach proposes a lower support level only after verified independent success. The learner can accept, keep the current level, request more detail, or return to guided mode at any time.

Progress is stored in `state/progress.json`. It records skill state, verification source, and small learning counters—not transcripts, DOM content, URLs, or screenshots.

## Spoken commands

| Vietnamese command | Behaviour |
| --- | --- |
| `bắt đầu học` | Start or resume the current lesson. |
| `gợi ý` | Move one level up the hint ladder. |
| `tôi đang ở đâu` | Describe the current focused control. |
| `mục tiêu bài học` | Explain the skill being practised. |
| `bài tự luyện` | Offer a transfer task for independent practice. |
| `xong bước này` | Verify the current DOM condition before advancing. |
| `tôi đã hoàn thành bài học` | Verify all lesson completion conditions. |
| `dừng hướng dẫn` | Stop voice guidance without marking the lesson complete. |
| `focus giúp` | Focus the approved target after an explicit request. |
| `bấm giúp` | Activate a permitted target after an explicit request. |

If local state cannot verify a learner's completion claim, the coach asks for a distinct, explicit confirmation phrase. User-confirmed progress is stored separately from DOM-verified independent completion.

## Runtime layers

1. **Lesson layer** — parses the approved PDF into a `LessonPlan` with citations and completion conditions.
2. **Browser layer** — attaches to one approved tab, observes focus and DOM changes, binds exact target labels, and evaluates reviewed probes.
3. **Session layer** — applies intent, assistance, speech, consent, and completion policy.
4. **Voice layer** — uses VAD, Smart Turn, PhoWhisper, a priority speech queue, and streamed ZeroTTS audio.
5. **Optional cloud layer** — handles open-ended paraphrasing or redacted vision only after feature enablement and session consent.

DOM state is authoritative for focus, selectors, actions, and completion. Vision may describe the interface or choose among labels already observed in the DOM, but it cannot invent selectors, operate the browser, change the lesson, or complete a step.

## Privacy boundary

- Audio, DOM, focus events, completion checks, and progress stay local by default.
- `COACH_TTS=zerotts` keeps speech synthesis on the machine.
- `COACH_TTS=edge` sends utterance text to Microsoft and records that egress locally.
- Text LLM requests exclude raw DOM, credentials, screenshots, and form values.
- Vision screenshots are redacted, held in memory for one request, and released in `finally` paths.
- Logs contain timing, decision, origin, and redacted audit metadata—not transcripts or screenshot bytes.

See [SECURITY.md](SECURITY.md) for the trust boundary, current dependency exception, and release requirements.

## Test

Deterministic core suite:

```bash
.venv312/bin/python -m pytest -q \
  -k "not test_edge_tts_returns_audio and not test_zerotts_streams_audible_audio and not test_phowhisper_transcribes_on_the_gpu and not test_silero_and_smart_turn_score_local_audio"
```

Browser integration and system smoke:

```bash
env -u PLAYWRIGHT_BROWSERS_PATH .venv312/bin/python -m pytest -m integration -q
env -u PLAYWRIGHT_BROWSERS_PATH .venv312/bin/python -m pytest -m system -q
```

Local model probes:

```bash
.venv312/bin/python -m pytest \
  tests/test_local_voice.py tests/test_voice_stack.py tests/test_local_audio.py -q
```

Run latency checks after at least 100 warm samples per path:

```bash
.venv312/bin/python -m coach latency-report --kind voice
.venv312/bin/python -m coach latency-report --kind browser
.venv312/bin/python -m coach latency-report --kind vision
```

The complete test matrix and manual acceptance procedure are documented in [docs/TESTING.md](docs/TESTING.md).

## CLI reference

```text
python -m coach app                    Local control panel
python -m coach live                   Guided browser and voice runtime
python -m coach demo                   Closed-loop, no-egress demo
python -m coach serve                  Local accessibility fixture
python -m coach speak                  ZeroTTS audio probe
python -m coach latency-report         SLO report from local JSONL traces
```

## Further reading

- [Documentation index](docs/README.md)
- [Product principles](docs/PRODUCT_PRINCIPLES.md)
- [Accessible navigation](docs/ACCESSIBLE_NAVIGATION.md)
- [Implementation status](docs/IMPLEMENTATION_STATUS.md)
- [Test strategy](docs/TESTING.md)
- [Demo script](demo/SCRIPT.md)
