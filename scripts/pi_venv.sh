#!/usr/bin/env bash
# On the Pi: create ~/pulse/.venv if it's missing, (re)install pi/requirements.txt only when the file changed.
# Used by setup_pi.sh and deploy.sh.
set -euo pipefail
cd "$(dirname "$0")/.."

REQ=pi/requirements.txt
STAMP=.venv/.requirements.sha256

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
  echo "CHANGED: created ~/pulse/.venv ($(.venv/bin/python --version))"
fi

want=$(sha256sum "$REQ" | cut -d' ' -f1)
if [ "$(cat "$STAMP" 2>/dev/null)" != "$want" ]; then
  echo "installing $REQ into the venv..."
  .venv/bin/pip install --disable-pip-version-check -q -r "$REQ"
  echo "$want" > "$STAMP"
  echo "CHANGED: installed $REQ"
else
  echo "ok: $REQ unchanged, venv up to date"
fi
