# CAN Tools project guidance

## Start here

Read README.md and docs/development.md. For hardware diagnosis, also read
docs/wiring.md and docs/bench-status.md. Keep the latest user's instructions
and authorizations in scope; do not repeatedly ask for permission already given.

## Project map

- src/main.cpp: shared ESP32 firmware, CAN controller and UART routing.
- include/config.h and platformio.ini: master/slave roles, pins and speeds.
- include/protocol.h and tools/can_protocol.py: matching wire protocols.
- tools/dualcan.py: serial CLI; tools/link_check.py: status-only link test.
- tools/socketcan_bridge.py: SocketCAN bridge for SavvyCAN and Linux tools.
- test/: host tests; these do not prove physical CAN operation.
- CANdevStudio-qt6/: locally adapted Qt 6 CANdevStudio and bundled dependencies.
- linux can tools/can-utils/: bundled upstream Linux CAN utilities.
- integrations/clickup/: optional helper; credentials live outside this repo.

## Hardware contract

- Classic ESP32: CAN TX GPIO25, CAN RX GPIO26 on each board.
- Inter-board UART: TX GPIO17 crossed to the other board's RX GPIO16; common GND.
- UART link 115200 baud; master USB serial 57600 baud, both 8N1.
- Master/MS CAN 125000 bit/s; slave/HS CAN 500000 bit/s.
- Default CAN mode is listen-only. Preserve the active-mode watchdog, single-shot
  transmission and separate queued acknowledgement/final transmission result.
- Keep C++ and Python protocol changes synchronized. Keep pin changes synchronized
  across build flags, config defaults and documentation.

## Development and checks

Use Python 3, g++, and PlatformIO. Fresh environment setup is in docs/codex.md.
Run from the repository root:

```bash
python3 -m unittest discover -s test -v
g++ -std=c++11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -Iinclude test/protocol_test.cpp -o /tmp/can-tools-protocol-test
ASAN_OPTIONS=detect_leaks=0 /tmp/can-tools-protocol-test
ASAN_OPTIONS=detect_leaks=0 CPP_PROTOCOL_TEST=/tmp/can-tools-protocol-test python3 -m unittest discover -s test -v
./tools/pio run -e master -e slave
```

The sanitizer setting avoids LeakSanitizer's ptrace restriction; address and UB
checks remain enabled. The two kernel integration tests require dedicated UP
vcan interfaces; do not point them at a live hardware bridge. Build both firmware
targets after shared firmware changes. Run relevant checks for host changes.
Qt 6 changes use the build and test instructions in CANdevStudio-qt6/README.md.

## Hardware work and reporting

Cloud host tests can run without USB devices. Do not claim flashing, CAN reception
or vehicle validation from a successful build or mocked test. Identify the current
serial device and board role before flashing; /dev/ttyUSB numbers can change.
Use the user's authorized isolated bench setup for active transmission tests.
Keep vehicle capture listen-only unless the user explicitly requests otherwise.
Restore listen-only after active bench tests, and stop a test adapter that is
retrying failed transmissions when possible. Report cleanup requiring local sudo.
Capture fault counters before changing CAN mode, because mode changes reset live
controller counters. Separate USB/UART framing faults from CAN bus faults.

Do not commit credentials, virtual environments, firmware binaries or build trees.
Preserve bundled source licenses and local Qt 6 changes. The GitHub snapshot vendors
nested dependencies as files, not submodule links; do not replace them with upstream
versions as a routine cleanup. Do not post ClickUp comments unless requested.
