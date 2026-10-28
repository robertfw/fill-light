"""The tray app: ties camera, tray item, lights and editor together, and serves the D-Bus control
interface the CLI talks to."""

from __future__ import annotations

import json
import signal
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QApplication

from . import config as cfg
from .camera import CameraWatcher
from .editor import Editor
from .lights import Lights
from .screens import default_roles, monitors
from .sni import MenuItem, StatusNotifierItem

BUS_NAME = "org.robertfw.FillLight"
OBJECT_PATH = "/FillLight"
SET_LABELS = {"sides+top": "Sides + top", "sides": "Sides"}


class FillLight:
    def __init__(self, bus: dbus.Bus) -> None:
        self.bus = bus
        self.config = cfg.load()
        if not self.config.screens:
            self.config.screens = default_roles(monitors())
            self.config.save()
        self.on = False
        self.previewing: cfg.Preset | None = None
        self.editor: Editor | None = None

        self.lights = Lights(bus, on_escape=self.turn_off)
        self.camera = CameraWatcher()
        self.camera.changed.connect(lambda _: self.update())
        self.tray = StatusNotifierItem("fill-light", "Fill light")
        self.tray.on_activate = self.toggle
        self.tray.on_secondary = self.edit
        app = QGuiApplication.instance()
        app.screenAdded.connect(lambda _: self._screens_changed())
        app.screenRemoved.connect(lambda _: self._screens_changed())
        self.update()

    # -- actions --------------------------------------------------------------------------------

    def turn_on(self, preset: str = "", screen_set: str = "") -> None:
        if preset and (p := self.config.find(preset)):
            self.config.preset = p.name
        if screen_set in cfg.SCREEN_SETS:
            self.config.screen_set = screen_set
        self.config.save()
        self.on = True
        self.update()

    def turn_off(self) -> None:
        self.on = False
        if self.editor:
            self.editor.preview_box.setChecked(False)  # Esc on a preview means "stop lighting"
        self.update()

    def toggle(self) -> None:
        self.turn_off() if self.on else self.turn_on()

    def choose_preset(self, name: str) -> None:
        self.config.preset = name
        self.config.save()
        if self.editor:
            self.editor._reload_list(name)
        self.update()

    def choose_set(self, screen_set: str) -> None:
        self.config.screen_set = screen_set
        self.config.save()
        self.update()

    def edit(self) -> None:
        if self.editor:
            self.editor.raise_()
            self.editor.activateWindow()
            return
        self.editor = Editor(self.config, monitors(), preview=self._preview, changed=self.update)
        self.editor.finished.connect(self._editor_closed)
        self.editor.show()

    def _editor_closed(self) -> None:
        self.editor.deleteLater()
        self.editor = None
        self._preview(None)

    def _preview(self, preset: cfg.Preset | None) -> None:
        self.previewing = preset
        self.update()

    def _screens_changed(self) -> None:
        # Qt reports the new screen before its geometry settles; give it a moment.
        QTimer.singleShot(1000, self.update)

    # -- state -> world -------------------------------------------------------------------------

    def lit_monitors(self):
        roles = cfg.SCREEN_SETS[self.config.screen_set]
        return [m for m in monitors() if self.config.screens.get(m.key, "none") in roles]

    def update(self) -> None:
        preset = self.previewing or (self.config.current() if self.on else None)
        if preset:
            self.lights.show(self.lit_monitors(), preset.color())
        else:
            self.lights.hide()
        self.tray.set_status("Active" if self.camera.active or self.lights.lit else "Passive")
        current = self.config.current()
        self.tray.set_tooltip(
            f"{'On' if self.on else 'Off'} · {current.name} · {SET_LABELS[self.config.screen_set]}"
            + (" · camera live" if self.camera.active else ""))
        self.tray.set_icon(icon_pixmaps((preset or current).color(), self.lights.lit, self.camera.active))
        self.tray.menu.set_items(self._menu())

    def _menu(self) -> list[MenuItem]:
        items = [MenuItem("Light on", self.toggle, toggle="checkmark", checked=self.on), MenuItem(separator=True)]
        for p in self.config.presets:
            items.append(MenuItem(p.name, lambda n=p.name: self.choose_preset(n), toggle="radio",
                                  checked=p.name == self.config.preset))
        items.append(MenuItem(separator=True))
        for key, label in SET_LABELS.items():
            items.append(MenuItem(label, lambda k=key: self.choose_set(k), toggle="radio",
                                  checked=key == self.config.screen_set))
        items += [MenuItem(separator=True), MenuItem("Edit presets & screens…", self.edit),
                  MenuItem("Quit", QApplication.quit)]
        return items

    def status(self) -> dict:
        return {"on": self.on, "preset": self.config.current().name, "set": self.config.screen_set,
                "camera": self.camera.active, "lit": sorted(self.lights.windows)}


