/* Module 3 — 4-DOF arm firmware: the muscles (deck slide 29, slide 36).
 *
 * The Arduino stays THIN on purpose: it parses a line, clamps the angles,
 * ramps the servos smoothly, and answers OK. All the thinking (vision, IK,
 * sequences) lives on the Pi — so we never re-flash this while tuning.
 *
 * Protocol (115200, one message per line):
 *   J,<base>,<shoulder>,<elbow>,<gripper>   move joints, degrees
 *   H                                       go to home pose
 *   OK  / ERR                               replies
 *
 * Wiring (signal only — servos need their OWN 5-6 V supply, see docs):
 *   D3 base   D5 shoulder   D6 elbow   D9 gripper
 *   Servo GND and Nano GND must join the supply GND (common ground!).
 */

#include <Servo.h>

// ---- pins -----------------------------------------------------------------
const int PIN_BASE = 3, PIN_SHOULDER = 5, PIN_ELBOW = 6, PIN_GRIP = 9;

// ---- safe ranges (degrees) — edit after calibrating YOUR arm ---------------
const int MIN_B = 0,   MAX_B = 180;
const int MIN_S = 15,  MAX_S = 165;
const int MIN_E = 0,   MAX_E = 160;
const int MIN_G = 20,  MAX_G = 100;

// ---- home pose --------------------------------------------------------------
const int HOME_B = 90, HOME_S = 90, HOME_E = 90, HOME_G = 30;

// ---- ramp speed: milliseconds per degree. smaller = faster = more jitter ---
const int STEP_MS = 15;

Servo base, shoulder, elbow, grip;
int pos[4];  // where the servos were last told to go

int clampi(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

void moveTo(int b, int s, int e, int g) {
  int target[4] = { b, s, e, g };
  int start[4];
  for (int i = 0; i < 4; i++) start[i] = pos[i];

  // longest joint travel decides how many steps; all joints move together
  int steps = 0;
  for (int i = 0; i < 4; i++) {
    int d = abs(target[i] - start[i]);
    if (d > steps) steps = d;
  }
  for (int n = 1; n <= steps; n++) {
    int t[4];
    for (int i = 0; i < 4; i++)
      t[i] = start[i] + (long)(target[i] - start[i]) * n / steps;
    base.write(t[0]); shoulder.write(t[1]); elbow.write(t[2]); grip.write(t[3]);
    delay(STEP_MS);
  }
  for (int i = 0; i < 4; i++) pos[i] = target[i];
}

void setup() {
  base.attach(PIN_BASE);
  shoulder.attach(PIN_SHOULDER);
  elbow.attach(PIN_ELBOW);
  grip.attach(PIN_GRIP);
  pos[0] = HOME_B; pos[1] = HOME_S; pos[2] = HOME_E; pos[3] = HOME_G;
  moveTo(pos[0], pos[1], pos[2], pos[3]);   // start from a known pose
  Serial.begin(115200);
}

void loop() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();

  if (line == "H") {
    moveTo(HOME_B, HOME_S, HOME_E, HOME_G);
    Serial.println("OK");
    return;
  }

  if (line.startsWith("J,")) {
    int b, s, e, g;
    if (sscanf(line.c_str(), "J,%d,%d,%d,%d", &b, &s, &e, &g) != 4 ||
        b < 0 || b > 180 || s < 0 || s > 180 ||
        e < 0 || e > 180 || g < 0 || g > 180) {
      Serial.println("ERR");                // unreadable or impossible angle
      return;
    }
    // inside 0..180: pull into each joint's SAFE range, then move
    moveTo(clampi(b, MIN_B, MAX_B), clampi(s, MIN_S, MAX_S),
           clampi(e, MIN_E, MAX_E), clampi(g, MIN_G, MAX_G));
    Serial.println("OK");
    return;
  }

  Serial.println("ERR");                    // anything else is not our protocol
}
