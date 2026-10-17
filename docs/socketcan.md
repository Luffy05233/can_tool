[← Project setup](../README.md)

# SocketCAN commands

## Interface mapping

| Interface | Device | Physical bitrate |
| --- | --- | --- |
| `can0` | ESP32 master / MS | 125000 bit/s |
| `can1` | ESP32 slave / HS, when added | 500000 bit/s |
| `can-test` | Optional SH-C30A bench adapter | Set to match the bus being tested |

The ESP32 interfaces are `vcan` devices. Their physical bitrates are fixed in
firmware; do not apply `ip link ... type can bitrate` to them. Names can be
changed with the bridge's `--ms-interface` and `--hs-interface` options.

## Enable sending

Stop the existing bridge with Ctrl+C. For MS-CAN on a terminated bench bus:

```bash
~/.platformio/penv/bin/python tools/socketcan_bridge.py --port /dev/ttyUSB1 --bus ms --active ms
```

In another terminal:

```bash
cansend can0 123#01020304
```

`--active ms` enables CAN acknowledgement and transmission on MS. Without it,
application TX is discarded. The bus needs another active node to acknowledge
sent frames. Use `--active hs` or `--active all` for the other selections.

A successful `cansend` and local echo only mean Linux accepted the frame. Check
`tx_confirmed` in bridge output for physical transmission. A command failure,
controller reset, bus-off or missing status disables further TX on that channel
until the bridge is restarted. Uncertain transmissions are not retried.

## Add the slave

Flash the slave while individually connected to USB. Substitute its actual port:

```bash
./tools/pio run -e slave -t upload --upload-port /dev/ttyUSB0
```

Follow the [inter-board wiring and power instructions](wiring.md). Then create
its virtual interface, provided `can1` is not already occupied by another adapter:

```bash
sudo ip link add dev can1 type vcan
sudo ip link set dev can1 up
```

Stop the master-only bridge and start both channels:

```bash
~/.platformio/penv/bin/python tools/socketcan_bridge.py --port /dev/ttyUSB1 --bus all
```

Watch both:

```bash
candump can0 can1
```

The firmware never forwards traffic between the two physical buses.

## Stop and clean up

Ctrl+C stops the bridge and requests listen-only. The firmware watchdog also
returns an active channel to listen-only after three seconds without host commands.
Remove only the virtual interfaces you created:

```bash
sudo ip link set dev can0 down
sudo ip link delete dev can0
```

If you also created the slave interface:

```bash
sudo ip link set dev can1 down
sudo ip link delete dev can1
```

## Limits

- Classical CAN: standard/extended IDs, RTR, and up to eight data bytes. No CAN FD.
- PC serial: **57600 baud, 8N1**. Inter-board UART: **115200 baud, 8N1**.
  `--baud` must match the firmware's `PC_BAUD`; changing firmware settings requires reflashing.
  The inter-board rate is reduced for link troubleshooting; reflash both boards
  when changing `LINK_BAUD`. The CLI's `--baud` changes only the PC connection.
- 57600 is the reduced rate for serial troubleshooting. It cannot sustain heavily loaded CAN capture.
  The classic CP2102 is rated up to 1 Mbps; do not restore the old 2 Mbaud PC setting.
  See the [Silicon Labs datasheet](https://www.silabs.com/documents/public/data-sheets/CP2102-9.pdf).
- Virtual interfaces do not expose physical bitrate configuration, hardware
  timestamps or controller error frames. Frame timestamps reflect PC injection time.
- Capture and TX can drop frames under load. Kernel TX socket queue losses are
  not included in bridge counters. Timing-sensitive protocols need bench validation.
