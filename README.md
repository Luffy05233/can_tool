# Dual ESP32 CAN adapter

One USB connection, two independent Classical CAN buses: **master = MS at
125 kbit/s**, **slave = HS at 500 kbit/s**. Start with the master only.

## Index

- [Setup and flash](#setup-and-flash)
- [Check the master](#check-the-master)
- [Flash and check both boards](#flash-and-check-both-boards)
- [Start CAN capture](#start-can-capture)
- [SavvyCAN setup on Linux](#savvycan-setup-on-linux)
- [Car-test recording to CSV](#car-test-recording-to-csv)
- [Stop and clean up](#stop-and-clean-up)
- [Wiring and power](docs/wiring.md)
- [SocketCAN commands: sending, slave, shutdown](docs/socketcan.md)
- [Bench test with the SH-C30A](docs/bench-test.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Project files and development](docs/development.md)
- [Codex workspace setup](docs/codex.md)
- [Latest bench-test handoff](docs/bench-status.md)

## Setup and flash

Run commands from this project folder. Examples use **`/dev/ttyUSB1` for the
master**; check the port after reconnecting USB. Close other serial monitors.

**1. Install Linux tools** (Debian/Ubuntu):

```bash
sudo apt install can-utils iproute2 kmod
```

**2. Install PlatformIO** if needed, using the PlatformIO IDE extension in VS Code.
Open `CAN-Tools.code-workspace`. The `tools/pio` launcher uses your installed
PlatformIO. Python commands below use its Python environment, which includes pyserial.

**3. Flash the master:**

```bash
./tools/pio run -e master -t upload --upload-port /dev/ttyUSB1
```

Wait for `master SUCCESS`. The master can be tested without the slave connected.
See [wiring and power](docs/wiring.md) before attaching transceivers or the slave.

## Check the master

```bash
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 status --bus ms
```

Expected: `role: master`, `bitrate: 125000`, `mode: listen`, `state: running`.
`peer_online: false` is normal without a slave. This status check works without a
CAN bus attached. If it times out, use [troubleshooting](docs/troubleshooting.md)
before continuing.

## Flash and check both boards

Flash one board at a time to keep the port assignments clear. Disconnect the
inter-board 5 V feed while powering the boards separately by USB; see
[wiring and power](docs/wiring.md).

**1. Connect only the master and list the ports:**

```bash
~/.platformio/penv/bin/python tools/dualcan.py --list-ports
```

Use its actual port in the upload command:

```bash
./tools/pio run -e master -t upload --upload-port /dev/ttyUSB1
```

**2. Wait for SUCCESS, unplug the master, and connect only the slave.** List
ports again, then substitute the slave's actual port below:

```bash
./tools/pio run -e slave -t upload --upload-port /dev/ttyUSB1
```

The same example port can belong to either board when connected individually;
always check it. Close serial monitors and disconnect OctoPrint from the board's
port if it has grabbed it. If uploading stays at `Connecting...`, hold BOOT until
writing starts, then release.

**3. After both uploads succeed, unplug USB, restore the inter-board wiring,
and connect USB to the master.** Check its port again, then query both buses:

```bash
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 status --bus all
```

Expected: MS reports `role: master`, `bitrate: 125000`, and `peer_online: true`;
HS reports `role: slave` and `bitrate: 500000`. Both should report `mode: listen`
and `state: running`. The slave's `peer_online: null` is normal. Repeat the check
to see whether `invalid_packets` increases; rising values indicate new malformed
UART packets and need [link troubleshooting](docs/troubleshooting.md).

## Start CAN capture

**1. Create the virtual interface** once per boot, or after deleting it:

```bash
sudo modprobe vcan
sudo ip link add dev can0 type vcan
sudo ip link set dev can0 up
```

**2. Start the bridge** and leave this terminal open:

```bash
~/.platformio/penv/bin/python tools/socketcan_bridge.py --port /dev/ttyUSB1 --bus ms
```

**3. In another terminal, watch received frames:**

```bash
candump can0
```

Blank output is normal without active CAN traffic. For a two-node bench test,
follow the [SH-C30A test guide](docs/bench-test.md), which enables acknowledgements.

The ESP32 is a USB serial device; the running bridge connects it to the virtual
SocketCAN interface. **USB baud is 57600; physical MS-CAN bitrate is 125000.**
The bridge starts listen-only. Ctrl+C stops it; interfaces are managed manually.

## SavvyCAN setup on Linux

SavvyCAN connects through this project's SocketCAN bridge using the existing
firmware. The bridge opens the master's USB serial port; SavvyCAN opens the
virtual CAN interfaces. See the official
[SavvyCAN connection guide](https://www.savvycan.com/docs/connectionwindow.html).

**1. Stop any `dualcan.py monitor` session or existing bridge with Ctrl+C.**
Only one program should open the master's serial port at a time. Run status
checks before starting the bridge or after stopping it.

**2. Create both virtual interfaces** once per boot, or after deleting them.
First check whether the names are already in use:

```bash
ip -details link show can0
ip -details link show can1
```

If an interface does not exist, create it below. If it already exists, skip its
`ip link add` command only after confirming it is this adapter's `vcan` interface.
If another adapter owns the name, choose different names and pass them to the
bridge with `--ms-interface` and `--hs-interface`.

```bash
sudo modprobe vcan
sudo ip link add dev can0 type vcan
sudo ip link add dev can1 type vcan
sudo ip link set dev can0 up
sudo ip link set dev can1 up
```

**3. Start the bridge and leave this terminal running:**

```bash
~/.platformio/penv/bin/python tools/socketcan_bridge.py --port /dev/ttyUSB1 --bus all
```

Both channels start listen-only. Keep the terminal visible for loss or connection
warnings. For the first car capture, leave out `--active` and use receive-only
tools in SavvyCAN.

**4. Add the connections in SavvyCAN:**

1. Open **Connection → Open Connection Window**.
2. Click **Add New Device Connection**.
3. Select **QT SerialBus Devices**.
4. Set **SerialBus Device Type** to **socketcan**.
5. Select port **can0**, then click **Create New Connection**.
6. Repeat for **can1**.

| Interface | Board / physical bus | Physical CAN bitrate |
| --- | --- | --- |
| `can0` | Master / MS | 125000 bit/s |
| `can1` | Slave / HS | 500000 bit/s |

Select these interfaces in SavvyCAN, rather than a serial/GVRET connection to
`/dev/ttyUSB1`. Bitrates are fixed in the firmware; do not apply
`ip link ... type can bitrate` to these virtual interfaces.

To check incoming traffic independently, run this in another terminal while the
bridge stays running:

```bash
candump can0 can1
```

Blank output means no frames are reaching these interfaces; it does not confirm
that the vehicle bus is inactive. Check the bridge output, wiring, bus selection,
and firmware bitrate if traffic is expected.

## Car-test recording to CSV

Use this direct recording option when you want CSV logs without running the
SocketCAN bridge. Stop the bridge first. These CSV files use the project's own
column format; for live SavvyCAN capture, use the SocketCAN setup above.

Before connecting to a vehicle, follow [wiring and power](docs/wiring.md): verify
the vehicle's bus pinout and physical-layer compatibility, leave OBD +12 V
disconnected, and disable added termination when tapping an already terminated
bus. Start with listen-only capture while parked.

**1. From the project folder, create a log directory and check both boards:**

```bash
mkdir -p logs
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 status --bus all
```

**2. Watch and record both buses:**

```bash
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 monitor --bus all --log "logs/car-$(date +%Y%m%d-%H%M%S).csv"
```

Alternatively, record without the scrolling frame display:

```bash
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 monitor --bus all --quiet --log "logs/car-$(date +%Y%m%d-%H%M%S).csv"
```

Run only one recording command at a time. Each command uses a timestamped
filename. Change one thing at a time—ignition, lights, door open/closed—and note
the time to match actions to frames later.

**3. Press Ctrl+C to stop and close the recording, then check status and files:**

```bash
~/.platformio/penv/bin/python tools/dualcan.py --port /dev/ttyUSB1 status --bus all
ls -lh logs/
```

Check `invalid_packets`, `bus_errors`, `rx_missed`, `rx_overrun`, and
`transport_dropped` against the starting status. The current **57600-baud USB
connection cannot sustain heavily loaded CAN capture**, including in SavvyCAN.
Reported losses mean the capture is incomplete; zero reported losses do not
prove lossless capture. See [capture limits](docs/socketcan.md#limits).

## Stop and clean up

Stop recording before unplugging the adapter. For SavvyCAN, disconnect its CAN
connections and press Ctrl+C in the bridge terminal. For direct CSV recording,
press Ctrl+C in the monitor terminal. Stop `candump` with Ctrl+C if it is running.

The virtual interfaces can stay available for the next session. To remove them,
run the following only for interfaces you created for this adapter:

```bash
sudo ip link set dev can0 down
sudo ip link delete dev can0
sudo ip link set dev can1 down
sudo ip link delete dev can1
```
