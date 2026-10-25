#!/usr/bin/env bash
# Rimeclaw installer: an Emberfall desktop pet that walks around your screen and roasts you.
# One-liner:  curl -fsSL https://raw.githubusercontent.com/tmacgoat/rimeclaw/main/install.sh | bash
set -euo pipefail
SLUG=rimeclaw
REPO=tmacgoat/rimeclaw
BRANCH=main
DEST="$HOME/.local/share/$SLUG"
BIN="$HOME/.local/bin/$SLUG"
APPS="$HOME/.local/share/applications"
AUTO="$HOME/.config/autostart"
say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

if [ "$(id -u)" = 0 ]; then
  echo "Please run this as your normal user (no sudo in front). It will ask for your password when it needs it."
  exit 1
fi

# 1) system packages (from Ubuntu's own repos, no pip)
need=()
python3 -c 'import PyQt6.QtWidgets, PyQt6.QtNetwork' >/dev/null 2>&1 || need+=(python3-pyqt6)
dpkg -s libxcb-cursor0 >/dev/null 2>&1 || need+=(libxcb-cursor0)
command -v pw-play >/dev/null 2>&1 || command -v paplay >/dev/null 2>&1 || need+=(pipewire-bin)
command -v curl >/dev/null 2>&1 || need+=(curl)
if [ ${#need[@]} -gt 0 ]; then
  say "Installing: ${need[*]} (your password may be asked)"
  sudo apt-get update -qq || true
  sudo apt-get install -y "${need[@]}"
fi

# 2) files -> ~/.local/share/rimeclaw
here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || true)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
if [ -n "$here" ] && [ -f "$here/app/rimeclaw.py" ]; then
  say "Copying from $here"
  cp -a "$here/." "$tmp/src"
else
  say "Downloading Rimeclaw"
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar xz -C "$tmp"
  mv "$tmp/$SLUG-$BRANCH" "$tmp/src"
fi
# stop an old copy if it's running
if [ -x "$BIN" ]; then "$BIN" quit >/dev/null 2>&1 || true; sleep 1; fi
pkill -f "$DEST/app/rimeclaw.py" >/dev/null 2>&1 || true
rm -rf "$DEST.new"; mkdir -p "$(dirname "$DEST")"
cp -a "$tmp/src" "$DEST.new"; rm -rf "$DEST.new/.git"
rm -rf "$DEST"; mv "$DEST.new" "$DEST"
chmod +x "$DEST/app/rimeclaw.py" "$DEST/uninstall.sh" 2>/dev/null || true

# 3) launcher command, app menu entry, autostart
mkdir -p "$(dirname "$BIN")" "$APPS" "$AUTO"
cat > "$BIN" <<SH
#!/bin/sh
# Rimeclaw launcher. Uses XWayland on GNOME Wayland so the pet can roam and stay on top.
exec python3 "$DEST/app/rimeclaw.py" "\$@"
SH
chmod +x "$BIN"

cat > "$APPS/$SLUG.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Rimeclaw
GenericName=Desktop Pet
Comment=A frost dragon from Emberfall that walks around your screen and roasts you
Exec=$BIN
Icon=$DEST/app/icons/rimeclaw.png
Terminal=false
Categories=Game;Amusement;
Keywords=pet;dragon;goblin;emberfall;roast;
StartupNotify=false
Actions=roast;rant;quit;

[Desktop Action roast]
Name=Roast me now
Exec=$BIN roast

[Desktop Action rant]
Name=Rant now
Exec=$BIN rant

[Desktop Action quit]
Name=Quit Rimeclaw
Exec=$BIN quit
DESK

cat > "$AUTO/$SLUG.desktop" <<DESK
[Desktop Entry]
Type=Application
Name=Rimeclaw
Comment=Start the Rimeclaw desktop pet when you log in
Exec=$BIN
Icon=$DEST/app/icons/rimeclaw.png
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=10
NoDisplay=true
DESK
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" >/dev/null 2>&1 || true

# 4) start it
if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
  say "Starting Rimeclaw"
  (setsid "$BIN" >/dev/null 2>&1 < /dev/null &) || true
else
  warn "No desktop session detected here; Rimeclaw will start next time you log in (or open it from the app grid)."
fi
if [ "${XDG_SESSION_TYPE:-}" = "wayland" ] && [ -z "${DISPLAY:-}" ]; then
  warn "XWayland is not available, so Rimeclaw will sit in its own little window instead of roaming."
fi

cat <<MSG

  Rimeclaw is installed.  The frost dragon should drop onto the bottom of your screen in a few seconds.
  - Right-click him for the menu: Roast me now, Rant now, Mute voice, Roast frequency, Clean mode, Switch pet, Sleep, Quit.
  - Drag him around and throw him. Click him to poke him.
  - Find "Rimeclaw" in your app grid to start him again. He also starts when you log in.
  - Uninstall:  bash ~/.local/share/rimeclaw/uninstall.sh

MSG
