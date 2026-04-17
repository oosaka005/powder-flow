from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hardware_api.powder_dispenser.p_dispenser_HAT_api import (
    cleanup_motors,
    run_all_motors,
)


def main() -> None:
    print("[test] run_all_motors starting (level=1, duration=3s).")
    try:
        run_all_motors(1, 3.0)
    finally:
        cleanup_motors()
    print("[test] run_all_motors complete.")


if __name__ == "__main__":
    main()
