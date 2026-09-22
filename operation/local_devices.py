"""Legacy in-process adapters retained for the desktop UI.

Production Web UI operation does not use these adapters.  It reaches hardware
through the two SiLA 2 layers instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from operation.device_interfaces import StepResult


class LocalPowderDispenserAdapter:
    @staticmethod
    def _api():
        from hardware_api.powder_dispenser import p_dispenser_HAT_api

        return p_dispenser_HAT_api

    def index_chamber(
        self,
        pwm_0_255: int = 255,
        max_seconds: float = 0.65,
        reverse: bool = False,
    ) -> StepResult:
        return self._api().step(
            pwm_0_255=pwm_0_255,
            max_seconds=max_seconds,
            reverse=reverse,
        )

    def vibrate(self, level: int, duration_sec: float) -> None:
        self._api().vib(level, duration_sec)

    def vibrate_with_auger(self, level: int, duration_sec: float) -> None:
        # Use one driver operation boundary while preserving the old forward
        # auger direction and simultaneous motor timing.
        import threading

        api = self._api()
        vib_thread = threading.Thread(target=api.vib, args=(level, duration_sec), daemon=True)
        aug_thread = threading.Thread(
            target=api.aug,
            args=(duration_sec,),
            kwargs={"reverse": False},
            daemon=True,
        )
        vib_thread.start()
        aug_thread.start()
        vib_thread.join()
        aug_thread.join()

    def run_all_motors(self, vib_level: int, duration_sec: float) -> StepResult:
        return self._api().run_all_motors(vib_level, duration_sec)

    def stop_all(self) -> None:
        api = self._api()
        for motor_name in ("rot", "vib", "aug"):
            try:
                api.stop_motor(motor_name)
            except Exception:
                pass

    def close(self) -> None:
        self._api().cleanup_motors()


class LocalBalanceAdapter:
    def __init__(self) -> None:
        from hardware_api.balance.balance_api import Balance

        self._balance = Balance()

    def read_weight(self) -> float:
        return float(self._balance.read_weight())

    def read_weight_immediate(self) -> float:
        return float(self._balance.read_weight(settle_time=0.0))

    def tare(self) -> None:
        self._balance.tare()

    def disconnect(self) -> None:
        self._balance.disconnect()


class LocalCameraAdapter:
    def capture_image(
        self,
        output_path: Path | str,
        *,
        rotation: int = 180,
        autofocus_mode: str | None = None,
        lens_position: float | None = None,
    ) -> None:
        from hardware_api.camera.camera_api import capture_image

        capture_image(
            output_path,
            rotation=rotation,
            autofocus_mode=autofocus_mode,
            lens_position=lens_position,
        )

    def capture_powder_image(self, output_path: Path | str) -> None:
        from hardware_api.camera.camera_api import capture_powder_image

        capture_powder_image(output_path)


def create_local_dispenser() -> LocalPowderDispenserAdapter:
    return LocalPowderDispenserAdapter()


def create_local_balance() -> LocalBalanceAdapter:
    return LocalBalanceAdapter()


def create_local_camera() -> LocalCameraAdapter:
    return LocalCameraAdapter()
