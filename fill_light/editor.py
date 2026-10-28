"""Preset and screen-role editor. Every change saves straight away and, with Preview on, lights
the screens with the preset being edited so it can be tuned against the camera feed."""

from __future__ import annotations

from typing import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QSlider, QTabWidget,
                             QVBoxLayout, QWidget)

from .config import ROLES, Config, Preset, kelvin_to_rgb
from .screens import Monitor


class Editor(QDialog):
    def __init__(self, config: Config, monitors: list[Monitor], *,
                 preview: Callable[[Preset | None], None], changed: Callable[[], None]) -> None:
        super().__init__()
        self.config = config
        self.preview_cb = preview
        self.changed_cb = changed
        self._loading = False
        self.setWindowTitle("Fill light")
        self.resize(560, 380)

        tabs = QTabWidget()
        tabs.addTab(self._presets_tab(), "Presets")
        tabs.addTab(self._screens_tab(monitors), "Screens")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

        self._reload_list(self.config.preset)

    # -- presets --------------------------------------------------------------------------------

    def _presets_tab(self) -> QWidget:
        self.list = QListWidget()
        self.list.currentRowChanged.connect(self._select)
        add, dup, delete, up, down = (QPushButton(t) for t in ("Add", "Duplicate", "Delete", "▲", "▼"))
        add.clicked.connect(lambda: self._insert(Preset(self._unique("New"), 4500, 1.0)))
        dup.clicked.connect(lambda: self.preset and self._insert(
            Preset(self._unique(self.preset.name), self.preset.kelvin, self.preset.intensity, self.preset.rgb)))
        delete.clicked.connect(self._delete)
        up.clicked.connect(lambda: self._move(-1))
        down.clicked.connect(lambda: self._move(1))
        list_buttons = QHBoxLayout()
        for b in (add, dup, delete, up, down):
            list_buttons.addWidget(b)
        left = QVBoxLayout()
        left.addWidget(self.list)
        left.addLayout(list_buttons)

        self.name = QLineEdit()
        self.name.editingFinished.connect(self._rename)
        self.kelvin = QSlider(Qt.Orientation.Horizontal, minimum=19, maximum=100, pageStep=5)  # ×100 K
        self.kelvin_label = QLabel()
        self.kelvin.valueChanged.connect(self._edit)
        self.intensity = QSlider(Qt.Orientation.Horizontal, minimum=5, maximum=100, pageStep=5)
        self.intensity_label = QLabel()
        self.intensity.valueChanged.connect(self._edit)
        self.custom = QCheckBox("Custom colour")
        self.custom.toggled.connect(self._edit)
        self.pick = QPushButton("Pick…")
        self.pick.clicked.connect(self._pick)
        self.swatch = QLabel()
        self.swatch.setMinimumHeight(48)
        self.preview_box = QCheckBox("Preview on screens")
        self.preview_box.setChecked(True)
        self.preview_box.toggled.connect(lambda _: self._preview())

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Temperature", _row(self.kelvin, self.kelvin_label))
        form.addRow("Intensity", _row(self.intensity, self.intensity_label))
        form.addRow(_row(self.custom, self.pick))
        form.addRow(self.swatch)
        form.addRow(self.preview_box)

        tab = QWidget()
        layout = QHBoxLayout(tab)
        layout.addLayout(left, 2)
        layout.addLayout(form, 3)
        return tab

    @property
    def preset(self) -> Preset | None:
        row = self.list.currentRow()
        return self.config.presets[row] if 0 <= row < len(self.config.presets) else None

    def _reload_list(self, select: str | None) -> None:
        self._loading = True
        self.list.clear()
        self.list.addItems(p.name for p in self.config.presets)
        self._loading = False
        names = [p.name for p in self.config.presets]
        self.list.setCurrentRow(names.index(select) if select in names else 0)

    def _select(self, _row: int) -> None:
        if self._loading:
            return
        p = self.preset
        self._loading = True
        for w in (self.name, self.kelvin, self.intensity, self.custom, self.pick):
            w.setEnabled(p is not None)
        if p:
            self.name.setText(p.name)
            self.kelvin.setValue(round(p.kelvin / 100))
            self.intensity.setValue(round(p.intensity * 100))
            self.custom.setChecked(p.rgb is not None)
            # Selecting a preset in the editor makes it the active one, like the menu does.
            self.config.preset = p.name
        self._loading = False
        self._refresh()
        if p:
            self._save()

    def _edit(self) -> None:
        p = self.preset
        if self._loading or not p:
            return
        p.kelvin = self.kelvin.value() * 100
        p.intensity = self.intensity.value() / 100
        if self.custom.isChecked() and p.rgb is None:
            p.rgb = kelvin_to_rgb(p.kelvin)  # start the custom colour from where the slider was
        elif not self.custom.isChecked():
            p.rgb = None
        self._refresh()
        self._save()

    def _pick(self) -> None:
        p = self.preset
        if not p:
            return
        start = QColor(*(p.rgb or kelvin_to_rgb(p.kelvin)))
        color = QColorDialog.getColor(start, self, "Fill colour")
        if color.isValid():
            p.rgb = (color.red(), color.green(), color.blue())
            self._loading = True
            self.custom.setChecked(True)
            self._loading = False
            self._refresh()
            self._save()

    def _refresh(self) -> None:
        p = self.preset
        self.kelvin_label.setText(f"{self.kelvin.value() * 100} K")
        self.intensity_label.setText(f"{self.intensity.value()} %")
        self.kelvin.setEnabled(bool(p) and p.rgb is None)
        self.pick.setEnabled(bool(p) and self.custom.isChecked())
        rgb = p.color() if p else (0, 0, 0)
        self.swatch.setStyleSheet(f"background: rgb{rgb}; border-radius: 6px;")
        self._preview()

    def _preview(self) -> None:
        self.preview_cb(self.preset if self.preview_box.isChecked() else None)

    def _rename(self) -> None:
        p = self.preset
        new = self.name.text().strip()
        if not p or not new or new == p.name:
            return
        if any(o is not p and o.name.lower() == new.lower() for o in self.config.presets):
            self.name.setText(p.name)  # names select presets from the CLI, so they stay unique
            return
        if self.config.preset == p.name:
            self.config.preset = new
        p.name = new
        self.list.currentItem().setText(new)
        self._save()

    def _unique(self, base: str) -> str:
        names = {p.name.lower() for p in self.config.presets}
        if base.lower() not in names:
            return base
        n = 2
        while f"{base} {n}".lower() in names:
            n += 1
        return f"{base} {n}"

    def _insert(self, preset: Preset) -> None:
        row = self.list.currentRow() + 1
        self.config.presets.insert(row, preset)
        self._reload_list(preset.name)
        self._save()

    def _delete(self) -> None:
        p = self.preset
        if not p or len(self.config.presets) == 1:
            return
        row = self.list.currentRow()
        self.config.presets.remove(p)
        self._reload_list(self.config.presets[min(row, len(self.config.presets) - 1)].name)
        self._save()

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        to = row + delta
        if not 0 <= to < len(self.config.presets):
            return
        presets = self.config.presets
        presets[row], presets[to] = presets[to], presets[row]
        self._reload_list(presets[to].name)
        self._save()

    # -- screens --------------------------------------------------------------------------------

    def _screens_tab(self, monitors: list[Monitor]) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        form.addRow(QLabel("“Sides” lights the side screens; “Sides + top” adds the top one."))
        for mon in monitors:
            combo = QComboBox()
            combo.addItems(ROLES)
            combo.setCurrentText(self.config.screens.get(mon.key, "none"))
            combo.currentTextChanged.connect(lambda role, key=mon.key: self._set_role(key, role))
            form.addRow(mon.describe(), combo)
        return tab

    def _set_role(self, key: str, role: str) -> None:
        self.config.screens[key] = role
        self._save()
        self._preview()

    # -------------------------------------------------------------------------------------------

    def _save(self) -> None:
        if not self._loading:
            self.config.save()
            self.changed_cb()

    def closeEvent(self, event) -> None:
        self.preview_cb(None)
        super().closeEvent(event)

    def done(self, result: int) -> None:
        self.preview_cb(None)
        super().done(result)


def _row(*widgets: QWidget) -> QWidget:
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return w
