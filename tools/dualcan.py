#!/usr/bin/env python3
"""Linux monitor and transmitter for the two-ESP32 CAN adapter."""
import argparse
from collections import deque
import csv
from datetime import datetime, timezone
import json
import struct
import sys
import time

from can_protocol import Frame, Mode, Packet, Parser, Result, Type
from can_protocol import decode_frame, decode_status, encode, encode_frame

BUS_NAMES = {0: "MS", 1: "HS"}


class AdapterError(Exception):
    pass


class Client:
    def __init__(self, serial_port, timeout=2.5):
        self.port = serial_port
        self.timeout = timeout
        self.parser = Parser()
        self.sequence = 0
        self.responses = deque(maxlen=64)
        self.on_packet = None

    def pump(self):
        data = self.port.read(min(4096, max(1, self.port.in_waiting)))
        for packet in self.parser.feed(data):
            if packet.type == Type.RECEIVED:
                if packet.bus not in BUS_NAMES or packet.sequence != 0:
                    self.parser.errors += 1
                    continue
                try:
                    decode_frame(packet.payload)
                except ValueError:
                    self.parser.errors += 1
                    continue
            if self.on_packet:
                self.on_packet(packet)
            if packet.sequence and packet.type in (Type.ACK, Type.STATUS, Type.TX_RESULT):
                self.responses.append(packet)

    def request(self, kind, bus, payload=b""):
        self.sequence = self.sequence % 65535 + 1
        packet = Packet(kind, bus, self.sequence, payload)
        wire = encode(packet)
        if self.port.write(wire) != len(wire):
            raise AdapterError("incomplete serial write")
        return packet

    def wait(self, request, expected):
        deadline = time.monotonic() + self.timeout
        while True:
            for packet in list(self.responses):
                if packet.bus != request.bus or packet.sequence != request.sequence:
                    continue
                if packet.type not in (expected, Type.ACK):
                    continue
                self.responses.remove(packet)
                if packet.type in (Type.ACK, Type.TX_RESULT):
                    if len(packet.payload) != 6:
                        raise AdapterError("malformed command response")
                    kind, result, error = struct.unpack("<BBi", packet.payload)
                    if kind != request.type:
                        continue
                    if result != Result.OK:
                        name = Result(result).name if result in Result._value2member_map_ else str(result)
                        raise AdapterError(f"{BUS_NAMES[request.bus]}: {name} (driver error {error})")
                    if packet.type != expected:
                        raise AdapterError("unexpected acknowledgement without requested response")
                return packet
            if time.monotonic() >= deadline:
                raise AdapterError(f"{BUS_NAMES[request.bus]}: response timed out; check power, UART wiring and baud")
            self.pump()

    def command(self, kind, bus, payload=b""):
        request = self.request(kind, bus, payload)
        expected = Type.STATUS if kind == Type.GET_STATUS else Type.ACK
        return self.wait(request, expected)

    def set_mode(self, bus, mode):
        self.command(Type.SET_MODE, bus, bytes([mode]))

    def transmit(self, bus, frame):
        request = self.request(Type.TRANSMIT, bus, encode_frame(frame))
        self.wait(request, Type.ACK)  # Queued, not yet delivered.
        self.wait(request, Type.TX_RESULT)  # Controller reports successful CAN transmission.


def selected_buses(name):
    return [0, 1] if name == "all" else [0 if name == "ms" else 1]


