"""
MJPEG camera streamer using picamera2.
Captures raw BGR frames in a background thread; generate_frames() yields
the multipart MJPEG bytes for a FastAPI StreamingResponse.
get_raw_frame() returns the latest numpy BGR array for the ball detector.
"""

import threading
import time

import cv2
import numpy as np


class CameraStreamer:
    def __init__(self, width: int = 640, height: int = 480, jpeg_quality: int = 85):
        self._width = width
        self._height = height
        self._jpeg_quality = jpeg_quality
        self._frame: bytes | None = None  # latest MJPEG-encoded bytes
        self._raw_frame: np.ndarray | None = None  # latest BGR numpy array
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
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        while self._running:
            try:
                # Capture as a numpy array (RGB888 from picamera2)
                raw_rgb = self._camera.capture_array()

                # Convert RGB → BGR for OpenCV compatibility
                bgr = cv2.cvtColor(raw_rgb, cv2.COLOR_RGB2BGR)

                # Encode to JPEG in-memory
                ok, encoded = cv2.imencode(".jpg", bgr, encode_params)
                if not ok:
                    continue

                with self._lock:
                    self._frame = encoded.tobytes()
                    self._raw_frame = bgr

            except Exception as e:
                print(f"[camera] Capture error: {e}")
                time.sleep(0.1)

    def generate_frames(self):
        """Yields MJPEG multipart chunks for use with StreamingResponse."""
        while True:
            with self._lock:
                frame = self._frame
            if frame:
                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n")
            time.sleep(0.033)  # ~30 fps cap

    def get_raw_frame(self) -> np.ndarray | None:
        """Return the latest BGR numpy array, or None if not yet available."""
        with self._lock:
            return self._raw_frame

    def stop(self):
        self._running = False
        if self._camera:
            self._camera.stop()
