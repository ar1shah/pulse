#!/usr/bin/env bash
# From the Mac: copy the repo to ~/pulse on the Pi, update the venv only if requirements changed, restart the
# server, reload the kiosk page. Works on a fresh Pi too (then it tells you to run setup_pi.sh). No sudo needed.
#   PI_HOST=pulse@pulse.local scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -z "${PI_HOST:-}" ] && [ -f .env ]; then PI_HOST=$(sed -n 's/^PI_HOST=//p' .env | tail -1); fi
PI_HOST=${PI_HOST:-pulse@pulse.local}

rev=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
[ -z "$(git status --porcelain 2>/dev/null)" ] || rev="$rev+uncommitted"
echo "deploying $rev to $PI_HOST:~/pulse"

# --delete never touches excluded paths, so the Pi keeps its own .env, .venv and recordings.
rsync -az --delete \
  --exclude .git --exclude .venv --exclude .env --exclude recordings --exclude __pycache__ \
  --exclude .pytest_cache --exclude .DS_Store --exclude .claude \
  ./ "$PI_HOST:pulse/"
echo "ok: files copied"

ssh "$PI_HOST" PI_HOST="$PI_HOST" bash -s <<'EOF'
set -euo pipefail
cd ~/pulse
bash scripts/pi_venv.sh

unit=~/.config/systemd/user/pulse.service
if [ -f "$unit" ]; then
  cmp -s scripts/pulse.service "$unit" \
    || echo "warning: scripts/pulse.service changed; re-run setup_pi.sh to install it (running the old one)"
  systemctl --user restart pulse.service
  for _ in $(seq 30); do (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null && break; sleep 0.5; done
  if (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; then
    echo "ok: pulse.service restarted, server up on :8000"
  else
    echo "warning: pulse.service restarted but :8000 isn't answering; run scripts/pi_logs.sh"
  fi
else
  echo "pulse.service isn't installed yet. Run once: ssh -t $PI_HOST bash pulse/scripts/setup_pi.sh"
fi

pidfile=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/pulse-kiosk.pid
if [ -f "$pidfile" ] && kill "$(cat "$pidfile")" 2>/dev/null; then
  echo "ok: kiosk reloading (Chromium relaunches in a few seconds)"
else
  echo "kiosk not running (it starts at login once setup_pi.sh has run and the Pi has rebooted)"
fi
EOF
