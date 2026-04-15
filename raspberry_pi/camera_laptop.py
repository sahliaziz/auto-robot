"""
MJPEG camera streamer using OpenCV VideoCapture.
Designed for laptop integrated webcams or any V4L2 / DirectShow device.

Drop-in replacement for camera.py — identical public interface:
    start(), stop(), generate_frames(), get_raw_frame()
"""

import threading
import time

import cv2
import numpy as np


class CameraStreamer:
    def __init__(
        self,
        device_index: int = 0,
        width: int = 640,
        height: int = 480,
        jpeg_quality: int = 85,
    ):
        self._device_index = device_index
        self._width = width
        self._height = height
        self._jpeg_quality = jpeg_quality
        self._frame: bytes | None = None  # latest MJPEG-encoded bytes
        self._raw_frame: np.ndarray | None = None  # latest BGR numpy array
        self._lock = threading.Lock()
        self._running = False
        self._cap: cv2.VideoCapture | None = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        cap = cv2.VideoCapture(self._device_index)
        if not cap.isOpened():
            print(f"[camera] Cannot open device index {self._device_index}")
            return

        # Request the desired resolution; the driver may round to the nearest
        # supported mode, so we log what was actually granted.
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)

        # Keep the internal capture buffer as small as possible so
        # get_raw_frame() always returns a fresh frame.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._cap = cap
        self._running = True
        threading.Thread(target=self._capture_loop, daemon=True).start()

        actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"[camera] Started — device {self._device_index}  {actual_w}x{actual_h}")

    def stop(self):
        self._running = False
        if self._cap:
            self._cap.release()
            self._cap = None
        print("[camera] Stopped")

    # ── Internal capture loop ─────────────────────────────────────────────────

    def _capture_loop(self):
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality]
        while self._running:
            try:
                ok, bgr = self._cap.read()
                if not ok:
                    # Camera may have been unplugged or briefly unavailable.
                    print("[camera] Frame grab failed — retrying in 100 ms")
                    time.sleep(0.1)
                    continue

                # OpenCV VideoCapture already delivers BGR, no conversion needed.
                ok, encoded = cv2.imencode(".jpg", bgr, encode_params)
                if not ok:
                    continue

                with self._lock:
                    self._frame = encoded.tobytes()
                    self._raw_frame = bgr

            except Exception as exc:
                print(f"[camera] Capture error: {exc}")
                time.sleep(0.1)

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_frames(self):
        """Yield MJPEG multipart chunks for use with FastAPI StreamingResponse."""
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
