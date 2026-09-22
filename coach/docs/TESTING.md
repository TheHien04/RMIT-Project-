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
- browser audit redaction;
- non-blocking audio callback buffer.

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

This replays the five-step Supabase navigation lesson against its reviewed
manifest, verifying each step advances only on the exact target path.

## Manual hardware/system acceptance

Before a demo, use a staging-only Supabase project:

1. Launch the isolated Chrome profile with `sh scripts/launch_coach_chrome.sh`.
2. Log in manually and open the approved project tab.
3. Run `.venv312/bin/python -m coach live`.
4. Say `bắt đầu học`, use Tab/Enter to finish every navigation step.
5. Confirm each URL probe advances one step and the final TTS stops the runner.
6. Review `logs/browser-audit.jsonl` and `logs/egress.jsonl`; neither should
   contain raw DOM, cookies, tokens, passwords, or screenshots.
