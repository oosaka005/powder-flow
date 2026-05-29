"""Powder dispenser wiring definitions and simple motor helpers (Motor HAT)."""

from __future__ import annotations

import time

import RPi.GPIO as GPIO

from adafruit_motorkit import MotorKit

# IR beam sensor input
IR_SENSOR_PIN = 15  # Physical pin 10 / HAT RXD (shared with UART RX; safe because liquid/powder modes are physically exclusive via magnetic connector)
IR_ACTIVE_LEVEL = 1  # 黒が検出されたら1
IR_INACTIVE_LEVEL = 0
IR_DEBOUNCE_SEC = 0.010
IR_POLL_INTERVAL_SEC = 0.001

# HAT motor assignments
ROT_MOTOR = "motor1"
VIB_MOTOR = "motor2"
AUG_MOTOR = "motor3"

VIB_MIN_PWM = 50
VIB_MAX_PWM = 150

DEFAULT_STEP_TIMEOUT_SEC = 0.65
BLIND_PHASE_SEC = 0.1

_gpio_initialized = False
_ir_initialized = False
_kit: MotorKit | None = None

_MOTOR_CHANNELS = {
    "rot": ROT_MOTOR,
    "vib": VIB_MOTOR,
    "aug": AUG_MOTOR,
}


def _ensure_gpio_mode() -> None:
    global _gpio_initialized
    if _gpio_initialized:
        return
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    _gpio_initialized = True


