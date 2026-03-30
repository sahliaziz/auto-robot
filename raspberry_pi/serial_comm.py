"""
Serial communication with the Arduino motor controller.
Connects on the first available ttyACM* port.
"""

import serial
import serial.tools.list_ports
import threading
import time
import re


def _find_arduino_port() -> str:
    """Return the first ttyACM* port, fall back to /dev/ttyACM0."""
    for p in serial.tools.list_ports.comports():
        if "ttyACM" in p.device or "Arduino" in (p.description or ""):
            return p.device
    return "/dev/ttyACM0"


class SerialComm:
    def __init__(self, port: str | None = None, baud: int = 9600):
        self._port = port or _find_arduino_port()
        self._baud = baud
        self._lock = threading.Lock()
        self._ser: serial.Serial | None = None
        # Latest ultrasonic reading pushed by the Arduino (cm)
        self.distance_cm: float = 0.0
        self._connect()

    # ── Connection ────────────────────────────────────────────────────────────

    def _connect(self):
        try:
            self._ser = serial.Serial(self._port, self._baud, timeout=1)
            time.sleep(2)  # Wait for Arduino bootloader reset
            print(f"[serial] Connected to Arduino on {self._port}")
            # Start background reader for sensor data
            t = threading.Thread(target=self._reader, daemon=True)
            t.start()
        except Exception as e:
            print(f"[serial] Connection failed: {e}")

    def _reader(self):
        """Read lines from Arduino (e.g. DIST:42) without blocking sends."""
        while self._ser and self._ser.is_open:
            try:
                line = self._ser.readline().decode(errors="ignore").strip()
                if line.startswith("DIST:"):
                    m = re.match(r"DIST:(\d+)", line)
                    if m:
                        self.distance_cm = float(m.group(1))
            except Exception:
                break

    # ── Commands ──────────────────────────────────────────────────────────────

    def send(self, cmd: str):
        if self._ser and self._ser.is_open:
            with self._lock:
                self._ser.write((cmd + "\n").encode())

    def set_motors(self, left: int, right: int):
        """Real-time differential drive. left/right in -255..255."""
        left  = max(-255, min(255, int(left)))
        right = max(-255, min(255, int(right)))
        self.send(f"SET:{left}:{right}")

    def stop(self):
        self.send("STOP")

    def close(self):
        self.stop()
        if self._ser:
            self._ser.close()
