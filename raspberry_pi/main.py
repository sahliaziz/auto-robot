"""
Robot web server — FastAPI
  GET  /          → web UI (static files from ../web)
  GET  /camera    → MJPEG stream
  WS   /ws        → control commands in, lidar + sensor data out
"""

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from serial_comm import SerialComm
from camera import CameraStreamer
from lidar import LidarReader

# ── Singletons ────────────────────────────────────────────────────────────────

serial_comm = SerialComm()
camera = CameraStreamer()
lidar = LidarReader()

# ── App lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    lidar.start()
    camera.start()
    yield
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
        serial_comm.stop()  # Safety: stop motors when browser disconnects


async def _push_loop(websocket: WebSocket):
    """Push lidar scans and sensor readings to the browser at ~10 Hz."""
    try:
        while True:
            scan = lidar.get_scan()
            payload = {
                "type": "telemetry",
                "lidar": scan,
                "distance_cm": serial_comm.distance_cm,
            }
            await websocket.send_text(json.dumps(payload))
            await asyncio.sleep(0.1)
    except Exception:
        pass


def _handle(msg: dict):
    cmd = msg.get("cmd")

    if cmd == "move":
        # x: turn (-1=left, 1=right), y: throttle (-1=back, 1=fwd)
        y = float(msg.get("y", 0))
        x = float(msg.get("x", 0))
        left  = (y + x) * 255
        right = (y - x) * 255
        serial_comm.set_motors(int(left), int(right))

    elif cmd == "stop":
        serial_comm.stop()

    elif cmd == "action":
        # Named autonomous commands: AVANCER, RECULER, TOURNER_G, etc.
        serial_comm.send(msg.get("name", "STOP"))

# ── Static files (web UI) — mounted last so API routes take priority ──────────

app.mount("/", StaticFiles(directory="../web", html=True), name="static")
