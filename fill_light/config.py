"""Presets, screen roles and the selected state, persisted as JSON.

Monitors are keyed by EDID ("MFG MODEL SERIAL"), not connector name: MST connector names can
shift between boots, the EDID doesn't.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG = Path.home() / ".config" / "fill-light" / "config.json"

SCREEN_SETS = {"sides+top": ("side", "top"), "sides": ("side",)}
ROLES = ("none", "side", "top")


@dataclass
class Preset:
    name: str
    kelvin: int = 5000
    intensity: float = 1.0  # 0..1, scales the colour
    rgb: tuple[int, int, int] | None = None  # overrides kelvin when set

    def color(self) -> tuple[int, int, int]:
        base = self.rgb if self.rgb else kelvin_to_rgb(self.kelvin)
        return tuple(round(c * self.intensity) for c in base)


DEFAULT_PRESETS = [
    Preset("Candle", 2700, 1.0),
    Preset("Warm", 3500, 1.0),
    Preset("Neutral", 4500, 1.0),
    Preset("Daylight", 5600, 1.0),
    Preset("Soft", 4000, 0.6),
]


@dataclass
class Config:
    presets: list[Preset] = field(default_factory=lambda: list(DEFAULT_PRESETS))
    preset: str = "Neutral"
    screen_set: str = "sides+top"
    screens: dict[str, str] = field(default_factory=dict)  # EDID key -> role

    def current(self) -> Preset:
        for p in self.presets:
            if p.name == self.preset:
                return p
        return self.presets[0] if self.presets else Preset("White", 6500)

    def find(self, name: str) -> Preset | None:
        lowered = name.lower()
        return next((p for p in self.presets if p.name.lower() == lowered), None)

    def save(self) -> None:
        CONFIG.parent.mkdir(parents=True, exist_ok=True)
        tmp = CONFIG.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2) + "\n")
        tmp.replace(CONFIG)


def load() -> Config:
    try:
        raw = json.loads(CONFIG.read_text())
    except (OSError, ValueError):
        return Config()
    presets = [Preset(p["name"], int(p.get("kelvin", 5000)), float(p.get("intensity", 1.0)),
                      tuple(p["rgb"]) if p.get("rgb") else None)
               for p in raw.get("presets", [])]
    return Config(presets or list(DEFAULT_PRESETS), raw.get("preset", "Neutral"),
                  raw.get("screen_set", "sides+top") if raw.get("screen_set") in SCREEN_SETS else "sides+top",
                  dict(raw.get("screens", {})))


def kelvin_to_rgb(kelvin: float) -> tuple[int, int, int]:
    """Tanner Helland's blackbody approximation, good from 1000 K to 40000 K."""
    t = max(1000.0, min(40000.0, kelvin)) / 100
    if t <= 66:
        r = 255.0
        g = 99.4708025861 * math.log(t) - 161.1195681661
        b = 0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307
    else:
        r = 329.698727446 * (t - 60) ** -0.1332047592
        g = 288.1221695283 * (t - 60) ** -0.0755148492
        b = 255.0
    return tuple(round(max(0.0, min(255.0, c))) for c in (r, g, b))
