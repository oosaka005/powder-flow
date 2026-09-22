"""Application service for the second-layer Powder Characterizer server."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace
from typing import Any, Callable

from operation.workflows import (
    CancellationToken,
    FlowAbortedError,
    FlowHooks,
    run_automated_experiment,
    run_capture_repose_preview,
    run_clog_clear,
    run_manual_camera_preview,
    run_manual_experiment,
    run_single_test,
)
from service.result_store import (
    discard_results,
    save_results,
    save_single_test_result,
)
from service.settings_store import load_settings, save_settings
from sila2_servers.powder_characterizer_server.devices import SilaDeviceFactory


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class OperationBusyError(RuntimeError):
    pass


ProgressCallback = Callable[[dict[str, Any]], None]


def _json_safe_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove artifact bytes from transport JSON without changing stored data."""
    public = deepcopy(result)
    artifacts = public.get("artifacts", {})
    for payload in artifacts.values():
        data = payload.pop("data", b"")
        payload["size"] = len(data)
    return public


def _assert_same_keys(candidate: Any, reference: Any, path: str = "settings") -> None:
    if isinstance(reference, dict):
        if not isinstance(candidate, dict):
            raise ValueError(f"{path} must be an object.")
        missing = set(reference) - set(candidate)
        added = set(candidate) - set(reference)
        if missing or added:
            raise ValueError(
                f"{path} keys must remain unchanged; missing={sorted(missing)}, added={sorted(added)}"
            )
        for key in reference:
            _assert_same_keys(candidate[key], reference[key], f"{path}.{key}")


