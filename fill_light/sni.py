"""A StatusNotifierItem with a com.canonical.dbusmenu menu, over dbus-python.

QSystemTrayIcon always reports Status=Active, and Plasma's "Shown when relevant" only hides
Passive items, so we speak the protocol ourselves. dbus-python's GLib main loop runs inside Qt's
event loop because Qt's dispatcher on Linux is GLib's default context.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

import dbus
import dbus.service

SNI_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"


@dataclass
class MenuItem:
    label: str = ""
    action: Callable[[], None] | None = None
    separator: bool = False
    toggle: str = ""  # "", "checkmark" or "radio"
    checked: bool = False
    enabled: bool = True
    children: list[MenuItem] = field(default_factory=list)

    def props(self) -> dbus.Dictionary:
        if self.separator:
            p = {"type": "separator"}
        else:
            p = {"label": self.label, "enabled": self.enabled}
            if self.toggle:
                p["toggle-type"] = self.toggle
                p["toggle-state"] = dbus.Int32(1 if self.checked else 0)
            if self.children:
                p["children-display"] = "submenu"
        return dbus.Dictionary(p, signature="sv")


class Menu(dbus.service.Object):
    def __init__(self, bus: dbus.Bus) -> None:
        super().__init__(bus, MENU_PATH)
        self.revision = 0
        self._items: dict[int, MenuItem] = {}
        self._root = MenuItem()

    def set_items(self, items: list[MenuItem]) -> None:
        self._root = MenuItem(children=items)
        self._index()
        self.revision += 1
        self.LayoutUpdated(dbus.UInt32(self.revision), dbus.Int32(0))

    def _index(self) -> None:
        """Ids are positions in a depth-first walk; stable until the next set_items."""
        self._items = {0: self._root}

        def walk(item: MenuItem) -> None:
            for child in item.children:
                self._items[len(self._items)] = child
                walk(child)
        walk(self._root)

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parent_id, depth, _props):
        ids = {id(it): i for i, it in self._items.items()}

        def build(item: MenuItem, d: int) -> dbus.Struct:
            props = item.props() if item is not self._root else dbus.Dictionary(
                {"children-display": "submenu"}, signature="sv")
            children = [build(c, d - 1) for c in item.children] if d != 0 else []
            return dbus.Struct((dbus.Int32(ids[id(item)]), props, dbus.Array(children, signature="v")),
                               signature="ia{sv}av")
        parent = self._items.get(int(parent_id), self._root)
        return dbus.UInt32(self.revision), build(parent, int(depth))

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, _props):
        wanted = [int(i) for i in ids] or list(self._items)
        return dbus.Array([dbus.Struct((dbus.Int32(i), self._items[i].props()), signature="ia{sv}")
                           for i in wanted if i in self._items and i != 0], signature="(ia{sv})")

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, item_id, name):
        return self._items[int(item_id)].props().get(str(name), "")

    @dbus.service.method(MENU_IFACE, in_signature="isvu", out_signature="")
    def Event(self, item_id, event_id, _data, _timestamp):
        if event_id != "clicked":
            return
        item = self._items.get(int(item_id))
        if item and item.action and item.enabled:
            item.action()

    @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        for item_id, event_id, data, timestamp in events:
            self.Event(item_id, event_id, data, timestamp)
        return dbus.Array([], signature="i")

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, _item_id):
        return False

    @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, _ids):
        return dbus.Array([], signature="i"), dbus.Array([], signature="i")

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
    def ItemsPropertiesUpdated(self, updated, removed):
        pass

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return self.GetAll(iface)[prop]

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, _iface):
        return dbus.Dictionary({"Version": dbus.UInt32(3), "TextDirection": "ltr", "Status": "normal",
                                "IconThemePath": dbus.Array([], signature="s")}, signature="sv")


class StatusNotifierItem(dbus.service.Object):
    """Left click -> on_activate, middle click -> on_secondary, right click -> the menu."""

    def __init__(self, item_id: str, title: str) -> None:
        self.bus = dbus.SessionBus()
        self.service = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        # Not self._name: dbus.service.Object.__init__ overwrites that, dropping (and releasing) it.
        self._bus_name = dbus.service.BusName(self.service, self.bus)
        super().__init__(self.bus, ITEM_PATH)
        self.menu = Menu(self.bus)
        self.item_id = item_id
        self.title = title
        self.status = "Passive"
        self.tooltip = title
        self.pixmaps: list[tuple[int, int, bytes]] = []
        self.on_activate: Callable[[], None] = lambda: None
        self.on_secondary: Callable[[], None] = lambda: None
        # The watcher lives in plasmashell; register again whenever it (re)appears.
        self.bus.watch_name_owner(WATCHER, lambda owner: owner and self._register())

    def _register(self) -> None:
        try:
            self.bus.get_object(WATCHER, "/StatusNotifierWatcher").RegisterStatusNotifierItem(
                self.service, dbus_interface=WATCHER)
        except dbus.DBusException:
            pass  # no tray right now; watch_name_owner retries when one shows up

    def set_status(self, status: str) -> None:
        if status != self.status:
            self.status = status
            self.NewStatus(status)

    def set_icon(self, pixmaps: list[tuple[int, int, bytes]]) -> None:
        """ARGB32 in network byte order, one per size."""
        self.pixmaps = pixmaps
        self.NewIcon()

    def set_tooltip(self, text: str) -> None:
        if text != self.tooltip:
            self.tooltip = text
            self.NewToolTip()

    def _icon_array(self) -> dbus.Array:
        return dbus.Array([dbus.Struct((dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(data)),
                                       signature="iiay") for w, h, data in self.pixmaps],
                          signature="(iiay)")

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, prop):
        return self.GetAll(iface)[prop]

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, _iface):
        empty_icon = dbus.Array([], signature="(iiay)")
        return dbus.Dictionary({
            "Category": "Hardware",
            "Id": self.item_id,
            "Title": self.title,
            "Status": self.status,
            "WindowId": dbus.Int32(0),
            "IconName": "",
            "IconPixmap": self._icon_array(),
            "OverlayIconName": "",
            "OverlayIconPixmap": empty_icon,
            "AttentionIconName": "",
            "AttentionIconPixmap": empty_icon,
            "AttentionMovieName": "",
            "ToolTip": dbus.Struct(("", empty_icon, self.title, self.tooltip), signature="sa(iiay)ss"),
            "ItemIsMenu": False,
            "Menu": dbus.ObjectPath(MENU_PATH),
            "IconThemePath": "",
        }, signature="sv")

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def Activate(self, _x, _y):
        self.on_activate()

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def SecondaryActivate(self, _x, _y):
        self.on_secondary()

    @dbus.service.method(SNI_IFACE, in_signature="ii", out_signature="")
    def ContextMenu(self, _x, _y):
        pass  # the host shows Menu itself

    @dbus.service.method(SNI_IFACE, in_signature="is", out_signature="")
    def Scroll(self, _delta, _orientation):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewIcon(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="")
    def NewToolTip(self):
        pass

    @dbus.service.signal(SNI_IFACE, signature="s")
    def NewStatus(self, status):
        pass
