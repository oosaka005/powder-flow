from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware_api.balance.balance_api import Balance
from hardware_api.powder_dispenser.p_dispenser_HAT_api import cleanup_motors
from operation.powder_flow_api import measure_bulk_density, measure_tapped_density


def main() -> None:
    print("[hausner] Measurement starting.")
    balance = Balance()
    try:
        mean_bulk, stdev_bulk, densities, success = measure_bulk_density(balance)
        print(f"[bulk] success={success}")
        for idx, density in enumerate(densities, 1):
            print(f"[bulk] sample_{idx}={density}")
        print(f"[bulk] mean={mean_bulk}")
        print(f"[bulk] stdev={stdev_bulk}")

        mean_tapped, stdev_tapped, densities_tapped, success_tapped = (
            measure_tapped_density(balance)
        )
        print(f"[tapped] success={success_tapped}")
        for idx, density in enumerate(densities_tapped, 1):
            print(f"[tapped] sample_{idx}={density}")
        print(f"[tapped] mean={mean_tapped}")
        print(f"[tapped] stdev={stdev_tapped}")

        hausner_ratio = (
            mean_tapped / mean_bulk
            if mean_bulk is not None and mean_tapped is not None and mean_bulk
            else None
        )
        print(f"[hausner] ratio={hausner_ratio}")
    finally:
        balance.disconnect()
        cleanup_motors()
    print("[hausner] Measurement complete.")


if __name__ == "__main__":
    main()
