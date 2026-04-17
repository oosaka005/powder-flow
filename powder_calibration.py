from __future__ import annotations
import sys
import time
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import numpy as np
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from drivers.powder_dispenser.p_dispenser_api import PowderDispenser
from drivers.balance.balance_api import Balance
from operation.p_dispenser_ops import p_dispense_mass
from service.settings_store import load_settings
from utils.config_loader import load_equipment_config

# ---------------- User-configurable parameters ----------------
VIB_LEVELS: List[int] = [3, 2, 1]      # vibration strengths to try (in order)
VIB_TIME_CANDIDATES: List[float] = [1.0, 2.0]  # seconds, tried in order at the best level
STEPS_PER_LEVEL: int = 10                    # repeats for each level and each time candidate
STABILITY_STEPS: int = 20                    # repeats for final stability test
NOISE_THRESHOLD_G: float = 0.003             # minimum detectable mass per step
MAT_NAME: str = "CB-A100S"          # material name stored in calibration CSV
DISK_ID: str = "D02"                         # disk ID from app settings disk_master
DISPENSER_ID: Optional[str] = None           # set to specific dispenser ID; None uses first in config
BALANCE_ID: Optional[str] = "balance1"             # set to specific balance ID; None uses first in config
DISPENSER_DEBUG: bool = True                # set True to print device responses during calibration
# ----------------------------------------------------------------


@dataclass
class SeriesResult:
    level: int
    vib_time: float
    cumulative: List[float]
    per_step: List[float]
    successes: List[bool]

    @property
    def success_all(self) -> bool:
        return all(self.successes)

    @property
    def mean_step_mass(self) -> float:
        return float(np.mean(self.per_step)) if self.per_step else 0.0

    @property
    def std_step_mass(self) -> float:
        return float(np.std(self.per_step)) if self.per_step else 0.0


def measure_series(dispenser: PowderDispenser, balance: Balance, level: int, vib_time: float,
                   steps: int, noise_threshold_g: float) -> SeriesResult:
    balance.tare()
    cumulative: List[float] = []
    per_step: List[float] = []
    successes: List[bool] = []
    last_mass = 0.0

    for i in range(steps):
        mass = p_dispense_mass(dispenser, balance, level=level, vib_seconds=vib_time, tare_before=False)
        delta = mass - last_mass
        success = delta >= noise_threshold_g
        cumulative.append(mass)
        per_step.append(delta)
        successes.append(success)
        last_mass = mass
        print(f"[SERIES] step {i+1}/{steps} @level {level}, {vib_time:.2f}s -> delta {delta:.6f} g ({'OK' if success else 'FAIL'})")

    return SeriesResult(level=level, vib_time=vib_time, cumulative=cumulative, per_step=per_step, successes=successes)


def save_series_csv(path: Path, series: List[SeriesResult]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["condition", "step_index", "cumulative_mass_g", "per_step_mass_g", "success"])
        for s in series:
            label = f"level{ s.level }_t{ s.vib_time }"
            for idx, (cum, step, ok) in enumerate(zip(s.cumulative, s.per_step, s.successes), 1):
                writer.writerow([label, idx, f"{cum:.6f}", f"{step:.6f}", ok])


def plot_level_exploration(series: List[SeriesResult], optimal: SeriesResult, out_path: Path) -> None:
    plt.figure(figsize=(10, 6))
    max_steps = max(len(s.cumulative) for s in series)
    # Non-optimal lines: grayscale that fades as level decreases (earlier levels darker)
    non_optimal = [s for s in series if s is not optimal]
    shades = np.linspace(0.2, 0.8, num=len(non_optimal)) if non_optimal else []
    for idx, s in enumerate(non_optimal):
        color = str(shades[idx])  # grayscale
        plt.plot(
            range(1, len(s.cumulative) + 1),
            s.cumulative,
            label=f"L{s.level}",
            color=color,
            linewidth=1.8,
            marker="o",
            markersize=4,
        )
    # Optimal line: emphasize in red and thicker
    plt.plot(
        range(1, len(optimal.cumulative) + 1),
        optimal.cumulative,
        label=f"L{optimal.level} (optimal)",
        color="red",
        linewidth=2.8,
        marker="o",
        markersize=5,
    )
    plt.xlabel("Step #")
    plt.ylabel("Cumulative mass [g]")
    plt.title("Powder calibration - level exploration")
    plt.xticks(range(1, max_steps + 1))
    plt.grid(True, alpha=0.3)
    plt.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()

