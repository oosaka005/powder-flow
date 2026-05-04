from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from operation.workflows import (
    CancellationToken,
    FlowAbortedError,
    FlowHooks,
    run_automated_experiment,
)
from service.settings_store import load_settings


class RunView(QWidget):
    result_ready = Signal(dict)
    setup_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._elapsed_seconds = 0
        self._cancel_token = CancellationToken()
        self._thread: QThread | None = None
        self._worker: _FlowWorker | None = None
        self._can_return_to_setup = False
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _build_ui(self) -> None:
        self.setWindowTitle("Run")

        self.title_label = QLabel("Run Mode")
        self.title_label.setStyleSheet("font-size: 22px; font-weight: 700; margin-bottom: 8px;")
        self.run_datetime_label = QLabel("Run datetime: -")
        self.status_label = QLabel("Status: Stopped")
        self.elapsed_label = QLabel("Elapsed: 00:00")
        self.material_label = QLabel("Material: -")
        self.disk_label = QLabel("Disk ID: -")
        self.levels_label = QLabel("Candidate vibration levels: -")
        self.times_label = QLabel("Candidate vibration times [s]: -")
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)

        self.abort_button = QPushButton("Abort")
        self.abort_button.setEnabled(False)
        self.abort_button.clicked.connect(self.abort)
        self.retry_button = QPushButton("Run Same Conditions Again")
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self._retry_run)
        self.back_button = QPushButton("Back to Setup")
        self.back_button.setEnabled(False)
        self.back_button.clicked.connect(self.setup_requested.emit)

        layout = QVBoxLayout()
        layout.addWidget(self.title_label)
        layout.addWidget(self.run_datetime_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.elapsed_label)
        layout.addWidget(self.material_label)
        layout.addWidget(self.disk_label)
        layout.addWidget(self.levels_label)
        layout.addWidget(self.times_label)
        layout.addWidget(self.log_text)

        controls = QHBoxLayout()
        controls.addWidget(self.abort_button)
        controls.addWidget(self.retry_button)
        controls.addWidget(self.back_button)
        layout.addLayout(controls)
        self.setLayout(layout)

    def _set_running_ui(self, running: bool) -> None:
        self.status_label.setText("Status: Running" if running else "Status: Stopped")
        self.abort_button.setEnabled(running)
        self.retry_button.setEnabled((not running) and self._can_return_to_setup)
        self.back_button.setEnabled((not running) and self._can_return_to_setup)

    def _set_run_summary(
        self,
        *,
        material_name: str,
        disk_id: str,
        vib_levels: list[int],
        vib_time_candidates: list[float],
    ) -> None:
        self.material_label.setText(f"Material: {material_name}")
        self.disk_label.setText(f"Disk ID: {disk_id}")
        self.levels_label.setText(
            "Candidate vibration levels: "
            + ", ".join(str(level) for level in vib_levels)
        )
        self.times_label.setText(
            "Candidate vibration times [s]: "
            + ", ".join(str(candidate) for candidate in vib_time_candidates)
        )

    def start_automated_experiment_from_settings(self) -> None:
        if self._thread is not None:
            return

        settings = load_settings()
        material = settings["material"]
        calibration = settings["calibration"]

        material_name = material["material_name"]
        disk_id = material["disk_id"]
        answer = QMessageBox.question(
            self,
            "Confirm — Run All",
            f"Material: {material_name}\nDisk ID: {disk_id}\n\nStart the automated experiment with these conditions?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return

        self.log_text.clear()
        self._can_return_to_setup = False
        self._reset_cancel()
        self._set_running_ui(True)
        self.start_elapsed()
        self.run_datetime_label.setText(
            f"Run datetime: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        self.append_log("Starting automated experiment...")
        payload = {
            "material_name": material["material_name"],
            "disk_id": material["disk_id"],
            "vib_levels": [int(v) for v in calibration["vib_levels"]],
            "vib_time_candidates": [float(v) for v in calibration["vib_time_candidates"]],
            "steps_per_level": int(calibration["steps_per_level"]),
            "stability_steps": int(calibration["stability_steps"]),
        }
        self._set_run_summary(
            material_name=payload["material_name"],
            disk_id=payload["disk_id"],
            vib_levels=payload["vib_levels"],
            vib_time_candidates=payload["vib_time_candidates"],
        )

        worker = _FlowWorker(cancel_token=self._cancel_token)
        self._start_worker(worker)

    def _retry_run(self) -> None:
        if self._thread is not None:
            return
        self.start_automated_experiment_from_settings()

    def start_elapsed(self) -> None:
        self._elapsed_seconds = 0
        self.elapsed_label.setText("Elapsed: 00:00")
        self._timer.start(1000)

    def stop_elapsed(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        minutes, seconds = divmod(self._elapsed_seconds, 60)
        self.elapsed_label.setText(f"Elapsed: {minutes:02d}:{seconds:02d}")

    def append_log(self, message: str) -> None:
        self.log_text.append(message)

    def _reset_cancel(self) -> None:
        self._cancel_token = CancellationToken()

    def _start_worker(self, worker: "_FlowWorker") -> None:
        self._thread = QThread(self)
        self._worker = worker
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self.append_log)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.aborted.connect(self._on_worker_aborted)
        self._worker.done.connect(self._on_worker_done)
        self._thread.start()

    def _on_worker_finished(self, result: dict) -> None:
        self.append_log("Experiment completed.")
        self.result_ready.emit(result)

    def _on_worker_failed(self, message: str) -> None:
        self.append_log(f"Failed: {message}")
        self._can_return_to_setup = True

    def _on_worker_aborted(self, message: str) -> None:
        self.append_log(f"Stopped: {message}")
        self._can_return_to_setup = True

    def _cleanup_worker(self) -> None:
        self.stop_elapsed()
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_running_ui(False)

    def _on_worker_done(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(1000)
        self._cleanup_worker()

    def abort(self) -> None:
        self._cancel_token.cancel()
        self.append_log("Abort requested.")
        self._can_return_to_setup = True


class _SignalWriter(io.TextIOBase):
    def __init__(self, emit_log: Signal) -> None:
        super().__init__()
        self._emit_log = emit_log
        self._buffer = ""

    def write(self, s: str) -> int:
        self._buffer += s
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self._emit_log.emit(line)
        return len(s)

    def flush(self) -> None:
        if self._buffer.strip():
            self._emit_log.emit(self._buffer.strip())
        self._buffer = ""


class _FlowWorker(QObject):
    log = Signal(str)
    finished = Signal(dict)
    failed = Signal(str)
    aborted = Signal(str)
    done = Signal()

    def __init__(self, *, cancel_token: CancellationToken) -> None:
        super().__init__()
        self._cancel_token = cancel_token

    def _hooks(self) -> FlowHooks:
        return FlowHooks(on_log=self.log.emit)

    def run(self) -> None:
        writer = _SignalWriter(self.log)
        try:
            with redirect_stdout(writer), redirect_stderr(writer):
                result = run_automated_experiment(
                    hooks=self._hooks(),
                    cancel_token=self._cancel_token,
                )
            self.finished.emit(result)
        except FlowAbortedError as exc:
            self.aborted.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            writer.flush()
            self.done.emit()
