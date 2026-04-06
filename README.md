# Autonomous Robot

A remotely controlled robot built around a Raspberry Pi and an Arduino, accessible through a browser-based interface. The interface shows a live camera feed, a real-time lidar map, and controls for driving the robot manually or triggering autonomous behaviours.

---

## Hardware

| Component | Role |
|---|---|
| Raspberry Pi | Brain: runs the web server, streams camera, reads lidar |
| Arduino + Adafruit Motor Shield v1 | Controls the 4 DC motors |
| Raspberry Pi Camera Module | First-person video stream |
| RPLIDAR (USB, CP210x bridge) | 360° distance scanning |
| HC-SR04 ultrasonic sensor | Short-range obstacle detection (pins 9/10) |

---

## Architecture

```
Browser
  │
  ├── GET /          → HTML/CSS/JS (served by RPi)
  ├── GET /camera    → MJPEG video stream
  └── WS  /ws        → control commands ↑ / telemetry ↓
                              │
                        Raspberry Pi
                         (FastAPI)
                        /          \
               picamera2          rplidar
               (camera.py)        (lidar.py)
                                      │
                              /dev/ttyUSB0 (115200 baud)
                              RPLIDAR A-series

                        serial_comm.py
                              │
                        /dev/ttyACM0 (9600 baud)
                              │
                           Arduino
                       (AFMotor shield)
                        /    |    |    \
                       M1   M2   M3   M4
                      (left pair)  (right pair)
```

### Component communication

**Raspberry Pi ↔ Arduino — Serial (USB)**

The Arduino is connected to the RPi over USB. The RPi sends plain-text commands terminated by `\n`. The Arduino pushes sensor data back at 5 Hz.

| Direction | Message | Meaning |
|---|---|---|
| RPi → Arduino | `SET:<left>:<right>\n` | Real-time differential drive. Values -255..255. Negative = reverse. |
| RPi → Arduino | `STOP\n` | Release all motors immediately. |
| RPi → Arduino | `AVANCER\n` | Drive forward 1 m (blocking, timed). |
| RPi → Arduino | `RECULER\n` | Drive backward 1 m. |
| RPi → Arduino | `TOURNER_G\n` | Turn left 90°. |
| RPi → Arduino | `TOURNER_D\n` | Turn right 90°. |
| Arduino → RPi | `DIST:<cm>\n` | Ultrasonic distance reading, sent every 200 ms. |

**Browser ↔ Raspberry Pi — WebSocket + HTTP**

The browser opens a persistent WebSocket to `/ws`. Control commands flow from browser to RPi; the RPi pushes telemetry back at ~10 Hz.

Browser → RPi (JSON):
```json
{ "cmd": "move",   "x": 0.0, "y": 1.0 }   // real-time drive (x=turn, y=throttle, -1..1)
{ "cmd": "stop" }                           // release motors
{ "cmd": "action", "name": "TOURNER_G" }    // trigger a named autonomous command
```

RPi → Browser (JSON):
```json
{
  "type": "telemetry",
  "lidar": [[angle_deg, distance_mm], ...], // full 360° scan
  "distance_cm": 42                         // ultrasonic reading
}
```

The camera stream is a standard MJPEG multipart HTTP response at `/camera`. The browser points an `<img>` tag at it — no WebSocket needed for video.

**Raspberry Pi ↔ RPLIDAR — Serial (USB)**

The lidar connects on `/dev/ttyUSB0` at 115200 baud using the `rplidar-roboticia` Python library. A background thread continuously calls `iter_scans()` and stores the latest full 360° scan. The FastAPI push loop sends that scan to all connected browsers every 100 ms.

---

## Project structure

```
.
├── arduino/
│   └── motor_controller/
│       └── motor_controller.ino   # Arduino firmware
│
├── raspberry_pi/
│   ├── main.py                    # FastAPI app (entry point)
│   ├── serial_comm.py             # Arduino serial wrapper
│   ├── camera.py                  # MJPEG camera streamer (picamera2)
│   ├── lidar.py                   # RPLIDAR background reader
│   └── requirements.txt
│
└── web/
    ├── index.html                 # Single-page UI
    ├── style.css
    └── app.js                     # WebSocket client + lidar canvas renderer
```

---

## Setup

### 1. Flash the Arduino

Open `arduino/motor_controller/motor_controller.ino` in the Arduino IDE, select your board (Uno / Mega), and upload. Requires the **Adafruit Motor Shield v1** library (`AFMotor.h`).

### 2. Install Raspberry Pi dependencies

```bash
uv sync
```

> `picamera2` may already be installed on Raspberry Pi OS. If not, use `sudo apt install python3-picamera2`.

### 3. Enable the camera

```bash
sudo raspi-config
# Interface Options → Camera → Enable
```

### 4. Check device ports

| Device | Expected port |
|---|---|
| Arduino | `/dev/ttyACM0` |
| RPLIDAR | `/dev/ttyUSB0` |

If the Arduino lands on a different port, pass it explicitly:

```python
# raspberry_pi/serial_comm.py
serial_comm = SerialComm(port="/dev/ttyACM1")
```

### 5. Run the server

```bash
cd raspberry_pi
uvicorn main:app --host 0.0.0.0 --port 8080
```

Open `http://<raspberry-pi-ip>:8080` in any browser on the same network.

### 6. (Optional) Run on boot

Create `/etc/systemd/system/robot.service`:

```ini
[Unit]
Description=Robot web server
After=network.target

[Service]
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8080
WorkingDirectory=/home/pi/robot/raspberry_pi
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable robot
sudo systemctl start robot
```

---

## Web interface

| Area | Description |
|---|---|
| Camera panel | Live MJPEG feed from the RPi camera |
| Lidar panel | Canvas rendering of the 360° scan. Red dots = close obstacles, green = far. Rings every 1.5 m. White dot + tick = robot and forward direction. |
| D-pad | Arrow buttons for real-time driving. Also bound to keyboard arrow keys; Space = stop. Works on touchscreens. |
| Autonomous panel | Buttons that trigger the timed manoeuvre commands on the Arduino. |
| Status indicator | Shows WebSocket connection state. Auto-reconnects every 2 s on disconnect. |
| Sonar badge | Live ultrasonic distance updated from Arduino pushes. |

> **Safety:** the server sends a `STOP` command to the Arduino whenever the browser WebSocket disconnects, so the robot stops if the connection is lost.

---

## Motor wiring (Adafruit Motor Shield v1)

| Motor | Shield port | Side |
|---|---|---|
| M1 | Port 1 | Left front |
| M2 | Port 2 | Left rear |
| M3 | Port 3 | Right front |
| M4 | Port 4 | Right rear |

For forward motion all four motors run `FORWARD`. For turning, the left pair and right pair run in opposite directions (tank/differential steering).

---

## Calibration

The timed autonomous commands use `delay(distance * 10)` ms as a rough time-to-distance mapping. Tune the multiplier in `motor_controller.ino` to match your robot's actual speed:

```cpp
// avancer / reculer
t = distance * 10;  // increase if the robot undershoots, decrease if it overshoots

// tourner
t = angle * 10;     // tune until a 90° command turns exactly 90°
```
