"""
Ball detector — HSV-based colour segmentation running in a background thread.

Reads raw BGR frames from a CameraStreamer via get_raw_frame() and exposes
get_detections(), which returns a JSON-serialisable list of ball dicts:

    {
        "color":       str,           # French colour name, e.g. "Rouge"
        "bbox":        [x1,y1,x2,y2], # integer pixel coords
        "center":      [cx, cy],
        "radius":      int,           # pixels
        "circularity": float,         # 4π·A/P², 1.0 = perfect circle
    }

Only contours that pass AREA_MIN **and** CIRCULARITY_MIN are reported as balls.
"""

import math
import threading
import time
from typing import TYPE_CHECKING

import cv2
import numpy as np

if TYPE_CHECKING:
    from camera import CameraStreamer

# ── Parameters (tune for your environment) ────────────────────────────────────

SAT_MIN = 60  # HSV saturation threshold 0-255  (↑ = only vivid colours)
VAL_MIN = 40  # HSV value threshold 0-255       (↑ = ignores dark pixels)
AREA_MIN = 400  # minimum contour area in pixels
CIRCULARITY_MIN = 0.75  # minimum 4π·A/P²  (1.0 = perfect circle)
BLUR_K = 5  # Gaussian kernel size (must be odd); 0 = disabled
DETECTION_FPS = 10  # max detection cycles per second

# ── Named colours (RGB reference values) ─────────────────────────────────────

COLOUR_TABLE = [
    ("Rouge", (255, 0, 0)),
    ("Vert", (0, 255, 0)),
    ("Bleu", (0, 0, 255)),
    ("Jaune", (255, 255, 0)),
    ("Orange", (255, 65, 0)),
    ("Blanc", (255, 255, 255)),
]

# ── Internal helpers ──────────────────────────────────────────────────────────


def _build_mask(frame: np.ndarray, sat_min: int) -> np.ndarray:
    """
    Build a cleaned binary mask: white = saturated (likely ball) pixel.

    Steps:
      1. Gaussian blur  — kills per-pixel noise before thresholding
      2. BGR → HSV      — perceptually uniform colour space
      3. Threshold S≥sat_min and V≥VAL_MIN
      4. Morphological open  — removes specks
      5. Morphological close — fills small holes inside blobs

    Why HSV instead of RGB max-min?
      HSV separates hue, saturation, and brightness cleanly; thresholding on S
      reliably keeps vivid objects regardless of exposure.
    """
    blurred = cv2.GaussianBlur(frame, (BLUR_K, BLUR_K), 0) if BLUR_K > 0 else frame
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)

    # cv2 HSV: H ∈ [0,179], S ∈ [0,255], V ∈ [0,255]
    mask = cv2.inRange(hsv, (0, sat_min, VAL_MIN), (179, 255, 255))

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def _mean_colour(frame: np.ndarray, mask: np.ndarray, cnt) -> tuple:
    """
    Average (quantised) BGR colour of pixels inside cnt, restricted to the mask
    to exclude background bleed at contour edges. Returns (R, G, B).
    """
    obj_mask = np.zeros(mask.shape, dtype=np.uint8)
    cv2.drawContours(obj_mask, [cnt], -1, 255, cv2.FILLED)
    obj_mask &= mask

    pixels = frame[obj_mask == 255]
    if len(pixels) == 0:
        return (128, 128, 128)

    step = 16
    quant = (pixels // step) * step + step // 2
    mean = quant.mean(axis=0)  # B, G, R order (OpenCV)
    return (int(mean[2]), int(mean[1]), int(mean[0]))  # → R, G, B


def _colour_name(rgb: tuple) -> str:
    """Nearest-neighbour match in RGB space against the named colour table."""
    best, best_d = "Inconnu", float("inf")
    for nom, ref in COLOUR_TABLE:
        d = sum((a - b) ** 2 for a, b in zip(rgb, ref))
        if d < best_d:
            best_d, best = d, nom
    return best


def _circularity(cnt) -> float:
    """
    Isoperimetric circularity  4π·A / P²

    Why better than bounding-box fill ratio (A / bbox)?
      A rectangle, diamond, or rounded square can all have A/bbox ≈ π/4.
      This metric is 1.0 ONLY for a perfect circle and degrades sharply for any
      other shape, giving far fewer false positives.
    """
    area = cv2.contourArea(cnt)
    perimeter = cv2.arcLength(cnt, closed=True)
    if perimeter == 0:
        return 0.0
    return (4 * math.pi * area) / (perimeter**2)


# ── BallDetector ──────────────────────────────────────────────────────────────


class BallDetector:
    """
    Background-thread ball detector.

    Usage::

        detector = BallDetector(camera_streamer)
        detector.start()
        ...
        balls = detector.get_detections()   # call at any time from any thread
        ...
        detector.stop()
    """

    def __init__(self, camera: "CameraStreamer", sat_min: int = SAT_MIN):
        self._camera = camera
        self._sat_min = sat_min
        self._detections: list[dict] = []
        self._lock = threading.Lock()
        self._running = False

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._running = True
        threading.Thread(
            target=self._detect_loop, daemon=True, name="ball-detector"
        ).start()
        print("[ball_detector] Started")

    def stop(self) -> None:
        self._running = False
        print("[ball_detector] Stopped")

    def get_detections(self) -> list[dict]:
        """
        Return the latest list of confirmed ball detections (thread-safe).
        Each item is JSON-serialisable and contains:
            color, bbox [x1,y1,x2,y2], center [cx,cy], radius, circularity.
        """
        with self._lock:
            return list(self._detections)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _detect_loop(self) -> None:
        interval = 1.0 / DETECTION_FPS
        while self._running:
            t0 = time.monotonic()
            try:
                frame = self._camera.get_raw_frame()
                if frame is not None:
                    detections = self._process(frame)
                    with self._lock:
                        self._detections = detections
            except Exception as exc:
                print(f"[ball_detector] Error during detection: {exc}")
            elapsed = time.monotonic() - t0
            time.sleep(max(0.0, interval - elapsed))

    def _process(self, frame: np.ndarray) -> list[dict]:
        """Run one full detection pass on a BGR frame; return list of ball dicts."""
        mask = _build_mask(frame, self._sat_min)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        results: list[dict] = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < AREA_MIN:
                continue

            circ = _circularity(cnt)
            if circ < CIRCULARITY_MIN:
                continue

            (cx, cy), radius = cv2.minEnclosingCircle(cnt)
            cx, cy, radius = int(cx), int(cy), int(radius)

            x, y, w, h = cv2.boundingRect(cnt)
            rgb = _mean_colour(frame, mask, cnt)
            nom = _colour_name(rgb)

            entry = {
                "color": nom,
                "bbox": [x, y, x + w, y + h],
                "center": [cx, cy],
                "radius": radius,
                "circularity": round(circ, 3),
            }
            results.append(entry)
            print(
                f"[ball_detector] {nom:6s}  bbox=({x},{y},{x + w},{y + h})  "
                f"centre=({cx},{cy})  r={radius}px  circ={circ:.3f}"
            )

        return results
