#!/usr/bin/env python3
"""Expose the dual ESP32 adapter to Linux SocketCAN applications."""
import argparse
from collections import Counter
from contextlib import ExitStack
import errno
import json
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import time

from can_protocol import Frame, Mode, Result, Type, decode_frame, decode_status, encode_frame
from dualcan import AdapterError, BUS_NAMES, Client, selected_buses

CAN_FRAME = struct.Struct("=IB3x8s")
EFF = 0x80000000
RTR = 0x40000000
ERR = 0x20000000
ID_MASK = 0x1FFFFFFF


def pack_frame(frame):
    encode_frame(frame)  # Share the adapter's ID, DLC and RTR validation.
    can_id = frame.id | (EFF if frame.extended else 0) | (RTR if frame.remote else 0)
    return CAN_FRAME.pack(can_id, frame.dlc, frame.data.ljust(8, b"\0"))


def unpack_frame(data):
    if len(data) != CAN_FRAME.size:
        raise ValueError("only Classical CAN frames are supported")
    can_id, dlc, payload = CAN_FRAME.unpack(data)
    if can_id & ERR:
        raise ValueError("CAN error frames cannot be transmitted")
    frame = Frame(can_id & ID_MASK, b"" if can_id & RTR else payload[:dlc],
                  bool(can_id & EFF), bool(can_id & RTR), dlc)
    encode_frame(frame)
    return frame


def open_can(name):
    sock = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    try:
        # One socket per bus: injected physical RX must never become physical TX.
        sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_RECV_OWN_MSGS, 0)
        sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 1)
        sock.bind((name,))
        sock.setblocking(False)
        return sock
    except BaseException:
        sock.close()
        raise


class Bridge:
    """Nonblocking command tracking keeps a slow bus from starving the other."""
    def __init__(self, client, sockets, active=(), clock=time.monotonic, report=None):
        self.client, self.sockets, self.clock = client, sockets, clock
        self.active = set(active)
        self.report = report or (lambda message: print(message, file=sys.stderr))
        self.ready = set(sockets)
        self.pending = {}
        self.tx_pending = set()
        now = clock()
        self.last_status = {bus: now for bus in sockets}
        self.last_ping = now
        self.last_report = now
        self.counts = Counter()
        self.last_counts = Counter()
        self.losses = {}
        client.on_packet = self.receive

    def disable(self, bus, reason):
        if bus in self.ready:
            self.ready.remove(bus)
            self.report(f"{BUS_NAMES[bus]}: {reason}; forwarding TX disabled. Restart the bridge to reconnect.")

    def request(self, kind, bus, payload=b""):
        command = self.client.request(kind, bus, payload)
        self.pending[bus, command.sequence] = (command, self.clock())
        if kind == Type.TRANSMIT:
            self.tx_pending.add(bus)

    def from_socket(self, bus, data):
        try:
            frame = unpack_frame(data)
        except ValueError:
            self.counts["invalid_socket_frames"] += 1
            return
        if bus not in self.active or bus not in self.ready:
            self.counts["tx_blocked"] += 1
            return
        if bus in self.tx_pending:
            self.counts["tx_busy_dropped"] += 1
            return
        self.request(Type.TRANSMIT, bus, encode_frame(frame))

    def receive(self, packet):
        bus = packet.bus
        if bus not in self.sockets:
            return
        if packet.type == Type.RECEIVED:
            try:
                wire = pack_frame(decode_frame(packet.payload))
                if self.sockets[bus].send(wire) != len(wire):
                    self.counts["rx_socket_dropped"] += 1
            except OSError as error:
                if error.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.ENOBUFS):
                    raise
                self.counts["rx_socket_dropped"] += 1
            return
        if packet.type == Type.STATUS:
            try:
                status = decode_status(packet.payload)
            except ValueError:
                self.counts["invalid_status"] += 1
                return
            self.last_status[bus] = self.clock()
            expected = "normal" if bus in self.active else "listen"
            if status["state"] != "running" or status["mode"] != expected:
                self.disable(bus, f"controller is {status['state']}/{status['mode']}")
            losses = tuple(status[key] for key in ("rx_missed", "rx_overrun", "transport_dropped"))
            if any(losses) and losses != self.losses.get(bus):
                self.report(f"{BUS_NAMES[bus]} losses: RX queue={losses[0]}, FIFO={losses[1]}, transport={losses[2]}")
            self.losses[bus] = losses
            return
        key = (bus, packet.sequence)
        if key not in self.pending or packet.type not in (Type.ACK, Type.TX_RESULT):
            return
        command, _ = self.pending[key]
        if len(packet.payload) != 6:
            self.counts["invalid_response"] += 1
            return
        kind, result, error = struct.unpack("<BBi", packet.payload)
        if kind != command.type or (packet.type == Type.TX_RESULT and kind != Type.TRANSMIT):
            return
        if result != Result.OK:
            name = Result(result).name if result in Result._value2member_map_ else str(result)
            self.disable(bus, f"{name} (driver error {error})")
            self.counts["command_failed"] += 1
        elif kind == Type.TRANSMIT and packet.type == Type.ACK:
            return  # Queued is not confirmation; keep this bus's TX slot occupied.
        elif packet.type == Type.TX_RESULT:
            self.counts["tx_confirmed"] += 1
        del self.pending[key]
        if kind == Type.TRANSMIT:
            self.tx_pending.discard(bus)

    def tick(self):
        now = self.clock()
        for key, (command, started) in list(self.pending.items()):
            if now - started >= self.client.timeout:
                del self.pending[key]
                if command.type == Type.TRANSMIT:
                    self.tx_pending.discard(command.bus)
                self.counts["command_timeout"] += 1
                self.disable(command.bus, "adapter response timed out")
        for bus in self.sockets:
            if now - self.last_status[bus] >= 3:
                self.disable(bus, "adapter status stopped arriving")
        if now - self.last_ping >= 1:
            for bus in sorted(self.ready):
                if not any(cmd.bus == bus and cmd.type == Type.PING for cmd, _ in self.pending.values()):
                    self.request(Type.PING, bus)
            self.last_ping = now
        self.counts["invalid_serial_packets"] = self.client.parser.errors
        if now - self.last_report >= 1 and self.counts != self.last_counts:
            self.report("Bridge totals: " + ", ".join(f"{key}={value}" for key, value in sorted(self.counts.items()) if value))
            self.last_counts = self.counts.copy()
            self.last_report = now

    def run(self):
        while True:
            # Do not drain active TX sockets while a physical transmission is in
            # flight. Kernel receive queues bound buffering; overload can drop TX.
            readers = [sock for bus, sock in self.sockets.items() if bus not in self.tx_pending]
            readable, _, _ = select.select([self.client.port, *readers], [], [], 0.05)
            if self.client.port in readable:
                self.client.pump()
            self.tick()
            for bus, sock in self.sockets.items():
                if sock in readable:
                    try:
                        self.from_socket(bus, sock.recv(72))
                    except BlockingIOError:
                        pass


