[← Project setup](../README.md)

# Bench test with the SH-C30A

Use the SH-C30A as a second CAN node to send a known frame to the ESP32 master.
Its standard candleLight firmware supports Linux SocketCAN.
[Manufacturer information](https://www.deshide.com/product-details_SH-C30A.html)

## 1. Wire the two nodes

Power both devices through USB. Connect to the ESP32's **SN65HVD230 transceiver**,
not directly to ESP32 GPIO pins:

| SH-C30A | SN65HVD230 module |
| --- | --- |
| CAN_H | CAN_H |
| CAN_L | CAN_L |
| GND | GND |

Use 120 Ω termination at each end. Enable the SH-C30A's termination switch and
check whether the SN65HVD230 module already has a 120 Ω resistor before adding one.
See [ESP32-to-transceiver wiring](wiring.md).

## 2. Identify the SH-C30A interface

With the ESP32's virtual `can0` already created, compare the output before and
after plugging in the SH-C30A:

```bash
ip -details link show
```

The newly appearing hardware interface might be `can1`. Confirm it is the
SH-C30A, not an existing virtual slave interface. If no CAN interface appears,
check the device's firmware/driver before continuing.

The following commands assume the SH-C30A appeared as **`can1`**. Substitute its
actual name. Rename it to `can-test` so it does not conflict with the future slave:

```bash
sudo ip link set dev can1 down
sudo ip link set dev can1 name can-test
sudo ip link set dev can-test type can bitrate 125000
sudo ip link set dev can-test up
```

This bitrate command applies to the SH-C30A hardware, not the ESP32's virtual `can0`.

## 3. Start the ESP32 bridge

Stop any existing bridge first. In terminal 1:

```bash
~/.platformio/penv/bin/python tools/socketcan_bridge.py --port /dev/ttyUSB1 --bus ms --active ms
```

The `--active ms` option lets the ESP32 acknowledge the SH-C30A's frames.
A listen-only ESP32 will not ACK a two-node bench transmitter.

## 4. Receive and send

In terminal 2, watch the ESP32 side:

```bash
candump can0
```

In terminal 3, send one frame through the SH-C30A:

```bash
cansend can-test 123#01020304
```

Expected in terminal 2:

```text
can0  123   [4]  01 02 03 04
```

Seeing the frame on `can0` confirms it crossed the physical bus and the ESP32
serial bridge. Watching `can-test` alone could just show the sender's local echo.

## 5. Finish

Stop the bridge with Ctrl+C. Bring the test adapter down:

```bash
sudo ip link set dev can-test down
```

The hardware interface disappears when unplugged. See [manual virtual-interface
cleanup](socketcan.md#stop-and-clean-up) for `can0`.
