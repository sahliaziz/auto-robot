"""
RPLIDAR reader (Silicon Labs CP210x, /dev/ttyUSB0).
Runs in a background thread and exposes the latest 360° scan.
"""

import threading


class LidarReader:
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self._port = port
        self._baudrate = baudrate
        self._latest_scan: list[list[float]] = []
        self._lock = threading.Lock()
        self._lidar = None
        self._running = False

    def start(self):
        self._running = True
        threading.Thread(target=self._run, daemon=True).start()
        print(f"[lidar] Started on {self._port}")

    def _run(self):
        from rplidar import RPLidar
        self._lidar = RPLidar(self._port, baudrate=self._baudrate)
        try:
            for scan in self._lidar.iter_scans():
                # Each scan: list of (quality, angle_deg, distance_mm)
                points = [
                    [round(angle, 1), round(distance)]
                    for _, angle, distance in scan
                    if distance > 0
                ]
                with self._lock:
                    self._latest_scan = points
        except Exception as e:
            print(f"[lidar] Error: {e}")
        finally:
            try:
                self._lidar.stop()
                self._lidar.disconnect()
            except Exception:
                pass

    def get_scan(self) -> list[list[float]]:
        """Return the latest full 360° scan as [[angle_deg, distance_mm], ...]."""
        with self._lock:
            return list(self._latest_scan)

    def stop(self):
        self._running = False
        if self._lidar:
            try:
                self._lidar.stop()
                self._lidar.disconnect()
            except Exception:
                pass