def monitor(client, args):
    buses = selected_buses(args.bus)
    log_file = open(args.log, "w", newline="", encoding="utf-8") if args.log else None
    writer = csv.writer(log_file) if log_file else None
    if writer:
        writer.writerow(["host_utc", "bus", "timestamp_us", "id", "extended", "rtr", "dlc", "data"])
    active = []
    drop_counts = {}

    def receive(packet):
        if packet.type == Type.STATUS and packet.bus in buses:
            try:
                status = decode_status(packet.payload)
            except ValueError:
                client.parser.errors += 1
                return
            counts = tuple(status[key] for key in ("rx_missed", "rx_overrun", "transport_dropped"))
            if any(counts) and counts != drop_counts.get(packet.bus):
                print(f"{BUS_NAMES[packet.bus]} losses: RX queue={counts[0]}, FIFO={counts[1]}, transport={counts[2]}", file=sys.stderr)
            drop_counts[packet.bus] = counts
        if packet.type != Type.RECEIVED or packet.bus not in buses:
            return
        frame = decode_frame(packet.payload)
        can_id = f"{frame.id:08X}" if frame.extended else f"{frame.id:03X}"
        data = f"R{frame.dlc}" if frame.remote else frame.data.hex().upper()
        if not args.quiet:
            print(f"{frame.timestamp_us:10d}us  {BUS_NAMES[packet.bus]}  {can_id}#{data}")
        if writer:
            writer.writerow([datetime.now(timezone.utc).isoformat(), BUS_NAMES[packet.bus],
                             frame.timestamp_us, can_id, int(frame.extended), int(frame.remote),
                             frame.dlc, frame.data.hex().upper()])

    client.on_packet = receive
    try:
        ready = []
        for bus in buses:
            try:
                # Reopening monitoring after a stopped session restarts reception.
                client.set_mode(bus, Mode.NORMAL if args.active else Mode.LISTEN)
                ready.append(bus)
                if args.active:
                    active.append(bus)
                status = decode_status(client.command(Type.GET_STATUS, bus).payload)
                print(f"{BUS_NAMES[bus]}: {status['bitrate']} bit/s, {status['mode']}, {status['state']}", file=sys.stderr)
            except AdapterError as error:
                print(error, file=sys.stderr)
        if not ready:
            raise AdapterError("neither selected CAN channel is available")
        last_keepalive = time.monotonic()
        while True:
            client.pump()
            if args.active and time.monotonic() - last_keepalive >= 1:
                for bus in list(active):
                    try:
                        client.command(Type.PING, bus)
                    except AdapterError as error:
                        print(error, file=sys.stderr)
                        active.remove(bus)
                last_keepalive = time.monotonic()
            if log_file:
                log_file.flush()
    finally:
        client.on_packet = None
        for bus in active:
            try:
                client.set_mode(bus, Mode.LISTEN)
            except AdapterError as error:
                print(error, file=sys.stderr)
        if log_file:
            log_file.close()


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="master serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=57600, help="must match PC_BAUD (default: 57600)")
    parser.add_argument("--list-ports", action="store_true")
    commands = parser.add_subparsers(dest="command")
    watch = commands.add_parser("monitor", help="display both CAN buses; Ctrl+C to stop")
    watch.add_argument("--bus", choices=("all", "ms", "hs"), default="all")
    watch.add_argument("--active", action="store_true", help="use normal mode and acknowledge CAN traffic")
    watch.add_argument("--log", metavar="CSV", help="write frames to a CSV file")
    watch.add_argument("--quiet", action="store_true", help="suppress frame output (use with --log)")
    for name in ("status", "stop"):
        sub = commands.add_parser(name)
        sub.add_argument("--bus", choices=("all", "ms", "hs"), default="all")
    send = commands.add_parser("send", help="transmit one frame, then return the selected bus to listen-only")
    send.add_argument("--bus", choices=("ms", "hs"), required=True)
    send.add_argument("--id", type=lambda value: int(value, 16), required=True, help="CAN ID in hexadecimal")
    send.add_argument("--data", default="", help="up to eight hex bytes, e.g. '01 02 03'")
    send.add_argument("--extended", action="store_true", help="use a 29-bit ID")
    send.add_argument("--rtr", action="store_true", help="send a remote request with no data")
    send.add_argument("--dlc", type=int, help="requested length for RTR; otherwise must match --data")
    args = parser.parse_args(argv)
    if not args.list_ports and (not args.port or not args.command):
        parser.error("--port and a command are required (or use --list-ports)")
    if args.baud <= 0:
        parser.error("--baud must be positive")
    if args.command == "send":
        try:
            data = bytes.fromhex(args.data)
            args.frame = Frame(args.id, data, args.extended, args.rtr,
                               len(data) if args.dlc is None else args.dlc)
            encode_frame(args.frame)
        except ValueError as error:
            parser.error(str(error))
    return args


def main(argv=None):
    args = arguments(argv)
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        print("Install pyserial: python3 -m pip install pyserial", file=sys.stderr)
        return 1
    if args.list_ports:
        for port in list_ports.comports():
            print(f"{port.device}\t{port.description}")
        return 0
    port = serial.Serial(port=None, baudrate=args.baud, timeout=0.05, write_timeout=1)
    port.dtr = False
    port.rts = False
    port.port = args.port
    try:
        port.open()
        time.sleep(1.5)  # Allow a board reset caused by the USB-UART bridge to finish.
        port.reset_input_buffer()
        client = Client(port)
        if args.command == "monitor":
            monitor(client, args)
        elif args.command == "send":
            bus = selected_buses(args.bus)[0]
            try:
                client.set_mode(bus, Mode.NORMAL)
                client.transmit(bus, args.frame)
                print(f"{BUS_NAMES[bus]}: CAN transmission confirmed")
            finally:
                client.set_mode(bus, Mode.LISTEN)
        else:
            failed = False
            for bus in selected_buses(args.bus):
                try:
                    if args.command == "stop":
                        client.set_mode(bus, Mode.STOPPED)
                        print(f"{BUS_NAMES[bus]}: stopped")
                    else:
                        status = decode_status(client.command(Type.GET_STATUS, bus).payload)
                        print(f"{BUS_NAMES[bus]}: {json.dumps(status, sort_keys=True)}")
                except AdapterError as error:
                    failed = True
                    print(error, file=sys.stderr)
            if failed:
                return 1
        if client.parser.errors:
            print(f"Discarded {client.parser.errors} malformed serial packets", file=sys.stderr)
        return 0
    except KeyboardInterrupt:
        return 0
    except (AdapterError, ValueError, OSError, serial.SerialException) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        if port.is_open:
            port.close()


if __name__ == "__main__":
    sys.exit(main())
