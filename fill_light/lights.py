"""The light itself: one frameless fullscreen window per lit monitor, plus the inhibits that keep
its colour honest (Night Color off) and the screens awake (no idle blanking) while it's on."""

from __future__ import annotations

import dbus
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QCursor, QKeyEvent, QPalette
from PyQt6.QtWidgets import QWidget

from .screens import Monitor


class FillWindow(QWidget):
    def __init__(self, monitor: Monitor, on_escape) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint)
        self.on_escape = on_escape
        self.setWindowTitle(f"fill-light:{monitor.connector}")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAutoFillBackground(True)
        self.setCursor(QCursor(Qt.CursorShape.BlankCursor))
        self.setScreen(monitor.screen)
        self.setGeometry(monitor.screen.geometry())

    def set_color(self, rgb: tuple[int, int, int]) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(*rgb))
        self.setPalette(pal)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.on_escape()


class Inhibits:
    """Night Color and idle inhibits; both are dropped by the session if we die."""

    def __init__(self, bus: dbus.Bus) -> None:
        self.bus = bus
        self.night = self.idle = None

    def acquire(self) -> None:
        if self.night is None:
            self.night = self._call("org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight",
                                    "inhibit")
        if self.idle is None:
            self.idle = self._call("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver",
                                   "Inhibit", "fill-light", "Fill light is on")

    def release(self) -> None:
        if self.night is not None:
            self._call("org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight", "uninhibit",
                       dbus.UInt32(self.night))
            self.night = None
        if self.idle is not None:
            self._call("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver",
                       "UnInhibit", dbus.UInt32(self.idle))
            self.idle = None

    def _call(self, service: str, path: str, iface: str, method: str, *args):
        try:
            return self.bus.get_object(service, path).get_dbus_method(method, iface)(*args)
        except dbus.DBusException:
            return None


class Lights:
    def __init__(self, bus: dbus.Bus, on_escape) -> None:
        self.on_escape = on_escape
        self.inhibits = Inhibits(bus)
        self.windows: dict[str, FillWindow] = {}

    @property
    def lit(self) -> bool:
        return bool(self.windows)

    def show(self, monitors: list[Monitor], rgb: tuple[int, int, int]) -> None:
        wanted = {m.connector: m for m in monitors if m.screen}
        for name in list(self.windows):
            if name not in wanted:
                self.windows.pop(name).close()
        for name, mon in wanted.items():
            win = self.windows.get(name)
            if win is None:
                win = self.windows[name] = FillWindow(mon, self.on_escape)
                win.set_color(rgb)
                win.showFullScreen()
            else:
                win.set_color(rgb)
        if self.windows:
            self.inhibits.acquire()
        else:
            self.inhibits.release()

    def hide(self) -> None:
        for win in self.windows.values():
            win.close()
        self.windows.clear()
        self.inhibits.release()
