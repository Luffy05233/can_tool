# Bench status — 2026-10-17

This is a historical handoff, not a statement of the currently connected hardware.

## Setup

Two classic ESP32 boards with WCMCU-230 / SN65HVD230 modules. CAN TX is GPIO25,
CAN RX GPIO26. The inter-board UART is GPIO17 TX crossed to GPIO16 RX at 115200
baud. Master USB uses 57600 baud. Master/MS is 125 kbit/s; slave/HS is 500 kbit/s.
The SH-C30A gs_usb bench adapter most recently appeared as can2. The master CP2102
appeared as /dev/ttyUSB1; another USB serial device was associated with OctoPrint.
Re-identify devices before using them.

Both module R2 termination resistors were removed for vehicle capture. A separate
bench bus needs its own two endpoint terminators. The user reported a 2016 Mazda 6
GT, but vehicle connector pinout and MS physical-layer compatibility remain
unverified. Bench tests described below were separate from the vehicle.

## Observations

- Earlier master tests passed five frames in each direction at 125 kbit/s.
- A later status-only UART test passed five queries per board, with zero malformed
  USB packets and no increase in the slave's invalid-packet counter.
- Repeated slave transmission tests at 500 kbit/s returned DRIVER_ERROR (-1), with
  CAN transmit-failure/bus-error increments. This does not identify an ACK, bit,
  wiring, transceiver, timing or controller fault on its own.
- Latest independent receive test: can2 was UP at 500000 bit/s, sample point 87.5%.
  Slave was explicitly in normal/running mode at 500000 bit/s. One frame submitted
  through can2 produced zero valid slave frames, 16 new slave bus errors and a
  receive-error counter of 135. No new slave UART errors occurred.
- That receive test recorded 464 malformed USB packets. The preceding receive
  test had the same CAN failure with zero malformed USB packets. USB framing is
  therefore an intermittent additional problem, not a proven explanation for all
  CAN failures. Reinitializing the host port at 115200 and then 57600 has sometimes
  recovered communication; it is not a verified fix.
- Slave was restored to listen-only. Bringing can2 down required the user's sudo
  authentication; do not assume the adapter is stopped in a future session.

## Review and limits

Both firmware targets built successfully. Host tests passed (24 with Python/C++
interop enabled; two optional SocketCAN kernel tests skipped). No confirmed root
cause was found in the code review. No pin changes or firmware uploads were made
during the final link and receive checks.

src/main.cpp reports generic TX failures without setting last_error unless bus-off
occurs. Successful mode configuration overwrites last_error and reinstalls the
driver, resetting live TEC/REC counters. Cumulative bus-error and TX-failure counts
are retained. Read counters before cleanup; last_error=0 is not proof of success.

Useful next work: establish the powered-off termination of the complete bench
bus, compare master and slave using the same verified adapter/transceiver setup,
and investigate the receive errors and intermittent USB framing separately.
Do not infer successful vehicle operation from a working inter-board UART link.
