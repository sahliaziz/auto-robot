"use strict";

// ── WebSocket ─────────────────────────────────────────────────────────────────

const WS_URL = `ws://${location.host}/ws`;
let ws = null;

function connect() {
    ws = new WebSocket(WS_URL);

    ws.onopen = () => setStatus(true);

    ws.onclose = () => {
        setStatus(false);
        setTimeout(connect, 2000);
    };

    ws.onerror = () => ws.close();

    ws.onmessage = ({ data }) => {
        const msg = JSON.parse(data);
        if (msg.type === "telemetry") {
            if (msg.lidar?.length) drawLidar(msg.lidar);
            document.getElementById("distance").textContent =
                `Sonar: ${msg.distance_cm ?? "--"}cm`;
            const balls = msg.balls ?? [];
            document.getElementById("balls").textContent =
                `Balls: ${balls.length}`;
            drawBalls(balls);
        }
    };
}

function send(obj) {
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
}

function setStatus(connected) {
    const el = document.getElementById("status");
    el.textContent = connected ? "Connected" : "Disconnected";
    el.className = `status ${connected ? "connected" : "disconnected"}`;
}

// ── Controls ──────────────────────────────────────────────────────────────────

const MOVES = {
    forward: { y: 1, x: 0 },
    backward: { y: -1, x: 0 },
    left: { y: 0, x: 1 },
    right: { y: 0, x: -1 },
};

function startMove(cmd) {
    if (cmd === "stop") {
        send({ cmd: "stop" });
        return;
    }
    const { x, y } = MOVES[cmd];
    send({ cmd: "move", x, y });
}

function stopMove() {
    send({ cmd: "stop" });
}

// D-pad buttons — mouse, touch, keyboard all handled
const activeKeys = new Set();

document.querySelectorAll(".dpad-btn").forEach((btn) => {
    const cmd = btn.dataset.cmd;

    const press = (e) => {
        e.preventDefault();
        btn.classList.add("pressed");
        startMove(cmd);
    };
    const release = () => {
        btn.classList.remove("pressed");
        if (cmd !== "stop") stopMove();
    };

    btn.addEventListener("mousedown", press);
    btn.addEventListener("mouseup", release);
    btn.addEventListener("mouseleave", release);
    btn.addEventListener("touchstart", press, { passive: false });
    btn.addEventListener("touchend", release);
    btn.addEventListener("touchcancel", release);
});

const KEY_MAP = {
    ArrowUp: "forward",
    ArrowDown: "backward",
    ArrowLeft: "left",
    ArrowRight: "right",
    " ": "stop",
};

document.addEventListener("keydown", (e) => {
    const cmd = KEY_MAP[e.key];
    if (!cmd || activeKeys.has(cmd)) return;
    e.preventDefault();
    activeKeys.add(cmd);
    const btn = document.querySelector(`.dpad-btn[data-cmd="${cmd}"]`);
    btn?.classList.add("pressed");
    startMove(cmd);
});

document.addEventListener("keyup", (e) => {
    const cmd = KEY_MAP[e.key];
    if (!cmd) return;
    activeKeys.delete(cmd);
    const btn = document.querySelector(`.dpad-btn[data-cmd="${cmd}"]`);
    btn?.classList.remove("pressed");
    if (cmd !== "stop" && activeKeys.size === 0) stopMove();
});

// Autonomous action buttons
document.querySelectorAll(".action-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
        send({ cmd: "action", name: btn.dataset.action });
    });
});

// ── Lidar canvas ──────────────────────────────────────────────────────────────

const canvas = document.getElementById("lidar-canvas");
const ctx = canvas.getContext("2d");
const MAX_DIST_MM = 6000;

