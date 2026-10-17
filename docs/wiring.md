[← Project setup](../README.md)

# Hardware and wiring

The default target is a **classic ESP32 Dev Module**, using its USB-to-UART bridge
for the PC connection. If the boards are another ESP32 family, update the board
target and USB implementation before flashing. USB-C describes the connector;
these builds use UART0 through a USB-to-UART bridge, not native USB CDC.

On **each** board:

| ESP32 connection | SN65HVD230 module connection |
| --- | --- |
| 3V3 | VCC (3.3 V) |
| GND | GND |
| GPIO25 / CAN TX | TX / D / TXD input |
| GPIO26 / CAN RX | RX / R / RXD output |

Inter-board wiring:

| Master | Slave |
| --- | --- |
| GPIO17 / TX2 | GPIO16 / RX2 |
| GPIO16 / RX2 | GPIO17 / TX2 |
| USB-derived 5 V, if available on this board | Regulated dev-board 5V/VIN input |
| GND | GND |

Both firmware targets use GPIO17 for UART TX and GPIO16 for UART RX. This
assumes the boards' TX2/RX2 labels map to GPIO17/GPIO16; verify the board pinout.
These pins must be available on the module (ESP32-WROVER reserves them for PSRAM;
see the [Espressif board guide](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html)).
The inter-board UART runs at **115200 baud** for link troubleshooting.
Reflash both boards when changing its pins or baud rate.

Keep the UART wiring short inside the enclosure. UART signals are **3.3 V**.
The 5 V feed is for the dev-board regulator; both SN65HVD230 modules get **3.3 V**.
Verify the master's power path can supply both boards and transceivers. Disconnect
the inter-board 5 V feed when separately powering the slave by USB to flash it,
unless the exact board supports both power sources.

Vehicle wiring:

| Vehicle cable | Connection |
| --- | --- |
| MS CAN-H / CAN-L | Master transceiver CAN-H / CAN-L |
| HS CAN-H / CAN-L | Slave transceiver CAN-H / CAN-L |
| Signal ground | Common ground |
| OBD +12 V | Leave disconnected |

Use the vehicle's documented connector pinout. No vehicle model or OBD pinout is
assumed by this project. The SN65HVD230 implements the ISO 11898-2 physical layer;
the vehicle's MS bus must use that physical layer too. A 125 kbit/s rate does not
establish compatibility with an ISO 11898-3 fault-tolerant bus. If the module
exposes RS, it needs a defined operating state; RS tied to GND selects high-speed
operation. See the [TI SN65HVD230 datasheet](https://www.ti.com/lit/ds/symlink/sn65hvd230.pdf).

Disable/remove the modules' built-in 120 ohm termination when tapping a vehicle bus
that already has its required termination. A separate bench CAN bus needs its own
termination at the two endpoints. See [TI CAN termination guidance](https://www.ti.com/lit/ds/symlink/sn65hvda1050a-q1.pdf).

