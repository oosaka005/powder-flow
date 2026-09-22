"""Hardware boundaries used by the powder-flow application layer.

The measurement code depends on these protocols only.  Concrete implementations
may be the legacy in-process Raspberry Pi drivers, SiLA 2 clients, or test fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypedDict


class StepResult(TypedDict):
    success: bool
    stop_reason: str
    elapsed_sec: float


class PowderDispenserInterface(Protocol):
    def index_chamber(
        self,
        pwm_0_255: int = 255,
        max_seconds: float = 0.65,
        reverse: bool = False,
    ) -> StepResult: ...

    def vibrate(self, level: int, duration_sec: float) -> None: ...

    def vibrate_with_auger(self, level: int, duration_sec: float) -> None: ...

    def run_all_motors(self, vib_level: int, duration_sec: float) -> StepResult: ...

    def stop_all(self) -> None: ...

    def close(self) -> None: ...


class BalanceInterface(Protocol):
    def read_weight(self) -> float: ...

    def read_weight_immediate(self) -> float: ...

    def tare(self) -> None: ...

    def disconnect(self) -> None: ...


class CameraInterface(Protocol):
    def capture_image(
        self,
        output_path: Path | str,
        *,
        rotation: int = 180,
        autofocus_mode: str | None = None,
        lens_position: float | None = None,
    ) -> None: ...

    def capture_powder_image(self, output_path: Path | str) -> None: ...


@dataclass(frozen=True)
class DeviceBundle:
    powder_dispenser: PowderDispenserInterface
    balance: BalanceInterface
    camera: CameraInterface
