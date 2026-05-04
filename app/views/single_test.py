from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtGui import QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from operation.workflows import (
    CancellationToken,
    FlowHooks,
    run_capture_repose_preview,
    run_manual_camera_preview,
    run_single_test,
)
from operation.step_timing_probe import measure_step_sensor_timing
from service.settings_store import load_settings


class SingleTestView(QWidget):
    back_to_setup = Signal()
    result_ready = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        self._thread: QThread | None = None
        self._worker: _SingleTestWorker | None = None
        self._cancel_token = CancellationToken()
        self._image_window: _ImagePreviewWindow | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Single Test Mode")

        self.title_label = QLabel("Single Test Mode")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 8px;")

        self.notice_label = QLabel(
            "The tests on this screen use the current Setup Mode configuration.\n"
            "Update the settings in Setup Mode first if you need different test conditions."
        )
        self.notice_label.setWordWrap(True)

        self.status_label = QLabel("Status: Ready")
        self.result_label = QLabel("Result: -")
        self.result_label.setWordWrap(True)

        self.prep_dispense_button = QPushButton("Dispense Once")
        self.capture_image_button = QPushButton("Capture Image")
        self.calibration_button = QPushButton("Calibration")
        self.tapped_density_button = QPushButton("Tapped Density")
        self.bulk_density_button = QPushButton("Bulk Density")
        self.repose_button = QPushButton("Angle of Repose")

        self.prep_dispense_button.setMinimumHeight(48)
        self.prep_dispense_button.setMaximumHeight(48)
        self.capture_image_button.setMinimumHeight(48)
        self.capture_image_button.setMaximumHeight(48)
        self.calibration_button.setMinimumHeight(40)
        self.tapped_density_button.setMinimumHeight(40)
        self.bulk_density_button.setMinimumHeight(40)
        self.repose_button.setMinimumHeight(40)
        self.prep_dispense_button.clicked.connect(
            lambda: self._start_stage("prep_dispense", "Dispense Once")
        )
        self.capture_image_button.clicked.connect(
            lambda: self._start_stage("capture_image", "Capture Image")
        )
        self.calibration_button.clicked.connect(
            lambda: self._start_stage("calibration", "Calibration")
        )
        self.tapped_density_button.clicked.connect(
            lambda: self._start_stage("tapped_density", "Tapped Density")
        )
        self.bulk_density_button.clicked.connect(
            lambda: self._start_stage("bulk_density", "Bulk Density")
        )
        self.repose_button.clicked.connect(
            lambda: self._start_stage("angle_of_repose", "Angle of Repose")
        )

        stage_grid = QGridLayout()
        stage_grid.setHorizontalSpacing(12)
        stage_grid.setVerticalSpacing(12)
        stage_grid.addWidget(self.calibration_button, 0, 0)
        stage_grid.addWidget(self.repose_button, 0, 1)
        stage_grid.addWidget(self.tapped_density_button, 1, 0)
        stage_grid.addWidget(self.bulk_density_button, 1, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.prep_dispense_button)
        bottom.addWidget(self.capture_image_button)

        layout = QVBoxLayout()
        layout.setContentsMargins(9, 9, 9, 9)
        layout.addWidget(self.title_label)
        layout.addWidget(self.notice_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.result_label)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(80)
        layout.addWidget(self.log_text)
        layout.addLayout(stage_grid)
        layout.addLayout(bottom)
        layout.addSpacing(10)
        self.setLayout(layout)

    def _set_running_ui(self, running: bool) -> None:
        self.prep_dispense_button.setEnabled(not running)
        self.capture_image_button.setEnabled(not running)
        self.calibration_button.setEnabled(not running)
        self.tapped_density_button.setEnabled(not running)
        self.bulk_density_button.setEnabled(not running)
        self.repose_button.setEnabled(not running)

    def _start_stage(self, stage: str, label: str) -> None:
        if self._thread is not None:
            return
        if stage not in {"prep_dispense", "step_timing", "capture_image"} and not self._confirm_stage_start(stage, label):
            return
        self._cancel_token = CancellationToken()
        self.status_label.setText(f"Status: Running {label}...")
        self.result_label.setText("Result: -")
        self.log_text.clear()
        self._set_running_ui(True)

        self._thread = QThread(self)
        self._worker = _SingleTestWorker(stage=stage, cancel_token=self._cancel_token)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.logged.connect(self.log_text.append)
        self._worker.done.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _confirm_stage_start(self, stage: str, label: str) -> bool:
        settings = load_settings()
        material_name = settings["material"]["material_name"]
        disk_id = settings["material"]["disk_id"]
        header = f"Material: {material_name}\nDisk ID: {disk_id}"
        if stage == "angle_of_repose":
            detail = "Has the powder pile been formed?"
        else:
            detail = "Has the material priming been completed?"
        message = f"{header}\n\n{detail}"
        answer = QMessageBox.question(
            self,
            f"Confirm — {label}",
            message,
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return answer == QMessageBox.Yes

    def _on_finished(self, result: dict[str, Any]) -> None:
        if result.get("action") == "camera_preview":
            image_bytes = result.get("image_bytes", b"")
            pixmap = QPixmap()
            if not pixmap.loadFromData(image_bytes):
                self.status_label.setText("Status: Failed")
                self.result_label.setText("Result: could not load captured image")
                return
            self._show_image_preview(pixmap)
            self.status_label.setText("Status: Completed")
            self.result_label.setText("Result: camera_preview success=True")
            return
        metadata = result.get("metadata", {})
        stage = metadata.get("stage", "-")
        success = bool(metadata.get("success", False))
        self.status_label.setText("Status: Completed" if success else "Status: Finished")
        if stage == "step_timing":
            probe = result.get("step_probe", {})
            transition_summary = ", ".join(
                f"{entry.get('label')}={float(entry.get('elapsed_sec', 0.0)):.4f}s"
                for entry in probe.get("transitions", [])
            )
            if not transition_summary:
                transition_summary = "no transitions"
            timeout_target = probe.get("timeout_target")
            timeout_text = f", timeout={timeout_target}" if timeout_target else ""
            self.result_label.setText(
                "Result: "
                f"{stage} success={success}, "
                f"initial={probe.get('initial_level')}, "
                f"sequence={probe.get('sequence')}, "
                f"{transition_summary}, "
                f"total={float(probe.get('total_elapsed_sec', 0.0)):.4f}s"
                f"{timeout_text}"
            )
        else:
            repose = result.get("angle_of_repose", {})
            repose_error = repose.get("error") if isinstance(repose, dict) else None
            if repose_error:
                self.status_label.setText("Status: Failed")
                self.result_label.setText(f"Result: Angle of repose measurement failed: {repose_error}")
            else:
                self.result_label.setText(f"Result: {stage} success={success}")
        if stage in {"calibration", "bulk_density", "tapped_density", "angle_of_repose"}:
            self.result_ready.emit(result)

    def _on_failed(self, message: str) -> None:
        self.status_label.setText("Status: Failed")
        self.result_label.setText(f"Result: {message}")

    def _cleanup_worker(self) -> None:
        self._worker = None
        self._thread = None
        self._set_running_ui(False)

    def _show_image_preview(self, pixmap: QPixmap) -> None:
        self._image_window = _ImagePreviewWindow(pixmap)
        self._image_window.show()


class _SingleTestWorker(QObject):
    finished = Signal(dict)
    failed = Signal(str)
    logged = Signal(str)
    done = Signal()

    def __init__(self, *, stage: str, cancel_token: CancellationToken) -> None:
        super().__init__()
        self._stage = stage
        self._cancel_token = cancel_token

    def _hooks(self) -> FlowHooks:
        return FlowHooks(on_log=self.logged.emit)

    def run(self) -> None:
        try:
            if self._stage == "prep_dispense":
                from hardware_api.powder_dispenser.p_dispenser_HAT_api import (
                    cleanup_motors,
                    run_all_motors,
                )

                if self._cancel_token.cancelled:
                    raise RuntimeError("Operation was aborted by user.")
                try:
                    step_success = run_all_motors(vib_level=3, duration_sec=1.0)
                finally:
                    cleanup_motors()
                self.finished.emit(
                    {
                        "metadata": {
                            "stage": self._stage,
                            "success": bool(step_success),
                        }
                    }
                )
                return
            if self._stage == "step_timing":
                from hardware_api.powder_dispenser.p_dispenser_HAT_api import cleanup_motors

                if self._cancel_token.cancelled:
                    raise RuntimeError("Operation was aborted by user.")
                try:
                    step_probe = measure_step_sensor_timing()
                finally:
                    cleanup_motors()
                self.finished.emit(
                    {
                        "metadata": {
                            "stage": self._stage,
                            "success": bool(step_probe.get("success")),
                        },
                        "step_probe": step_probe,
                    }
                )
                return
            if self._stage == "capture_image":
                result = run_capture_repose_preview(
                    hooks=self._hooks(),
                    cancel_token=self._cancel_token,
                )
                self.finished.emit(result)
                return
            result = run_single_test(
                stage=self._stage,
                hooks=self._hooks(),
                cancel_token=self._cancel_token,
            )
            self.finished.emit(result)
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
