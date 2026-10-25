# Rimeclaw: an Emberfall desktop pet

A small white-and-blue frost dragon from Emberfall walks along the bottom of your screen. He climbs the edges, falls when you drop him, naps when you leave, and roasts you out loud. Switch pets to get **Skarn the goblin** instead.

![demo](screenshots/demo.gif)

## Install (Ubuntu / GNOME)

```bash
curl -fsSL https://raw.githubusercontent.com/tmacgoat/rimeclaw/main/install.sh | bash
```

The installer asks for your password once so it can `apt install python3-pyqt6 libxcb-cursor0`, which are Ubuntu's own packages; nothing is installed with pip. It then:
- copies the app to `~/.local/share/rimeclaw`
- adds **Rimeclaw** to your app grid
- makes him start each time you log in
- starts him right away

## Using him
- **Right-click** the pet, or use the tray icon, to open the menu: Roast me now · Rant now · Mute voice · Clean mode · Roast frequency · Switch pet · Size · Sleep · Quit
- **Drag** him around and let go to throw him. **Click** him to poke him, which he doesn't like.
- He speaks about every 7 minutes. You can change that under *Roast frequency* or set it to "Only when I ask". About 1 line in 4 is a conspiracy rant.
- He reacts when your battery is low, when you're up late, and after 2 hours of nonstop screen time. He falls asleep while you're away.
- **Clean mode** is off by default. Turn it on to get lines without swearing.
- Commands: `rimeclaw roast`, `rimeclaw rant`, `rimeclaw quit`
- Settings are saved in `~/.config/rimeclaw/settings.json`.

## Uninstall
```bash
bash ~/.local/share/rimeclaw/uninstall.sh
```

## Wayland notes
GNOME on Wayland doesn't let apps place their own windows, so Rimeclaw runs through **XWayland** (`QT_QPA_PLATFORM=xcb`). XWayland is built into Ubuntu. That is what lets him roam, stay on top of other windows and let clicks pass through him. If XWayland is missing he still runs, but in a small fixed window instead of roaming.

## Rebuilding the voice
The lines are in `tools/lines_src.py` and the voice settings in `tools/voices.json`. To rebuild:

```bash
cd tools
python3 build_lines.py
python3 render.py
```

**Voices.** Rimeclaw speaks with the ElevenLabs voice **Final Boss** (`eleven_v4`). Skarn the goblin uses edge-tts (`en-US-EricNeural`).

Not every dragon line is voiced yet. A line without a Final Boss clip shows as a text-only speech bubble; it never falls back to another voice. These lines are listed under `"pending"` in `app/voice/dragon/index.json`.

To voice the pending lines later:
- **Manual:** drop ElevenLabs clips named `<line id>.wav` or `.mp3` into `tools/cache/el/d3qrd1ge6zWDvUxIeXiH/` and run `python3 render.py dragon`.
- **Automatic:** run `ELEVENLABS_API_KEY=... PENDING=1 python3 render.py dragon`. This uses ElevenLabs credits, and it stops cleanly if it hits a quota or auth error.

`FORCE=1` re-runs post-processing on every line that has audio. The steps are silence trim, 70 Hz high-pass, light 2:1 compression and 2-pass loudnorm to -16 LUFS, with no reverb. The goblin needs edge-tts.

All jokes are original. The conspiracy rants are comedy, not claims of fact.
