#!/usr/bin/env bash
# One-time Pi setup, safe to re-run: serial ports, the server service, the Chromium kiosk. Prints every change it
# makes and never reboots. Run on the Pi as the desktop user (it asks for the sudo password once), after
# scripts/deploy.sh has copied the repo to ~/pulse:
#   ssh -t pulse@pulse.local bash pulse/scripts/setup_pi.sh
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
CONFIG=/boot/firmware/config.txt
CMDLINE=/boot/firmware/cmdline.txt
CURSOR_THEME=pulse-blank
CHANGES=()
REBOOT=()

changed() { echo "CHANGED: $1"; CHANGES+=("$1"); }
ok() { echo "ok: $1"; }
die() { echo; echo "STOP: $1" >&2; exit 1; }
# append $2 to file $1 unless that exact line is already there
ensure_line() { grep -qxF -- "$2" "$1" 2>/dev/null || { echo "$2" >> "$1"; return 1; }; }

[ "$(id -u)" -ne 0 ] || die "run this as the desktop user (pulse), not with sudo; it calls sudo itself"
[ "$REPO" = "$HOME/pulse" ] || die "expected the repo at ~/pulse, found $REPO (copy it with scripts/deploy.sh)"

echo "== detect"
. /etc/os-release
echo "OS:         $PRETTY_NAME"
bits=$(getconf LONG_BIT)
echo "arch:       $(uname -m), $bits-bit userland ($(dpkg --print-architecture))"
[ "$bits" = 64 ] || echo "warning: 32-bit OS; the playbook expects 64-bit (Pulse should still run)"

if [ -x /usr/bin/labwc ] || [ -x /usr/bin/wayfire ] || [ -x /usr/bin/startlxde-pi ] || dpkg -s lightdm &>/dev/null; then
  echo "image:      desktop"
else
  die "this is Raspberry Pi OS Lite (no desktop). The kiosk needs the desktop image: reflash with Raspberry Pi
      Imager, OS 'Raspberry Pi OS (64-bit)' (the one with the desktop), then deploy and run this again."
fi

compositor=""
for c in labwc wayfire; do pgrep -x "$c" >/dev/null && { compositor=$c; break; }; done
if [ -z "$compositor" ] && pgrep -x Xorg >/dev/null; then compositor=x11; fi
if [ -z "$compositor" ]; then       # desktop not running right now: go by the autologin session
  session=$(sed -n 's/^autologin-session=//p; s/^user-session=//p' /etc/lightdm/lightdm.conf 2>/dev/null | tail -1)
  case "$session" in *labwc*) compositor=labwc ;; *wayfire*) compositor=wayfire ;; ?*) compositor=x11 ;; esac
fi
[ -n "$compositor" ] || die "can't tell which compositor the desktop uses (labwc, wayfire or X11)"
echo "compositor: $compositor"

chromium=$(command -v chromium || command -v chromium-browser || true)
[ -n "$chromium" ] || die "no Chromium found (chromium or chromium-browser); install it: sudo apt install chromium"
echo "chromium:   $chromium ($("$chromium" --version 2>/dev/null || echo 'version unknown'))"

echo
echo "sudo needs your Pi password once:"
sudo -v

echo
echo "== serial ports"
config_before=$(mktemp); cmdline_before=$(mktemp)
cp "$CONFIG" "$config_before"; cp "$CMDLINE" "$cmdline_before"

if [ "$(sudo raspi-config nonint get_serial_cons)" = 0 ]; then
  sudo raspi-config nonint do_serial_cons 1
  changed "serial login console off"
else
  ok "serial login console already off"
fi
if [ "$(sudo raspi-config nonint get_serial_hw)" != 0 ]; then
  sudo raspi-config nonint do_serial_hw 0
  changed "serial hardware on"
else
  ok "serial hardware already on"
fi

# enable_uart=1, dtoverlay=disable-bt, dtoverlay=uart3: each exactly once in the [all] part of config.txt
sudo python3 - "$CONFIG" <<'PY'
import sys

path = sys.argv[1]
want = ["enable_uart=1", "dtoverlay=disable-bt", "dtoverlay=uart3"]
out, seen, section = [], set(), "all"
for line in open(path).read().splitlines():
    s = line.strip()
    if s.startswith("[") and s.endswith("]"):
        section = s[1:-1].strip().lower()
    elif section == "all" and (s in want or s == "enable_uart=0"):
        if s in seen or s == "enable_uart=0":
            continue                    # a duplicate, or the opposite setting
        seen.add(s)
    out.append(line)
missing = [w for w in want if w not in seen]
if missing:
    if section != "all":
        out.append("[all]")
    out.append("# Pulse: UART0 on the PL011 for the LD2450 (256000 baud), UART3 for the C1001 (scripts/setup_pi.sh)")
    out += missing
