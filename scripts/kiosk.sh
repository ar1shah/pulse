#!/usr/bin/env bash
# Chromium kiosk on the 7" screen. Started at login by the compositor's autostart (setup_pi.sh adds it).
# Waits for the server, then runs Chromium full screen and relaunches it whenever it exits:
# deploy.sh reloads the page by killing Chromium (pid in $XDG_RUNTIME_DIR/pulse-kiosk.pid). The UI's EXIT button
# (pi/pulse/kiosk.py) creates pulse-kiosk.exit first, and then this loop stops instead of relaunching.
set -u

RUN=${XDG_RUNTIME_DIR:-/tmp}
exec 9>"$RUN/pulse-kiosk.lock"
flock -n 9 || exit 0            # one kiosk loop at a time

URL=http://localhost:8000/
PROFILE=$HOME/.config/pulse-kiosk
rm -f "$RUN/pulse-kiosk.exit"
CHROMIUM=$(command -v chromium || command -v chromium-browser)
# on Wayland say so: launched from ssh (no XDG_SESSION_TYPE) Chromium would try X11 and exit at once
PLATFORM=()
[ -n "${WAYLAND_DISPLAY:-}" ] && PLATFORM=(--ozone-platform=wayland)

server_up() { (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; }

while true; do
  for _ in $(seq 60); do server_up && break; sleep 1; done

  # A killed Chromium thinks it crashed; mark the last exit clean so it never offers "Restore pages?".
  prefs=$PROFILE/Default/Preferences
  [ -f "$prefs" ] && sed -i -e 's/"exited_cleanly":false/"exited_cleanly":true/' \
                            -e 's/"exit_type":"[A-Za-z]*"/"exit_type":"Normal"/' "$prefs"

  "$CHROMIUM" --kiosk --user-data-dir="$PROFILE" "${PLATFORM[@]}" \
    --noerrdialogs --disable-infobars --no-first-run --no-default-browser-check \
    --disable-session-crashed-bubble --hide-crash-restore-bubble \
    --disable-features=Translate,TranslateUI --disable-pinch --overscroll-history-navigation=0 \
    --password-store=basic --disable-component-update \
    "$URL" 9>&- &
  echo $! > "$RUN/pulse-kiosk.pid"
  wait $!
  if [ -e "$RUN/pulse-kiosk.exit" ]; then
    rm -f "$RUN/pulse-kiosk.exit" "$RUN/pulse-kiosk.pid"
    exit 0
  fi
  sleep 1
done
