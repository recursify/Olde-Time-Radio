//#define DIO_0 2
//#define DIO_1 3
//#define DIO_2 4

int potPin1 = 0;
int potPin2 = 3;
int potPin3 = 5;
int potPin1_value = 0;
int potPin2_value = 0;
int potPin3_value = 0;


void setup() {
  // start serial port at 9600 bps:
  //pinMode(DIO_0, INPUT);
  //pinMode(DIO_1, INPUT);
  //pinMode(DIO_2, INPUT);
  Serial.begin(9600);
}

// This works because digital inputs are 10 bits and we convert to 8
inline char sensorToChar(int a) {
  return (char)(a >> 2);
}

void loop() {
  waitForAck();
  potPin1_value = analogRead(potPin1);
  potPin2_value = analogRead(potPin2);
  potPin3_value = analogRead(potPin3);
  sendSensorValues(potPin1_value,potPin2_value, potPin3_value);
}

void waitForAck() {
  // Wait for an ACK
  while (Serial.read() == -1) {
    delay(20);
  }
  while(Serial.read() != -1) {} // Clear the buffer, just in case we wrote too many ACKs
}

void sendSensorValues(int sensor1, int sensor2, int sensor3) {
  Serial.print(sensorToChar(sensor1), BYTE);
  Serial.print(sensorToChar(sensor2), BYTE);
  Serial.print(sensorToChar(sensor3), BYTE);
  Serial.print("\n"); // Terminating char.  On client side we can call ser.getLine()
}