class PowderCharacterizerApplication:
    def __init__(self, device_factory: SilaDeviceFactory | None = None) -> None:
        self._device_factory = device_factory or SilaDeviceFactory()
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._started_monotonic: float | None = None
        self._state: dict[str, Any] = {
            "run_id": None,
            "operation": None,
            "status": "idle",
            "stage": None,
            "progress": 0.0,
            "elapsed_sec": 0.0,
            "logs": [],
            "result": None,
            "error": None,
        }
        self._cancel_token: CancellationToken | None = None
        self._active_devices: Any | None = None
        self._pending_result: dict[str, Any] | None = None
        self._pending_kind: str | None = None
        self._pending_artifacts: dict[str, dict[str, Any]] = {}

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            snapshot = deepcopy(self._state)
            snapshot["result_pending"] = self._pending_result is not None
            if self._started_monotonic is not None and snapshot["status"] == "running":
                snapshot["elapsed_sec"] = round(
                    time.monotonic() - self._started_monotonic, 3
                )
            return snapshot

    def snapshot_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=False)

    def _notify(self, callback: ProgressCallback | None) -> None:
        if callback is not None:
            callback(self.snapshot())

    def _begin(self, operation: str, callback: ProgressCallback | None) -> None:
        with self._state_lock:
            if self._pending_result is not None:
                raise OperationBusyError(
                    "A result is pending. Save or discard it before starting another operation."
                )
        if not self._operation_lock.acquire(blocking=False):
            raise OperationBusyError("Another Powder Characterizer operation is already running.")
        with self._state_lock:
            self._started_monotonic = time.monotonic()
            self._state = {
                "run_id": None,
                "operation": operation,
                "status": "running",
                "stage": "starting",
                "progress": 0.0,
                "elapsed_sec": 0.0,
                "logs": [],
                "result": None,
                "error": None,
            }
            self._cancel_token = CancellationToken()
        self._notify(callback)

    @staticmethod
    def _progress_for_message(message: str, current: float) -> float:
        lowered = message.lower()
        stages = (
            ("starting", 0.02),
            ("priming", 0.05),
            ("calibration", 0.10),
            ("bulk density", 0.50),
            ("angle of repose", 0.70),
            ("tapped density", 0.85),
            ("completed", 1.0),
        )
        for marker, value in stages:
            if marker in lowered:
                return max(current, value)
        return current

    def _on_log(self, message: str, callback: ProgressCallback | None) -> None:
        with self._state_lock:
            logs = self._state["logs"]
            logs.append(str(message))
            if len(logs) > 1000:
                del logs[:-1000]
            self._state["stage"] = str(message)
            self._state["progress"] = self._progress_for_message(
                str(message), float(self._state["progress"])
            )
        self._notify(callback)

    @staticmethod
    def _result_run_id(result: dict[str, Any], operation: str) -> str:
        result_data = result.get("result_data", {})
        metadata = result_data.get("metadata", result.get("metadata", {}))
        if metadata.get("run_id"):
            return str(metadata["run_id"])
        timestamp = str(metadata.get("timestamp") or datetime.now().strftime("%Y%m%d_%H%M%S"))
        material = str(metadata.get("material_name") or operation)
        stage = str(metadata.get("stage") or operation)
        return f"{timestamp}_{material}_{stage}"

    def _finish(
        self,
        result: dict[str, Any],
        operation: str,
        callback: ProgressCallback | None,
        pending_kind: str | None,
    ) -> dict[str, Any]:
        public = _json_safe_result(result)
        run_id = self._result_run_id(result, operation)
        with self._state_lock:
            self._state["run_id"] = run_id
            self._state["status"] = "completed"
            self._state["stage"] = "completed"
            self._state["progress"] = 1.0
            self._state["elapsed_sec"] = round(
                time.monotonic() - (self._started_monotonic or time.monotonic()), 3
            )
            self._state["result"] = public
            if pending_kind is not None:
                self._pending_result = result
                self._pending_kind = pending_kind
                self._pending_artifacts = {
                    payload["filename"]: payload
                    for payload in result.get("artifacts", {}).values()
                }
        self._notify(callback)
        return public

    def _fail(
        self,
        exc: Exception,
        callback: ProgressCallback | None,
    ) -> None:
        with self._state_lock:
            aborted = isinstance(exc, FlowAbortedError) or (
                self._cancel_token is not None and self._cancel_token.cancelled
            )
            self._state["status"] = "aborted" if aborted else "failed"
            self._state["stage"] = self._state["status"]
            self._state["error"] = str(exc)
            self._state["elapsed_sec"] = round(
                time.monotonic() - (self._started_monotonic or time.monotonic()), 3
            )
        self._notify(callback)

    def _end(self) -> None:
        with self._state_lock:
            self._active_devices = None
            self._cancel_token = None
            self._started_monotonic = None
        self._operation_lock.release()

    def _raise_if_cancelled(self) -> None:
        with self._state_lock:
            token = self._cancel_token
        if token is not None and token.cancelled:
            raise FlowAbortedError("Operation was aborted by user.")

    def run_automated(self, callback: ProgressCallback | None = None) -> dict[str, Any]:
        operation = "automated"
        self._begin(operation, callback)
        devices = None
        try:
            devices = self._device_factory.create()
            self._active_devices = devices
            result = run_automated_experiment(
                hooks=FlowHooks(on_log=lambda msg: self._on_log(msg, callback)),
                cancel_token=self._cancel_token,
                powder_dispenser=devices.powder_dispenser,
                balance=devices.balance,
                camera=devices.camera,
            )
            self._raise_if_cancelled()
            return self._finish(result, operation, callback, "automated")
        except Exception as exc:
            self._fail(exc, callback)
            raise
        finally:
            if devices is not None:
                devices.close()
            self._end()

    def run_single(
        self,
        stage: str,
        callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        operation = stage.strip().lower()
        self._begin(operation, callback)
        devices = None
        try:
            devices = self._device_factory.create()
            self._active_devices = devices
            result = run_single_test(
                stage=stage,
                hooks=FlowHooks(on_log=lambda msg: self._on_log(msg, callback)),
                cancel_token=self._cancel_token,
                powder_dispenser=devices.powder_dispenser,
                balance=devices.balance,
                camera=devices.camera,
            )
            self._raise_if_cancelled()
            return self._finish(result, operation, callback, "single")
        except Exception as exc:
            self._fail(exc, callback)
            raise
        finally:
            if devices is not None:
                devices.close()
            self._end()

    def run_manual(
        self,
        *,
        vib_level: int,
        vib_seconds: float,
        dose_count: int,
        use_aug: bool,
        callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        operation = "manual"
        self._begin(operation, callback)
        dispenser = None
        try:
            dispenser = self._device_factory.create_dispenser()
            self._active_devices = SimpleNamespace(powder_dispenser=dispenser)
            result = run_manual_experiment(
                vib_level=vib_level,
                vib_seconds=vib_seconds,
                dose_count=dose_count,
                use_aug=use_aug,
                hooks=FlowHooks(on_log=lambda msg: self._on_log(msg, callback)),
                cancel_token=self._cancel_token,
                powder_dispenser=dispenser,
            )
            self._raise_if_cancelled()
            return self._finish(result, operation, callback, None)
        except Exception as exc:
            self._fail(exc, callback)
            raise
        finally:
            if dispenser is not None:
                dispenser.close()
            self._end()

    def clear_clog(self) -> dict[str, Any]:
        operation = "clear_clog"
        self._begin(operation, None)
        dispenser = None
        try:
            dispenser = self._device_factory.create_dispenser()
            self._active_devices = SimpleNamespace(powder_dispenser=dispenser)
            result = run_clog_clear(
                hooks=FlowHooks(on_log=lambda msg: self._on_log(msg, None)),
                cancel_token=self._cancel_token,
                powder_dispenser=dispenser,
            )
            self._raise_if_cancelled()
            return self._finish(result, operation, None, None)
        except Exception as exc:
            self._fail(exc, None)
            raise
        finally:
            if dispenser is not None:
                dispenser.close()
            self._end()

    def capture_camera_preview(self, focus_mode: str, lens_position: float) -> dict[str, Any]:
        if not self._operation_lock.acquire(blocking=False):
            raise OperationBusyError("Camera preview is unavailable while an operation is running.")
        camera = None
        try:
            camera = self._device_factory.create_camera()
            return run_manual_camera_preview(
                focus_mode=focus_mode,
                lens_position=lens_position,
                camera=camera,
            )
        finally:
            if camera is not None:
                camera.close()
            self._operation_lock.release()

    def capture_repose_preview(self) -> dict[str, Any]:
        if not self._operation_lock.acquire(blocking=False):
            raise OperationBusyError("Camera preview is unavailable while an operation is running.")
        camera = None
        try:
            camera = self._device_factory.create_camera()
            return run_capture_repose_preview(camera=camera)
        finally:
            if camera is not None:
                camera.close()
            self._operation_lock.release()

    def abort(self) -> None:
        with self._state_lock:
            if self._cancel_token is not None:
                self._cancel_token.cancel()
            active = self._active_devices
        if active is not None:
            active.powder_dispenser.stop_all()

    def save_pending(self, *, update_material_database: bool = False) -> None:
        with self._state_lock:
            if self._pending_result is None or self._pending_kind is None:
                raise RuntimeError("There is no pending result to save.")
            result = self._pending_result
            kind = self._pending_kind
            result["update_material_database"] = bool(update_material_database)
        if kind == "automated":
            save_results(result)
        else:
            save_single_test_result(result)
        with self._state_lock:
            self._pending_result = None
            self._pending_kind = None

    def discard_pending(self) -> None:
        with self._state_lock:
            if self._pending_result is None:
                return
            discard_results(self._pending_result)
            self._pending_result = None
            self._pending_kind = None
            self._pending_artifacts = {}

    @staticmethod
    def get_settings() -> dict[str, Any]:
        return load_settings(PROJECT_ROOT / "config" / "app_settings.json")

    def update_settings(self, settings: dict[str, Any]) -> None:
        # Keep one run's settings immutable. This also makes "Run Again" use
        # the same persisted conditions until the pending result is resolved.
        if not self._operation_lock.acquire(blocking=False):
            raise OperationBusyError("Settings cannot be changed while an operation is running.")
        try:
            with self._state_lock:
                if self._pending_result is not None:
                    raise OperationBusyError(
                        "Save or discard the pending result before changing settings."
                    )
            current = self.get_settings()
            _assert_same_keys(settings, current)
            save_settings(settings, PROJECT_ROOT / "config" / "app_settings.json")
        finally:
            self._operation_lock.release()

    @staticmethod
    def get_material_database() -> Any:
        path = PROJECT_ROOT / "config" / "material_database.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def get_artifact(self, run_id: str, filename: str) -> tuple[bytes, str]:
        if Path(filename).name != filename:
            raise ValueError("Artifact filename must not contain path separators.")
        with self._state_lock:
            payload = self._pending_artifacts.get(filename)
            if payload is not None and self._state.get("run_id") == run_id:
                return bytes(payload["data"]), str(payload["content_type"])

        log_root = Path(self.get_settings()["paths"]["log_root"])
        if not log_root.is_absolute():
            log_root = PROJECT_ROOT / log_root
        for run_dir in (log_root / "all" / run_id, log_root / "single" / run_id):
            try:
                resolved_dir = run_dir.resolve()
                resolved_root = log_root.resolve()
                if resolved_root not in resolved_dir.parents:
                    continue
            except OSError:
                continue
            for path in run_dir.rglob(filename) if run_dir.exists() else ():
                if path.is_file() and path.name == filename:
                    suffix = path.suffix.lower()
                    media_type = (
                        "image/png"
                        if suffix == ".png"
                        else "image/jpeg"
                        if suffix in {".jpg", ".jpeg"}
                        else "application/octet-stream"
                    )
                    return path.read_bytes(), media_type
        raise FileNotFoundError(f"Artifact not found: {run_id}/{filename}")
