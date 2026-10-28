# fill-light

Turns the side (and top) monitors into a fill light for video calls. Lives in the Plasma tray.

> **AI disclaimer:** this was vibe coded: written almost entirely by an AI coding agent (Claude),
> tried out on one machine, and not otherwise reviewed. It may be wrong in ways nobody has
> noticed. Read it before you run it. Provided as is, with no warranty of any kind (see
> [LICENSE](LICENSE)).

- **Tray icon** sits in the overflow until a webcam is streaming (or the light is on), then shows
  on the panel. It never turns the light on by itself. Left click toggles, middle click opens the
  editor, right click is the menu: on/off, presets, **Sides + top** / **Sides**, editor, quit.
- **Light**: one frameless fullscreen window per lit monitor. **Esc** on one turns it off. While
  it's on, Night Color and idle blanking are inhibited.
- **Editor**: presets as colour temperature + intensity (or a custom RGB), previewed live on the
  screens; and a role per monitor (none / side / top).

```sh
bin/fill-light                     # the tray app (autostarted)
bin/fill-light on [PRESET] [SET]   # SET: sides+top | sides
bin/fill-light off | toggle | edit | status | presets
bin/fill-light install             # start at login (writes ~/.config/autostart/fill-light.desktop)
bin/fill-light uninstall
```

Config: `~/.config/fill-light/config.json`. Monitors are keyed by EDID (`MFG MODEL SERIAL` from
`/sys/class/drm/*/edid`) because MST connector names can move; first run guesses roles (biggest
screen none, portraits side, other landscapes top).

## How it works

- `camera.py`: inotify on `/dev` wakes on any open/close of a `video*` node; a node counts as live
  when some process has it mmap'd (V4L2 streaming buffers), so device probing doesn't count. Polls
  every 2 s only while something holds a node open.
- `sni.py`: a hand-rolled StatusNotifierItem + `com.canonical.dbusmenu` over dbus-python, because
  `QSystemTrayIcon` always reports `Status=Active` and Plasma's "Shown when relevant" only hides
  `Passive` items. dbus-python's GLib loop runs inside Qt's (Qt's Linux dispatcher is GLib).
- `app.py`: state, menu, and the `org.robertfw.FillLight` D-Bus interface the CLI calls.

## Requirements

Linux, with Python 3.10+, PyQt6 and dbus-python. On Debian/Ubuntu:
`sudo apt install python3-pyqt6 python3-dbus`. No pip install; run it from a clone.

Built and tested on KDE Plasma 6 (Wayland) only. Elsewhere:

- Pausing Night Color is KDE-only; on other desktops the light still works, it just gets tinted
  if a night filter is on.
- The tray icon is a StatusNotifierItem: native on KDE, needs the AppIndicator extension on GNOME.
- Camera detection, monitor identification and fullscreen-per-output are plain Linux / Wayland
  (X11 should work too).

## License

MIT. See [LICENSE](LICENSE).
