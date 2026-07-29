# device/esp32_example.ino
/* Example Arduino sketch for ESP32: reads JSON lines on Serial and outputs PWM to steering servo and ESC.
 * Pins: change STEER_PWM_PIN and ESC_PWM_PIN to match wiring
 */

#include <Arduino.h>
#include <ArduinoJson.h>

const int STEER_PWM_PIN = 18; // change as needed
const int ESC_PWM_PIN = 19;   // change as needed

void setup() {
  Serial.begin(115200);
  ledcAttachPin(STEER_PWM_PIN, 0);
  ledcSetup(0, 50, 16); // 50Hz, 16-bit
  ledcAttachPin(ESC_PWM_PIN, 1);
  ledcSetup(1, 50, 16);
}

float mapNormalizedToDuty(float v) {
  // v: -1..1 -> pulse 1000..2000 us -> duty assuming 50Hz and 16-bit
  float pulse = 1500 + v * 500; // 1000..2000
  float period_us = 1000000.0 / 50.0; // 20000
  float duty = (pulse / period_us) * 65535.0;
  return duty;
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    if (line.length() < 5) return;
    StaticJsonDocument<128> doc;
    DeserializationError err = deserializeJson(doc, line);
    if (err) return;
    float steer = doc.containsKey("steer") ? doc["steer"].as<float>() : 0.0;
    float throttle = doc.containsKey("throttle") ? doc["throttle"].as<float>() : 0.0;
    uint32_t duty_steer = (uint32_t)mapNormalizedToDuty(steer);
    uint32_t duty_esc = (uint32_t)mapNormalizedToDuty(throttle);
    ledcWrite(0, duty_steer);
    ledcWrite(1, duty_esc);
  }
}
