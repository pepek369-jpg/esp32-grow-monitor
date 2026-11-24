#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_SHT31.h>
#include <HX711.h>
#include <ArduinoJson.h>

// --- Pin Definitions (Matching Wiring Diagram) ---
// Ultrasonic Sensors (JSN-SR04T)
#define TRIG_1 5
#define ECHO_1 18
#define TRIG_2 13   // Moved from GPIO 17 to avoid conflict with RS485_TX
#define ECHO_2 19

// Analog Water Level Sensors
#define WATER_LVL_1 36
#define WATER_LVL_2 39

// Load Cells (HX711)
#define HX1_DT 32
#define HX1_SCK 33
#define HX2_DT 25
#define HX2_SCK 26

// RS485 Soil Probe (MAX485 via Serial2)
#define RS485_RX 16
#define RS485_TX 17
#define RS485_DE_RE 4

// --- Sensor Objects ---
Adafruit_SHT31 sht35_1 = Adafruit_SHT31();
Adafruit_SHT31 sht35_2 = Adafruit_SHT31();
HX711 scale1;
HX711 scale2;

// Calibration factors for 100kg load cells (adjust after calibration)
float calibration_factor_1 = -21500.0;
float calibration_factor_2 = -21500.0;

// Modbus RTU query frame for RS485 Soil Probe (Address 0x01, Read Holding Registers)
const byte soil_query[] = {0x01, 0x03, 0x00, 0x00, 0x00, 0x04, 0x44, 0x09};

float readUltrasonic(int trigPin, int echoPin) {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH, 30000); // 30ms timeout
  if (duration == 0) return -1.0;
  return duration * 0.0343 / 2.0; // Distance in cm
}

void readSoilProbe(float &moisture, float &temp, float &ec, float &ph) {
  digitalWrite(RS485_DE_RE, HIGH); // Enable TX
  delay(2);
  Serial2.write(soil_query, sizeof(soil_query));
  Serial2.flush();
  digitalWrite(RS485_DE_RE, LOW);  // Enable RX

  unsigned long startTime = millis();
  byte response[13];
  int idx = 0;

  while (millis() - startTime < 200 && idx < 13) {
    if (Serial2.available()) {
      response[idx++] = Serial2.read();
    }
  }

  if (idx >= 11 && response[0] == 0x01 && response[1] == 0x03) {
    moisture = ((response[3] << 8) | response[4]) / 10.0;
    temp     = ((response[5] << 8) | response[6]) / 10.0;
    ec       = ((response[7] << 8) | response[8]);
    ph       = ((response[9] << 8) | response[10]) / 10.0;
  } else {
    moisture = -1.0;
    temp = -1.0;
    ec = -1.0;
    ph = -1.0;
  }
}

void setup() {
  Serial.begin(115200);
  Wire.begin();

  // RS485 setup
  pinMode(RS485_DE_RE, OUTPUT);
  digitalWrite(RS485_DE_RE, LOW);
  Serial2.begin(4800, SERIAL_8N1, RS485_RX, RS485_TX);

  // Ultrasonic pins
  pinMode(TRIG_1, OUTPUT);
  pinMode(ECHO_1, INPUT);
  pinMode(TRIG_2, OUTPUT);
  pinMode(ECHO_2, INPUT);

  // SHT35 initialization (0x44 and 0x45)
  sht35_1.begin(0x44);
  sht35_2.begin(0x45);

  // HX711 initialization
  scale1.begin(HX1_DT, HX1_SCK);
  scale1.set_scale(calibration_factor_1);
  scale1.tare();

  scale2.begin(HX2_DT, HX2_SCK);
  scale2.set_scale(calibration_factor_2);
  scale2.tare();
}

void loop() {
  // Check for serial commands (non-blocking)
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd == "TARE1") {
      scale1.tare();
      Serial.println("{\"status\":\"tare1_ok\"}");
    } else if (cmd == "TARE2") {
      scale2.tare();
      Serial.println("{\"status\":\"tare2_ok\"}");
    }
  }

  StaticJsonDocument<512> doc;

  // 1. Ultrasonic distances (cm)
  doc["dist_1_cm"] = round(readUltrasonic(TRIG_1, ECHO_1) * 10) / 10.0;
  doc["dist_2_cm"] = round(readUltrasonic(TRIG_2, ECHO_2) * 10) / 10.0;

  // 2. Water level analog readings (0 - 4095 mapped to %)
  int rawWater1 = analogRead(WATER_LVL_1);
  int rawWater2 = analogRead(WATER_LVL_2);
  doc["water_1_pct"] = map(constrain(rawWater1, 0, 4095), 0, 4095, 0, 100);
  doc["water_2_pct"] = map(constrain(rawWater2, 0, 4095), 0, 4095, 0, 100);

  // 3. SHT35 Temp & Humidity
  doc["temp_1_c"] = round(sht35_1.readTemperature() * 10) / 10.0;
  doc["hum_1_pct"] = round(sht35_1.readHumidity() * 10) / 10.0;
  doc["temp_2_c"] = round(sht35_2.readTemperature() * 10) / 10.0;
  doc["hum_2_pct"] = round(sht35_2.readHumidity() * 10) / 10.0;

  // 4. Load Cells (kg)
  float weight1 = scale1.is_ready() ? scale1.get_units(3) : 0.0;
  float weight2 = scale2.is_ready() ? scale2.get_units(3) : 0.0;
  doc["weight_1_kg"] = round(weight1 * 100) / 100.0;
  doc["weight_2_kg"] = round(weight2 * 100) / 100.0;

  // 5. RS485 Soil Probe
  float s_moist, s_temp, s_ec, s_ph;
  readSoilProbe(s_moist, s_temp, s_ec, s_ph);
  doc["soil_moist_pct"] = s_moist;
  doc["soil_temp_c"] = s_temp;
  doc["soil_ec_us"] = s_ec;
  doc["soil_ph"] = s_ph;

  // Send JSON line over USB Serial
  serializeJson(doc, Serial);
  Serial.println();

  delay(1000); // 1 second update interval
}
