#!/bin/sh
# Open an isolated, user-controlled Chrome profile for the real-web coach.
# It binds DevTools only to loopback. The learner performs every login step.

set -eu
umask 077

if [ -n "${COACH_CDP_PORT:-}" ]; then
  PORT="$COACH_CDP_PORT"
else
  PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
PROFILE="${COACH_CHROME_PROFILE:-$HOME/Library/Application Support/OnboardCoachChrome}"
CHROME="${COACH_CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
START_URL="${COACH_START_URL:-https://supabase.com/dashboard}"

if [ ! -x "$CHROME" ]; then
  echo "Chrome was not found at: $CHROME" >&2
  echo "Set COACH_CHROME_BIN to your Chrome executable." >&2
  exit 1
fi

mkdir -p "$PROFILE"
chmod 700 "$PROFILE"
if [ "$PORT" = "0" ]; then
  rm -f "$PROFILE/DevToolsActivePort"
fi
echo "Coach Chrome DevTools: http://127.0.0.1:$PORT" >&2
exec "$CHROME" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --new-window \
  "$START_URL"