def _ensure_ir_setup() -> None:
    global _ir_initialized
    if _ir_initialized:
        return
    _ensure_gpio_mode()
    GPIO.setup(IR_SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    _ir_initialized = True


def _ensure_kit() -> MotorKit:
    global _kit
    if _kit is None:
        _kit = MotorKit()
    return _kit


def _get_motor(name: str):
    if name not in _MOTOR_CHANNELS:
        raise ValueError(f"Unknown motor name: {name}")
    kit = _ensure_kit()
    return getattr(kit, _MOTOR_CHANNELS[name])


def _pwm255_to_throttle(pwm_0_255: int, reverse: bool) -> float:
    pwm_0_255 = max(0, min(255, int(pwm_0_255)))
    throttle = pwm_0_255 / 255.0
    return -throttle if reverse else throttle


def _wait_for_ir_level(target_level: int, deadline: float) -> bool:
    """
    Poll the IR sensor until it stays at target_level for IR_DEBOUNCE_SEC.
    """
    stable_start = None
    _ensure_ir_setup()
    while time.monotonic() < deadline:
        level = GPIO.input(IR_SENSOR_PIN)
        now = time.monotonic()
        if level == target_level:
            if stable_start is None:
                stable_start = now
            elif now - stable_start >= IR_DEBOUNCE_SEC:
                return True
        else:
            stable_start = None
        time.sleep(IR_POLL_INTERVAL_SEC)
    return False


def drive_motor(motor_name: str, pwm_0_255: int, reverse: bool = False) -> None:
    """
    Spin the selected motor using the requested PWM strength.

    Args:
        motor_name: "rot", "vib", or "aug".
        pwm_0_255: Desired power level (0 stops the motor, 255 is max).
        reverse: When True, flip the direction.
    """
    name = motor_name.lower()
    motor = _get_motor(name)
    motor.throttle = _pwm255_to_throttle(pwm_0_255, reverse)


def vib_level_to_pwm(level: int) -> int:
    """Map a vibration level (1-5) to the configured PWM range."""
    level = max(1, min(5, int(level)))
    step = (VIB_MAX_PWM - VIB_MIN_PWM) / 4.0
    return int(round(VIB_MIN_PWM + (level - 1) * step))


def vib(level: int, duration_sec: float) -> None:
    """Run the vibration motor at the requested level for duration_sec seconds."""
    pwm_value = vib_level_to_pwm(level)
    drive_motor("vib", pwm_value)
    try:
        time.sleep(max(0.0, float(duration_sec)))
    finally:
        stop_motor("vib")


def aug(
    duration_sec: float,
    *,
    pwm_0_255: int = 255,
    reverse: bool = False,
) -> None:
    """Run the auger motor for duration_sec seconds at a fixed PWM."""
    drive_motor("aug", pwm_0_255, reverse=reverse)
    try:
        time.sleep(max(0.0, float(duration_sec)))
    finally:
        stop_motor("aug")


def run_all_motors(
    vib_level: int,
    duration_sec: float,
) -> dict[str, object]:
    """Run vib/aug/rot together at vib_level for duration_sec, then step once.

    Returns the step result dict with keys: success, stop_reason, elapsed_sec.
    """
    pwm_value = vib_level_to_pwm(vib_level)
    drive_motor("vib", pwm_value)
    drive_motor("aug", 255, False)
    drive_motor("rot", 255, False)
    try:
        time.sleep(max(0.0, float(duration_sec)))
    finally:
        stop_motor("vib")
        stop_motor("aug")
        stop_motor("rot")
    return step()


def step(
    pwm_0_255: int = 255,
    max_seconds: float = DEFAULT_STEP_TIMEOUT_SEC,
    reverse: bool = False,
) -> dict[str, object]:
    """
    Advance the rotation motor by one index using IR sensor feedback and
    report whether the stop was determined by the IR sensor or the safety timeout.

    After BLIND_PHASE_SEC, the current sensor state is read:
    - If white (INACTIVE): wait for black (ACTIVE) → stop
    - If black (ACTIVE): wait for white (INACTIVE) → then wait for black (ACTIVE) → stop

    Returns:
        A dict including:
        - success: True when the expected sensor transition completed in time
        - stop_reason: "sensor" or "timeout"
        - elapsed_sec: measured step duration
    """
    _ensure_ir_setup()
    start = time.monotonic()
    deadline = start + max(0.0, float(max_seconds))
    drive_motor("rot", pwm_0_255, reverse=reverse)
    try:
        time.sleep(BLIND_PHASE_SEC)
        # Determine stable sensor state after blind phase
        stable_start = None
        stable_level = None
        level_after_blind = None
        while time.monotonic() < deadline:
            level = GPIO.input(IR_SENSOR_PIN)
            now = time.monotonic()
            if level == stable_level:
                if stable_start is not None and now - stable_start >= IR_DEBOUNCE_SEC:
                    level_after_blind = stable_level
                    break
            else:
                stable_level = level
                stable_start = now
            time.sleep(IR_POLL_INTERVAL_SEC)
        if level_after_blind is None:
            return {
                "success": False,
                "stop_reason": "timeout",
                "elapsed_sec": time.monotonic() - start,
            }
        if level_after_blind == IR_ACTIVE_LEVEL:
            if not _wait_for_ir_level(IR_INACTIVE_LEVEL, deadline):
                return {
                    "success": False,
                    "stop_reason": "timeout",
                    "elapsed_sec": time.monotonic() - start,
                }
        if not _wait_for_ir_level(IR_ACTIVE_LEVEL, deadline):
            return {
                "success": False,
                "stop_reason": "timeout",
                "elapsed_sec": time.monotonic() - start,
            }
        return {
            "success": True,
            "stop_reason": "sensor",
            "elapsed_sec": time.monotonic() - start,
        }
    finally:
        stop_motor("rot")


def stop_motor(motor_name: str) -> None:
    """Stop the selected motor immediately."""
    name = motor_name.lower()
    motor = _get_motor(name)
    motor.throttle = 0.0


def cleanup_motors() -> None:
    """Release motor resources and reset GPIO."""
    global _gpio_initialized, _ir_initialized, _kit
    for name in list(_MOTOR_CHANNELS.keys()):
        try:
            stop_motor(name)
        except Exception:
            pass
    _kit = None
    if _gpio_initialized:
        GPIO.cleanup()
        _gpio_initialized = False
        _ir_initialized = False


__all__ = [
    "IR_SENSOR_PIN",
    "drive_motor",
    "vib_level_to_pwm",
    "vib",
    "aug",
    "run_all_motors",
    "step",
    "stop_motor",
    "cleanup_motors",
]
