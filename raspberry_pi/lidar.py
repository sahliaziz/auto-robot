import threading
import time
from rplidar import RPLidar, RPLidarException

class LidarReader:
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200):
        self._port = port
        self._baudrate = baudrate
        self._latest_scan = []
        self._lock = threading.Lock()
        self._lidar = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print(f"[lidar] Thread started on {self._port}")

    def _run(self):
        while self._running:
            try:
                self._lidar = RPLidar(self._port, baudrate=self._baudrate)
                # Clear the internal state of the LIDAR in case it's "stuck"
                self._lidar.reset()
                time.sleep(1) # Give it a second to reboot after reset

                print("[lidar] Connected and scanning...")
                for scan in self._lidar.iter_scans():
                    if not self._running:
                        break

                    points = [[round(angle, 1), round(dist)] for _, angle, dist in scan if dist > 0]

                    with self._lock:
                        self._latest_scan = points

            except Exception as e:
                print(f"[lidar] Runtime Error: {e}")
                self._cleanup()
                # Wait before trying to reconnect
                time.sleep(2)

    def _cleanup(self):
        """Safely shuts down the lidar connection."""
        if self._lidar:
            try:
                self._lidar.stop()
                self._lidar.stop_motor()
                self._lidar.disconnect()
            except:
                pass
            finally:
                self._lidar = None

    def get_scan(self):
        with self._lock:
            return list(self._latest_scan)

    def stop(self):
        self._running = False
        self._cleanup()
        print("[lidar] Stopped.")
