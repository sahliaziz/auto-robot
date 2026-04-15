"""
Robot web server — FastAPI  (laptop / dev version)
  GET  /          → web UI (static files from ../web)
  GET  /camera    → MJPEG stream  (OpenCV webcam)
  WS   /ws        → control commands in, lidar + sensor + ball data out

Differences from main.py:
  - Uses camera_laptop.CameraStreamer  (cv2.VideoCapture) instead of picamera2
  - Includes BallDetector; ball detections are pushed over the WebSocket
  - Autonomous lidar-based navigation logic retained from the original main2
"""

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from ball_detector import BallDetector
from camera_laptop import CameraStreamer
from lidar import LidarReader
from serial_comm import SerialComm

# ── Singletons ────────────────────────────────────────────────────────────────

serial_comm = SerialComm()
camera = CameraStreamer()
lidar = LidarReader()
ball_detector = BallDetector(camera)

# ── Zones angulaires ──────────────────────────────────────────────────────────

SEUIL_MM = 1000  # obstacle si moins de 1 mètre

ZONES = {
    "AVANT": (0, 180),
    "AVANT-DROITE": (0, 90),
    "DROITE": (90, 180),
    "ARRIERE": (180, 360),
    "GAUCHE": (180, 270),
    "AVANT-GAUCHE": (270, 360),
}


def _angle_dans_zone(angle: float, debut: int, fin: int) -> bool:
    if debut > fin:
        return angle >= debut or angle <= fin
    return debut <= angle <= fin


def _calculer_commande(scan: list) -> str:
    """Analyse le scan lidar et retourne la commande moteur: F / L / R / S."""
    zones_bloquees = {zone: False for zone in ZONES}

    for angle, distance in scan:
        if 0 < distance < SEUIL_MM:
            for zone, (debut, fin) in ZONES.items():
                if _angle_dans_zone(angle, debut, fin):
                    zones_bloquees[zone] = True

    zones_libres = [z for z, bloque in zones_bloquees.items() if not bloque]

    if "AVANT" in zones_libres:
        return "F"
    elif "AVANT-GAUCHE" in zones_libres:
        return "L"
    elif "AVANT-DROITE" in zones_libres:
        return "R"
    elif "GAUCHE" in zones_libres:
        return "L"
    elif "DROITE" in zones_libres:
        return "R"
    else:
        return "S"


# ── App lifecycle ─────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    lidar.start()
    camera.start()
    ball_detector.start()
    yield
    ball_detector.stop()
    lidar.stop()
    camera.stop()
    serial_comm.close()


app = FastAPI(lifespan=lifespan)


# ── Camera endpoint ───────────────────────────────────────────────────────────


@app.get("/camera")
def camera_stream():
    return StreamingResponse(
        camera.generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ── WebSocket ─────────────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    push_task = asyncio.create_task(_push_loop(websocket))
    try:
        while True:
            text = await websocket.receive_text()
            _handle(json.loads(text))
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        push_task.cancel()
        serial_comm.stop()


async def _push_loop(websocket: WebSocket):
    """Push lidar scan, sensor readings, auto command, and ball detections at ~10 Hz."""
    try:
        while True:
            try:
                scan = lidar.get_scan()
                cmd = _calculer_commande(scan)
                balls = ball_detector.get_detections()

                # Send autonomous command to motors
                serial_comm.send(cmd)

                payload = {
                    "type": "telemetry",
                    "lidar": scan,
                    "distance_cm": serial_comm.distance_cm,
                    "cmd": cmd,
                    "balls": balls,
                }
                await websocket.send_text(json.dumps(payload))
            except Exception as exc:
                # Log but do NOT break — a single bad frame must not kill the loop.
                print(f"[ws] Push error (skipping frame): {exc}")
            await asyncio.sleep(0.02)
    except Exception:
        pass


def _handle(msg: dict):
    """Manual commands from the browser — overrides autonomous drive if needed."""
    cmd = msg.get("cmd")
    if cmd == "move":
        y = float(msg.get("y", 0))
        x = float(msg.get("x", 0))
        left = (y + x) * 255
        right = (y - x) * 255
        serial_comm.set_motors(int(left), int(right))
    elif cmd == "stop":
        serial_comm.stop()
    elif cmd == "action":
        serial_comm.send(msg.get("name", "STOP"))


# ── Static files (web UI) — mounted last so API routes take priority ──────────

app.mount("/", StaticFiles(directory="../web", html=True), name="static")