function drawLidar(points) {
    const W = canvas.width;
    const H = canvas.height;
    const cx = W / 2;
    const cy = H / 2;
    const radius = W / 2 - 16;
    const scale = radius / MAX_DIST_MM;

    // Background
    ctx.fillStyle = "#050505";
    ctx.fillRect(0, 0, W, H);

    // Distance rings (every 1.5m)
    ctx.lineWidth = 1;
    for (let d = 1500; d <= MAX_DIST_MM; d += 1500) {
        const r = d * scale;
        ctx.strokeStyle = "#1c2e1c";
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.stroke();
        ctx.fillStyle = "#2a4a2a";
        ctx.font = "10px system-ui";
        ctx.fillText(`${d / 1000}m`, cx + r + 3, cy - 3);
    }

    // Crosshairs
    ctx.strokeStyle = "#1c2e1c";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, cy - radius);
    ctx.lineTo(cx, cy + radius);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(cx - radius, cy);
    ctx.lineTo(cx + radius, cy);
    ctx.stroke();

    // Scan points
    points.forEach(([angle, dist]) => {
        if (dist < 80 || dist > MAX_DIST_MM) return;

        // Angle 0° = forward (top of canvas)
        const rad = (angle - 90) * (Math.PI / 180);
        const px = cx + Math.cos(rad) * dist * scale;
        const py = cy + Math.sin(rad) * dist * scale;

        // Color: red (close) → yellow → green (far)
        const t = dist / MAX_DIST_MM; // 0 = close, 1 = far
        const r = Math.round(255 * (1 - t));
        const g = Math.round(210 * t + 45);
        ctx.fillStyle = `rgb(${r},${g},30)`;
        ctx.fillRect(px - 1.5, py - 1.5, 3, 3);
    });

    // Robot indicator
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(cx, cy, 5, 0, Math.PI * 2);
    ctx.fill();

    // Forward direction tick
    ctx.strokeStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy - 5);
    ctx.lineTo(cx, cy - 18);
    ctx.stroke();
}

// ── Ball overlay canvas ───────────────────────────────────────────────────────

const ballCanvas = document.getElementById("ball-canvas");
const ballCtx = ballCanvas.getContext("2d");

// Maps French colour names to CSS colours matching the robot palette
const BALL_COLORS = {
    Rouge: "#ff4444",
    Vert: "#44cc44",
    Bleu: "#5588ff",
    Jaune: "#ffff44",
    Orange: "#ff8822",
    Blanc: "#e0e0e0",
    Inconnu: "#808080",
};

/**
 * Draw bounding boxes for detected balls on the overlay canvas.
 *
 * The camera img uses object-fit:contain, so the rendered image may be
 * letter-boxed inside its container. We compute the same scale/offset that
 * the browser uses so the boxes line up with the actual pixels.
 */
function drawBalls(balls) {
    const img = document.getElementById("camera-feed");
    const containerW = img.clientWidth;
    const containerH = img.clientHeight;

    // Resize the canvas to always match the container
    ballCanvas.width = containerW;
    ballCanvas.height = containerH;
    ballCtx.clearRect(0, 0, containerW, containerH);

    if (!balls.length) return;

    // Natural (source) dimensions — fall back to stream resolution
    const naturalW = img.naturalWidth || 640;
    const naturalH = img.naturalHeight || 480;

    // Replicate object-fit:contain scaling
    const scale = Math.min(containerW / naturalW, containerH / naturalH);
    const renderedW = naturalW * scale;
    const renderedH = naturalH * scale;
    const offsetX = (containerW - renderedW) / 2;
    const offsetY = (containerH - renderedH) / 2;

    balls.forEach((ball) => {
        const [x1, y1, x2, y2] = ball.bbox;
        const color = BALL_COLORS[ball.color] ?? BALL_COLORS.Inconnu;

        // Map source pixel coordinates → canvas coordinates
        const bx = offsetX + x1 * scale;
        const by = offsetY + y1 * scale;
        const bw = (x2 - x1) * scale;
        const bh = (y2 - y1) * scale;

        // Bounding box
        ballCtx.strokeStyle = color;
        ballCtx.lineWidth = 2;
        ballCtx.strokeRect(bx, by, bw, bh);

        // Corner accent marks (top-left and bottom-right)
        const tick = Math.min(bw, bh) * 0.18;
        ballCtx.lineWidth = 3;
        ballCtx.beginPath();
        ballCtx.moveTo(bx, by + tick);
        ballCtx.lineTo(bx, by);
        ballCtx.lineTo(bx + tick, by);
        ballCtx.moveTo(bx + bw - tick, by + bh);
        ballCtx.lineTo(bx + bw, by + bh);
        ballCtx.lineTo(bx + bw, by + bh - tick);
        ballCtx.stroke();

        // Centre crosshair
        const [cx, cy] = ball.center;
        const px = offsetX + cx * scale;
        const py = offsetY + cy * scale;
        const arm = 5;
        ballCtx.lineWidth = 1.5;
        ballCtx.beginPath();
        ballCtx.moveTo(px - arm, py);
        ballCtx.lineTo(px + arm, py);
        ballCtx.moveTo(px, py - arm);
        ballCtx.lineTo(px, py + arm);
        ballCtx.stroke();

        // Label — semi-transparent pill behind text
        const label = `${ball.color}  c=${ball.circularity.toFixed(2)}`;
        ballCtx.font = "bold 11px 'IBM Plex Mono', monospace";
        const textW = ballCtx.measureText(label).width;
        const pillX = bx;
        const pillY = by > 20 ? by - 20 : by + bh + 4;

        ballCtx.fillStyle = "rgba(0,0,0,0.65)";
        ballCtx.beginPath();
        ballCtx.roundRect(pillX, pillY, textW + 10, 16, 3);
        ballCtx.fill();

        ballCtx.fillStyle = color;
        ballCtx.fillText(label, pillX + 5, pillY + 12);
    });
}

