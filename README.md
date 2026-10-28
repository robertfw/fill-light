# fill-light

Turns the side (and top) monitors into a fill light for video calls. Lives in the Plasma tray.

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
```

Autostart: `ln -s ~/prj/fill-light/fill-light.desktop ~/.config/autostart/`.

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

Needs only system packages: `python3-pyqt6`, `python3-dbus`.
