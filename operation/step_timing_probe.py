from __future__ import annotations

import time
from typing import Any

import RPi.GPIO as GPIO

from hardware_api.powder_dispenser import p_dispenser_HAT_api as dispenser_hat


def measure_step_sensor_timing(
    *,
    pwm_0_255: int = 255,
    max_seconds: float = dispenser_hat.DEFAULT_STEP_TIMEOUT_SEC,
    reverse: bool = False,
) -> dict[str, Any]:
    """
    Temporary helper that mirrors step() and records the sensor transition timing.
    """
    dispenser_hat._ensure_ir_setup()
    initial_level = GPIO.input(dispenser_hat.IR_SENSOR_PIN)
    if initial_level == dispenser_hat.IR_ACTIVE_LEVEL:
        sequence = [
            ("inactive", dispenser_hat.IR_INACTIVE_LEVEL),
            ("active", dispenser_hat.IR_ACTIVE_LEVEL),
        ]
    else:
        sequence = [("active", dispenser_hat.IR_ACTIVE_LEVEL)]

    start = time.monotonic()
    deadline = start + max(0.0, float(max_seconds))
    transitions: list[dict[str, Any]] = []
    timeout_target: str | None = None

    dispenser_hat.drive_motor("rot", pwm_0_255, reverse=reverse)
    try:
        for label, target_level in sequence:
            stable_start = None
            while time.monotonic() < deadline:
                now = time.monotonic()
                level = GPIO.input(dispenser_hat.IR_SENSOR_PIN)
                if level == target_level:
                    if stable_start is None:
                        stable_start = now
                    elif now - stable_start >= dispenser_hat.IR_DEBOUNCE_SEC:
                        transitions.append(
                            {
                                "label": label,
                                "target_level": target_level,
                                "elapsed_sec": now - start,
                            }
                        )
                        break
                else:
                    stable_start = None
                time.sleep(dispenser_hat.IR_POLL_INTERVAL_SEC)
            else:
                timeout_target = label
                break
    finally:
        dispenser_hat.stop_motor("rot")

    end = time.monotonic()
    return {
        "success": timeout_target is None,
        "initial_level": initial_level,
        "sequence": [label for label, _ in sequence],
        "transitions": transitions,
        "timeout_target": timeout_target,
        "total_elapsed_sec": end - start,
    }
