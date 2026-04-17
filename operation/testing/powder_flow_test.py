from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware_api.balance.balance_api import Balance
from hardware_api.powder_dispenser.p_dispenser_api import cleanup_motors
from hardware_api.camera.camera_api import capture_image
from operation.powder_flow_api import (
    _load_disk_volume,
    measure_bulk_density,
    measure_tapped_density,
)
from service.settings_store import load_settings

# TODO: Update this before running the test.
MATERIAL_NAME = "sample_material"


def wait_for_enter(message: str) -> None:
    input(f"{message}\nPress Enter to continue...")


def main() -> None:
    print("Powder-flow API check starting.")
    balance = Balance()
    settings = load_settings()
    disk_id = settings["material"]["disk_id"]
    date_str = datetime.now().strftime("%Y%m%d")
    timestamp = datetime.now().strftime("%H%M%S")
    run_dir = Path("logs/test") / date_str / MATERIAL_NAME
    run_dir.mkdir(parents=True, exist_ok=True)
    summary_lines: list[str] = []

    try:
        wait_for_enter("[bulk] Ensure disk is set and balance is ready.")
        mean_bulk, stdev_bulk, samples_bulk = measure_bulk_density(balance)
        bulk_volume = _load_disk_volume(disk_id)
        bulk_masses = [density * bulk_volume for density in samples_bulk]

        wait_for_enter("[tapped] Ensure setup is ready for tapped density.")
        mean_tapped, stdev_tapped, samples_tapped = measure_tapped_density(balance)
        tapped_volume = _load_disk_volume(disk_id)
        tapped_masses = [density * tapped_volume for density in samples_tapped]
        hausner_ratio = mean_tapped / mean_bulk if mean_bulk else float("inf")

        wait_for_enter("[repose] Ensure camera is ready.")
        image_path = run_dir / f"repose_{timestamp}.jpg"
        capture_image(image_path)
        summary_lines.extend(
            [
                f"[bulk] mean={mean_bulk:.6f}, stdev={stdev_bulk:.6f}",
                f"[bulk] masses={bulk_masses}",
                f"[tapped] mean={mean_tapped:.6f}, stdev={stdev_tapped:.6f}",
                f"[tapped] masses={tapped_masses}",
                f"[hausner] ratio={hausner_ratio:.6f}",
                f"[repose] image={image_path}",
            ]
        )
    finally:
        balance.disconnect()
        cleanup_motors()

    for line in summary_lines:
        print(line)
    print("Powder-flow API check complete.")


if __name__ == "__main__":
    main()
