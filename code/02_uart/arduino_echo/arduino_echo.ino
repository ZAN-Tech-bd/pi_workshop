/* Task 2.4 — Arduino: read a line, answer with an ack (deck slide 25).
 * Upload, then talk to it:
 *   - from the Pi:  python3 pi_send.py
 *   - or monitor:   arduino-cli monitor -c arduino:avr:nano -p /dev/ttyUSB0
 * Sends back every line you send, prefixed with ACK:.
 */
void setup() {
  Serial.begin(115200);
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    Serial.print("ACK:");
    Serial.println(line);
  }
}