def links():
    return {item["ifname"]: item for item in json.loads(subprocess.check_output(
        ["ip", "-j", "-d", "link", "show"], text=True))}


def check_interfaces(names):
    existing = links()
    for name in names:
        info = existing.get(name, {})
        if info.get("linkinfo", {}).get("info_kind") != "vcan" or "UP" not in info.get("flags", []):
            raise AdapterError(f"{name} must be an UP vcan interface; see the manual ip link commands in README.md")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="master USB serial device")
    parser.add_argument("--baud", type=int, default=57600, help="master PC_BAUD (default: 57600)")
    parser.add_argument("--bus", choices=("all", "ms", "hs"), default="all")
    parser.add_argument("--ms-interface", default="can0")
    parser.add_argument("--hs-interface", default="can1")
    parser.add_argument("--active", choices=("all", "ms", "hs"), help="enable ACK and TX on these buses; default is listen-only")
    args = parser.parse_args(argv)
    if args.baud <= 0:
        parser.error("--baud must be positive")
    for name in (args.ms_interface, args.hs_interface):
        if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,14}", name):
            parser.error("interface names must be 1–15 letters, digits, underscores, dots or hyphens")
    if args.ms_interface == args.hs_interface:
        parser.error("the two buses need different interface names")
    if args.active and not set(selected_buses(args.active)) <= set(selected_buses(args.bus)):
        parser.error("--active must refer only to selected buses")
    return args


def restore_listen(client, buses):
    client.on_packet = None
    client.port.timeout = 0.05
    for bus in buses:
        try:
            client.set_mode(bus, Mode.LISTEN)
        except (AdapterError, OSError) as error:
            print(f"Could not restore {BUS_NAMES[bus]} listen-only: {error}. Firmware watchdog expires after 3 seconds without commands.", file=sys.stderr)


def main(argv=None):
    args = arguments(argv)
    if sys.platform != "linux":
        print("SocketCAN requires Linux.", file=sys.stderr)
        return 1
    try:
        import serial
    except ImportError:
        print("Install pyserial with: python3 -m pip install -r tools/requirements.txt", file=sys.stderr)
        return 1
    buses = selected_buses(args.bus)
    active = selected_buses(args.active) if args.active else []
    names = {0: args.ms_interface, 1: args.hs_interface}
    try:
        check_interfaces([names[bus] for bus in buses])
        with ExitStack() as stack:
            port = serial.Serial(port=None, baudrate=args.baud, timeout=0, write_timeout=0.25, exclusive=True)
            port.dtr = port.rts = False
            port.port = args.port
            port.open()
            stack.callback(port.close)
            time.sleep(1.5)
            port.reset_input_buffer()
            # Blocking reads are useful during discovery; streaming uses select.
            port.timeout = 0.05
            client = Client(port)
            for bus in buses:
                client.set_mode(bus, Mode.LISTEN)
                status = decode_status(client.command(Type.GET_STATUS, bus).payload)
                if status["state"] != "running" or status["bitrate"] != (125000 if bus == 0 else 500000):
                    raise AdapterError(f"{BUS_NAMES[bus]} is unavailable or has an unexpected bitrate")
            sockets = {bus: stack.enter_context(open_can(names[bus])) for bus in buses}
            stack.callback(restore_listen, client, buses)
            for bus in active:
                client.set_mode(bus, Mode.NORMAL)
                # Drain prior listen-only status before installing the callback.
                client.command(Type.GET_STATUS, bus)
            port.timeout = 0
            bridge = Bridge(client, sockets, active)
            for bus in buses:
                print(f"{names[bus]} → {BUS_NAMES[bus]} ({125000 if bus == 0 else 500000} bit/s), "
                      f"{'ACK/TX enabled' if bus in active else 'listen-only'}", file=sys.stderr)
            print("Ready. Run candump " + " ".join(names[bus] for bus in buses) + "; Ctrl+C to stop.", file=sys.stderr)
            bridge.run()
    except KeyboardInterrupt:
        return 0
    except (AdapterError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"SocketCAN bridge: {error}", file=sys.stderr)
        print("Check the USB port, baud and master firmware. Test serial status with tools/dualcan.py before starting the bridge.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    def stop_on_signal(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_on_signal)
    sys.exit(main())
