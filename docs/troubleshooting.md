[← Project setup](../README.md)

# Troubleshooting

## Serial status times out

Stop the SocketCAN bridge and any serial monitor before running another serial
client. List the currently connected ports:

```bash
~/.platformio/penv/bin/python tools/dualcan.py --list-ports
```

Use the master's actual port in this command:

```bash
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 status --bus ms
```

The master firmware and host tools must agree on **57600 baud**. If the board
still has an older build, flash the current `master` environment using the
[setup instructions](../README.md#setup-and-flash). Check the USB cable and power
if the port disappears. A permission error requires access to the serial device;
on Debian/Ubuntu, check your membership in the device's `dialout` group and sign
out and back in after changing group membership.

## Master works but HS does not

`peer_online: false` is expected with only the master connected. Start the bridge
with `--bus ms` in that configuration. For HS, flash the slave environment and
check slave power, common ground, and crossed TX2/GPIO17 and RX2/GPIO16 wiring against
the [wiring guide](wiring.md). Both boards must use the same inter-board baud
(currently 115200); reflash both after changing it. The PC connection remains
57600 baud. Rising `invalid_packets` on the slave means it is rejecting new
UART input, not reporting CAN bus errors. Check the count across repeated status
requests; a single successful reply does not establish a reliable link.

## Bridge rejects an interface

```bash
ip -details link show
```

The selected interface must exist, be UP, and have type `vcan`. Create it using
the [README commands](../README.md#start-can-capture). If the name already belongs
to hardware or another application, choose a different name and pass
`--ms-interface` or `--hs-interface` to the bridge.

## No frames or transmission fails

Blank `candump` output is normal without bus traffic. Check CAN-H/CAN-L, common
ground, termination, and matching bitrates. Use the
[two-node bench procedure](bench-test.md) to send a known frame. The ESP32 needs
`--active ms` to acknowledge a bench transmitter when it is the only other node.

A local `cansend` echo does not confirm physical delivery; look for
`tx_confirmed` in bridge output. If TX is disabled after a timeout, reset, or
bus-off, resolve the cause and restart the bridge. It deliberately does not retry
an uncertain transmission. Rising loss counters indicate incomplete capture;
57600 baud cannot carry a heavily loaded CAN bus.
