# device/README.md

Device integration for ALSET -> IVY

This directory contains the Raspberry Pi device/publisher scaffold to integrate the ALSET vehicle with the IVY webapp.

Structure
- vehicle_ws.py       WebSocket device client (IVY device channel)
- signal_publisher.py Direct WebRTC publisher (aiortc) using the Pi camera
- picam_track.py      picamera2 -> aiortc VideoTrack with overlay support
- esp32_comm.py       Serial-over-USB protocol to send steering/throttle to ESP32
- gps_reader.py       BN-880 NMEA parser (pynmea2)
- telemetry_client.py Telemetry queue and POST to /api/input
- menu.py             Menu state machine + overlay renderer
- mission_executor.py Mission persistence and control loop (pure-pursuit + P speed controller)
- test_mission.py     Mission simulation harness (no hardware required)
- vehicle_main.py     Orchestrator that wires everything together
- run.sh              Simple start script
- .env.example        Example environment variables

Installation (Raspberry Pi 5)
1. OS & prerequisites
   - Debian Bullseye / Bookworm for Pi 5 with libcamera and picamera2 support
   - Enable camera in raspi-config and enable serial (UART)

2. System packages
   sudo apt update
   sudo apt install -y python3-venv python3-pip libatlas-base-dev libopenjp2-7 pigpio git
   sudo systemctl enable --now pigpiod  # optional (pigpio daemon)

3. Python packages (use venv recommended)
   python3 -m venv venv
   source venv/bin/activate
   pip install --upgrade pip
   pip install av aiortc aiohttp websockets requests picamera2 numpy opencv-python pynmea2 pyserial

4. Wiring summary
   - Pi Camera (OV5647) to CSI camera connector
   - BN-880 GPS -> Pi UART (TX/RX to Pi RX/TX) OR USB-UART adapter
   - ESP32 -> USB serial to Pi (shows up at /dev/ttyUSB0)
   - ESP32 controls ESC and steering servo PWM output (use a proper BEC for servos and power ESC from battery)

ESP32 firmware
- ESP32 should run firmware that reads JSON lines from serial and converts {"steer": -1..1, "throttle": -1..1} to PWM for servo/ESC.
- A simple Arduino sketch is provided in the repo (device/esp32_example.ino) — adapt your pins and calibrate pulse widths.

Running
1. Copy .env.example -> .env and edit values
   cp device/.env.example device/.env
   # Edit device/.env: set DEVICE_WS, SIGNAL_URL, TELEMETRY_URL, VEHICLE_ID, DEVICE_ID, DEVICE_SHARED_SECRET, GPS_DEVICE, ESP32_SERIAL etc.

2. Activate venv and run
   source venv/bin/activate
   cd device
   chmod +x run.sh
   ./run.sh

What the device runs
- GPS reader (device/gps_reader.py) — reads BN-880 NMEA and exposes robot.gps.latest
- ESP32 comm (device/esp32_comm.py) — sends JSON lines to the ESP32; supports arm()/disarm(), safe_send(), estop latching
- Telemetry client (device/telemetry_client.py) — background POST queue to /api/input
- Picamera2 publisher (device/picam_track.py + device/signal_publisher.py) — frame overlays and WebRTC
- Mission executor (device/mission_executor.py) — mission persistence and execution
- Device WebSocket client (device/vehicle_ws.py) — HMAC device_hello and control/mission handling

Controller mapping & menu usage (default Gamepad API mapping)
| Control | Ivy array | Vehicle action |
| --- | --- | --- |
| R2 | `buttons[7]` | throttle |
| L2 | `buttons[6]` | brake |
| Left stick X | `axes[0]` | steering |
| R1 | `buttons[5]` | gear up |
| L1 | `buttons[4]` | gear down |
| R1 + L1 | `buttons[5] + buttons[4]` | neutral |
| PS button | `buttons[16]` | latched estop |
| Pause/options | `buttons[9]` | pause input, sends neutral while held/toggled |
| Share/create | `buttons[8]` | auto/manual mode request |
| D-pad up/down | `buttons[12]`,`buttons[13]` | menu cursor up/down |
| D-pad right/left | `buttons[15]`,`buttons[14]` | expand/exit menu |
| X | `buttons[0]` | accept menu item |
| O | `buttons[1]` | cancel/back |
| Right stick | `axes[2]`,`axes[3]` | optional camera gimbal pan/tilt |

