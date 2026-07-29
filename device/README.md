# device/README.md
Device integration for ALSET -> IVY

This folder contains the Raspberry Pi device and publisher scaffold to integrate the ALSET vehicle with the IVY webapp.

Structure
- vehicle_ws.py       WebSocket device client (IVY device channel)
- signal_publisher.py Direct WebRTC publisher (aiortc) using the Pi camera
- picam_track.py      picamera2 -> aiortc VideoTrack with overlay support
- esp32_comm.py       Serial-over-USB protocol to send steering/throttle to ESP32
- gps_reader.py       BN-880 NMEA parser (pynmea2)
- telemetry_client.py Telemetry queue and POST to /api/input
- menu.py             Menu state machine + overlay renderer
- vehicle_main.py     Orchestrator that wires everything together
- run.sh              Simple start script
- .env.example        Example environment variables

Installation (Raspberry Pi 5)
1. OS & prerequisites
   - Debian Bullseye / Bookworm for Pi 5 with libcamera and picamera2 support
   - Enable camera in raspi-config and enable serial (UART)

2. System packages
   sudo apt update
   sudo apt install -y python3-pip libatlas-base-dev libopenjp2-7 libavcodec-dev libavformat-dev libswscale-dev git

3. Start pigpiod if needed (ESP32 handles PWM in this design):
   sudo apt install -y pigpio
   sudo systemctl enable --now pigpiod

4. Python packages (use venv recommended)
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install av aiortc aiohttp websockets requests picamera2 numpy opencv-python pynmea2 pyserial

5. Wiring summary
   - Pi Camera (OV5647) to CSI camera connector
   - BN-880 GPS -> Pi UART (TX/RX to Pi RX/TX) and ground/power
   - ESP32 -> USB serial to Pi (shows up at /dev/ttyUSB0)
   - ESP32 controls ESC and steering servo PWM output (recommended to use separate battery for ESC)

ESP32 firmware
- ESP32 should run firmware that reads JSON lines from serial and converts {"steer": -1..1, "throttle": -1..1} to PWM for servo/ESC.
- A simple Arduino sketch is provided in the repo (see device/esp32_example.ino) — adapt your pins and calibrate pulse widths.

Running
1. Copy .env.example -> .env and edit values
2. Start device
   chmod +x device/run.sh
   ./device/run.sh

Testing
- Run in DEBUG mode to print incoming control payloads and verify mapping. Press buttons in the webapp to navigate the overlay menu and see changes on the video feed.

Notes on LiveKit vs direct WebRTC
- The code prefers a LiveKit token if IVY /api/sfu/token returns an enabled LiveKit response. Full LiveKit publishing from Python is non-trivial; the easiest path is to use IVY-provided LiveKit token with an external publisher (GStreamer/ffmpeg or a LiveKit SDK). This scaffold implements direct WebRTC signaling via IVY /signal using aiortc. See docs/LiveKit.md for more details and example commands.

Safety
- The ESC is kept neutral until commands are received. Always test with propellers or wheels disconnected.
