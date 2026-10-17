# Test strategy

The suite is intentionally split so that a green test does not claim more than
it proves.

## Unit tests

Run without a real authenticated website:

```bash
.venv/bin/python -m pytest \
  tests/test_lesson.py tests/test_targets.py tests/test_dom_map.py \
  tests/test_session.py tests/test_privacy.py tests/test_local_audio.py
```

They cover:

- PDF citation grounding and completion-probe parsing;
- exact URL path versus child-route behavior;
- origin allowlist and reviewed target manifests;
- semantic/role-less binding and ambiguous labels;
- spoken navigation modes, explicit assist, and no completion on assertion;
- adaptive per-skill coaching, learner-controlled speech levels, hint ladder,
  focus-loop recovery, and local progress persistence;
- target-only keyboard repair that never focuses or activates the control;
- browser audit redaction;
- non-blocking audio callback buffer.
- quiet speech priority/deduplication and 100-turn latency summaries;
- per-session vision consent, structured-output grounding, low-to-high retry,
  in-memory screenshot capture, and redacted egress metadata.

## Integration tests

These launch a local fixture browser with loopback CDP. They never use a real
Supabase account:

```bash
env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/python -m pytest -m integration -q
```

They prove:

- manual-auth fixture → pinned CDP attach → native focus binding → URL probe;
- explicit `bấm giúp` for a role-less div;
- no observation after navigation to an unapproved origin;
- browser bridge, lesson session, completion probe, and audit work together.

## Voice/model tests

Run in Python 3.12 only:

```bash
.venv312/bin/python -m pytest \
  tests/test_local_voice.py tests/test_voice_stack.py tests/test_local_audio.py -q
```

They load Silero, Smart Turn, MLX PhoWhisper GPU, ZeroTTS audio streaming, and
the local audio output contract. They do not require microphone permission.

## System smoke

```bash
env -u PLAYWRIGHT_BROWSERS_PATH .venv/bin/python -m pytest -m system -q
```

This replays the Supabase navigation lesson against its reviewed
manifest, verifying each step advances only on the exact target path.

## Manual hardware/system acceptance

Before a demo, use a staging-only Supabase project:

1. Launch the isolated Chrome profile from Coach Companion so it receives a
   random lifecycle-bound CDP port. For manual testing only, use
   `COACH_CDP_PORT=49173 sh scripts/launch_coach_chrome.sh` and set
   `COACH_CDP_URL=http://127.0.0.1:49173` for that run.
2. Log in manually and open the approved project tab.
3. Run `.venv312/bin/python -m coach live`.
4. Say `bắt đầu học`, use Tab/Enter to open `Table Editor`.
5. On the role-less `Create a table` target, confirm Tab can reach it after the
   repair notice and that nothing opens until the learner presses Enter.
6. Confirm the lesson advances only after the reviewed `Name` input selector appears.
7. Enter `coach_demo_tasks`, keep RLS plus the default `id` and `created_at`
   columns, then Tab to Save. Confirm `bấm giúp` is refused on this destructive step.
8. Press Enter yourself and confirm completion only after Supabase navigates to
   the newly created table route. This writes a real table to staging.
9. Repeat a learned step and confirm guidance fades; say `gợi ý` and
   `hướng dẫn chi tiết` to confirm support can always be restored.
10. Confirm each scoped selector/URL probe advances one step and final TTS stops the runner.
11. Review `logs/browser-audit.jsonl` and `logs/egress.jsonl`; neither should
   contain raw DOM, cookies, tokens, passwords, or screenshots.