Menu overlay & interaction
- The menu is rendered into the video stream on the Pi and is controlled via the same gamepad messages.
- Default options:
  - Drive mode: `manual`, `auto`
  - Gear: `R`, `N`, `1`, `2`, `3`, `4`
  - Path following: `hold`, `follow`
  - AI lane assist: `off`, `on`
  - AI sign detect: `off`, `on`
  - AI obstacle guard: `off`, `on`
  - Lights: `off`, `on`
  - HUD: `full`, `minimal`, `hidden`
  - Preprogrammed motion: `idle`, `steering sweep`, `slow roll`, `brake pulse`
  - Camera profile: `480p`, `720p`, `1080p`
  - Overlay class: `hud`, `menu`, `alerts`, `debug`, `route`
  - Estop: `latched`, `clear`
  - Debug: `off`, `on`

Navigation:
- D-pad up/down shows the menu if hidden and moves the cursor.
- D-pad right shows the menu and expands the selected option.
- D-pad up/down while expanded changes that option value.
- X accepts the selected value. For preprogrammed motions, X starts the motion.
- D-pad left collapses an expanded option; if nothing is expanded it hides the menu.
- O cancels/back and hides the menu.

Arming, safety & heartbeat
- ESC arming is required before non-zero throttle is accepted. Arm via menu option or dedicated button combo (configured).
- Arming sends neutral pulses for ESC arming then sets `esp.armed = True`.
- Disarm sends neutral and clears `esp.armed`.
- PS button latches estop immediately; estop prevents arming and forces neutral until cleared.
- SafetyMonitor (device/safety.py) checks last control message timestamp and if no control message is received in `CONTROL_HEARTBEAT_MS` (default 1500ms) executes `SAFETY_ACTION` (neutral|disarm|estop).
- Brake (L2) always wins over throttle. Reverse requires gear = R.

Missions (waypoints)
- Missions are received as WebSocket 'mission' messages and are validated and persisted in `device/missions/`.
- MissionExecutor runs a 20Hz control loop using GPS and computes steering (pure pursuit-like) and throttle (P controller) and sends commands with `esp.safe_send()`.
- Arrival: when distance ≤ arrivalRadiusM the vehicle stops, loiters if configured, then advances to the next waypoint.
- AI assists (lane assist, obstacle guard, sign detection) blend into steering/throttle and can override if needed.
- Mission progress is sent to telemetry for server visibility.

Testing & tuning
- Simulate a mission without hardware:
  source venv/bin/activate
  python3 device/test_mission.py
- Bench test (hardware connected but motors disconnected): verify steering pulses and throttle remain neutral until armed.
- Field test: low MAX_THROTTLE and short mission. Tune KP_SPEED and LOOKAHEAD_M.

LiveKit publishing
- Device requests /api/sfu/token. If enabled:true & provider=livekit the device attempts to spawn the helper `device/publish_livekit.sh` with LIVEKIT_URL and LIVEKIT_TOKEN in the env.
- If LiveKit is not configured, the device falls back to direct /signal aiortc publisher.

Troubleshooting
- Camera: try `libcamera-hello` and picamera2 examples
- GPS: verify wiring and use a USB-UART adapter if serial is occupied
- ESP32: check `/dev/ttyUSB0` and baud; use serial monitor to debug
- ESC: test with motors disconnected and confirm neutral pulses during arming
- LiveKit: ensure server returns token with enabled:true and provides a token + url

Contributing & next steps
- Add persistent config file support (config.yml)
- Add visual route overlay with lookahead and local path (useful for tuning)
- Add mission resume on boot

