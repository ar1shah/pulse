#!/usr/bin/env bash
# On the Pi, no sudo: ways to reopen the kiosk after the UI's EXIT button. A Pulse icon on the desktop, a menu entry
# (Accessories > Pulse) and a `pulse` command for the desktop Terminal. setup_pi.sh runs this; it's also fine to run
# by hand in the Pi's desktop Terminal: bash ~/pulse/scripts/pi_launchers.sh
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)

entry="[Desktop Entry]
Type=Application
Name=Pulse
Comment=Open the Pulse radar full screen
Exec=bash $REPO/scripts/kiosk.sh
Icon=$REPO/ui/icon.svg
Terminal=false
Categories=Utility;"

for f in "$HOME/.local/share/applications/pulse.desktop" "$HOME/Desktop/pulse.desktop"; do
  if [ "$(cat "$f" 2>/dev/null)" = "$entry" ]; then
    echo "ok: $f already there"
  else
    mkdir -p "$(dirname "$f")"
    echo "$entry" > "$f"
    chmod +x "$f"
    echo "CHANGED: Pulse launcher $f"
  fi
done

alias_line="alias pulse='setsid bash $REPO/scripts/kiosk.sh >/dev/null 2>&1 &'   # open the Pulse kiosk"
if grep -qxF "$alias_line" "$HOME/.bashrc" 2>/dev/null; then
  echo "ok: 'pulse' command already in ~/.bashrc"
else
  sed -i '/^alias pulse=/d' "$HOME/.bashrc"
  echo "$alias_line" >> "$HOME/.bashrc"
  echo "CHANGED: 'pulse' command in ~/.bashrc (works in Terminal windows opened from now on)"
fi
