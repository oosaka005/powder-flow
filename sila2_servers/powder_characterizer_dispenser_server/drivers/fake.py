from __future__ import annotations


class FakePowderCharacterizerDispenser:
    """No-sleep first-layer fake for browser and SiLA integration testing."""

    status = "ready"

    def index_chamber(self, pwm_0_255=255, max_seconds=0.65, reverse=False):
        return {"success": True, "stop_reason": "sensor", "elapsed_sec": 0.1}

    def vibrate(self, level: int, duration_sec: float) -> None:
        return None

    def vibrate_with_auger(self, level: int, duration_sec: float) -> None:
        return None

    def run_all_motors(self, vib_level: int, duration_sec: float):
        return {"success": True, "stop_reason": "sensor", "elapsed_sec": 0.1}

    def stop_all(self) -> None:
        return None

    def close(self) -> None:
        return None
