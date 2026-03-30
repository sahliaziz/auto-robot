#include <AFMotor.h>

#define TRIG_PIN 9
#define ECHO_PIN 10
#define SEUIL_OBSTACLE 20
#define LARGEUR_DEPASSEMENT 30

AF_DCMotor m1(1), m2(2), m3(3), m4(4);
int vitesse = 150;

// ── Primitives ────────────────────────────────────────────────────────────────

void stop() {
  m1.run(RELEASE);
  m2.run(RELEASE);
  m3.run(RELEASE);
  m4.run(RELEASE);
}

// Real-time differential drive: left/right in range -255..255
void setMotors(int left, int right) {
  left  = constrain(left,  -255, 255);
  right = constrain(right, -255, 255);

  m1.setSpeed(abs(left));
  m2.setSpeed(abs(left));
  m3.setSpeed(abs(right));
  m4.setSpeed(abs(right));

  if (left == 0) { m1.run(RELEASE); m2.run(RELEASE); }
  else if (left > 0) { m1.run(FORWARD);  m2.run(FORWARD); }
  else               { m1.run(BACKWARD); m2.run(BACKWARD); }

  if (right == 0) { m3.run(RELEASE); m4.run(RELEASE); }
  else if (right > 0) { m3.run(FORWARD);  m4.run(FORWARD); }
  else                { m3.run(BACKWARD); m4.run(BACKWARD); }
}

// ── Timed moves (autonomous mode) ────────────────────────────────────────────

void avancer(int speed, int distance) {
  setMotors(speed, speed);
  delay(distance * 10);
  stop();
}

void reculer(int speed, int distance) {
  setMotors(-speed, -speed);
  delay(distance * 10);
  stop();
}

// sens: true = gauche, false = droite
void tourner(bool sens, int speed, int angle) {
  if (sens) setMotors(-speed,  speed);
  else      setMotors( speed, -speed);
  delay(angle * 10);
  stop();
}

// ── Sensors ───────────────────────────────────────────────────────────────────

long mesureDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duree = pulseIn(ECHO_PIN, HIGH, 30000);
  return duree * 0.034 / 2;
}

// ── Autonomous behaviours ─────────────────────────────────────────────────────

void contourner_obstacle(bool sens) {
  tourner(sens, vitesse, 90);
  avancer(vitesse, LARGEUR_DEPASSEMENT);
  tourner(!sens, vitesse, 90);
  while (mesureDistance() < SEUIL_OBSTACLE) {
    avancer(vitesse, 10);
  }
  avancer(vitesse, LARGEUR_DEPASSEMENT);
  tourner(!sens, vitesse, 90);
  avancer(vitesse, LARGEUR_DEPASSEMENT);
  tourner(sens, vitesse, 90);
}

// ── Setup / Loop ──────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
}

void loop() {
  // Periodically push ultrasonic distance so the Pi can read it
  static unsigned long lastSensor = 0;
  if (millis() - lastSensor > 200) {
    lastSensor = millis();
    Serial.print("DIST:");
    Serial.println(mesureDistance());
  }

  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    // ── Real-time web control ──────────────────────────────────────────────
    // SET:<left>:<right>   e.g. SET:200:-200  (differential drive, -255..255)
    if (cmd.startsWith("SET:")) {
      int sep = cmd.indexOf(':', 4);
      if (sep != -1) {
        int left  = cmd.substring(4, sep).toInt();
        int right = cmd.substring(sep + 1).toInt();
        setMotors(left, right);
      }
    }

    // ── Named commands (autonomous / manual) ──────────────────────────────
    else if (cmd == "STOP")        { stop(); }
    else if (cmd == "AVANCER")     { avancer(vitesse, 100); }
    else if (cmd == "RECULER")     { reculer(vitesse, 100); }
    else if (cmd == "TOURNER_G")   { tourner(true,  vitesse, 90); }
    else if (cmd == "TOURNER_D")   { tourner(false, vitesse, 90); }
    else if (cmd == "CONTOURNER_G"){ contourner_obstacle(true); }
    else if (cmd == "CONTOURNER_D"){ contourner_obstacle(false); }
  }
}
