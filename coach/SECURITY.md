# Security policy

## Local trust boundary

- `coach/.env` must be owner-readable only (`chmod 600 coach/.env`). Startup
  fails if a file containing `OPENAI_API_KEY` is group- or world-accessible.
- Chrome DevTools binds only to `127.0.0.1`, uses an isolated `0700` profile,
  and obtains its port from Chrome's owner-controlled `DevToolsActivePort`.
- Browser actions, screenshot capture, origins and lesson completion are
  capabilities declared in the reviewed target manifest and default closed.
- Text LLM and Vision use separate, audible, per-session consent. Declining
  either leaves the corresponding content on the device.

## Dependency exception

`pipecat-ai==1.8.1` declares `nltk>=3.10,<4`. As of 2026-10-15, pip-audit
reports `PYSEC-2026-3740` / `CVE-2026-81726` and no fixed NLTK release. The
issue affects NLTK model import/export APIs when an application relies on
NLTK `pathsec` to constrain attacker-controlled paths. Coach does not import
NLTK, enable `pathsec`, expose NLTK model paths, or call the affected APIs.

CI ignores only this exact advisory and continues to fail on every other
reported vulnerability. Remove the exception as soon as Pipecat or NLTK
ships a patched compatible version.

## Release requirements

Before distributing outside the development machine:

1. Rotate any development API key and provision a least-privilege key.
2. Run the complete test suite, dependency audit and 100-turn latency checks.
3. Sign with an Apple Developer ID and notarize the app. The default ad-hoc
   signature is only an integrity seal for local development.
4. Complete manual acceptance with blind VoiceOver users on a staging project.