def plot_time_exploration(series: List[SeriesResult], optimal_time: SeriesResult, out_path: Path) -> None:
    plt.figure(figsize=(10, 6))
    max_steps = max(len(s.cumulative) for s in series)
    non_optimal = [s for s in series if s is not optimal_time]
    shades = np.linspace(0.2, 0.8, num=len(non_optimal)) if non_optimal else []
    for idx, s in enumerate(non_optimal):
        color = str(shades[idx])
        plt.plot(
            range(1, len(s.cumulative) + 1),
            s.cumulative,
            label=f"{s.vib_time:.2f}s",
            color=color,
            linewidth=1.8,
            marker="o",
            markersize=4,
        )
    plt.plot(
        range(1, len(optimal_time.cumulative) + 1),
        optimal_time.cumulative,
        label=f"{optimal_time.vib_time:.2f}s (optimal)",
        color="red",
        linewidth=2.8,
        marker="o",
        markersize=5,
    )
    plt.xlabel("Step #")
    plt.ylabel("Cumulative mass [g]")
    plt.title(f"Powder calibration - time exploration (level {optimal_time.level})")
    plt.xticks(range(1, max_steps + 1))
    plt.grid(True, alpha=0.3)
    plt.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


def plot_stability(series: SeriesResult, out_path: Path) -> None:
    plt.figure(figsize=(10, 6))
    steps = range(1, len(series.per_step) + 1)
    plt.plot(steps, series.per_step, marker="o", linestyle="-", label="Per-step mass")
    mean = series.mean_step_mass
    plt.axhline(mean, color="red", linestyle="--", label=f"Mean={mean:.6f}g")
    plt.xlabel("Step #")
    plt.ylabel("Per-step mass [g]")
    plt.title(f"Powder calibration - stability test (level {series.level}, time {series.vib_time:.2f}s)")
    plt.xticks(range(1, len(series.per_step) + 1))
    plt.grid(True, alpha=0.3)
    plt.legend()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close()


