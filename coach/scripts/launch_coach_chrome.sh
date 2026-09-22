#!/bin/sh
# Open an isolated, user-controlled Chrome profile for the real-web coach.
# It binds DevTools only to loopback. The learner performs every login step.

set -eu

PORT="${COACH_CDP_PORT:-9222}"
PROFILE="${COACH_CHROME_PROFILE:-$HOME/Library/Application Support/OnboardCoachChrome}"
CHROME="${COACH_CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

if [ ! -x "$CHROME" ]; then
  echo "Chrome was not found at: $CHROME" >&2
  echo "Set COACH_CHROME_BIN to your Chrome executable." >&2
  exit 1
fi

mkdir -p "$PROFILE"
exec "$CHROME" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" \
  --no-first-run \
  --no-default-browser-check \
  --new-window