// ── Gamepad ───────────────────────────────────────────────────────────────────

// Standard gamepad mapping indices
const GP_RT = 7; // R2 / RT  → forward
const GP_DPAD_L = 14; // D-pad left  → turn left
const GP_DPAD_R = 15; // D-pad right → turn right

const GP_DEADZONE = 0.05; // ignore trigger noise below this value

// Track active D-pad directions and last sent RT value to avoid redundant sends
const gpActive = { left: false, right: false };
let gpLastSpeed = 0;

function pollGamepad() {
    const gamepads = navigator.getGamepads ? navigator.getGamepads() : [];
    const gp = [...gamepads].find((g) => g); // use first connected gamepad

    if (gp) {
        const rtValue = gp.buttons[GP_RT]?.value ?? 0;
        const speed = rtValue > GP_DEADZONE ? rtValue : 0; // 0.0–1.0
        const wantLeft = gp.buttons[GP_DPAD_L]?.pressed ?? false;
        const wantRight = gp.buttons[GP_DPAD_R]?.pressed ?? false;

        // ── RT: analog forward speed ──────────────────────────────────────────
        if (speed !== gpLastSpeed) {
            gpLastSpeed = speed;
            if (speed > 0) {
                const x = gpActive.left ? -1 : gpActive.right ? 1 : 0;
                send({ cmd: "move", x, y: speed });
                document
                    .querySelector('.dpad-btn[data-cmd="forward"]')
                    ?.classList.add("pressed");
            } else {
                send({ cmd: "stop" });
                document
                    .querySelector('.dpad-btn[data-cmd="forward"]')
                    ?.classList.remove("pressed");
            }
        }

        // ── D-pad left ────────────────────────────────────────────────────────
        if (wantLeft !== gpActive.left) {
            gpActive.left = wantLeft;
            document
                .querySelector('.dpad-btn[data-cmd="left"]')
                ?.classList.toggle("pressed", wantLeft);
            if (gpLastSpeed > 0)
                send({ cmd: "move", x: wantLeft ? -1 : 0, y: gpLastSpeed });
            else if (wantLeft) send({ cmd: "move", x: -1, y: 0 });
            else send({ cmd: "stop" });
        }

        // ── D-pad right ───────────────────────────────────────────────────────
        if (wantRight !== gpActive.right) {
            gpActive.right = wantRight;
            document
                .querySelector('.dpad-btn[data-cmd="right"]')
                ?.classList.toggle("pressed", wantRight);
            if (gpLastSpeed > 0)
                send({ cmd: "move", x: wantRight ? 1 : 0, y: gpLastSpeed });
            else if (wantRight) send({ cmd: "move", x: 1, y: 0 });
            else send({ cmd: "stop" });
        }
    }

    requestAnimationFrame(pollGamepad);
}

window.addEventListener("gamepadconnected", (e) => {
    console.log(`Gamepad connected: ${e.gamepad.id}`);
});

window.addEventListener("gamepaddisconnected", (e) => {
    console.log(`Gamepad disconnected: ${e.gamepad.id}`);
    Object.keys(gpActive).forEach((k) => {
        if (gpActive[k]) {
            gpActive[k] = false;
            document
                .querySelector(`.dpad-btn[data-cmd="${k}"]`)
                ?.classList.remove("pressed");
        }
    });
    stopMove();
});

// ── Boot ──────────────────────────────────────────────────────────────────────

connect();
requestAnimationFrame(pollGamepad);
