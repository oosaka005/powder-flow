from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_DB_PATH = Path(__file__).resolve().parents[2] / "config" / "material_database.json"

_COLUMNS: list[tuple[str, str]] = [
    ("diskID",               "Disk ID"),
    ("volume_ml",            "Volume (mL)"),
    ("vib_level",            "Vib Level"),
    ("vib_time",             "Vib Time (s)"),
    ("step_mass_mean",       "Step Mass Mean (g)"),
    ("step_mass_std",        "Step Mass Std (g)"),
    ("density_g_per_ml",     "Density (g/mL)"),
    ("bulk_density_mean",    "Bulk Density (g/mL)"),
    ("tapped_density_mean",  "Tapped Density (g/mL)"),
    ("hausner_ratio",        "Hausner Ratio"),
    ("hausner_class",        "Hausner Class"),
    ("angle_of_repose_deg",  "Angle of Repose (°)"),
    ("repose_class",         "Repose Class"),
]

_FLOAT_KEYS = {
    "volume_ml", "step_mass_mean", "step_mass_std", "density_g_per_ml",
    "bulk_density_mean", "tapped_density_mean", "hausner_ratio",
    "angle_of_repose_deg",
}


def _fmt(key: str, value: object) -> str:
    if value is None:
        return "—"
    if key in _FLOAT_KEYS:
        try:
            return f"{float(value):.4f}"
        except (TypeError, ValueError):
            pass
    return str(value)


class MaterialDbView(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._entries: list[dict] = []
        self._build_ui()
        self._load_db()

    def _build_ui(self) -> None:
        title = QLabel("Material DB")
        title.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 8px;")

        self._material_selector = QComboBox()
        self._material_selector.currentTextChanged.connect(self._on_material_changed)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setMaximumWidth(110)
        refresh_btn.clicked.connect(self._load_db)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("Material:"))
        selector_row.addWidget(self._material_selector, stretch=1)
        selector_row.addWidget(refresh_btn)

        self._table = QTableWidget()
        self._table.setColumnCount(len(_COLUMNS))
        self._table.setHorizontalHeaderLabels([label for _, label in _COLUMNS])
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet("""
            QScrollBar:horizontal {
                height: 36px;
            }
            QScrollBar::handle:horizontal {
                min-width: 40px;
            }
        """)

        root = QVBoxLayout()
        root.setContentsMargins(9, 9, 9, 9)
        root.setSpacing(8)
        root.addWidget(title)
        root.addLayout(selector_row)
        root.addWidget(self._table, stretch=1)
        self.setLayout(root)

    def _load_db(self) -> None:
        self._entries = []
        if _DB_PATH.exists():
            try:
                self._entries = json.loads(_DB_PATH.read_text(encoding="utf-8"))
            except Exception:
                pass

        current = self._material_selector.currentText()
        names: list[str] = list(dict.fromkeys(
            e["mat_name"] for e in self._entries
            if isinstance(e, dict) and e.get("mat_name")
        ))

        self._material_selector.blockSignals(True)
        self._material_selector.clear()
        self._material_selector.addItems(names)
        if current in names:
            self._material_selector.setCurrentText(current)
        self._material_selector.blockSignals(False)

        self._populate_table(self._material_selector.currentText())

    def _on_material_changed(self, name: str) -> None:
        self._populate_table(name)

    def _populate_table(self, mat_name: str) -> None:
        rows = [e for e in self._entries if isinstance(e, dict) and e.get("mat_name") == mat_name]
        rows.sort(key=lambda e: e.get("diskID", ""))

        self._table.setRowCount(len(rows))
        for row_idx, entry in enumerate(rows):
            for col_idx, (key, _) in enumerate(_COLUMNS):
                value = entry.get(key)
                if key == "bulk_density_mean" and entry.get("bulk_density_success") is False:
                    text = "Failed"
                elif key == "tapped_density_mean" and entry.get("tapped_density_success") is False:
                    text = "Failed"
                else:
                    text = _fmt(key, value)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                self._table.setItem(row_idx, col_idx, item)
