from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPixmap, QResizeEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from app.widgets.touch_numeric_input import TouchNumericInput
from operation.workflows import (
    CancellationToken,
    FlowHooks,
    run_clog_clear,
    run_manual_camera_preview,
    run_manual_experiment,
)
from service.settings_store import load_settings, update_settings


class ManualView(QWidget):
    back_to_run = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._worker: _ManualWorker | None = None
        self._cancel_token = CancellationToken()
        self._image_window: _ImagePreviewWindow | None = None
        self._build_ui()
        self._load_defaults()

    def _build_ui(self) -> None:
        self.setWindowTitle("Manual Mode")

        self.title_label = QLabel("Manual Mode")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 8px;")

        self.vib_level_checks: list[QCheckBox] = []
        self.vib_levels_widget = QWidget()
        self.vib_levels_layout = QHBoxLayout()
        self.vib_levels_layout.setContentsMargins(0, 0, 0, 0)
        self.vib_levels_layout.setSpacing(6)
        self.vib_levels_widget.setLayout(self.vib_levels_layout)
        self.vib_levels_widget.setMinimumWidth(250)
        for level in [0, 1, 2, 3, 4, 5]:
            checkbox = QCheckBox(str(level))
            checkbox.toggled.connect(
                lambda checked, current=checkbox: self._enforce_single_choice(
                    current,
                    self.vib_level_checks,
                    checked,
                )
            )
            self.vib_level_checks.append(checkbox)
            self.vib_levels_layout.addWidget(checkbox)

        self.vib_time_checks: list[QCheckBox] = []
        self.vib_times_widget = QWidget()
        self.vib_times_layout = QHBoxLayout()
        self.vib_times_layout.setContentsMargins(0, 0, 0, 0)
        self.vib_times_widget.setLayout(self.vib_times_layout)
        for vib_time in [1.0, 2.0, 3.0]:
            checkbox = QCheckBox(str(int(vib_time)))
            checkbox.toggled.connect(
                lambda checked, current=checkbox: self._enforce_single_choice(
                    current,
                    self.vib_time_checks,
                    checked,
                )
            )
            self.vib_time_checks.append(checkbox)
            self.vib_times_layout.addWidget(checkbox)

        self.use_aug_checkbox = QCheckBox("Use aug")
        self.dose_count = TouchNumericInput()
        self.dose_count.setRange(0, 99)
        self.dose_count.setSingleStep(1)
        self.dose_count.setDecimals(0)
        self.camera_focus_checks: list[QCheckBox] = []
        self.camera_focus_widget = QWidget()
        self.camera_focus_layout = QHBoxLayout()
        self.camera_focus_layout.setContentsMargins(0, 0, 0, 0)
        self.camera_focus_widget.setLayout(self.camera_focus_layout)
        for mode in ["Auto", "Manual"]:
            checkbox = QCheckBox(mode)
            checkbox.toggled.connect(
                lambda checked, current=checkbox: self._enforce_single_choice(
                    current,
                    self.camera_focus_checks,
                    checked,
                )
            )
            checkbox.toggled.connect(lambda _checked: self._update_camera_focus_ui())
            self.camera_focus_checks.append(checkbox)
            self.camera_focus_layout.addWidget(checkbox)
        if self.camera_focus_checks:
            self.camera_focus_checks[0].setChecked(True)
        self.camera_lens_position = TouchNumericInput()
        self.camera_lens_position.setRange(0.0, 32.0)
        self.camera_lens_position.setSingleStep(0.1)
        self.camera_lens_position.setDecimals(1)

        self.manual_run_button = QPushButton("Run")
        self.clog_clear_button = QPushButton("Clog Clear")
        self.camera_button = QPushButton("Capture Image")

        self.manual_run_button.setMinimumHeight(48)
        self.clog_clear_button.setMinimumHeight(48)
        self.camera_button.setMinimumHeight(48)

        self.manual_run_button.clicked.connect(self._on_manual_run)
        self.clog_clear_button.clicked.connect(self._on_clog_clear)
        self.camera_button.clicked.connect(self._on_capture_camera)

        manual_form = QFormLayout()
        manual_form.setLabelAlignment(Qt.AlignTop)
        manual_form.setContentsMargins(12, 18, 12, 12)
        manual_form.setHorizontalSpacing(12)
        manual_form.setVerticalSpacing(12)
        manual_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        vibration_levels_label = self._form_label(
            "Vibration levels\n(0 = step only, 1 = min / weak, 5 = max / strong)"
        )
        vibration_levels_label.setMinimumWidth(165)
        vibration_levels_label.setMinimumHeight(76)
        manual_form.addRow(
            vibration_levels_label,
            self.vib_levels_widget,
        )
        manual_form.addRow(self._form_label("Vibration times [s]"), self.vib_times_widget)
        manual_form.addRow(
            self._form_label("Dose count\n(0-99, 0 = no dose)"),
            self.dose_count,
        )
        manual_form.addRow(self.use_aug_checkbox)
        manual_buttons = QHBoxLayout()
        manual_buttons.addWidget(self.manual_run_button)
        manual_buttons.addWidget(self.clog_clear_button)
        manual_form.addRow(manual_buttons)
        manual_box = QGroupBox("Manual Dispense")
        manual_box.setLayout(manual_form)
        manual_box.setMinimumWidth(0)
        manual_box.setMinimumHeight(320)
        manual_box.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid #7f7f7f;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 8px 8px 8px;
                font-weight: 700;
                text-decoration: underline;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            """
        )

        camera_form = QFormLayout()
        camera_form.setLabelAlignment(Qt.AlignTop)
        camera_form.setContentsMargins(12, 18, 12, 12)
        camera_form.setHorizontalSpacing(12)
        camera_form.setVerticalSpacing(12)
        camera_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        camera_description = QLabel("Capture still image and open preview window")
        camera_description.setWordWrap(True)
        camera_form.addRow(camera_description)
        camera_focus_row = QWidget()
        camera_focus_row_layout = QVBoxLayout()
        camera_focus_row_layout.setContentsMargins(0, 0, 0, 0)
        camera_focus_row_layout.setSpacing(6)
        camera_focus_row.setLayout(camera_focus_row_layout)
        camera_focus_row_layout.addWidget(self._form_label("Focus mode"))
        camera_focus_row_layout.addWidget(self.camera_focus_widget)
        camera_form.addRow(camera_focus_row)

        camera_lens_row = QWidget()
        camera_lens_row_layout = QVBoxLayout()
        camera_lens_row_layout.setContentsMargins(0, 0, 0, 0)
        camera_lens_row_layout.setSpacing(6)
        camera_lens_row.setLayout(camera_lens_row_layout)
        camera_lens_row_layout.addWidget(self._form_label("Lens position (0.0-32.0)"))
        camera_lens_row_layout.addWidget(self.camera_lens_position)
        camera_form.addRow(camera_lens_row)
        camera_form.addRow(self.camera_button)
        camera_box = QGroupBox("Camera")
        camera_box.setLayout(camera_form)
        camera_box.setMinimumWidth(240)
        camera_box.setMaximumWidth(280)
        camera_box.setMinimumHeight(320)
        camera_box.setStyleSheet(
            """
            QGroupBox {
                border: 1px solid #7f7f7f;
                border-radius: 6px;
                margin-top: 12px;
                padding: 12px 8px 8px 8px;
                font-weight: 700;
                text-decoration: underline;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            """
        )

        top = QHBoxLayout()
        top.setSpacing(18)
        top.addWidget(manual_box)
        top.addWidget(camera_box)
        top.setStretch(0, 9)
        top.setStretch(1, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(9, 9, 9, 9)
        layout.addWidget(self.title_label)
        layout.addLayout(top)
        layout.addSpacing(10)
        self.setLayout(layout)

    def _form_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setMinimumWidth(200)
        return label

    def _load_defaults(self) -> None:
        settings = load_settings()
        manual = settings["manual"]
        self._set_selected_checkbox(
            self.vib_level_checks,
            str(int(manual["manual_vibration_level"])),
        )
        self._set_selected_checkbox(
            self.vib_time_checks,
            str(int(float(manual["manual_vibration_sec"]))),
        )
        self.use_aug_checkbox.setChecked(bool(manual.get("manual_use_aug", True)))
        self.dose_count.setValue(int(manual.get("manual_dose_count", 1)))
        focus_mode = str(manual.get("manual_camera_focus_mode", "auto")).capitalize()
        self._set_selected_checkbox(self.camera_focus_checks, focus_mode)
        self.camera_lens_position.setValue(float(manual.get("manual_camera_lens_position", 15.0)))
        self._update_camera_focus_ui()

    def _enforce_single_choice(
        self,
        active_checkbox: QCheckBox,
        group: list[QCheckBox],
        checked: bool,
    ) -> None:
        if not checked:
            if not any(checkbox.isChecked() for checkbox in group):
                active_checkbox.blockSignals(True)
                active_checkbox.setChecked(True)
                active_checkbox.blockSignals(False)
            return
        for checkbox in group:
            if checkbox is active_checkbox:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)

    def _set_selected_checkbox(self, group: list[QCheckBox], value: str) -> None:
        matched = False
        for checkbox in group:
            is_match = checkbox.text() == value
            checkbox.blockSignals(True)
            checkbox.setChecked(is_match)
            checkbox.blockSignals(False)
            matched = matched or is_match
        if not matched and group:
            group[0].setChecked(True)

    def _selected_value(self, group: list[QCheckBox], *, cast: type[int] | type[float]) -> int | float:
        for checkbox in group:
            if checkbox.isChecked():
                return cast(checkbox.text())
        raise ValueError("No option selected.")

    def _selected_text(self, group: list[QCheckBox]) -> str:
        for checkbox in group:
            if checkbox.isChecked():
                return checkbox.text()
        raise ValueError("No option selected.")

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._thread is None:
            self._load_defaults()

    def _set_running_ui(self, running: bool) -> None:
        self.manual_run_button.setEnabled(not running)
        self.clog_clear_button.setEnabled(not running)
        self.camera_button.setEnabled(not running)
        focus_is_manual = self._selected_text(self.camera_focus_checks) == "Manual"
        self.camera_lens_position.setEnabled((not running) and focus_is_manual)

    def _set_status(self, msg: str) -> None:
        _ = msg

    def _update_camera_focus_ui(self) -> None:
        if not hasattr(self, "camera_lens_position"):
            return
        focus_is_manual = self._selected_text(self.camera_focus_checks) == "Manual"
        self.camera_lens_position.setEnabled(focus_is_manual and self._thread is None)

    def _save_manual_settings(self) -> None:
        selected_level = int(self._selected_value(self.vib_level_checks, cast=int))
        selected_time = float(self._selected_value(self.vib_time_checks, cast=float))
        focus_mode = self._selected_text(self.camera_focus_checks).lower()
        update_settings(
            {
                "manual": {
                    "manual_vibration_level": selected_level,
                    "manual_vibration_sec": selected_time,
                    "manual_use_aug": self.use_aug_checkbox.isChecked(),
                    "manual_dose_count": self.dose_count.value(),
                    "manual_camera_focus_mode": focus_mode,
                    "manual_camera_lens_position": float(self.camera_lens_position.value()),
                }
            }
        )

    def _on_manual_run(self) -> None:
        self._save_manual_settings()
        selected_level = int(self._selected_value(self.vib_level_checks, cast=int))
        selected_time = float(self._selected_value(self.vib_time_checks, cast=float))
        self._start_worker(
            mode="manual_run",
            payload={
                "vib_level": selected_level,
                "vib_seconds": selected_time,
                "dose_count": self.dose_count.value(),
                "use_aug": self.use_aug_checkbox.isChecked(),
            },
        )

    def _on_clog_clear(self) -> None:
        self._start_worker(mode="clog_clear", payload={})

    def _on_capture_camera(self) -> None:
        self._save_manual_settings()
        self._start_worker(
            mode="camera_preview",
            payload={
                "focus_mode": self._selected_text(self.camera_focus_checks).lower(),
                "lens_position": float(self.camera_lens_position.value()),
            },
        )

    def _show_image_preview(self, pixmap: QPixmap) -> None:
        self._image_window = _ImagePreviewWindow(pixmap)
        self._image_window.show()

    def _start_worker(self, *, mode: str, payload: dict[str, Any]) -> None:
        if self._thread is not None:
            return
        self._cancel_token = CancellationToken()
        self._set_running_ui(True)
        self._thread = QThread(self)
        self._worker = _ManualWorker(mode=mode, payload=payload, cancel_token=self._cancel_token)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._set_status)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _on_finished(self, result: dict[str, Any]) -> None:
        action = result.get("action")
        if action == "camera_preview":
            image_bytes = result.get("image_bytes", b"")
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                self._set_status("Failed: could not load captured image.")
                return
            self._show_image_preview(pixmap)
            self._set_status("Camera image captured.")
            return
        self._set_status(f"Done: {result}")

    def _on_failed(self, message: str) -> None:
        self._set_status(f"Failed: {message}")

    def _cleanup_worker(self) -> None:
        self._worker = None
        self._thread = None
        self._set_running_ui(False)


class _ManualWorker(QObject):
    log = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)
    done = Signal()

    def __init__(
        self,
        *,
        mode: str,
        payload: dict[str, Any],
        cancel_token: CancellationToken,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._payload = payload
        self._cancel_token = cancel_token

    def _hooks(self) -> FlowHooks:
        return FlowHooks(on_log=self.log.emit)

    def run(self) -> None:
        try:
            if self._mode == "manual_run":
                result = run_manual_experiment(
                    vib_level=self._payload["vib_level"],
                    vib_seconds=self._payload["vib_seconds"],
                    dose_count=self._payload["dose_count"],
                    use_aug=self._payload["use_aug"],
                    hooks=self._hooks(),
                    cancel_token=self._cancel_token,
                )
                self.finished.emit(result)
                return
            if self._mode == "clog_clear":
                result = run_clog_clear(
                    hooks=self._hooks(),
                    cancel_token=self._cancel_token,
                )
                self.finished.emit(result)
                return
            if self._mode == "camera_preview":
                result = run_manual_camera_preview(
                    focus_mode=self._payload["focus_mode"],
                    lens_position=self._payload["lens_position"],
                    hooks=self._hooks(),
                    cancel_token=self._cancel_token,
                )
                self.finished.emit(result)
                return
            self.failed.emit(f"Unknown mode: {self._mode}")
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.done.emit()


class _ImagePreviewWindow(QWidget):
    def __init__(self, pixmap: QPixmap) -> None:
        super().__init__()
        self.setWindowTitle("Camera Preview")
        self.resize(800, 480)
        self._original_pixmap = pixmap

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.image_label)

        layout = QVBoxLayout()
        layout.addWidget(self.scroll)
        self.setLayout(layout)
        self._update_pixmap()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        viewport_size = self.scroll.viewport().size()
        if viewport_size.width() <= 0 or viewport_size.height() <= 0:
            return
        scaled = self._original_pixmap.scaled(
            viewport_size,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)
