import serial
import time

DEFAULT_SERIAL_PORT = (
    "/dev/serial/by-id/"
    "usb-Prolific_Technology_Inc._USB-Serial_Controller_BPCNb147613-if00-port0"
)
DEFAULT_BAUD_RATE = 9600
DEFAULT_TIMEOUT = 1.0


class Balance:
    """Simple serial wrapper for a single balance connected to the Raspberry Pi."""

    def __init__(
        self,
        serial_port: str = DEFAULT_SERIAL_PORT,
        baud_rate: int = DEFAULT_BAUD_RATE,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.serial_port = serial_port
        self.connection = serial.Serial(
            port=serial_port,
            baudrate=baud_rate,
            timeout=timeout,
        )
        print(f"[balance] Connected to {serial_port}")

    def read_weight(self, settle_time: float = 2.0):
        """Read weight from balance after optional settling delay."""
        if settle_time > 0:
            time.sleep(settle_time)
        self.connection.write(b"R")
        accumulated = ""

        while True:
            if self.connection.in_waiting:
                char = self.connection.read(1).decode()
                if char == "g":
                    break
                accumulated += char

        try:
            return float(accumulated.replace("\r", "").replace("\n", "").strip())
        except ValueError:
            raise RuntimeError(f"Failed to parse: {accumulated}")

    def tare(self):
        """Execute tare command."""
        time.sleep(2)
        self.connection.write(b"T")
        time.sleep(1)

    def zero(self):
        """Execute zero command."""
        self.connection.write(b"Z")
        time.sleep(1)

    def disconnect(self):
        """Close connection."""
        if self.connection.is_open:
            self.connection.close()
            print(f"[balance] Disconnected from {self.serial_port}")