class Control(dbus.service.Object):
    """What `fill-light on|off|toggle|edit|status` calls."""

    def __init__(self, bus: dbus.Bus, app: FillLight) -> None:
        super().__init__(bus, OBJECT_PATH)
        self.app = app

    @dbus.service.method(BUS_NAME, in_signature="ss", out_signature="s")
    def On(self, preset, screen_set):
        if preset and not self.app.config.find(preset):
            raise dbus.DBusException(f"no preset named {str(preset)!r}", name=f"{BUS_NAME}.Error")
        self.app.turn_on(str(preset), str(screen_set))
        return json.dumps(self.app.status())

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="s")
    def Off(self):
        self.app.turn_off()
        return json.dumps(self.app.status())

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="s")
    def Toggle(self):
        self.app.toggle()
        return json.dumps(self.app.status())

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="")
    def Edit(self):
        self.app.edit()

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="s")
    def Status(self):
        return json.dumps(self.app.status())

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="as")
    def Presets(self):
        return [p.name for p in self.app.config.presets]


def icon_pixmaps(rgb: tuple[int, int, int], lit: bool, camera: bool) -> list[tuple[int, int, bytes]]:
    """A disc in the preset's colour: glowing when lit, a ring when not; a red dot while the
    camera is live. ARGB32 big-endian, as the SNI spec wants."""
    out = []
    for size in (16, 22, 24, 32, 48, 64):
        img = QImage(size, size, QImage.Format.Format_ARGB32)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(size / 2, size / 2)
        color = QColor(*rgb) if max(rgb) > 0 else QColor(255, 255, 255)
        if lit:
            glow = QRadialGradient(c, size / 2)
            glow.setColorAt(0.0, QColor(255, 255, 255))
            glow.setColorAt(0.45, color)
            edge = QColor(color)
            edge.setAlpha(0)
            glow.setColorAt(1.0, edge)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, size / 2, size / 2)
        else:
            pen = QPen(color, max(1.5, size / 10))
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = size / 2 - pen.widthF()
            p.drawEllipse(c, r, r)
        if camera:
            d = size * 0.36
            p.setPen(QPen(QColor(0, 0, 0, 160), max(1.0, size / 24)))
            p.setBrush(QColor(230, 40, 40))
            p.drawEllipse(QRectF(size - d, size - d, d, d).adjusted(0.5, 0.5, -0.5, -0.5))
        p.end()
        # Format_ARGB32 is a native-endian uint32 per pixel; the spec wants network order.
        raw = bytearray(img.constBits().asstring(img.sizeInBytes()))
        if sys.byteorder == "little":
            raw[0::4], raw[1::4], raw[2::4], raw[3::4] = raw[3::4], raw[2::4], raw[1::4], raw[0::4]
        out.append((size, size, bytes(raw)))
    return out


def main() -> int:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    app = QApplication(sys.argv)
    app.setApplicationName("fill-light")
    app.setDesktopFileName("fill-light")
    app.setQuitOnLastWindowClosed(False)
    bus = dbus.SessionBus()
    if bus.request_name(BUS_NAME, dbus.bus.NAME_FLAG_DO_NOT_QUEUE) != dbus.bus.REQUEST_NAME_REPLY_PRIMARY_OWNER:
        print("fill-light is already running", file=sys.stderr)
        return 1
    fill = FillLight(bus)
    _control = Control(bus, fill)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    tick = QTimer(interval=500)  # lets Python see signals while Qt's loop runs
    tick.timeout.connect(lambda: None)
    tick.start()
    code = app.exec()
    fill.lights.hide()
    return code
