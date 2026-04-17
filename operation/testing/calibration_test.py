from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware_api.balance.balance_api import Balance
from hardware_api.powder_dispenser.p_dispenser_api import cleanup_motors
from operation.powder_flow_api import (
    explore_levels,
    explore_times,
    measure_series,
    prime_p_dispenser,
    select_optimal_series,
)
from operation.powder_flow_io import (
    plot_level_exploration,
    plot_stability,
    plot_time_exploration,
    save_calibration_config,
    save_series_csv,
)

# TODO: Update these before running.
VIB_LEVELS = [5, 4, 3, 2, 1]
VIB_TIME_CANDIDATES = [1.0]
STEPS_PER_LEVEL = 5
STABILITY_STEPS = 8
NOISE_THRESHOLD_G = 0.003

# For config output (P_calibration.csv compatible).
DISPENSER_ID = "powder_dispenser"
MAT_NAME = "sample_material"
DISK_ID = "D06"


def main() -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("logs/test") / f"calibration_{timestamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    balance = Balance()
    try:
        prime_p_dispenser(balance)
        vib_time = VIB_TIME_CANDIDATES[0]
        level_results = explore_levels(
            balance,
            vib_levels=VIB_LEVELS,
            vib_time=vib_time,
            steps_per_level=STEPS_PER_LEVEL,
            noise_threshold_g=NOISE_THRESHOLD_G,
        )
        optimal_level = select_optimal_series(level_results)

        time_results = None
        if len(VIB_TIME_CANDIDATES) > 1:
            time_results = explore_times(
                balance,
                level=optimal_level["level"],
                vib_times=VIB_TIME_CANDIDATES,
                steps_per_time=STEPS_PER_LEVEL,
                noise_threshold_g=NOISE_THRESHOLD_G,
            )
            best_time = select_optimal_series(time_results)
            vib_time = best_time["vib_time"]

        # Stability test: longer sequence at the selected level/time.
        stability_result = measure_series(
            balance,
            level=optimal_level["level"],
            vib_time=vib_time,
            steps=STABILITY_STEPS,
            noise_threshold_g=NOISE_THRESHOLD_G,
        )

        save_series_csv(out_dir / "level_exploration.csv", level_results)
        save_series_csv(out_dir / "stability_test.csv", [stability_result])
        if time_results:
            save_series_csv(out_dir / "vib_time_exploration.csv", time_results)

        try:
            plot_level_exploration(
                level_results, optimal_level, out_dir / "level_exploration.png"
            )
            if time_results:
                best_time = select_optimal_series(time_results)
                plot_time_exploration(
                    time_results, best_time, out_dir / "vib_time_exploration.png"
                )
            plot_stability(stability_result, out_dir / "stability_test.png")
        except RuntimeError as exc:
            print(f"[calibration] Plotting skipped: {exc}")

        calib_row = {
            "dispenserID": DISPENSER_ID,
            "mat_name": MAT_NAME,
            "diskID": DISK_ID,
            "calibration_date": timestamp,
            "vib_level": optimal_level["level"],
            "vib_time": vib_time,
            "step_mass_mean": f"{stability_result['mean_step_mass']:.6f}",
            "density_g_per_ml": "",
        }
        save_calibration_config(calib_row)
    finally:
        balance.disconnect()
        cleanup_motors()

    print(f"[calibration] Results saved to {out_dir}")


if __name__ == "__main__":
    main()
