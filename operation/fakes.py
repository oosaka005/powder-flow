"""Deterministic fake devices for regression tests and development."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Iterable

from operation.device_interfaces import StepResult


class FakePowderDispenser:
    def __init__(self, step_results: Iterable[StepResult] | None = None) -> None:
        self.calls: list[tuple] = []
        self._step_results = deque(step_results or [])
        self.stopped = False

    def index_chamber(
        self,
        pwm_0_255: int = 255,
        max_seconds: float = 0.65,
        reverse: bool = False,
    ) -> StepResult:
        self.calls.append(("index_chamber", pwm_0_255, max_seconds, reverse))
        if self._step_results:
            return self._step_results.popleft()
        return {"success": True, "stop_reason": "sensor", "elapsed_sec": 0.1}

    def vibrate(self, level: int, duration_sec: float) -> None:
        self.calls.append(("vibrate", level, duration_sec))

    def vibrate_with_auger(self, level: int, duration_sec: float) -> None:
        self.calls.append(("vibrate_with_auger", level, duration_sec))

    def run_all_motors(self, vib_level: int, duration_sec: float) -> StepResult:
        self.calls.append(("run_all_motors", vib_level, duration_sec))
        return {"success": True, "stop_reason": "sensor", "elapsed_sec": duration_sec}

    def stop_all(self) -> None:
        self.calls.append(("stop_all",))
        self.stopped = True

    def close(self) -> None:
        self.calls.append(("close",))
        self.stopped = True


class FakeBalance:
    def __init__(self, weights: Iterable[float] | None = None) -> None:
        self.calls: list[tuple] = []
        self._weights = deque(weights or [0.1])
        self._last = 0.0
        self.disconnected = False

    def _read(self, name: str) -> float:
        self.calls.append((name,))
        if self._weights:
            self._last = float(self._weights.popleft())
        return self._last

    def read_weight(self) -> float:
        return self._read("read_weight")

    def read_weight_immediate(self) -> float:
        return self._read("read_weight_immediate")

    def tare(self) -> None:
        self.calls.append(("tare",))

    def disconnect(self) -> None:
        self.calls.append(("disconnect",))
        self.disconnected = True


class FakeCamera:
    # A minimal valid JPEG marker stream is sufficient for transport tests.
    JPEG_BYTES = b"\xff\xd8\xff\xd9"

    def __init__(self, image_bytes: bytes | None = None) -> None:
        self.calls: list[tuple] = []
        self.image_bytes = image_bytes or self.JPEG_BYTES

    def capture_image(
        self,
        output_path: Path | str,
        *,
        rotation: int = 180,
        autofocus_mode: str | None = None,
        lens_position: float | None = None,
    ) -> None:
        self.calls.append(("capture_image", rotation, autofocus_mode, lens_position))
        Path(output_path).write_bytes(self.image_bytes)

    def capture_powder_image(self, output_path: Path | str) -> None:
        self.calls.append(("capture_powder_image",))
        Path(output_path).write_bytes(self.image_bytes)
