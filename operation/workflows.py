from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import tempfile
from typing import Any, Callable


@dataclass
class FlowHooks:
    on_log: Callable[[str], None] | None = None


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class FlowAbortedError(RuntimeError):
    pass


def _log(hooks: FlowHooks | None, message: str) -> None:
    if hooks and hooks.on_log:
        hooks.on_log(message)
    else:
        print(message)


def _log_stage(hooks: FlowHooks | None, message: str) -> None:
    _log(hooks, message)


def _format_optional(value: float | None, *, digits: int = 4, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}{suffix}"


def _raise_stage_error(stage: str, exc: Exception) -> None:
    raise RuntimeError(f"{stage} failed: {exc}") from exc


def _ensure_not_cancelled(token: CancellationToken | None) -> None:
    if token and token.cancelled:
        raise FlowAbortedError("Operation was aborted by user.")


def _content_type_for(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    return "application/octet-stream"


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "filename": path.name,
        "content_type": _content_type_for(path),
        "data": path.read_bytes(),
    }


def run_manual_experiment(
    *,
    vib_level: int,
    vib_seconds: float,
    dose_count: int,
    use_aug: bool,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from hardware_api.powder_dispenser.p_dispenser_HAT_api import cleanup_motors, step, vib
    from operation.powder_flow_api import vib_with_aug

    is_step_only = int(vib_level) <= 0
    _log(
        hooks,
        "Manual run started: "
        f"vib_level={vib_level}, vib_seconds={vib_seconds}, dose_count={dose_count}, "
        f"use_aug={use_aug}, step_only={is_step_only}",
    )

    try:
        vib_runner = vib_with_aug if use_aug else vib
        requested_steps = max(0, int(dose_count))
        succeeded_steps = 0

        if requested_steps == 0:
            _ensure_not_cancelled(cancel_token)
            if not is_step_only:
                vib_runner(vib_level, vib_seconds)
        else:
            for _ in range(requested_steps):
                _ensure_not_cancelled(cancel_token)
                if not is_step_only:
                    vib_runner(vib_level, vib_seconds)
                _ensure_not_cancelled(cancel_token)
                if not bool(step()["success"]):
                    break
                succeeded_steps += 1

        return {
            "requested_steps": requested_steps,
            "succeeded_steps": succeeded_steps,
            "vib_level": vib_level,
            "vib_seconds": vib_seconds,
            "use_aug": use_aug,
        }
    finally:
        cleanup_motors()


def run_clog_clear(
    *,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from hardware_api.powder_dispenser.p_dispenser_HAT_api import cleanup_motors, run_all_motors

    _log(hooks, "Clog clear started: vib_level=4, duration_sec=2.0")
    _ensure_not_cancelled(cancel_token)

    try:
        step_success = run_all_motors(vib_level=4, duration_sec=2.0)
        return {
            "vib_level": 4,
            "duration_sec": 2.0,
            "step_success": step_success,
        }
    finally:
        cleanup_motors()


def run_manual_camera_preview(
    *,
    focus_mode: str,
    lens_position: float | None,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from hardware_api.camera.camera_api import capture_image

    _log_stage(hooks, f"Camera: capturing preview image (focus={focus_mode})")
    _ensure_not_cancelled(cancel_token)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        capture_image(
            tmp_path,
            rotation=180,
            autofocus_mode=focus_mode,
            lens_position=lens_position if focus_mode == "manual" else None,
        )
        _ensure_not_cancelled(cancel_token)
        image_bytes = tmp_path.read_bytes()
        _log(hooks, "Camera preview captured")
        return {
            "action": "camera_preview",
            "filename": tmp_path.name,
            "image_bytes": image_bytes,
            "focus_mode": focus_mode,
            "lens_position": lens_position,
        }
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Camera preview capture", exc)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def run_capture_repose_preview(
    *,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    """Capture an image with repose settings and return the cropped image for preview."""
    from hardware_api.camera.camera_api import capture_powder_image
    from operation.repose_analysis import _preprocess_repose
    import cv2

    _log_stage(hooks, "Camera: capturing repose preview image")
    _ensure_not_cancelled(cancel_token)

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        capture_powder_image(output_path=tmp_path)
        _ensure_not_cancelled(cancel_token)

        arr = cv2.imread(str(tmp_path), cv2.IMREAD_UNCHANGED)
        if arr is None:
            raise RuntimeError("Failed to load captured image.")
        cropped, _, _ = _preprocess_repose(arr)
        _, buf = cv2.imencode(".png", cropped)
        image_bytes = buf.tobytes()

        _log(hooks, "Repose preview captured")
        return {
            "action": "camera_preview",
            "filename": tmp_path.name,
            "image_bytes": image_bytes,
        }
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Repose preview capture", exc)
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass


def run_automated_experiment(
    *,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from hardware_api.balance.balance_api import Balance
    from hardware_api.powder_dispenser.p_dispenser_HAT_api import cleanup_motors
    from operation.powder_flow_api import (
        classify_hausner,
        prime_p_dispenser,
    )
    from service.settings_store import load_settings

    settings = load_settings()
    material = settings["material"]
    calibration = settings["calibration"]

    material_name = material["material_name"]
    part_type = material["part_type"]
    disk_id = material["disk_id"]
    vib_levels = [int(v) for v in calibration["vib_levels"]]
    vib_time_candidates = [float(v) for v in calibration["vib_time_candidates"]]
    steps_per_level = int(calibration["steps_per_level"])
    stability_steps = int(calibration["stability_steps"])

    if not vib_levels:
        raise ValueError("vib_levels must contain at least one value.")
    if not vib_time_candidates:
        raise ValueError("vib_time_candidates must contain at least one value.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_prefix = f"{timestamp[:8]}_"
    run_id = f"{timestamp}_{material_name}"
    artifacts: dict[str, Any] = {}

    balance = Balance()
    try:
        _log_stage(hooks, "Starting automated experiment")

        _ensure_not_cancelled(cancel_token)
        _log_stage(hooks, "Calibration: priming dispenser")
        try:
            prime_p_dispenser(balance)
        except FlowAbortedError:
            raise
        except Exception as exc:
            _raise_stage_error("Calibration priming", exc)
        _log(hooks, "Priming completed")

        calibration_result = _run_calibration(
            balance=balance,
            material_name=material_name,
            timestamp=timestamp,
            vib_levels=vib_levels,
            vib_time_candidates=vib_time_candidates,
            steps_per_level=steps_per_level,
            stability_steps=stability_steps,
            disk_id=disk_id,
            date_prefix=date_prefix,
            hooks=hooks,
            cancel_token=cancel_token,
        )
        artifacts.update(calibration_result["artifacts"])
        calibration_data = calibration_result["calibration"]

        bulk_density_result = _run_bulk_density(
            balance=balance,
            material_name=material_name,
            timestamp=timestamp,
            disk_id=disk_id,
            hooks=hooks,
            cancel_token=cancel_token,
        )
        artifacts.update(bulk_density_result["artifacts"])
        bulk_density_data = bulk_density_result["bulk_density"]
        mean_bulk = bulk_density_data["mean"]
        bulk_success = bool(bulk_density_data["success"])

        repose_result = _run_repose(
            material_name=material_name,
            timestamp=timestamp,
            date_prefix=date_prefix,
            hooks=hooks,
            cancel_token=cancel_token,
        )
        artifacts.update(repose_result["artifacts"])
        repose_data = repose_result["angle_of_repose"]
        mean_angle = repose_data["angle_deg"]

        tapped_density_result = _run_tapped_density(
            balance=balance,
            material_name=material_name,
            timestamp=timestamp,
            disk_id=disk_id,
            hooks=hooks,
            cancel_token=cancel_token,
        )
        artifacts.update(tapped_density_result["artifacts"])
        tapped_density_data = tapped_density_result["tapped_density"]
        mean_tapped = tapped_density_data["mean"]
        tapped_success = bool(tapped_density_data["success"])
        hausner_ratio = (
            mean_tapped / mean_bulk
            if mean_bulk is not None and mean_tapped is not None and mean_bulk
            else None
        )
        hausner_class = (
            classify_hausner(hausner_ratio)
            if hausner_ratio is not None and bulk_success and tapped_success
            else None
        )
        _log(
            hooks,
            "Hausner ratio: "
            f"value={_format_optional(hausner_ratio, digits=4)}, "
            f"class={hausner_class if hausner_class is not None else 'n/a'}",
        )
    finally:
        balance.disconnect()
        cleanup_motors()

    result_data = {
        "metadata": {
            "run_id": run_id,
            "timestamp": timestamp,
            "app_settings": settings,
            "success": {
                "calibration": bool(calibration_data.get("success", False)),
                "bulk_density": bool(bulk_density_data.get("success", False)),
                "tapped_density": bool(tapped_density_data.get("success", False)),
                "angle_of_repose": bool(repose_data.get("success", False)),
            },
        },
        "calibration": calibration_data,
        "angle_of_repose": repose_data,
        "hausner": {
            "ratio": hausner_ratio,
            "class": hausner_class,
            "bulk_density": bulk_density_data,
            "tapped_density": tapped_density_data,
        },
    }

    _log(hooks, f"Automated experiment completed: {run_id}")
    return {
        "result_data": result_data,
        "artifacts": artifacts,
    }


def run_single_test(
    *,
    stage: str,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from hardware_api.balance.balance_api import Balance
    from hardware_api.powder_dispenser.p_dispenser_HAT_api import cleanup_motors
    from service.settings_store import load_settings

    settings = load_settings()
    material = settings["material"]
    calibration = settings["calibration"]

    material_name = material["material_name"]
    disk_id = material["disk_id"]
    vib_levels = [int(v) for v in calibration["vib_levels"]]
    vib_time_candidates = [float(v) for v in calibration["vib_time_candidates"]]
    steps_per_level = int(calibration["steps_per_level"])
    stability_steps = int(calibration["stability_steps"])

    if not vib_levels:
        raise ValueError("vib_levels must contain at least one value.")
    if not vib_time_candidates:
        raise ValueError("vib_time_candidates must contain at least one value.")

    stage_key = stage.strip().lower()
    if stage_key == "repose":
        stage_key = "angle_of_repose"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    date_prefix = f"{timestamp[:8]}_"
    artifacts: dict[str, Any] = {}
    balance: Any | None = None

    _ensure_not_cancelled(cancel_token)
    _log_stage(hooks, f"Starting single test: {stage_key}")

    try:
        if stage_key in {"calibration", "bulk_density", "tapped_density"}:
            balance = Balance()

        if stage_key == "calibration":
            stage_result = _run_calibration(
                balance=balance,
                material_name=material_name,
                timestamp=timestamp,
                vib_levels=vib_levels,
                vib_time_candidates=vib_time_candidates,
                steps_per_level=steps_per_level,
                stability_steps=stability_steps,
                disk_id=disk_id,
                date_prefix=date_prefix,
                hooks=hooks,
                cancel_token=cancel_token,
            )
            result_key = "calibration"
        elif stage_key == "bulk_density":
            stage_result = _run_bulk_density(
                balance=balance,
                material_name=material_name,
                timestamp=timestamp,
                disk_id=disk_id,
                hooks=hooks,
                cancel_token=cancel_token,
            )
            result_key = "bulk_density"
        elif stage_key == "angle_of_repose":
            stage_result = _run_repose(
                material_name=material_name,
                timestamp=timestamp,
                date_prefix=date_prefix,
                hooks=hooks,
                cancel_token=cancel_token,
            )
            result_key = "angle_of_repose"
        elif stage_key == "tapped_density":
            stage_result = _run_tapped_density(
                balance=balance,
                material_name=material_name,
                timestamp=timestamp,
                disk_id=disk_id,
                hooks=hooks,
                cancel_token=cancel_token,
            )
            result_key = "tapped_density"
        else:
            raise ValueError(f"Unknown single test stage: {stage}")

        artifacts.update(stage_result["artifacts"])
        stage_data = stage_result[result_key]
    finally:
        if balance is not None:
            balance.disconnect()
        cleanup_motors()

    return {
        "metadata": {
            "material_name": material_name,
            "timestamp": timestamp,
            "stage": stage_key,
            "app_settings": settings,
            "success": bool(stage_data.get("success", False)),
        },
        "result_data": {
            result_key: stage_data,
        },
        "artifacts": artifacts,
    }


def _run_calibration(
    *,
    balance: Any,
    material_name: str,
    timestamp: str,
    vib_levels: list[int],
    vib_time_candidates: list[float],
    steps_per_level: int,
    stability_steps: int,
    disk_id: str,
    date_prefix: str,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from operation.powder_flow_api import (
        _load_disk_volume,
        explore_levels,
        explore_times,
        measure_series,
        select_optimal_series,
        vib_with_aug,
    )
    from operation.powder_flow_io import plot_level_exploration, plot_stability, plot_time_exploration

    _ensure_not_cancelled(cancel_token)
    _log_stage(hooks, "Calibration: optimizing vibration conditions (level and time)")
    try:
        vib_time = vib_time_candidates[0]
        level_results = explore_levels(
            balance,
            vib_levels=vib_levels,
            vib_time=vib_time,
            steps_per_level=steps_per_level,
            vib_fn=vib_with_aug,
        )
        has_level_success = any(res["success_all"] for res in level_results)
        optimal_level = select_optimal_series(level_results) if has_level_success else None
        if optimal_level is None:
            raise RuntimeError("no vibration level achieved full success")

        time_results = None
        if len(vib_time_candidates) > 1:
            _ensure_not_cancelled(cancel_token)
            time_results = explore_times(
                balance,
                level=optimal_level["level"],
                vib_times=vib_time_candidates,
                steps_per_time=steps_per_level,
                vib_fn=vib_with_aug,
            )
            has_time_success = any(res["success_all"] for res in time_results)
            if has_time_success:
                best_time = select_optimal_series(time_results)
                vib_time = best_time["vib_time"]
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Calibration condition optimization", exc)
    _log(
        hooks,
        "Calibration result: "
        f"selected level={optimal_level['level']}, "
        f"time={_format_optional(vib_time, digits=3, suffix=' s')}",
    )

    _ensure_not_cancelled(cancel_token)
    _log_stage(hooks, "Calibration: running stability test")
    try:
        stability_results = []
        stability_result = measure_series(
            balance,
            level=optimal_level["level"],
            vib_time=vib_time,
            steps=stability_steps,
            vib_fn=vib_with_aug,
        )
        stability_results.append(stability_result)

        selected_level = optimal_level["level"]
        if not stability_results[-1]["success_all"]:
            _log(hooks, "Calibration: retrying stability with higher vibration level")
            for level in range(optimal_level["level"] + 1, 6):
                _ensure_not_cancelled(cancel_token)
                retry_result = measure_series(
                    balance,
                    level=level,
                    vib_time=vib_time,
                    steps=stability_steps,
                    vib_fn=vib_with_aug,
                )
                stability_results.append(retry_result)
                if retry_result["success_all"]:
                    selected_level = level
                    _log(hooks, f"Calibration result: stability recovered at level={level}")
                    break
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Calibration stability test", exc)

    artifacts: dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            level_plot_path = tmp_path / f"{date_prefix}level_exploration.png"
            plot_level_exploration(level_results, optimal_level, level_plot_path)
            artifacts["calibration_level_plot"] = _artifact_entry(level_plot_path)

            if time_results and any(res["success_all"] for res in time_results):
                best_time = select_optimal_series(time_results)
                time_plot_path = tmp_path / f"{date_prefix}vib_time_exploration.png"
                plot_time_exploration(time_results, best_time, time_plot_path)
                artifacts["calibration_time_plot"] = _artifact_entry(time_plot_path)

            for idx, result in enumerate(stability_results, 1):
                stability_plot_path = tmp_path / f"{date_prefix}stability_test_{idx}.png"
                plot_stability(result, stability_plot_path)
                artifacts[f"calibration_stability_plot_{idx}"] = _artifact_entry(
                    stability_plot_path
                )
    except RuntimeError as exc:
        _log(hooks, f"Calibration plot export skipped: {exc}")

    disk_volume = _load_disk_volume(disk_id)
    final_stability_result = stability_results[-1]
    calibration_success = bool(final_stability_result.get("success_all", False))
    _log(
        hooks,
        "Stability result: "
        f"level={selected_level}, "
        f"time={_format_optional(vib_time, digits=3, suffix=' s')}, "
        f"mean={_format_optional(final_stability_result['mean_step_mass'], digits=6, suffix=' g/step')}, "
        f"std={_format_optional(final_stability_result['std_step_mass'], digits=6)}, "
        f"steps={len(final_stability_result.get('per_step', []))}, "
        f"success={'yes' if calibration_success else 'no'}",
    )

    return {
        "metadata": {
            "material_name": material_name,
            "timestamp": timestamp,
        },
        "calibration": {
            "vib_levels": vib_levels,
            "vib_time_candidates": vib_time_candidates,
            "steps_per_level": steps_per_level,
            "stability_steps": stability_steps,
            "selected_vib_level": selected_level,
            "selected_vib_time": vib_time,
            "level_results": level_results,
            "time_results": time_results,
            "stability_results": stability_results,
            "success": calibration_success,
            "stability_success": calibration_success,
            "step_mass_mean": final_stability_result["mean_step_mass"],
            "step_mass_std": final_stability_result["std_step_mass"],
            "step_count": len(final_stability_result.get("per_step", [])),
            "density_g_per_ml": (
                final_stability_result["mean_step_mass"] / disk_volume if disk_volume else None
            ),
        },
        "artifacts": artifacts,
    }


def _run_bulk_density(
    *,
    balance: Any,
    material_name: str,
    timestamp: str,
    disk_id: str,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from operation.powder_flow_api import _load_disk_volume, measure_bulk_density

    _ensure_not_cancelled(cancel_token)
    _log_stage(hooks, "Flowability: measuring bulk density")
    try:
        mean_bulk, stdev_bulk, bulk_densities, bulk_success = measure_bulk_density(
            balance,
            disk_id=disk_id,
        )
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Bulk density measurement", exc)
    _log(
        hooks,
        "Bulk density result: "
        f"mean={_format_optional(mean_bulk, digits=6, suffix=' g/mL')}, "
        f"std={_format_optional(stdev_bulk, digits=6)}, "
        f"trials={len(bulk_densities)}, "
        f"success={'yes' if bulk_success else 'no'}",
    )

    disk_volume = _load_disk_volume(disk_id)
    bulk_masses = [density * disk_volume for density in bulk_densities]
    return {
        "metadata": {
            "material_name": material_name,
            "timestamp": timestamp,
        },
        "bulk_density": {
            "mean": mean_bulk,
            "stdev": stdev_bulk,
            "densities": bulk_densities,
            "masses": bulk_masses,
            "success": bulk_success,
        },
        "artifacts": {},
    }


def _run_repose(
    *,
    material_name: str,
    timestamp: str,
    date_prefix: str,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from hardware_api.powder_dispenser.p_dispenser_HAT_api import run_all_motors
    from operation.powder_flow_api import capture_and_analyze_repose, classify_repose
    from hardware_api.camera.camera_api import capture_powder_image

    _ensure_not_cancelled(cancel_token)
    _log_stage(hooks, "Flowability: measuring angle of repose")
    try:
        run_all_motors(1, 5.0)

        _ensure_not_cancelled(cancel_token)
        artifacts: dict[str, Any] = {}
        mean_angle: float | None = None
        analysis_error: str | None = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            repose_dir = Path(tmp_dir)
            image_name = f"{date_prefix}raw_image.png"
            try:
                image_path, analysis_artifacts, mean_angle = capture_and_analyze_repose(
                    output_dir=repose_dir,
                    image_name=image_name,
                    file_prefix=date_prefix,
                )
                artifacts["repose_raw_image"] = _artifact_entry(image_path)
                for artifact_key, image in analysis_artifacts.items():
                    generated_path = repose_dir / f"{artifact_key}.png"
                    import cv2

                    cv2.imwrite(str(generated_path), image)
                    artifacts[artifact_key] = _artifact_entry(generated_path)
            except FlowAbortedError:
                raise
            except Exception as analysis_exc:
                analysis_error = str(analysis_exc)
                raw_path = repose_dir / image_name
                if raw_path.exists():
                    artifacts["repose_raw_image"] = _artifact_entry(raw_path)
                for partial_key in ("repose_cropped_image", "repose_processed_image"):
                    file_stub = partial_key.replace("repose_", "").replace("_image", "")
                    partial_path = repose_dir / f"{date_prefix}{file_stub}.png"
                    if partial_path.exists():
                        artifacts[partial_key] = _artifact_entry(partial_path)
                _log(hooks, f"Angle of repose analysis failed: {analysis_error}")
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Angle of repose measurement", exc)

    if analysis_error is not None:
        return {
            "metadata": {
                "material_name": material_name,
                "timestamp": timestamp,
            },
            "angle_of_repose": {
                "angle_deg": None,
                "class": None,
                "success": False,
                "error": analysis_error,
            },
            "artifacts": artifacts,
        }

    _log(
        hooks,
        "Angle of repose result: "
        f"angle={_format_optional(mean_angle, digits=2, suffix=' deg')}, "
        f"class={classify_repose(mean_angle)}",
    )

    return {
        "metadata": {
            "material_name": material_name,
            "timestamp": timestamp,
        },
        "angle_of_repose": {
            "angle_deg": mean_angle,
            "class": classify_repose(mean_angle),
            "success": mean_angle is not None,
        },
        "artifacts": artifacts,
    }


def _run_tapped_density(
    *,
    balance: Any,
    material_name: str,
    timestamp: str,
    disk_id: str,
    hooks: FlowHooks | None = None,
    cancel_token: CancellationToken | None = None,
) -> dict[str, Any]:
    from operation.powder_flow_api import _load_disk_volume, measure_tapped_density

    _ensure_not_cancelled(cancel_token)
    _log_stage(hooks, "Flowability: measuring tapped density")
    try:
        mean_tapped, stdev_tapped, tapped_densities, tapped_success = measure_tapped_density(
            balance,
            disk_id=disk_id,
        )
    except FlowAbortedError:
        raise
    except Exception as exc:
        _raise_stage_error("Tapped density measurement", exc)
    _log(
        hooks,
        "Tapped density result: "
        f"mean={_format_optional(mean_tapped, digits=6, suffix=' g/mL')}, "
        f"std={_format_optional(stdev_tapped, digits=6)}, "
        f"trials={len(tapped_densities)}, "
        f"success={'yes' if tapped_success else 'no'}",
    )

    disk_volume = _load_disk_volume(disk_id)
    tapped_masses = [density * disk_volume for density in tapped_densities]
    return {
        "metadata": {
            "material_name": material_name,
            "timestamp": timestamp,
        },
        "tapped_density": {
            "mean": mean_tapped,
            "stdev": stdev_tapped,
            "densities": tapped_densities,
            "masses": tapped_masses,
            "success": tapped_success,
        },
        "artifacts": {},
    }
