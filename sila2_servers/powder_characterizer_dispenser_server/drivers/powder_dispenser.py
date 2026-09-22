"""Motor Bonnet driver for the Powder Characterizer dispenser.

The motion constants and ordering mirror ``p_dispenser_HAT_api.py``.  The
differences are the new GPIO4 wiring, automatic I2C address discovery, recovery
after a PCA9685 reset, and cancellable timed motor runs.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
import time
from typing import Any, Callable


IR_SENSOR_PIN = 4
IR_ACTIVE_LEVEL = 1
IR_INACTIVE_LEVEL = 0
IR_DEBOUNCE_SEC = 0.010
IR_POLL_INTERVAL_SEC = 0.001

MOTOR_CHANNELS = {"rot": "motor1", "vib": "motor2", "aug": "motor3"}
VIB_MIN_PWM = 50
VIB_MAX_PWM = 150
DEFAULT_STEP_TIMEOUT_SEC = 0.65
BLIND_PHASE_SEC = 0.1

ALL_CALL_ADDRESS = 0x70
RECONNECT_TIMEOUT_SEC = 2.0
RECONNECT_POLL_SEC = 0.05
MOTOR_SLICE_SEC = 0.05
REALIGN_TIMEOUT_SEC = 1.0


class DeviceNotConnectedError(RuntimeError):
    pass


class AmbiguousDeviceError(RuntimeError):
    pass


class OperationCancelledError(RuntimeError):
    pass


class _ChipReset(RuntimeError):
    pass


class PowderCharacterizerDispenser:
    """Own the dispenser's I2C and GPIO resources for one server process."""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        i2c_factory: Callable[[], Any] | None = None,
        kit_factory: Callable[..., Any] | None = None,
        gpio: Any | None = None,
        discover_on_start: bool = True,
        acquire_ownership_lock: bool = True,
    ) -> None:
        self._logger = logger or logging.getLogger(__name__)
        self._i2c_factory = i2c_factory or self._default_i2c_factory
        self._kit_factory = kit_factory or self._default_kit_factory
        self._gpio = gpio
        self._i2c: Any | None = None
        self._kit: Any | None = None
        self._pca: Any | None = None
        self._expected_prescale: int | None = None
        self._address: int | None = None
        self._gpio_initialized = False
        self._operation_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._status_lock = threading.Lock()
        self._status = "starting"
        self._ownership_file: Any | None = None
        if acquire_ownership_lock:
            self._acquire_ownership_lock()
        if discover_on_start:
            try:
                self._discover_and_connect()
            except DeviceNotConnectedError:
                pass
            except AmbiguousDeviceError:
                pass
            except Exception as exc:
                self._set_status("waiting_for_device")
                self._logger.warning("Initial dispenser discovery deferred: %s", exc)

    def _acquire_ownership_lock(self) -> None:
        """Prevent two Linux processes from owning the same I2C dispenser."""
        try:
            import fcntl
        except ImportError:
            return
        lock_path = Path(
            os.getenv(
                "POWDER_DISPENSER_LOCK_FILE",
                "/tmp/powder-characterizer-dispenser.lock",
            )
        )
        handle = lock_path.open("a+")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            self._set_status("fault")
            raise RuntimeError(
                "Another process already owns the Powder Characterizer dispenser."
            ) from exc
        self._ownership_file = handle

    @staticmethod
    def _default_i2c_factory() -> Any:
        import board
        from busio import I2C

        return I2C(board.SCL, board.SDA)

    @staticmethod
    def _default_kit_factory(*, address: int, i2c: Any) -> Any:
        from adafruit_motorkit import MotorKit

        return MotorKit(address=address, i2c=i2c)

    @property
    def status(self) -> str:
        with self._status_lock:
            return self._status

    @property
    def detected_address(self) -> int | None:
        """For technical logging/diagnostics only; never persisted as result data."""
        return self._address

    def _set_status(self, value: str) -> None:
        with self._status_lock:
            self._status = value

    def _ensure_gpio(self) -> None:
        if self._gpio_initialized:
            return
        if self._gpio is None:
            import RPi.GPIO as GPIO

            self._gpio = GPIO
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setwarnings(False)
        self._gpio.setup(IR_SENSOR_PIN, self._gpio.IN, pull_up_down=self._gpio.PUD_UP)
        self._gpio_initialized = True

    def _ensure_bus(self) -> Any:
        if self._i2c is None:
            self._i2c = self._i2c_factory()
        return self._i2c

    def _scan_bus(self) -> list[int]:
        bus = self._ensure_bus()
        locked_here = False
        if hasattr(bus, "try_lock"):
            deadline = time.monotonic() + RECONNECT_TIMEOUT_SEC
            while not bus.try_lock():
                if time.monotonic() >= deadline:
                    raise DeviceNotConnectedError("Unable to lock the I2C bus for discovery.")
                time.sleep(RECONNECT_POLL_SEC)
            locked_here = True
        try:
            addresses = [int(value) for value in bus.scan()]
        finally:
            if locked_here:
                bus.unlock()
        self._logger.debug(
            "I2C scan returned %s",
            ", ".join(f"0x{value:02X}" for value in addresses) or "no devices",
        )
        return addresses

    @staticmethod
    def select_bonnet_address(addresses: list[int]) -> int:
        """Resolve the only physical I2C device while ignoring PCA9685 All Call.

        No address range or configured candidate list is used.  The deployment
        contract is that one physical dispenser is connected; if other
        individual-address devices are present the result is deliberately
        ambiguous instead of guessing.
        """
        individual = sorted({value for value in addresses if value != ALL_CALL_ADDRESS})
        if not individual:
            raise DeviceNotConnectedError(
                "No individual I2C address was found (0x70 All Call is not a device)."
            )
        if len(individual) > 1:
            values = ", ".join(f"0x{value:02X}" for value in individual)
            raise AmbiguousDeviceError(f"Multiple Motor Bonnet candidates found: {values}")
        return individual[0]

    def _build_kit(self, address: int) -> None:
        kit = self._kit_factory(address=address, i2c=self._ensure_bus())
        self._kit = kit
        self._pca = getattr(kit, "_pca", None)
        self._expected_prescale = (
            int(self._pca.prescale_reg) if self._pca is not None else None
        )
        self._address = address
        self._ensure_gpio()
        self._stop_all_quiet()
        self._set_status("ready")
        self._logger.info("Motor Bonnet ready at I2C address 0x%02X", address)

    def _discover_and_connect(self) -> None:
        self._set_status("discovering")
        try:
            try:
                addresses = self._scan_bus()
            except Exception as exc:
                raise DeviceNotConnectedError(
                    "The I2C bus or Motor Bonnet is not currently available."
                ) from exc
            address = self.select_bonnet_address(addresses)
            self._build_kit(address)
        except DeviceNotConnectedError:
            self._clear_connection(keep_address=False)
            self._set_status("waiting_for_device")
            raise
        except AmbiguousDeviceError:
            self._clear_connection(keep_address=False)
            self._set_status("fault")
            raise

    def _clear_connection(self, *, keep_address: bool) -> None:
        self._kit = None
        self._pca = None
        self._expected_prescale = None
        if not keep_address:
            self._address = None

    def _assert_chip_healthy(self) -> None:
        if self._kit is None:
            raise DeviceNotConnectedError("Motor Bonnet is not connected.")
        if self._pca is not None and self._expected_prescale is not None:
            if int(self._pca.prescale_reg) != self._expected_prescale:
                raise _ChipReset("PCA9685 configuration was reset after an I2C power interruption.")

    def _ensure_connected(self) -> None:
        if self._kit is not None:
            try:
                self._assert_chip_healthy()
                return
            except (OSError, ValueError, _ChipReset):
                self._recover()
                return
        self._discover_and_connect()

    def _recover(self) -> bool:
        self._set_status("recovering")
        self._stop_all_quiet()
        deadline = time.monotonic() + RECONNECT_TIMEOUT_SEC
        last_error: Exception | None = None
        cached_address = self._address
        while time.monotonic() < deadline:
            try:
                self._clear_connection(keep_address=True)
                if cached_address is not None:
                    try:
                        self._build_kit(cached_address)
                    except (OSError, ValueError):
                        self._clear_connection(keep_address=False)
                        self._discover_and_connect()
                else:
                    self._discover_and_connect()
                realigned = self._realign_index()
                self._set_status("busy")
                self._logger.warning(
                    "Recovered Motor Bonnet connection (realigned=%s)", realigned
                )
                return realigned
            except AmbiguousDeviceError:
                self._set_status("fault")
                raise
            except Exception as exc:
                last_error = exc
                time.sleep(RECONNECT_POLL_SEC)
        self._clear_connection(keep_address=False)
        self._set_status("fault")
        raise DeviceNotConnectedError("Motor Bonnet recovery timed out.") from last_error

    def _get_motor(self, name: str) -> Any:
        if name not in MOTOR_CHANNELS:
            raise ValueError(f"Unknown motor: {name}")
        return getattr(self._kit, MOTOR_CHANNELS[name])

    @staticmethod
    def _throttle(pwm_0_255: int, reverse: bool = False) -> float:
        value = max(0, min(255, int(pwm_0_255))) / 255.0
        return -value if reverse else value

    @staticmethod
    def _vib_pwm(level: int) -> int:
        clamped = max(1, min(5, int(level)))
        return int(round(VIB_MIN_PWM + (clamped - 1) * (VIB_MAX_PWM - VIB_MIN_PWM) / 4.0))

    def _set_motor(self, name: str, pwm: int, reverse: bool = False) -> None:
        self._get_motor(name).throttle = self._throttle(pwm, reverse)

    def _stop_motor_quiet(self, name: str) -> None:
        try:
            self._get_motor(name).throttle = 0.0
        except Exception:
            pass

    def _stop_all_quiet(self) -> None:
        if self._kit is None:
            return
        for name in MOTOR_CHANNELS:
            self._stop_motor_quiet(name)

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise OperationCancelledError("Dispenser operation was stopped.")

    def _run_motors_for(self, motors: tuple[tuple[str, int, bool], ...], duration_sec: float) -> None:
        total = max(0.0, float(duration_sec))
        ran = 0.0
        while ran < total:
            self._check_cancelled()
            try:
                self._assert_chip_healthy()
                for name, pwm, reverse in motors:
                    self._set_motor(name, pwm, reverse)
                try:
                    while ran < total:
                        self._check_cancelled()
                        started = time.monotonic()
                        time.sleep(min(MOTOR_SLICE_SEC, total - ran))
                        self._assert_chip_healthy()
                        ran += time.monotonic() - started
                finally:
                    for name, _, _ in motors:
                        self._stop_motor_quiet(name)
            except OperationCancelledError:
                raise
            except (OSError, ValueError, _ChipReset):
                self._recover()

    def _stable_ir_level(self, deadline: float) -> int | None:
        stable_level: int | None = None
        stable_start: float | None = None
        while time.monotonic() < deadline:
            self._check_cancelled()
            level = int(self._gpio.input(IR_SENSOR_PIN))
            now = time.monotonic()
            if level == stable_level:
                if stable_start is not None and now - stable_start >= IR_DEBOUNCE_SEC:
                    return stable_level
            else:
                stable_level = level
                stable_start = now
            time.sleep(IR_POLL_INTERVAL_SEC)
        return None

    def _wait_for_ir_level(self, target: int, deadline: float) -> bool:
        stable_start: float | None = None
        while time.monotonic() < deadline:
            self._check_cancelled()
            level = int(self._gpio.input(IR_SENSOR_PIN))
            now = time.monotonic()
            if level == target:
                if stable_start is None:
                    stable_start = now
                elif now - stable_start >= IR_DEBOUNCE_SEC:
                    return True
            else:
                stable_start = None
            time.sleep(IR_POLL_INTERVAL_SEC)
        return False

    def _realign_index(self) -> bool:
        if int(self._gpio.input(IR_SENSOR_PIN)) == IR_ACTIVE_LEVEL:
            return False
        deadline = time.monotonic() + REALIGN_TIMEOUT_SEC
        self._set_motor("rot", 255)
        try:
            if not self._wait_for_ir_level(IR_ACTIVE_LEVEL, deadline):
                raise RuntimeError("IR realignment timed out; chamber position is unknown.")
        finally:
            self._stop_motor_quiet("rot")
        return True

    def _index_once(self, pwm: int, max_seconds: float, reverse: bool, started: float) -> dict[str, Any]:
        self._assert_chip_healthy()
        deadline = time.monotonic() + max(0.0, float(max_seconds))
        self._set_motor("rot", pwm, reverse)
        try:
            # Preserve the current blind phase, but make it cancellable.
            # The legacy driver always completes the full 100 ms blind phase,
            # even when a shorter custom timeout was supplied. Keep that timing
            # contract while polling cancellation instead of using one long sleep.
            blind_end = time.monotonic() + BLIND_PHASE_SEC
            while time.monotonic() < blind_end:
                self._check_cancelled()
                remaining = blind_end - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(IR_POLL_INTERVAL_SEC, remaining))
            level = self._stable_ir_level(deadline)
            stop_reason = "timeout"
            if level is not None:
                left_mark = level != IR_ACTIVE_LEVEL or self._wait_for_ir_level(
                    IR_INACTIVE_LEVEL, deadline
                )
                if left_mark and self._wait_for_ir_level(IR_ACTIVE_LEVEL, deadline):
                    stop_reason = "sensor"
        finally:
            self._stop_motor_quiet("rot")
        self._assert_chip_healthy()
        return {
            "success": stop_reason == "sensor",
            "stop_reason": stop_reason,
            "elapsed_sec": time.monotonic() - started,
        }

    def _index_inner(self, pwm: int, max_seconds: float, reverse: bool) -> dict[str, Any]:
        started = time.monotonic()
        while True:
            self._check_cancelled()
            try:
                return self._index_once(pwm, max_seconds, reverse, started)
            except OperationCancelledError:
                raise
            except (OSError, ValueError, _ChipReset):
                if self._recover():
                    return {
                        "success": True,
                        "stop_reason": "sensor",
                        "elapsed_sec": time.monotonic() - started,
                    }

    def _run_operation(self, action: Callable[[], Any]) -> Any:
        with self._operation_lock:
            self._cancel_event.clear()
            try:
                self._ensure_connected()
                self._set_status("busy")
                return action()
            except OperationCancelledError:
                self._set_status("ready" if self._kit is not None else "waiting_for_device")
                raise
            except DeviceNotConnectedError:
                self._set_status("waiting_for_device")
                raise
            except Exception:
                self._set_status("fault")
                raise
            finally:
                self._stop_all_quiet()
                if self.status == "busy":
                    self._set_status("ready")

    def index_chamber(
        self,
        pwm_0_255: int = 255,
        max_seconds: float = DEFAULT_STEP_TIMEOUT_SEC,
        reverse: bool = False,
    ) -> dict[str, Any]:
        return self._run_operation(
            lambda: self._index_inner(pwm_0_255, max_seconds, reverse)
        )

    def vibrate(self, level: int, duration_sec: float) -> None:
        self._run_operation(
            lambda: self._run_motors_for(
                (("vib", self._vib_pwm(level), False),), duration_sec
            )
        )

    def vibrate_with_auger(self, level: int, duration_sec: float) -> None:
        # Preserve current powder-flow behavior: auger forward (reverse=False).
        self._run_operation(
            lambda: self._run_motors_for(
                (("vib", self._vib_pwm(level), False), ("aug", 255, False)),
                duration_sec,
            )
        )

    def run_all_motors(self, vib_level: int, duration_sec: float) -> dict[str, Any]:
        def action() -> dict[str, Any]:
            self._run_motors_for(
                (
                    ("vib", self._vib_pwm(vib_level), False),
                    ("aug", 255, False),
                    ("rot", 255, False),
                ),
                duration_sec,
            )
            return self._index_inner(255, DEFAULT_STEP_TIMEOUT_SEC, False)

        return self._run_operation(action)

    def stop_all(self) -> None:
        self._cancel_event.set()
        self._stop_all_quiet()
        if self._kit is not None:
            self._set_status("ready")

    def close(self) -> None:
        self.stop_all()
        try:
            if self._gpio_initialized:
                self._gpio.cleanup()
        except Exception:
            pass
        self._gpio_initialized = False
        self._clear_connection(keep_address=False)
        self._set_status("waiting_for_device")
        if self._ownership_file is not None:
            try:
                import fcntl

                fcntl.flock(self._ownership_file.fileno(), fcntl.LOCK_UN)
                self._ownership_file.close()
            except Exception:
                pass
            self._ownership_file = None
