#!/usr/bin/env bash
# Removes Rimeclaw: the app, its launcher, autostart entry and settings. Leaves Ubuntu packages alone.
set -u
SLUG=rimeclaw
BIN="$HOME/.local/bin/$SLUG"
[ -x "$BIN" ] && "$BIN" quit >/dev/null 2>&1
sleep 1
pkill -f "$HOME/.local/share/$SLUG/app/rimeclaw.py" >/dev/null 2>&1
rm -f  "$BIN" "$HOME/.local/share/applications/$SLUG.desktop" "$HOME/.config/autostart/$SLUG.desktop"
rm -rf "$HOME/.config/$SLUG"
rm -rf "$HOME/.local/share/$SLUG"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1
echo "Rimeclaw is gone. (python3-pyqt6 was left installed; remove it with: sudo apt remove python3-pyqt6)"
