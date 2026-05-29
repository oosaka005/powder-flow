"""
Functional helpers for powder-flow experiments.
"""

from __future__ import annotations

from pathlib import Path
import statistics
import time
from typing import Any, Callable, Dict, List, Optional

from hardware_api.balance.balance_api import Balance
import threading

from hardware_api.powder_dispenser.p_dispenser_HAT_api import (
    aug,
    drive_motor,
    run_all_motors,
    step,
    stop_motor,
    vib,
)
from hardware_api.camera.camera_api import capture_powder_image
from operation.repose_analysis import analyze_repose
from service.settings_store import load_settings

PRIME_DISPENSER_SETTINGS = {
    "vib_level": 3,
    "vib_sec": 1.0,
    "max_cycles": 10,
    "min_delta": 0.05,
}

MAX_CONSECUTIVE_STEP_TIMEOUTS = 3


def _current_settings() -> dict[str, Any]:
    return load_settings()


def _material_settings() -> dict[str, Any]:
    return dict(_current_settings()["material"])


def _bulk_density_settings() -> dict[str, Any]:
    return dict(_current_settings()["bulk_density"])


def _tapped_density_settings() -> dict[str, Any]:
    return dict(_current_settings()["tapped_density"])


def _disk_master_settings() -> dict[str, Any]:
    return dict(_current_settings()["disk_master"])


def _noise_threshold_g() -> float:
    return float(_current_settings()["calibration"]["noise_threshold_g"])


def _guarded_step(
    consecutive_timeouts: int,
    *,
    on_log: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], int]:
    result = step()
    if on_log:
        elapsed = float(result.get("elapsed_sec", 0.0))
        on_log(
            "[debug step] "
            f"success={result.get('success')}, "
            f"reason={result.get('stop_reason')}, "
            f"elapsed={elapsed:.4f}s, "
            f"timeouts={consecutive_timeouts}/{MAX_CONSECUTIVE_STEP_TIMEOUTS}"
        )
    if result["success"]:
        return result, 0

    consecutive_timeouts += 1
    if on_log:
        on_log(
            "[debug step] "
            f"timeout incremented to {consecutive_timeouts}/{MAX_CONSECUTIVE_STEP_TIMEOUTS}"
        )
    if consecutive_timeouts >= MAX_CONSECUTIVE_STEP_TIMEOUTS:
        raise RuntimeError(
            f"Step safety timeout reached {MAX_CONSECUTIVE_STEP_TIMEOUTS} consecutive times."
        )
    return result, consecutive_timeouts


