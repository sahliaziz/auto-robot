"""
MJPEG camera streamer using picamera2.
Captures frames in a background thread; generate_frames() yields
the multipart MJPEG bytes for a FastAPI StreamingResponse.
"""

import io
import threading
import time


class CameraStreamer:
    def __init__(self, width: int = 640, height: int = 480):
        self._width = width
        self._height = height
        self._frame: bytes | None = None
        self._lock = threading.Lock()
        self._running = False
        self._camera = None

    def start(self):
        try:
            from picamera2 import Picamera2
            self._camera = Picamera2()
            cfg = self._camera.create_video_configuration(
                main={"size": (self._width, self._height), "format": "RGB888"}
            )
            self._camera.configure(cfg)
            self._camera.start()
            self._running = True
            threading.Thread(target=self._capture_loop, daemon=True).start()
            print("[camera] Started")
        except Exception as e:
            print(f"[camera] Failed to start: {e}")

    def _capture_loop(self):
        while self._running:
            try:
                buf = io.BytesIO()
                self._camera.capture_file(buf, format="jpeg")
                with self._lock:
                    self._frame = buf.getvalue()
            except Exception as e:
                print(f"[camera] Capture error: {e}")
                time.sleep(0.1)

    def generate_frames(self):
        """Yields MJPEG multipart chunks for use with StreamingResponse."""
        while True:
            with self._lock:
                frame = self._frame
            if frame:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
            time.sleep(0.033)  # ~30 fps cap

    def stop(self):
        self._running = False
        if self._camera:
            self._camera.stop()
