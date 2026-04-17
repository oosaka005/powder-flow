from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.widgets.touch_numeric_input import TouchNumericInput
from service.settings_store import load_settings, update_settings


class SetupView(QWidget):
    proceed_to_run = Signal()
    proceed_to_manual = Signal()
    proceed_to_single_test = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._settings = load_settings()
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Powder Flow Setup")

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        material = self._settings["material"]
        calibration = self._settings["calibration"]
        disk_master = self._settings["disk_master"]
        self.material_name_input = QComboBox()
        self.material_name_input.setEditable(True)
        self.material_name_input.setInsertPolicy(QComboBox.NoInsert)
        self._populate_material_name_candidates(material["material_name"])
        self.disk_id_input = QComboBox()
        disk_ids = sorted(disk_master.keys())
        self.disk_id_input.addItems(disk_ids)
        self.disk_id_input.setCurrentText(material["disk_id"])
        self.vib_level_checks: list[QCheckBox] = []
        self.vib_levels_widget = QWidget()
        self.vib_levels_layout = QHBoxLayout()
        self.vib_levels_layout.setContentsMargins(0, 0, 0, 0)
        self.vib_levels_widget.setLayout(self.vib_levels_layout)
        for level in [1, 2, 3, 4, 5]:
            checkbox = QCheckBox(str(level))
            checkbox.setChecked(level in calibration["vib_levels"])
            self.vib_level_checks.append(checkbox)
            self.vib_levels_layout.addWidget(checkbox)
        self.vib_time_checks: list[QCheckBox] = []
        self.vib_times_widget = QWidget()
        self.vib_times_layout = QHBoxLayout()
        self.vib_times_layout.setContentsMargins(0, 0, 0, 0)
        self.vib_times_widget.setLayout(self.vib_times_layout)
        for vib_time in [1.0, 2.0, 3.0]:
            label = str(int(vib_time))
            checkbox = QCheckBox(label)
            checkbox.setChecked(vib_time in calibration["vib_time_candidates"])
            self.vib_time_checks.append(checkbox)
            self.vib_times_layout.addWidget(checkbox)
        self.steps_per_level_input = TouchNumericInput()
        self.steps_per_level_input.setRange(3, 20)
        self.steps_per_level_input.setSingleStep(1)
        self.steps_per_level_input.setDecimals(0)
        self.steps_per_level_input.setValue(int(calibration["steps_per_level"]))

        self.stability_steps_input = TouchNumericInput()
        self.stability_steps_input.setRange(3, 20)
        self.stability_steps_input.setSingleStep(1)
        self.stability_steps_input.setDecimals(0)
        self.stability_steps_input.setValue(int(calibration["stability_steps"]))

        form.addRow("Material name", self.material_name_input)
        form.addRow("Disk ID", self.disk_id_input)
        form.addRow(
            "Candidate vibration levels\n(1 = min / weak, 5 = max / strong)",
            self.vib_levels_widget,
        )
        form.addRow("Candidate vibration times [s]", self.vib_times_widget)
        form.addRow("Dose count for level/time evaluation (3-20)", self.steps_per_level_input)
        form.addRow("Dose count for stability test (3-20)", self.stability_steps_input)

        self.run_button = QPushButton("Start Automated Evaluation")
        self.apply_button = QPushButton("Apply Settings")
        self.run_button.clicked.connect(self._on_save_and_open_run)
        self.apply_button.clicked.connect(self._on_apply_settings)
        self.run_button.setMinimumHeight(52)
        self.run_button.setMinimumWidth(520)
        self.apply_button.setMinimumHeight(52)
        self.apply_button.setMaximumWidth(220)

        buttons = QHBoxLayout()
        left_spacer = QWidget()
        center_slot = QWidget()
        right_slot = QWidget()
        center_layout = QHBoxLayout()
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.addStretch(1)
        center_layout.addWidget(self.run_button)
        center_layout.addStretch(1)
        center_slot.setLayout(center_layout)
        right_layout = QHBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addStretch(1)
        right_layout.addWidget(self.apply_button)
        right_slot.setLayout(right_layout)
        buttons.addWidget(left_spacer, 1)
        buttons.addWidget(center_slot, 1)
        buttons.addWidget(right_slot, 1)

        root = QVBoxLayout()
        root.setContentsMargins(9, 9, 9, 9)
        root.setSpacing(8)
        self.title_label = QLabel("Setup Mode")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 8px;")
        root.addWidget(self.title_label)
        root.addLayout(form)
        root.addLayout(buttons)
        self.setLayout(root)

    def _populate_material_name_candidates(self, current_name: str) -> None:
        calib_path = Path(__file__).resolve().parents[2] / "config" / "material_database.json"
        names: list[str] = []
        if calib_path.exists():
            try:
                entries = json.loads(calib_path.read_text(encoding="utf-8"))
                names = list(dict.fromkeys(
                    e["mat_name"] for e in entries if isinstance(e, dict) and e.get("mat_name")
                ))
            except Exception:
                pass
        self.material_name_input.clear()
        self.material_name_input.addItems(names)
        self.material_name_input.setCurrentText(current_name)

    def _save_settings_from_ui(self) -> bool:
        try:
            material_name = self.material_name_input.currentText().strip()
            disk_id = self.disk_id_input.currentText().strip()
            vib_levels = [
                int(checkbox.text()) for checkbox in self.vib_level_checks if checkbox.isChecked()
            ]
            vib_times = [
                float(checkbox.text()) for checkbox in self.vib_time_checks if checkbox.isChecked()
            ]
            steps_per_level = self.steps_per_level_input.value()
            stability_steps = self.stability_steps_input.value()

            if not material_name:
                raise ValueError("Material name is empty.")
            if not disk_id:
                raise ValueError("Disk ID is empty.")
            if not vib_levels:
                raise ValueError("VIB levels is empty.")
            if not vib_times:
                raise ValueError("VIB time candidates is empty.")
        except Exception as exc:
            QMessageBox.warning(self, "Input Error", str(exc))
            return False

        update_settings(
            {
                "material": {
                    "material_name": material_name,
                    "part_type": "metal",
                    "disk_id": disk_id,
                },
                "calibration": {
                    "vib_levels": vib_levels,
                    "vib_time_candidates": vib_times,
                    "steps_per_level": steps_per_level,
                    "stability_steps": stability_steps,
                },
            }
        )
        return True

    def _on_save_and_open_run(self) -> None:
        if not self._save_settings_from_ui():
            return
        self.proceed_to_run.emit()

    def _on_apply_settings(self) -> None:
        if not self._save_settings_from_ui():
            return
