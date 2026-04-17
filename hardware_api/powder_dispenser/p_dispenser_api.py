"""Powder dispenser wiring definitions and simple motor helpers.

IMPORTANT: Both motors are 12V DC loads (driver channel A = rotation, B = vibration).
"""

import time

import RPi.GPIO as GPIO

# IR beam sensor input
IR_SENSOR_PIN = 24  # Physical pin 18
IR_ACTIVE_LEVEL = 1  # 黒が検出されたら1
IR_INACTIVE_LEVEL = 0
IR_DEBOUNCE_SEC = 0.001
IR_POLL_INTERVAL_SEC = 0.001

# Rotation motor wires (Motor driver channel A, 12V DC motor)
ROT_ENA = 18  # Physical pin 12
ROT_IN1 = 17  # Physical pin 11
ROT_IN2 = 27  # Physical pin 13

# Vibration motor wires (Motor driver channel B, 12V DC motor)
VIB_ENB = 13  # Physical pin 33
VIB_IN3 = 16  # Physical pin 36
VIB_IN4 = 19  # Physical pin 35

VIB_MIN_PWM = 50
VIB_MAX_PWM = 150

PWM_FREQ_HZ = 1000
DEFAULT_STEP_TIMEOUT_SEC = 5.0

_gpio_initialized = False
_ir_initialized = False
_motor_pwms = {"rot": None, "vib": None}

_MOTOR_PINS = {
    "rot": {"ena": ROT_ENA, "in1": ROT_IN1, "in2": ROT_IN2},
    "vib": {"ena": VIB_ENB, "in1": VIB_IN3, "in2": VIB_IN4},
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


def _ensure_motor_setup(name: str) -> None:
    """Configure GPIO and PWM for the requested motor once."""
    if name not in _MOTOR_PINS:
        raise ValueError(f"Unknown motor name: {name}")
    if _motor_pwms[name] is not None:
        return

    _ensure_gpio_mode()
    pins = _MOTOR_PINS[name]
    GPIO.setup(pins["ena"], GPIO.OUT)
    GPIO.setup(pins["in1"], GPIO.OUT)
    GPIO.setup(pins["in2"], GPIO.OUT)
    GPIO.output(pins["in1"], GPIO.LOW)
    GPIO.output(pins["in2"], GPIO.LOW)

    pwm = GPIO.PWM(pins["ena"], PWM_FREQ_HZ)
    pwm.start(0)
    _motor_pwms[name] = pwm


def _pwm255_to_duty(pwm_0_255: int) -> float:
    """Clamp a 0-255 PWM value and convert to duty cycle percent."""
    pwm_0_255 = max(0, min(255, int(pwm_0_255)))
    return (pwm_0_255 / 255.0) * 100.0


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
        motor_name: "rot" or "vib".
        pwm_0_255: Desired power level (0 stops the motor, 255 is max).
        reverse: When True, flip the direction.
    """
    name = motor_name.lower()
    if name not in _MOTOR_PINS:
        raise ValueError(f"Unknown motor name: {motor_name}")
    _ensure_motor_setup(name)

    pins = _MOTOR_PINS[name]
    if reverse:
        GPIO.output(pins["in1"], GPIO.LOW)
        GPIO.output(pins["in2"], GPIO.HIGH)
    else:
        GPIO.output(pins["in1"], GPIO.HIGH)
        GPIO.output(pins["in2"], GPIO.LOW)

    _motor_pwms[name].ChangeDutyCycle(_pwm255_to_duty(pwm_0_255))


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


def step(
    pwm_0_255: int = 255,
    max_seconds: float = DEFAULT_STEP_TIMEOUT_SEC,
    reverse: bool = False,
) -> bool:
    """
    Advance the rotation motor by one index using IR sensor feedback.

    Returns:
        True if the IR sensor completed an inactive->active transition before timeout.
    """
    _ensure_ir_setup()
    initial_level = GPIO.input(IR_SENSOR_PIN)
    if initial_level == IR_ACTIVE_LEVEL:
        sequence = [IR_INACTIVE_LEVEL, IR_ACTIVE_LEVEL]
    else:
        sequence = [IR_ACTIVE_LEVEL]

    deadline = time.monotonic() + max(0.0, float(max_seconds))
    drive_motor("rot", pwm_0_255, reverse=reverse)
    try:
        for target_level in sequence:
            if not _wait_for_ir_level(target_level, deadline):
                return False
        return True
    finally:
        stop_motor("rot")


def stop_motor(motor_name: str) -> None:
    """Stop the selected motor immediately."""
    name = motor_name.lower()
    if name not in _MOTOR_PINS:
        raise ValueError(f"Unknown motor name: {motor_name}")
    pwm = _motor_pwms.get(name)
    if pwm is None:
        return
    pwm.ChangeDutyCycle(0)
    pins = _MOTOR_PINS[name]
    GPIO.output(pins["in1"], GPIO.LOW)
    GPIO.output(pins["in2"], GPIO.LOW)


def cleanup_motors() -> None:
    """Release PWM resources for all motors and reset GPIO."""
    global _gpio_initialized, _ir_initialized
    for name, pwm in _motor_pwms.items():
        if pwm is None:
            continue
        stop_motor(name)
        pwm.stop()
        _motor_pwms[name] = None
    if _gpio_initialized:
        GPIO.cleanup()
        _gpio_initialized = False
        _ir_initialized = False


__all__ = [
    "IR_SENSOR_PIN",
    "ROT_ENA",
    "ROT_IN1",
    "ROT_IN2",
    "VIB_ENB",
    "VIB_IN3",
    "VIB_IN4",
    "drive_motor",
    "vib_level_to_pwm",
    "vib",
    "step",
    "stop_motor",
    "cleanup_motors",
]