def measure_bulk_density(
    balance: Balance,
    *,
    disk_id: str | None = None,
    repeats: int | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[float | None, float | None, list[float], bool]:
    settings = _bulk_density_settings()
    strong_vib_level = settings["strong_vib_level"]
    active_disk_id = disk_id or _material_settings()["disk_id"]
    volume = _load_disk_volume(active_disk_id)
    densities: list[float] = []
    success = True
    consecutive_step_timeouts = 0
    disk_number = int(active_disk_id.lstrip("Dd"))
    large_disk = disk_number >= 7
    # Large disk uses a fixed 5 repeats regardless of settings, because the hopper
    # volume is limited and cannot sustain the full configured repeat count.
    effective_repeats = 5 if large_disk else (settings["repeats"] if repeats is None else repeats)
    run_all_motors(vib_level=2, duration_sec=3.0)
    for _ in range(max(1, int(effective_repeats))):
        if large_disk:
            pack_powder(1)
            _, consecutive_step_timeouts = _guarded_step(
                consecutive_step_timeouts,
                on_log=on_log,
            )
            vib_with_aug(strong_vib_level, 1.5)
            balance.tare()
            _, consecutive_step_timeouts = _guarded_step(
                consecutive_step_timeouts,
                on_log=on_log,
            )
            vib_with_aug(strong_vib_level, 1.5)
        else:
            pack_powder(1)
            balance.tare()
            _, consecutive_step_timeouts = _guarded_step(
                consecutive_step_timeouts,
                on_log=on_log,
            )
            vib_with_aug(strong_vib_level, 1.0)
        mass = balance.read_weight()
        if mass < _noise_threshold_g():
            if not clear_clogging(balance):
                success = False
                break
            # Flush one cycle after recovery before recording data.
            if large_disk:
                pack_powder(1)
                _, consecutive_step_timeouts = _guarded_step(
                    consecutive_step_timeouts,
                    on_log=on_log,
                )
                vib_with_aug(strong_vib_level, 1.5)
                balance.tare()
                _, consecutive_step_timeouts = _guarded_step(
                    consecutive_step_timeouts,
                    on_log=on_log,
                )
                vib_with_aug(strong_vib_level, 1.5)
            else:
                pack_powder(1)
                balance.tare()
                _, consecutive_step_timeouts = _guarded_step(
                    consecutive_step_timeouts,
                    on_log=on_log,
                )
                vib_with_aug(strong_vib_level, 1.0)
            mass = balance.read_weight()
            if mass < _noise_threshold_g():
                success = False
                break
        densities.append(mass / volume)
        _, consecutive_step_timeouts = _guarded_step(
            consecutive_step_timeouts,
            on_log=on_log,
        )

    if densities:
        ordered = sorted(densities)
        trimmed = ordered[1:-1] if len(ordered) >= 3 else ordered
        mean_density = statistics.mean(trimmed)
        stdev_density = statistics.pstdev(trimmed) if len(trimmed) > 1 else 0.0
    else:
        mean_density = None
        stdev_density = None

    return mean_density, stdev_density, densities, success

def classify_repose(angle_deg: float) -> str:
    if angle_deg <= 30:
        return "Excellent"
    if angle_deg <= 35:
        return "Good"
    if angle_deg <= 40:
        return "Fair"
    if angle_deg <= 45:
        return "Passable"
    if angle_deg <= 55:
        return "Poor"
    if angle_deg <= 65:
        return "Very poor"
    return "Very, very poor"

def classify_hausner(hausner_ratio: float) -> str:
    if hausner_ratio <= 1.11:
        return "Excellent"
    if hausner_ratio <= 1.18:
        return "Good"
    if hausner_ratio <= 1.25:
        return "Fair"
    if hausner_ratio <= 1.34:
        return "Passable"
    if hausner_ratio <= 1.45:
        return "Poor"
    if hausner_ratio <= 1.59:
        return "Very poor"
    return "Very, very poor"

def measure_tapped_density(
    balance: Balance,
    *,
    disk_id: str | None = None,
    repeats: int | None = None,
    vib_level: int | None = None,
    vib_sec: float | None = None,
) -> tuple[float | None, float | None, list[float], bool]:
    settings = _tapped_density_settings()
    active_disk_id = disk_id or _material_settings()["disk_id"]
    volume = _load_disk_volume(active_disk_id)
    densities: list[float] = []
    success = True
    consecutive_step_timeouts = 0
    vib_level_value = settings["vib_level"] if vib_level is None else vib_level
    vib_sec_value = settings["vib_sec"] if vib_sec is None else vib_sec
    disk_number = int(active_disk_id.lstrip("Dd"))
    large_disk = disk_number >= 7
    # Large disk uses a fixed 5 repeats regardless of settings, because the hopper
    # volume is limited and cannot sustain the full configured repeat count.
    effective_repeats = 5 if large_disk else (settings["repeats"] if repeats is None else repeats)
    run_all_motors(vib_level=2, duration_sec=3.0)
    for _ in range(max(1, int(effective_repeats))):
        pack_powder(vib_level_value)
        balance.tare()
        _, consecutive_step_timeouts = _guarded_step(consecutive_step_timeouts)
        vib_with_aug(vib_level_value, 2.0)
        mass = balance.read_weight()
        if mass < _noise_threshold_g():
            if not clear_clogging(balance):
                success = False
                break
            # Flush one cycle after recovery before recording data.
            pack_powder(vib_level_value)
            balance.tare()
            _, consecutive_step_timeouts = _guarded_step(consecutive_step_timeouts)
            vib_with_aug(vib_level_value, 2.0)
            mass = balance.read_weight()
            if mass < _noise_threshold_g():
                success = False
                break
        densities.append(mass / volume)

    if densities and success:
        ordered = sorted(densities)
        trimmed = ordered[1:-1] if len(ordered) >= 3 else ordered
        mean_density = statistics.mean(trimmed)
        stdev_density = statistics.pstdev(trimmed) if len(trimmed) > 1 else 0.0
    else:
        mean_density = None
        stdev_density = None
    return mean_density, stdev_density, densities, success


def vib_with_aug(vib_level: int = 2, vib_seconds: float = 3.0) -> None:
    """
    Run vibration (L2) and auger simultaneously to help clear a jam.
    """
    vib_thread = threading.Thread(
        target=vib,
        args=(vib_level, vib_seconds),
        daemon=True,
    )
    aug_thread = threading.Thread(
        target=aug,
        args=(vib_seconds,),
        kwargs={"reverse": False},
        daemon=True,
    )
    vib_thread.start()
    aug_thread.start()
    vib_thread.join()
    aug_thread.join()


def pack_powder(vib_level: int, half_rot_sec: float = 0.4) -> None:
    """Compact powder into the disk cavity by oscillating the rotation motor
    forward and backward while running the vibration and auger motors throughout.

    The rotation sequence returns the disk to its original position:
        forward  half_rot_sec
        reverse  half_rot_sec * 2
        forward  half_rot_sec
    Total rotation time: half_rot_sec * 4 + 0.2

    Args:
        vib_level: Vibration intensity (0-5).
        half_rot_sec: Base rotation interval in seconds; all other intervals
                      are multiples of this value.
    """
    direction_switch_pause_sec = 0.1
    total_time = half_rot_sec * 8 + (direction_switch_pause_sec * 2)

    # [TEMP TEST] aug + vib only (rotation motor disabled), fixed 5s
    vib_with_aug(vib_level, 5.0)

    # # Launch vibration and auger in parallel threads so they run for the full
    # # rotation sequence without blocking the main thread.
    # vib_thread = threading.Thread(
    #     target=vib,
    #     args=(vib_level, total_time),
    #     daemon=True,
    # )
    # aug_thread = threading.Thread(
    #     target=aug,
    #     args=(total_time,),
    #     kwargs={"reverse": False},
    #     daemon=True,
    # )
    # vib_thread.start()
    # aug_thread.start()

    # # Rotation oscillation sequence (PWM 150 based on measured step timing).
    # drive_motor("rot", 150, reverse=False)  # forward
    # time.sleep(half_rot_sec)
    # stop_motor("rot")
    # time.sleep(direction_switch_pause_sec)

    # drive_motor("rot", 150, reverse=True)   # reverse
    # time.sleep(half_rot_sec * 2)
    # stop_motor("rot")
    # time.sleep(direction_switch_pause_sec)

    # drive_motor("rot", 150, reverse=False)   # reverse
    # time.sleep(half_rot_sec * 2)
    # stop_motor("rot")
    # time.sleep(direction_switch_pause_sec)

    # drive_motor("rot", 150, reverse=True)   # reverse
    # time.sleep(half_rot_sec * 2)
    # stop_motor("rot")
    # time.sleep(direction_switch_pause_sec)

    # drive_motor("rot", 150, reverse=False)  # forward
    # time.sleep(half_rot_sec)
    # stop_motor("rot")

    # # Wait for vibration and auger to finish.
    # vib_thread.join()
    # aug_thread.join()


def clear_clogging(
    balance: Balance,
    *,
    vib_level: int = 4,
    vib_seconds: float = 3,
) -> bool:
    initial_mass = balance.read_weight()
    max_attempts = 3
    min_delta = _noise_threshold_g() * 10
    for _ in range(max_attempts):
        run_all_motors(vib_level, vib_seconds)
        mass = balance.read_weight()
        if mass >= initial_mass + float(min_delta):
            return True
    return False


def capture_and_analyze_repose(
    *,
    output_dir: Path | str,
    image_name: str = "raw_angle of repose.jpg",
    file_prefix: str = "",
    method: str = "direct_profile",
) -> tuple[Path, dict[str, Any], float]:
    """
    Capture an image, analyze the angle of repose, and save outputs in output_dir.
    """
    run_dir = Path(output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    image_path = run_dir / image_name
    capture_powder_image(output_path=image_path)

    analysis_artifacts, mean_angle = analyze_repose(
        image_path,
        output_dir=run_dir,
        file_prefix=file_prefix,
        method=method,
    )
    return image_path, analysis_artifacts, mean_angle


def _load_disk_volume(disk_id: int | str) -> float:
    disk_key = str(disk_id).strip().upper()
    entry = _disk_master_settings().get(disk_key)
    if entry is not None:
        return float(entry["volume_ml"])
    raise ValueError(
        f"DiskID '{disk_id}' was not found in app settings. Use the 'D06' format (e.g., 'D06')."
    )

def prime_p_dispenser(
    balance: Balance,
    *,
    vib_level: int | None = None,
    vib_sec: float | None = None,
    max_cycles: int | None = None,
    min_delta: float | None = None,
) -> tuple[float, int]:
    vib_level_value = PRIME_DISPENSER_SETTINGS["vib_level"] if vib_level is None else vib_level
    vib_sec_value = PRIME_DISPENSER_SETTINGS["vib_sec"] if vib_sec is None else vib_sec
    max_cycles_value = (
        PRIME_DISPENSER_SETTINGS["max_cycles"] if max_cycles is None else max_cycles
    )
    min_delta_value = PRIME_DISPENSER_SETTINGS["min_delta"] if min_delta is None else min_delta

    initial_mass = balance.read_weight()
    for cycle in range(1, max(1, int(max_cycles_value)) + 1):
        for _ in range(4):
            vib_with_aug(vib_level_value, vib_sec_value)
            step()
        mass = balance.read_weight()
        if mass > initial_mass + float(min_delta_value):
            return balance.tare()
    raise RuntimeError("Mass did not increase before max_cycles reached.")

def measure_series(
    balance: Balance,
    *,
    level: int,
    vib_time: float,
    steps: int,
    noise_threshold_g: float | None = None,
    vib_fn: Callable[[int, float], None] = vib,
    skip_first: bool = False,
) -> Dict[str, Any]:
    """
    Run repeated vib+step+weigh cycles and record per-step mass deltas.
    If skip_first is True, the first measurement result is excluded from
    mean/std/success calculations (but still stored in the raw lists).
    """
    threshold = _noise_threshold_g() if noise_threshold_g is None else float(noise_threshold_g)
    # Pre-loop: vibrate once to clear any residual powder from the previous run, then tare.
    vib_fn(level, vib_time)
    balance.tare()
    cumulative: List[float] = []
    per_step: List[float] = []
    successes: List[bool] = []
    step_stop_reasons: List[str] = []
    last_mass = 0.0
    consecutive_step_timeouts = 0

    for i in range(max(1, int(steps))):
        step_result, consecutive_step_timeouts = _guarded_step(consecutive_step_timeouts)
        step_stop_reasons.append(str(step_result["stop_reason"]))
        vib_fn(level, vib_time)
        mass = balance.read_weight()
        delta = mass - last_mass
        success = delta >= threshold
        cumulative.append(mass)
        per_step.append(delta)
        successes.append(success)
        last_mass = mass

    # For large disks the first result is skipped to avoid the initial settling effect.
    eval_per_step = per_step[1:] if skip_first and len(per_step) > 1 else per_step
    eval_successes = successes[1:] if skip_first and len(successes) > 1 else successes

    mean_step_mass = statistics.mean(eval_per_step) if eval_per_step else 0.0
    std_step_mass = statistics.pstdev(eval_per_step) if len(eval_per_step) > 1 else 0.0
    return {
        "level": level,
        "vib_time": vib_time,
        "cumulative": cumulative,
        "per_step": per_step,
        "successes": successes,
        "step_stop_reasons": step_stop_reasons,
        "success_all": all(eval_successes),
        "mean_step_mass": mean_step_mass,
        "std_step_mass": std_step_mass,
    }


def explore_levels(
    balance: Balance,
    *,
    vib_levels: List[int],
    vib_time: float,
    steps_per_level: int,
    noise_threshold_g: float | None = None,
    vib_fn: Callable[[int, float], None] = vib,
    skip_first: bool = False,
) -> List[Dict[str, Any]]:
    """
    Try vibration levels in order and return all results.
    """
    results: List[Dict[str, Any]] = []
    for level in sorted(vib_levels):
        res = measure_series(
            balance,
            level=level,
            vib_time=vib_time,
            steps=steps_per_level,
            noise_threshold_g=noise_threshold_g,
            vib_fn=vib_fn,
            skip_first=skip_first,
        )
        results.append(res)
    return results


def explore_times(
    balance: Balance,
    *,
    level: int,
    vib_times: List[float],
    steps_per_time: int,
    noise_threshold_g: float | None = None,
    vib_fn: Callable[[int, float], None] = vib,
    skip_first: bool = False,
) -> List[Dict[str, Any]]:

    results: List[Dict[str, Any]] = []
    for vib_time in sorted(vib_times):
        res = measure_series(
            balance,
            level=level,
            vib_time=vib_time,
            steps=steps_per_time,
            noise_threshold_g=noise_threshold_g,
            vib_fn=vib_fn,
            skip_first=skip_first,
        )
        results.append(res)
    return results


def select_optimal_series(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Select optimal series by:
      1) success_all must be True,
      2) filter by cumulative mass within tolerance of min-CV result,
      3) smallest vibration condition (level or vib_time).
    """
    if not results:
        raise ValueError("results must not be empty.")

    def coef_var(res: Dict[str, Any]) -> float:
        mean = res.get("mean_step_mass", 0.0)
        if mean <= 0:
            return float("inf")
        return res.get("std_step_mass", float("inf")) / mean

    eligible = [res for res in results if res.get("success_all")]
    if not eligible:
        raise RuntimeError("No result achieved 100% success.")
    baseline = min(eligible, key=coef_var)
    tolerance = float(baseline.get("mean_step_mass", 0.0))
    baseline_cumulative = (
        float(baseline["cumulative"][-1]) if baseline.get("cumulative") else 0.0
    )
    within_tolerance = []
    for res in eligible:
        cumulative = float(res["cumulative"][-1]) if res.get("cumulative") else 0.0
        if abs(cumulative - baseline_cumulative) <= tolerance:
            within_tolerance.append(res)

    if not within_tolerance:
        within_tolerance = [baseline]

    levels = {res.get("level") for res in within_tolerance}
    times = {res.get("vib_time") for res in within_tolerance}
    if len(levels) > 1 and len(times) == 1:
        return min(within_tolerance, key=lambda res: res.get("level", float("inf")))
    if len(times) > 1 and len(levels) == 1:
        return min(within_tolerance, key=lambda res: res.get("vib_time", float("inf")))
    return min(within_tolerance, key=lambda res: res.get("level", float("inf")))


def run_calibration(
    balance: Balance,
    *,
    vib_levels: List[int],
    vib_time_candidates: List[float],
    steps_per_level: int,
    stability_steps: int,
    noise_threshold_g: float | None = None,
    vib_fn: Callable[[int, float], None] = vib,
) -> Dict[str, Any]:
    """
    Run level exploration -> time exploration -> stability test and return results.
    """
    if not vib_levels:
        raise ValueError("vib_levels must contain at least one level.")
    if not vib_time_candidates:
        raise ValueError("vib_time_candidates must contain at least one candidate.")

    level_results = explore_levels(
        balance,
        vib_levels=vib_levels,
        vib_time=vib_time_candidates[0],
        steps_per_level=steps_per_level,
        noise_threshold_g=noise_threshold_g,
        vib_fn=vib_fn,
    )
    optimal_level = select_optimal_series(level_results)

    time_results = explore_times(
        balance,
        level=optimal_level["level"],
        vib_times=vib_time_candidates,
        steps_per_time=steps_per_level,
        noise_threshold_g=noise_threshold_g,
        vib_fn=vib_fn,
    )
    best_time = select_optimal_series(time_results)

    # Stability test: longer sequence at the selected level/time.
    stability_result = measure_series(
        balance,
        level=best_time["level"],
        vib_time=best_time["vib_time"],
        steps=stability_steps,
        noise_threshold_g=noise_threshold_g,
        vib_fn=vib_fn,
    )

    return {
        "level_results": level_results,
        "optimal_level": optimal_level,
        "time_results": time_results,
        "best_time": best_time,
        "stability_result": stability_result,
    }

__all__ = [
    "measure_bulk_density",
    "measure_tapped_density",
    "vib_with_aug",
    "clear_clogging",
    "classify_repose",
    "classify_hausner",
    "capture_and_analyze_repose",
    "_load_disk_volume",
    "prime_p_dispenser",
    "measure_series",
    "explore_levels",
    "explore_times",
    "select_optimal_series",
    "run_calibration",
]