open(path, "w").write("\n".join(out) + "\n")
PY

stamp=$(date +%Y%m%d-%H%M%S)
for pair in "$CONFIG:$config_before" "$CMDLINE:$cmdline_before"; do
  file=${pair%%:*}; before=${pair#*:}
  if cmp -s "$file" "$before"; then
    ok "$file already right"
  else
    sudo cp "$before" "$file.bak-$stamp"
    diff -u --label "$file (before)" --label "$file (now)" "$before" "$file" || true
    changed "edited $file (backup: $file.bak-$stamp)"
    REBOOT+=("$(basename "$file")")
  fi
  rm -f "$before"
done

# with disable-bt the Bluetooth modem service has no UART to attach to
if systemctl is-enabled hciuart.service 2>/dev/null | grep -qx enabled; then
  sudo systemctl disable hciuart.service
  changed "disabled hciuart.service (Bluetooth UART, freed by disable-bt)"
fi

if id -nG "$USER" | grep -qw dialout; then
  ok "$USER already in dialout"
else
  sudo usermod -aG dialout "$USER"
  changed "added $USER to dialout"
  REBOOT+=("dialout group")
fi

echo
echo "== packages"
pkgs=(python3-venv)
if [ "$compositor" = x11 ]; then pkgs+=(unclutter); fi
missing_pkgs=()
for p in "${pkgs[@]}"; do dpkg -s "$p" &>/dev/null || missing_pkgs+=("$p"); done
if [ ${#missing_pkgs[@]} -eq 0 ]; then
  ok "packages already installed: ${pkgs[*]}"
else
  sudo apt-get install -y "${missing_pkgs[@]}" || { sudo apt-get update && sudo apt-get install -y "${missing_pkgs[@]}"; }
  changed "apt installed ${missing_pkgs[*]}"
fi

echo
echo "== python venv"
venv_out=$(bash "$REPO/scripts/pi_venv.sh")
echo "$venv_out"
while IFS= read -r line; do
  if [[ $line == CHANGED:* ]]; then CHANGES+=("${line#CHANGED: }"); fi
done <<< "$venv_out"

echo
echo "== server service"
if [ -f "$REPO/.env" ]; then
  ok "~/pulse/.env exists (PULSE_SOURCE=$(sed -n 's/^PULSE_SOURCE=//p' "$REPO/.env" | tail -1))"
else
  grep -v '^PI_HOST=' "$REPO/.env.example" > "$REPO/.env"
  changed "created ~/pulse/.env from .env.example (PULSE_SOURCE=sim)"
fi

unit_dir=$HOME/.config/systemd/user
mkdir -p "$unit_dir"
restart=0
if cmp -s "$REPO/scripts/pulse.service" "$unit_dir/pulse.service"; then
  ok "pulse.service already installed"
else
  cp "$REPO/scripts/pulse.service" "$unit_dir/pulse.service"
  systemctl --user daemon-reload
  changed "installed pulse.service (systemd user unit, $unit_dir)"
  restart=1
fi
if systemctl --user is-enabled -q pulse.service; then
  ok "pulse.service already enabled"
else
  systemctl --user enable pulse.service
  changed "enabled pulse.service"
fi
if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = yes ]; then
  ok "linger already on"
else
  sudo loginctl enable-linger "$USER"
  changed "linger on for $USER (user services start at boot, without a login)"
fi
if [ $restart = 1 ] || ! systemctl --user is-active -q pulse.service; then
  systemctl --user restart pulse.service
  changed "(re)started pulse.service"
fi
for _ in $(seq 30); do (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null && break; sleep 1; done
python3 -c 'import json, urllib.request as u; s = json.load(u.urlopen("http://127.0.0.1:8000/api/snapshot", timeout=3)); print("ok: server answers on :8000, source " + s["source"])' \
  || echo "warning: server not answering on :8000 yet; see scripts/pi_logs.sh"

echo
echo "== kiosk + cursor + screen blanking ($compositor)"
kiosk_cmd="bash $REPO/scripts/kiosk.sh &"

if [ "$compositor" = labwc ] || [ "$compositor" = wayfire ]; then
  theme_dir=$HOME/.local/share/icons/$CURSOR_THEME
  if [ -f "$theme_dir/cursors/left_ptr" ]; then
    ok "blank cursor theme already there"
  else
    python3 - "$theme_dir" <<'PY'
import os, struct, sys

d = sys.argv[1]
os.makedirs(f"{d}/cursors", exist_ok=True)
with open(f"{d}/index.theme", "w") as f:
    f.write("[Icon Theme]\nName=pulse-blank\nComment=Invisible cursor for the Pulse kiosk\n")
IMAGE, SIZE = 0xFFFD0002, 24
chunk = struct.pack("<9I", 36, IMAGE, SIZE, 1, 1, 1, 0, 0, 0) + struct.pack("<I", 0)    # one transparent pixel
xcursor = b"Xcur" + struct.pack("<3I", 16, 0x10000, 1) + struct.pack("<3I", IMAGE, SIZE, 28) + chunk
with open(f"{d}/cursors/left_ptr", "wb") as f:
    f.write(xcursor)
names = """default pointer hand1 hand2 text xterm ibeam crosshair cross move fleur grab grabbing watch wait progress
left_ptr_watch not-allowed no-drop help question_arrow context-menu copy alias cell vertical-text zoom-in zoom-out
all-scroll col-resize row-resize ew-resize ns-resize nesw-resize nwse-resize n-resize s-resize e-resize w-resize
ne-resize nw-resize se-resize sw-resize sb_h_double_arrow sb_v_double_arrow top_side bottom_side left_side
right_side top_left_corner top_right_corner bottom_left_corner bottom_right_corner X_cursor""".split()
for n in names:
    p = f"{d}/cursors/{n}"
    if not os.path.lexists(p):
        os.symlink("left_ptr", p)
PY
    changed "created the blank cursor theme $theme_dir"
  fi
fi

case "$compositor" in
  labwc)
    mkdir -p "$HOME/.config/labwc"
    env_file=$HOME/.config/labwc/environment
    if grep -qx "XCURSOR_THEME=$CURSOR_THEME" "$env_file" 2>/dev/null; then
      ok "labwc cursor hidden (XCURSOR_THEME=$CURSOR_THEME)"
    else
      touch "$env_file"
      sed -i '/^XCURSOR_THEME=/d' "$env_file"
      echo "XCURSOR_THEME=$CURSOR_THEME" >> "$env_file"
      changed "labwc cursor hidden: XCURSOR_THEME=$CURSOR_THEME in $env_file (delete that line to get it back)"
      REBOOT+=("labwc environment")
    fi
    # Pi OS starts labwc with -m (merge config), so this file adds to the desktop's autostart, it doesn't replace it.
    if ensure_line "$HOME/.config/labwc/autostart" "$kiosk_cmd"; then
      ok "kiosk already in ~/.config/labwc/autostart"
    else
      changed "kiosk added to ~/.config/labwc/autostart"
      REBOOT+=("kiosk autostart")
    fi
    ;;
  wayfire)
    ini=$HOME/.config/wayfire.ini
    touch "$ini"
    if grep -q "pulse_kiosk" "$ini"; then
      ok "kiosk already in $ini"
    else
      printf '\n[autostart]\npulse_kiosk = %s\n\n[input]\ncursor_theme = %s\n' "bash $REPO/scripts/kiosk.sh" "$CURSOR_THEME" >> "$ini"
      changed "kiosk autostart + blank cursor added to $ini"
      REBOOT+=("kiosk autostart")
    fi
    ;;
  x11)
    lx=$HOME/.config/lxsession/LXDE-pi/autostart
    if [ ! -f "$lx" ]; then       # the user file replaces the system one, so start from a copy of it
      mkdir -p "$(dirname "$lx")"
      cp /etc/xdg/lxsession/LXDE-pi/autostart "$lx" 2>/dev/null || touch "$lx"
    fi
    n=0
    ensure_line "$lx" "@unclutter -idle 0.5 -root" || n=1
    ensure_line "$lx" "@bash $REPO/scripts/kiosk.sh" || n=1
    if [ $n = 1 ]; then changed "kiosk + unclutter added to $lx"; REBOOT+=("kiosk autostart"); else ok "kiosk already in $lx"; fi
    ;;
esac

# after the UI's EXIT button: a desktop icon, a menu entry and a `pulse` command bring the kiosk back
launch_out=$(bash "$REPO/scripts/pi_launchers.sh")
echo "$launch_out"
while IFS= read -r line; do
  if [[ $line == CHANGED:* ]]; then CHANGES+=("${line#CHANGED: }"); fi
done <<< "$launch_out"

if [ "$(sudo raspi-config nonint get_blanking)" = 0 ]; then
  sudo raspi-config nonint do_blanking 1
  changed "screen blanking off"
  REBOOT+=("screen blanking")
else
  ok "screen blanking already off"
fi

echo
echo "== summary"
if [ ${#CHANGES[@]} -eq 0 ]; then
  echo "Nothing changed: the Pi was already set up."
else
  echo "Changed:"
  printf '  - %s\n' "${CHANGES[@]}"
fi
if [ ${#REBOOT[@]} -gt 0 ]; then
  echo
  echo "REBOOT NEEDED for: ${REBOOT[*]}"
  echo "This script never reboots. When ready: sudo reboot"
fi