def save_powder_config(calib: Dict) -> None:
    config_path = ROOT / "config" / "P_calibration.csv"
    headers = [
        "dispenserID",
        "mat_name",
        "diskID",
        "calibration_date",
        "vib_level",
        "vib_time",
        "step_mass_mean",
        "density_g_per_ml",
    ]
    rows: List[Dict] = []
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    updated = False
    for i, r in enumerate(rows):
        if (
            r["dispenserID"] == calib["dispenserID"]
            and r["mat_name"] == calib["mat_name"]
            and r["diskID"] == calib["diskID"]
        ):
            rows[i] = calib
            updated = True
            break
    if not updated:
        rows.append(calib)
    with open(config_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[CONFIG] Updated {config_path}")


def _load_disk_volume_from_settings(disk_id: str) -> float:
    settings = load_settings(ROOT / "config" / "app_settings.json")
    disk_master = settings.get("disk_master", {})
    entry = disk_master.get(str(disk_id).strip().upper())
    if not entry:
        raise RuntimeError(f"DiskID {disk_id} not found in app_settings.json disk_master")
    return float(entry["volume_ml"])


def run_calibration(
    dispenser_port: str,
    balance_port: str,
    dispenser_id: str,
    disk_id: str,
    mat_name: str,
    vib_levels: List[int],
    vib_time_candidates: List[float],
    steps_per_level: int,
    stability_steps: int,
    noise_threshold_g: float,
) -> None:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    folder = ROOT / "logs" / "calibration" / "powder" / f"{mat_name}_{dispenser_id}_{timestamp}"
    folder.mkdir(parents=True, exist_ok=True)

    dispenser = PowderDispenser(port=dispenser_port, debug=DISPENSER_DEBUG)
    balance = Balance(balance_port, balance_id="powder_calibration_balance")
    dispenser.open()
    try:
        level_results: List[SeriesResult] = []
        optimal: Optional[SeriesResult] = None
        print(f"[STAGE] Level exploration: levels={vib_levels}, steps_per_level={steps_per_level}")
        for lvl in vib_levels:
            res = measure_series(
                dispenser,
                balance,
                level=lvl,
                vib_time=vib_time_candidates[0],  # use first candidate during level exploration
                steps=steps_per_level,
                noise_threshold_g=noise_threshold_g,
            )
            level_results.append(res)
            if res.success_all:
                optimal = res
            else:
                if optimal:
                    break
        if optimal is None:
            raise RuntimeError("No vibration level achieved 100% success.")

        save_series_csv(folder / "level_exploration.csv", level_results)
        plot_level_exploration(level_results, optimal, folder / "level_exploration.png")

        # Time exploration: reuse the time used in level exploration (first candidate),
        # then test only the remaining time candidates.
        time_results: List[SeriesResult] = [optimal]  # includes initial time (first candidate)
        best_time_result: SeriesResult = optimal
        remaining_times = vib_time_candidates[1:] if len(vib_time_candidates) > 1 else []
        print(f"[STAGE] Time exploration at level {optimal.level}: times={remaining_times or ['(none)']}, steps_per_time={steps_per_level}")
        for t in remaining_times:
            res = measure_series(dispenser, balance, level=optimal.level, vib_time=t, steps=steps_per_level, noise_threshold_g=noise_threshold_g)
            time_results.append(res)
            if res.success_all and best_time_result is optimal:
                # record the first fully successful time, but continue testing remaining candidates
                best_time_result = res
        save_series_csv(folder / "vib_time_exploration.csv", time_results)
        plot_time_exploration(time_results, best_time_result, folder / "vib_time_exploration.png")

        print(f"[STAGE] Stability test at level {best_time_result.level}, time {best_time_result.vib_time}: steps={stability_steps}")
        stability_result = measure_series(
            dispenser, balance, level=best_time_result.level, vib_time=best_time_result.vib_time,
            steps=stability_steps, noise_threshold_g=noise_threshold_g
        )
        save_series_csv(folder / "stability_test.csv", [stability_result])
        plot_stability(stability_result, folder / "stability_test.png")

        disk_vol = _load_disk_volume_from_settings(disk_id)
        mean_step = stability_result.mean_step_mass
        std_step = stability_result.std_step_mass
        density = mean_step / disk_vol if disk_vol > 0 else 0.0

        calib_row = {
            "dispenserID": dispenser_id,
            "mat_name": mat_name,
            "diskID": disk_id,
            "calibration_date": timestamp,
            "vib_level": best_time_result.level,
            "vib_time": best_time_result.vib_time,
            "step_mass_mean": f"{mean_step:.6f}",
            "density_g_per_ml": f"{density:.6f}",
        }
        save_powder_config(calib_row)

        print(f"[DONE] Logs saved to {folder}")

    finally:
        dispenser.close()
        balance.disconnect()


def main():
    cfg = load_equipment_config()

    # Resolve powder dispenser port
    pd_cfgs = cfg.get("powder dispenser", {})
    if not pd_cfgs:
        raise RuntimeError("No 'powder dispenser' entry in equipment_config.yaml")
    if "main_connection" in pd_cfgs and isinstance(pd_cfgs["main_connection"], dict):
        pd_conn = pd_cfgs["main_connection"]
        dispenser_id = DISPENSER_ID or "powder_dispenser"
    else:
        if DISPENSER_ID:
            pd_entry = pd_cfgs.get(DISPENSER_ID)
            if not pd_entry:
                raise RuntimeError(f"Dispenser '{DISPENSER_ID}' not found in equipment_config.yaml")
            dispenser_id = DISPENSER_ID
        else:
            dispenser_id, pd_entry = next(iter(pd_cfgs.items()))
        pd_conn = pd_entry.get("main_connection") or pd_entry.get("connection") or {}
    dispenser_port = pd_conn.get("serial_port")
    if not dispenser_port:
        raise RuntimeError(f"serial_port not configured for dispenser '{dispenser_id}'")

    # Resolve balance port
    bal_cfgs = cfg.get("balance", {})
    if not bal_cfgs:
        raise RuntimeError("No 'balance' entry in equipment_config.yaml")
    if BALANCE_ID:
        bal_entry = bal_cfgs.get(BALANCE_ID)
        if not bal_entry:
            raise RuntimeError(f"Balance '{BALANCE_ID}' not found in equipment_config.yaml")
        balance_id = BALANCE_ID
    else:
        balance_id, bal_entry = next(iter(bal_cfgs.items()))
    bal_conn = bal_entry.get("connection") or {}
    balance_port = bal_conn.get("serial_port")
    if not balance_port:
        raise RuntimeError(f"serial_port not configured for balance '{balance_id}'")

    print(f"[CONFIG] Dispenser '{dispenser_id}' on {dispenser_port}")
    print(f"[CONFIG] Balance '{balance_id}' on {balance_port}")
    print(f"[CONFIG] Levels={VIB_LEVELS}, Times={VIB_TIME_CANDIDATES}, Steps/level={STEPS_PER_LEVEL}, Stability_steps={STABILITY_STEPS}")

    run_calibration(
        dispenser_port=dispenser_port,
        balance_port=balance_port,
        dispenser_id=dispenser_id,
        disk_id=DISK_ID,
        mat_name=MAT_NAME,
        vib_levels=VIB_LEVELS,
        vib_time_candidates=VIB_TIME_CANDIDATES,
        steps_per_level=STEPS_PER_LEVEL,
        stability_steps=STABILITY_STEPS,
        noise_threshold_g=NOISE_THRESHOLD_G,
    )


if __name__ == "__main__":
    main()
