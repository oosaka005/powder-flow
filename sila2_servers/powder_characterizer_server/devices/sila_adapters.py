"""Adapters from first-layer SiLA 2 features to powder-flow interfaces."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import threading
from typing import Any

from sila2.client import SilaClient

from operation.device_interfaces import StepResult


@dataclass(frozen=True)
class DeviceEndpoints:
    dispenser_host: str = "127.0.0.1"
    dispenser_port: int = 50063
    balance_host: str = "127.0.0.1"
    balance_port: int = 50052
    camera_host: str = "127.0.0.1"
    camera_port: int = 50064
    insecure: bool = True

    @classmethod
    def from_environment(cls) -> "DeviceEndpoints":
        insecure = os.getenv("SILA_INSECURE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        return cls(
            dispenser_host=os.getenv("POWDER_DISPENSER_SILA_HOST", "127.0.0.1"),
            dispenser_port=int(os.getenv("POWDER_DISPENSER_SILA_PORT", "50063")),
            balance_host=os.getenv("BALANCE_SILA_HOST", "127.0.0.1"),
            balance_port=int(os.getenv("BALANCE_SILA_PORT", "50052")),
            camera_host=os.getenv("POWDER_CAMERA_SILA_HOST", "127.0.0.1"),
            camera_port=int(os.getenv("POWDER_CAMERA_SILA_PORT", "50064")),
            insecure=insecure,
        )


def _step_result(value: Any) -> StepResult:
    return {
        "success": bool(value.Success),
        "stop_reason": str(value.StopReason),
        "elapsed_sec": float(value.ElapsedSec),
    }


class PowderDispenserSilaAdapter:
    def __init__(self, client: SilaClient) -> None:
        self._client = client
        self._feature = client.PowderCharacterizerDispenser
        # One adapter is created per high-level operation. Once Abort has sent
        # StopAll, no later step in that same workflow may restart a motor.
        self._stopped = threading.Event()

    def _ensure_active(self) -> None:
        if self._stopped.is_set():
            raise RuntimeError("Dispenser operation was stopped.")

    def index_chamber(
        self,
        pwm_0_255: int = 255,
        max_seconds: float = 0.65,
        reverse: bool = False,
    ) -> StepResult:
        self._ensure_active()
        response = self._feature.IndexChamber(
            Pwm=pwm_0_255,
            MaxSeconds=max_seconds,
            Reverse=reverse,
        )
        return _step_result(response.Result)

    def vibrate(self, level: int, duration_sec: float) -> None:
        self._ensure_active()
        self._feature.Vibrate(Level=level, DurationSec=duration_sec)

    def vibrate_with_auger(self, level: int, duration_sec: float) -> None:
        self._ensure_active()
        self._feature.VibrateWithAuger(Level=level, DurationSec=duration_sec)

    def run_all_motors(self, vib_level: int, duration_sec: float) -> StepResult:
        self._ensure_active()
        response = self._feature.RunAllMotors(Level=vib_level, DurationSec=duration_sec)
        return _step_result(response.Result)

    def stop_all(self) -> None:
        self._stopped.set()
        self._feature.StopAll()

    def close(self) -> None:
        # Never call the remote Close for a normal experiment.
        self._client.close()

    @property
    def status(self) -> str:
        return str(self._feature.Status.get())


class BalanceSilaAdapter:
    """Adapt the existing Balance Server without using its Close command."""

    def __init__(self, client: SilaClient) -> None:
        self._client = client
        self._feature = client.Balance

    def read_weight(self) -> float:
        return float(self._feature.ReadWeight().Weight)

    def read_weight_immediate(self) -> float:
        return float(self._feature.ReadWeightImmediate().Weight)

    def tare(self) -> None:
        self._feature.Tare()

    def disconnect(self) -> None:
        # Intentionally close only the gRPC channel. Balance.Close would make
        # the existing serial server unusable for the next experiment.
        self._client.close()

    @property
    def status(self) -> str:
        return str(self._feature.Status.get())


class CameraSilaAdapter:
    def __init__(self, client: SilaClient) -> None:
        self._client = client
        self._feature = client.PowderCharacterizerCamera

    def capture_image(
        self,
        output_path: Path | str,
        *,
        rotation: int = 180,
        autofocus_mode: str | None = None,
        lens_position: float | None = None,
    ) -> None:
        mode = autofocus_mode or "auto"
        response = self._feature.Capture(
            Rotation=rotation,
            AutofocusMode=mode,
            LensPosition=float(lens_position or 0.0),
        )
        Path(output_path).write_bytes(bytes(response.ImageData))

    def capture_powder_image(self, output_path: Path | str) -> None:
        response = self._feature.CaptureRepose()
        Path(output_path).write_bytes(bytes(response.ImageData))

    def close(self) -> None:
        self._client.close()

    @property
    def status(self) -> str:
        return str(self._feature.Status.get())


@dataclass
class RemoteDeviceBundle:
    powder_dispenser: PowderDispenserSilaAdapter
    balance: BalanceSilaAdapter
    camera: CameraSilaAdapter

    def close(self) -> None:
        # Balance may already have closed its client in workflow cleanup.
        for adapter in (self.powder_dispenser, self.balance, self.camera):
            try:
                if adapter is self.balance:
                    adapter.disconnect()
                else:
                    adapter.close()
            except Exception:
                pass


class SilaDeviceFactory:
    def __init__(self, endpoints: DeviceEndpoints | None = None) -> None:
        self.endpoints = endpoints or DeviceEndpoints.from_environment()

    def create(self) -> RemoteDeviceBundle:
        dispenser = self.create_dispenser()
        balance = None
        try:
            balance = self.create_balance()
            camera = self.create_camera()
        except Exception:
            dispenser.close()
            if balance is not None:
                balance.disconnect()
            raise
        return RemoteDeviceBundle(
            powder_dispenser=dispenser,
            balance=balance,
            camera=camera,
        )

    def create_dispenser(self) -> PowderDispenserSilaAdapter:
        e = self.endpoints
        return PowderDispenserSilaAdapter(
            SilaClient(e.dispenser_host, e.dispenser_port, insecure=e.insecure)
        )

    def create_balance(self) -> BalanceSilaAdapter:
        e = self.endpoints
        return BalanceSilaAdapter(
            SilaClient(e.balance_host, e.balance_port, insecure=e.insecure)
        )

    def create_camera(self) -> CameraSilaAdapter:
        e = self.endpoints
        return CameraSilaAdapter(
            SilaClient(e.camera_host, e.camera_port, insecure=e.insecure)
        )
