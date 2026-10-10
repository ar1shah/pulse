#!/usr/bin/env bash
# From the Mac: follow the Pulse server's journal on the Pi (last 100 lines, then live). Ctrl-C to stop.
# Extra args go to journalctl, e.g. scripts/pi_logs.sh --since "10 min ago" --no-pager
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${PI_HOST:-}" ] && [ -f .env ]; then PI_HOST=$(sed -n 's/^PI_HOST=//p' .env | tail -1); fi
PI_HOST=${PI_HOST:-pulse@pulse.local}

follow=" -f"
args=""
for a in "$@"; do
  if [ "$a" = --no-pager ]; then follow=""; fi
  args+=" $(printf '%q' "$a")"
done
exec ssh -t "$PI_HOST" "journalctl --user -u pulse.service -n 100 -o short-iso$follow$args"
