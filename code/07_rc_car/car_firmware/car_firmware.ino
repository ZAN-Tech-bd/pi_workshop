/* Module 7 — RC car firmware: the muscles (evolves the ZAN Tech RC-101 code).
 *
 * Same course rule as the arm: the Nano stays THIN. It accepts two protocols:
 *
 *   1. The classic RC-101 single characters (phone app compatible):
 *        F forward   B backward   L left   R right   S stop
 *        G front-left  I front-right  H back-left  J back-right
 *        1..9, q  set cruise speed for direction keys
 *
 *   2. Line protocol from the Pi (newline-terminated, gets replies):
 *        D,<left>,<right>\n   signed motor powers -255..255
 *        PING\n               -> OK   (link check)
 *        bad / out of range   -> ERR
 *
 * FAIL-SAFE: no valid command for FAILSAFE_MS -> car stops. A moving robot
 * must never keep driving when its brain goes quiet.
 *
 * Wiring (RC Car 101 kit — L298N to Arduino):
 *   ENA->5 (left speed) IN1->6 IN2->7 (left dir) IN3->8 IN4->9 (right dir)
 *   ENB->10 (right speed); L298N GND with Arduino GND; motors on their own
 *   battery — never from the Arduino 5 V pin.
 *
 * Upload with the HC-05/06 TX+RX UNPLUGGED (pins 0/1), like any RC-101 build.
 * BAUD: 115200 for the Pi over USB. Using the HC-05 phone app instead?
 * Set BAUD 9600 (HC-05 default).
 */

#define ENA 5
#define IN1 6
#define IN2 7
#define IN3 8
#define IN4 9
#define ENB 10

#define BAUD 115200
const unsigned long FAILSAFE_MS = 900;

int cruise = 180;                 // PWM for direction keys (1..9, q scale it)
unsigned long last_cmd_ms = 0;
String line_buf = "";

void drive(int left, int right);  // signed -255..255 per side

void setup() {
  pinMode(ENA, OUTPUT); pinMode(IN1, OUTPUT); pinMode(IN2, OUTPUT);
  pinMode(IN3, OUTPUT); pinMode(IN4, OUTPUT); pinMode(ENB, OUTPUT);
  Serial.begin(BAUD);
  stopy();
  last_cmd_ms = millis();
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handle_line(line_buf);
      line_buf = "";
    } else if (c != '\r') {
      line_buf += c;
      if (line_buf.length() == 1 && !isLineProto(line_buf)) {
        // classic single char, app style — no newline, no reply
        handle_key(line_buf[0]);
        line_buf = "";
      }
    }
  }
  if (millis() - last_cmd_ms > FAILSAFE_MS) stopy();
}

bool isLineProto(String s) {
  // line messages start with D (D,...) or P (PING) — neither is a classic
  // RC-101 key, so the FIRST character alone decides the protocol
  return s[0] == 'D' || s[0] == 'P';
}

void handle_line(String s) {          // Pi protocol — answers OK / ERR
  if (s.startsWith("PING"))         { Serial.println("OK"); note(); }
  else if (s.startsWith("D,")) {
    int l, r;
    if (sscanf(s.c_str(), "D,%d,%d", &l, &r) != 2 ||
        l < -255 || l > 255 || r < -255 || r > 255) { Serial.println("ERR"); return; }
    drive(l, r);
    Serial.println("OK"); note();
  }
  else if (s.length() == 1) handle_key(s[0]);   // char sent WITH newline
  else Serial.println("ERR");
}

void handle_key(char k) {             // classic RC-101 keys
  switch (k) {
    case 'F': forward();       break;
    case 'B': backward();      break;
    case 'L': left();          break;
    case 'R': right();         break;
    case 'G': forward_left();  break;
    case 'I': forward_right(); break;
    case 'H': back_left();     break;
    case 'J': back_right();    break;
    case 'S': stopy();         break;
    case 'q': cruise = 255;    break;
    default:
      if (k >= '1' && k <= '9') cruise = 30 + (k - '1') * 25;   // 30..230
      break;
  }
  note();
}

void note() { last_cmd_ms = millis(); }

// --- one primitive: signed power per side -------------------------------
void drive(int left, int right) {
  analogWrite(ENA, abs(left));
  digitalWrite(IN1, left  > 0); digitalWrite(IN2, left  < 0);
  analogWrite(ENB, abs(right));
  digitalWrite(IN3, right > 0); digitalWrite(IN4, right < 0);
}

// --- the RC-101 vocabulary, now one line each ---------------------------
void forward()       { drive( cruise,  cruise); }
void backward()      { drive(-cruise, -cruise); }
void left()          { drive(-cruise,  cruise); }
void right()         { drive( cruise, -cruise); }
void forward_left()  { drive( cruise / 3, cruise); }
void forward_right() { drive( cruise, cruise / 3); }
void back_left()     { drive(-cruise / 3, -cruise); }
void back_right()    { drive(-cruise, -cruise / 3); }
void stopy()         { drive(0, 0); }
