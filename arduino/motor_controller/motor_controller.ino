#include <AFMotor.h>

#define TRIG_PIN 9
#define ECHO_PIN 10
#define SEUIL_OBSTACLE 20
#define LARGEUR_DEPASSEMENT 30

AF_DCMotor m1(1), m2(2), m3(3), m4(4);
int vitesse = 200;

// ── Primitives
// ────────────────────────────────────────────────────────────────

void stop() {
  m1.run(RELEASE);
  m2.run(RELEASE);
  m3.run(RELEASE);
  m4.run(RELEASE);
}

// Real-time differential drive: left/right in range -255..255
void setMotors(int left, int right) {
  left = constrain(left, -255, 255);
  right = constrain(right, -255, 255);

  m1.setSpeed(abs(left));
  m2.setSpeed(abs(right));
  m3.setSpeed(abs(left));
  m4.setSpeed(abs(right));

  if (left == 0) {
    m1.run(RELEASE);
    m3.run(RELEASE);
  } else if (left > 0) {
    m1.run(FORWARD);
    m3.run(FORWARD);
  } else {
    m1.run(BACKWARD);
    m3.run(BACKWARD);
  }

  if (right == 0) {
    m2.run(RELEASE);
    m4.run(RELEASE);
  } else if (right > 0) {
    m2.run(FORWARD);
    m4.run(FORWARD);
  } else {
    m2.run(BACKWARD);
    m4.run(BACKWARD);
  }
}

// ── Obstacle helper
// ───────────────────────────────────────────────────────────

// Stop motors and push OBSTACLE:<cm> to the Pi.
void reportObstacle(long dist) {
  stop();
  Serial.print("OBSTACLE:");
  Serial.println(dist);
}

// ── Timed moves (autonomous mode) ────────────────────────────────────────────
// Each function returns true on normal completion, false if an obstacle caused
// an early stop (motors are already released and OBSTACLE: already sent).

bool avancer(int speed, int distance) {
  setMotors(speed, speed);
  unsigned long duration = (unsigned long)distance * 10;
  delay(duration);
  stop();
  return true;
}

bool reculer(int speed, int distance) {
  setMotors(-speed, -speed);
  unsigned long duration = (unsigned long)distance * 10;
  delay(duration);
  stop();
  return true;
}

// sens: true = gauche, false = droite
bool tourner(bool sens, int speed, int angle) {
  if (sens)
    setMotors(-speed, speed);
  else
    setMotors(speed, -speed);
  unsigned long duration = (unsigned long)angle * 10;
  delay(duration);
  stop();
  return true;
}

// ── Setup / Loop
// ──────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
}

void loop() {

  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    // ── Real-time web control ──────────────────────────────────────────────
    // SET:<left>:<right>   e.g. SET:200:-200  (differential drive, -255..255)
    if (cmd.startsWith("SET:")) {
      int sep = cmd.indexOf(':', 4);
      if (sep != -1) {
        int left = cmd.substring(4, sep).toInt();
        int right = cmd.substring(sep + 1).toInt();
        setMotors(left, right);
      }
    }

    // ── Named commands (autonomous / manual) ──────────────────────────────
    else if (cmd == "STOP") {
      stop();
    } else if (cmd == "AVANCER") {
      avancer(vitesse, 100);
    } else if (cmd == "RECULER") {
      reculer(vitesse, 100);
    } else if (cmd == "TOURNER_G") {
      tourner(true, vitesse, 90);
    } else if (cmd == "TOURNER_D") {
      tourner(false, vitesse, 90);
    }
  }
}
