[← Project setup](../README.md)

# Project files and development

| Path | Purpose |
| --- | --- |
| `platformio.ini` | ESP32 master and slave build targets and pin settings |
| `src/main.cpp` | CAN controller, UART transport, command handling and watchdog |
| `include/config.h` | Bus rates, timeouts and pin checks |
| `include/protocol.h` | Firmware packet framing, CRC and CAN frame encoding |
| `tools/can_protocol.py` | Matching Python protocol implementation |
| `tools/dualcan.py` | Serial status, monitor and single-frame transmission CLI |
| `tools/socketcan_bridge.py` | Serial-to-SocketCAN bridge |
| `test/` | Host protocol, client, bridge and optional kernel integration checks |

Run commands from the project root. Build both firmware targets without flashing:

```bash
./tools/pio run -e master -e slave
```

Run the Python unit tests:

```bash
python3 -m unittest discover -s test -v
```

Compile and run the C++ protocol checks, then enable cross-language checks:

```bash
g++ -std=c++11 -Wall -Wextra -Werror -fsanitize=address,undefined -fno-omit-frame-pointer -Iinclude test/protocol_test.cpp -o /tmp/can-tools-protocol-test
/tmp/can-tools-protocol-test
CPP_PROTOCOL_TEST=/tmp/can-tools-protocol-test python3 -m unittest discover -s test -v
```

Under a debugger or sandbox that prevents LeakSanitizer from inspecting the
process, prefix the last two commands with `ASAN_OPTIONS=detect_leaks=0`.
AddressSanitizer and UndefinedBehaviorSanitizer remain enabled.

The two kernel integration tests are skipped unless
`SOCKETCAN_TEST_INTERFACES` names two dedicated, UP `vcan` devices, separated by a
comma. These tests inject frames; use isolated test interfaces, never interfaces
connected to a running hardware bridge. The CLI integration test also needs
`candump`, `cansend`, and pyserial in the Python environment running the tests.

Builds and host tests do not verify physical wiring, CAN acknowledgement, or
capture performance. Complete the [bench test](bench-test.md) on the actual
boards before relying on hardware operation.

## Desktop image assets

Bundled PNG artwork and demo screenshots are intentionally excluded from the
GitHub snapshot and retained only in the original local workspace. A fresh clone
needs the original CANdevStudio PNG assets restored before building the desktop
application. The excluded paths are listed in the root `.gitignore`. ESP32
firmware and Python tools do not depend on these images.
