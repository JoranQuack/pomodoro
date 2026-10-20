# Pomodoro

A Pomodoro timer for GNOME that lives in the top bar, with a companion app built with GTK 4 and libadwaita so it looks like the rest of the desktop.

## Features

**Top bar indicator** (GNOME Shell extension)
- A small ring that shrinks as time runs out, colored by phase: red for focus, green for short breaks, blue for long breaks
- Remaining time next to the ring (can be hidden)
- Menu with the countdown, start/pause, stop and skip buttons, progress toward the next long break, and quick access to each phase
- Middle-click the indicator to start or pause
- Sound and notification when a phase ends, with a button to start the next one
- Keeps running on the lock screen

**App**
- Large progress ring, phase switcher and controls
- Preferences for focus and break lengths, sessions before a long break, auto-start, sound and the top bar time
- Keyboard shortcuts: <kbd>Space</kbd> start/pause, <kbd>Ctrl</kbd>+<kbd>R</kbd> reset, <kbd>Ctrl</kbd>+<kbd>N</kbd> skip, <kbd>Ctrl</kbd>+<kbd>,</kbd> preferences
- `pomodoro --start work|short-break|long-break` starts a phase without opening the window

Both share their state through GSettings, so the top bar and the app always show the same timer. The extension finishes phases and sends notifications; if it isn't running, the app does that while its window is open.

The dots show finished focus sessions toward the next long break. When they are all filled, the next break is a long one.

## Requirements

- GNOME Shell 49
- Python 3 with PyGObject, GTK 4 and libadwaita 1.7 or newer (included in Fedora Workstation 43)

## Install

```sh
git clone https://github.com/JoranQuack/pomodoro.git
cd pomodoro
./install.sh
```

The installer links the extension into `~/.local/share/gnome-shell/extensions`, the app into `~/.local/bin`, and adds the launcher and icon. On Wayland, log out and back in once so GNOME Shell loads the extension.

## Layout

```
extension/   GNOME Shell extension (pomodoro@joran.dev) and GSettings schema
app/         libadwaita app (pomodoro.py)
data/        desktop file and app icon
install.sh   per-user installer
```

The timer logic exists in both `extension/timer.js` and `app/pomodoro.py`; keep them in sync when changing it.

## License

GPL-3.0-or-later
