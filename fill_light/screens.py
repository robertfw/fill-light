"""Connected monitors: connector name (as KWin/Qt call it) <-> EDID identity."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtGui import QGuiApplication, QScreen

DRM = Path("/sys/class/drm")


@dataclass
class Monitor:
    connector: str  # e.g. DP-7, matches QScreen.name()
    key: str  # "MFG MODEL SERIAL"
    model: str
    screen: QScreen | None

    def describe(self) -> str:
        if not self.screen:
            return f"{self.connector} · {self.model}"
        g = self.screen.geometry()
        shape = "portrait" if g.height() > g.width() else "landscape"
        return f"{self.connector} · {self.model} · {shape} {g.width()}×{g.height()}"


def parse_edid(edid: bytes) -> tuple[str, str]:
    """(key, model) from a base EDID block; the descriptor strings are 0xFC name, 0xFF serial."""
    if len(edid) < 128:
        return "", ""
    word = int.from_bytes(edid[8:10], "big")
    mfg = "".join(chr(((word >> s) & 31) + 64) for s in (10, 5, 0))
    name = serial = ""
    for i in range(54, 126, 18):
        block = edid[i:i + 18]
        if block[:3] == b"\0\0\0" and block[3] in (0xFC, 0xFF):
            text = block[5:].split(b"\n")[0].decode("ascii", "replace").strip()
            if block[3] == 0xFC:
                name = text
            else:
                serial = text
    if not serial:
        serial = str(int.from_bytes(edid[12:16], "little"))
    model = f"{mfg} {name}".strip()
    return f"{model} {serial}", model


def edid_by_connector() -> dict[str, tuple[str, str]]:
    found = {}
    for d in DRM.glob("card*-*"):
        try:
            if (d / "status").read_text().strip() != "connected":
                continue
            key, model = parse_edid((d / "edid").read_bytes())
        except OSError:
            continue
        if key:
            found[d.name.split("-", 1)[1]] = (key, model)
    return found


def monitors() -> list[Monitor]:
    """Connected monitors, left to right then top to bottom."""
    edids = edid_by_connector()
    screens = {s.name(): s for s in QGuiApplication.screens()}
    result = []
    for connector, screen in screens.items():
        key, model = edids.get(connector, (f"connector {connector}", connector))
        result.append(Monitor(connector, key, model, screen))
    result.sort(key=lambda m: (m.screen.geometry().x(), m.screen.geometry().y()))
    return result


def default_roles(mons: list[Monitor]) -> dict[str, str]:
    """First-run guess: the biggest screen is the one you look at; portraits are sides, any other
    landscape is the top."""
    if not mons:
        return {}
    area = lambda m: m.screen.size().width() * m.screen.size().height() * m.screen.devicePixelRatio() ** 2
    center = max(mons, key=area)
    roles = {}
    for m in mons:
        g = m.screen.geometry()
        roles[m.key] = "none" if m is center else ("side" if g.height() > g.width() else "top")
    return roles
