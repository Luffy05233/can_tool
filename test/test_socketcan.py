import errno
import os
from pathlib import Path
import pty
import queue
import select
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from can_protocol import Frame, Mode, Packet, Parser, Result, Type, encode, encode_frame
from dualcan import AdapterError, Client
from socketcan_bridge import (Bridge, CAN_FRAME, EFF, ERR, RTR, arguments, open_can,
                              pack_frame, check_interfaces, unpack_frame)
from test_host import FakePort, response


def status(bus, mode=Mode.LISTEN, state=1):
    payload = bytes([mode, state, 1 if bus == 0 else 255, bus + 1])
    payload += struct.pack("<12Ii", 125000 if bus == 0 else 500000, *([0] * 12))
    return Packet(Type.STATUS, bus, payload=payload)


class Sink:
    def __init__(self):
        self.sent = []

    def send(self, data):
        self.sent.append(data)
        return len(data)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.port = FakePort(lambda command: [])
        self.client = Client(self.port)
        self.sockets = {0: Sink(), 1: Sink()}
        self.messages = []
        self.bridge = Bridge(self.client, self.sockets, [0, 1],
                             clock=lambda: self.now, report=self.messages.append)

    def test_linux_abi_vectors(self):
        vectors = [
            (Frame(0x123, b"\xAA\xBB", dlc=2), 0x123, 2, b"\xAA\xBB" + b"\0" * 6),
            (Frame(0x1ABCDE, b"12345678", extended=True, dlc=8), EFF | 0x1ABCDE, 8, b"12345678"),
            (Frame(0x123, remote=True, dlc=8), RTR | 0x123, 8, b"\0" * 8),
            (Frame(0x1FFFFFFF, extended=True, remote=True, dlc=0), EFF | RTR | 0x1FFFFFFF, 0, b"\0" * 8),
            (Frame(0), 0, 0, b"\0" * 8),
        ]
        for frame, can_id, dlc, data in vectors:
            expected = struct.pack("=IB3x8s", can_id, dlc, data)
            self.assertEqual(pack_frame(frame), expected)
            self.assertEqual(unpack_frame(expected), frame)
        self.assertEqual(CAN_FRAME.size, 16)

    def test_reject_fd_error_invalid_id_and_dlc(self):
        for data in (b"\0" * 72, b"\0" * 15, CAN_FRAME.pack(ERR | 1, 0, b""),
                     CAN_FRAME.pack(0x800, 0, b""), CAN_FRAME.pack(0, 9, b"")):
            with self.assertRaises(ValueError):
                unpack_frame(data)
            self.bridge.from_socket(0, data)
        self.assertEqual(self.bridge.counts["invalid_socket_frames"], 5)
        self.assertFalse(self.port.writes)

    def test_rx_bus_separation_no_serial_transmit(self):
        for bus in (0, 1):
            frame = Frame(0x100 + bus, remote=bool(bus), dlc=bus)
            self.bridge.receive(Packet(Type.RECEIVED, bus, payload=encode_frame(frame)))
            self.assertEqual(self.sockets[bus].sent, [pack_frame(frame)])
        self.assertFalse(self.port.writes)

    def test_listen_only_blocks_tx_and_mixed_active_bus(self):
        self.bridge.active = {1}
        self.bridge.from_socket(0, pack_frame(Frame(0x123)))
        self.assertFalse(self.port.writes)
        self.bridge.from_socket(1, pack_frame(Frame(0x456)))
        self.assertEqual(self.port.writes[-1].bus, 1)
        self.assertEqual(self.bridge.counts["tx_blocked"], 1)

    def test_two_independent_tx_slots_and_correlated_confirmation(self):
        for bus in (0, 1):
            self.bridge.from_socket(bus, pack_frame(Frame(0x123)))
        first, second = self.port.writes
        self.bridge.receive(response(first))
        self.assertEqual(self.bridge.tx_pending, {0, 1})
        self.assertEqual(self.bridge.counts["tx_confirmed"], 0)
        self.bridge.receive(Packet(Type.TX_RESULT, 1, first.sequence, response(first).payload))
        self.assertEqual(self.bridge.tx_pending, {0, 1})
        self.bridge.receive(response(first, Type.TX_RESULT))
        self.assertEqual(self.bridge.tx_pending, {1})
        self.assertEqual(self.bridge.counts["tx_confirmed"], 1)
        self.bridge.from_socket(1, pack_frame(Frame(0)))
        self.assertEqual(len(self.port.writes), 2)
        self.bridge.receive(response(second, Type.TX_RESULT, Result.DRIVER_ERROR))
        self.assertEqual(self.bridge.ready, {0})
        self.assertFalse(self.bridge.tx_pending)

    def test_fragmented_serial_rx_interleaved_with_tx_ack(self):
        incoming = Packet(Type.RECEIVED, 1, payload=encode_frame(Frame(0x777)))
        self.port.on_write = lambda cmd: [incoming, response(cmd), response(cmd, Type.TX_RESULT)]
        self.bridge.from_socket(0, pack_frame(Frame(0)))
        while self.port.incoming:
            self.client.pump()
        self.assertEqual(self.sockets[1].sent, [pack_frame(Frame(0x777))])
        self.assertEqual(self.bridge.counts["tx_confirmed"], 1)
        self.assertFalse(self.bridge.tx_pending)

    def test_timeout_does_not_retry_ambiguous_transmission(self):
        self.bridge.from_socket(0, pack_frame(Frame(0)))
        self.now = 2.6
        self.bridge.tick()
        self.assertNotIn(0, self.bridge.ready)
        self.bridge.from_socket(0, pack_frame(Frame(0)))
        self.assertEqual(sum(cmd.type == Type.TRANSMIT for cmd in self.port.writes), 1)
        self.assertFalse(self.bridge.tx_pending)

    def test_keepalive_both_buses_and_stale_slave(self):
        self.now = 1.1
        self.bridge.tick()
        self.assertEqual([(cmd.type, cmd.bus) for cmd in self.port.writes], [(Type.PING, 0), (Type.PING, 1)])
        for command in self.port.writes[:]:
            self.bridge.receive(response(command))
        self.now = 3.1
        self.bridge.receive(status(0, Mode.NORMAL))
        self.bridge.tick()
        self.assertEqual(self.bridge.ready, {0})
        self.assertEqual(self.port.writes[-1].bus, 0)

    def test_reset_or_bus_off_does_not_automatically_rearm(self):
        for packet in (status(0, Mode.LISTEN), status(1, Mode.NORMAL, state=2)):
            self.bridge.receive(packet)
        self.assertFalse(self.bridge.ready)
        self.bridge.receive(status(0, Mode.NORMAL))
        self.assertFalse(self.bridge.ready)

    def test_full_socket_reports_rx_loss(self):
        with patch.object(self.sockets[0], "send", side_effect=OSError(errno.ENOBUFS, "full")):
            self.bridge.receive(Packet(Type.RECEIVED, 0, payload=encode_frame(Frame(0))))
        self.assertEqual(self.bridge.counts["rx_socket_dropped"], 1)

    def test_manual_setup_requires_virtual_interface(self):
        with patch("socketcan_bridge.links", return_value={"can0": {"flags": ["UP"], "linkinfo": {"info_kind": "can"}}}):
            with self.assertRaisesRegex(AdapterError, "vcan"):
                check_interfaces(["can0"])

    def test_cli(self):
        args = arguments(["--port", "/dev/test", "--bus", "hs", "--active", "hs", "--hs-interface", "vehiclehs"])
        self.assertEqual(args.hs_interface, "vehiclehs")
        self.assertIsNone(arguments(["--port", "/dev/test"]).active)
        for argv in (["--bus", "ms", "--active", "all"], ["--ms-interface", "can1"], ["--baud", "0"]):
            with patch("sys.stderr"), self.assertRaises(SystemExit):
                arguments(["--port", "/dev/test", *argv])


@unittest.skipUnless(os.environ.get("SOCKETCAN_TEST_INTERFACES"), "set SOCKETCAN_TEST_INTERFACES to two dedicated UP vcan devices")
class KernelIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("candump") and shutil.which("cansend"), "requires can-utils")
    def test_cli_with_serial_emulator_and_canutils(self):
        """Run the actual CLI against a PTY firmware peer and real can-utils."""
        names = os.environ["SOCKETCAN_TEST_INTERFACES"].split(",")
        master_fd, slave_fd = pty.openpty()
        modes = {0: Mode.LISTEN, 1: Mode.LISTEN}
        received_tx = queue.Queue()
        stopped = threading.Event()
        wire_lock = threading.Lock()

        def send(packet):
            with wire_lock:
                os.write(master_fd, encode(packet))

        def firmware():
            parser = Parser()
            last_status = time.monotonic()
            while not stopped.is_set():
                if select.select([master_fd], [], [], 0.02)[0]:
                    for cmd in parser.feed(os.read(master_fd, 4096)):
                        if cmd.type == Type.SET_MODE:
                            modes[cmd.bus] = Mode(cmd.payload[0])
                        if cmd.type == Type.GET_STATUS:
                            reply = status(cmd.bus, modes[cmd.bus])
                            send(Packet(reply.type, reply.bus, cmd.sequence, reply.payload))
                        else:
                            send(response(cmd))
                        if cmd.type == Type.TRANSMIT:
                            received_tx.put(cmd)
                            send(response(cmd, Type.TX_RESULT))
                if time.monotonic() - last_status >= 0.5:
                    for bus in modes:
                        send(status(bus, modes[bus]))
                    last_status = time.monotonic()

        thread = threading.Thread(target=firmware, daemon=True)
        thread.start()
        root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen([sys.executable, str(root / "tools/socketcan_bridge.py"),
                                    "--port", os.ttyname(slave_fd), "--active", "all",
                                    "--ms-interface", names[0], "--hs-interface", names[1]],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        dump = None
        try:
            output = b""
            deadline = time.monotonic() + 8
            while b"Ready." not in output and time.monotonic() < deadline:
                if select.select([process.stderr], [], [], 0.1)[0]:
                    chunk = os.read(process.stderr.fileno(), 4096)
                    if not chunk:
                        break
                    output += chunk
            self.assertIn(b"Ready.", output, output.decode())
            dump = subprocess.Popen(["candump", "-n", "1", "-T", "2000", names[1]],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            time.sleep(0.1)  # Let candump bind its socket before injecting RX.
            send(Packet(Type.RECEIVED, 1, payload=encode_frame(Frame(0x321, b"\xAB\xCD", dlc=2))))
            captured, errors = dump.communicate(timeout=3)
            self.assertEqual(dump.returncode, 0, errors)
            self.assertIn(b"321", captured)
            self.assertIn(b"AB CD", captured)
            self.assertTrue(received_tx.empty(), "physical RX was fed back as TX")
            subprocess.run(["cansend", names[0], "123#0102"], check=True, timeout=2)
            command = received_tx.get(timeout=2)
            self.assertEqual(command.bus, 0)
            self.assertEqual(command.payload, encode_frame(Frame(0x123, b"\x01\x02", dlc=2)))
            process.terminate()
            process.communicate(timeout=6)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(modes, {0: Mode.LISTEN, 1: Mode.LISTEN})
        finally:
            if dump is not None and dump.poll() is None:
                dump.kill()
                dump.communicate()
            if process.poll() is None:
                process.kill()
            process.communicate()
            stopped.set()
            thread.join(timeout=1)
            os.close(master_fd)
            os.close(slave_fd)

    def test_real_socket_routing_and_no_feedback(self):
        names = os.environ["SOCKETCAN_TEST_INTERFACES"].split(",")
        self.assertEqual(len(names), 2)
        sockets = {bus: open_can(name) for bus, name in enumerate(names)}
        apps = {bus: open_can(name) for bus, name in enumerate(names)}
        try:
            for app in apps.values():
                app.settimeout(0.2)
            port = FakePort(lambda command: [])
            bridge = Bridge(Client(port), sockets, [0, 1])
            frame = Frame(0x123, b"\x01\x02", dlc=2)
            bridge.receive(Packet(Type.RECEIVED, 1, payload=encode_frame(frame)))
            self.assertEqual(apps[1].recv(72), pack_frame(frame))
            with self.assertRaises(BlockingIOError):
                sockets[1].recv(72)  # RX injection must not return as TX.
            with self.assertRaises(socket.timeout):
                apps[0].recv(72)
            apps[0].send(pack_frame(frame))
            sockets[0].settimeout(0.2)
            bridge.from_socket(0, sockets[0].recv(72))
            self.assertEqual(port.writes[-1].bus, 0)
            self.assertEqual(port.writes[-1].payload, encode_frame(frame))
        finally:
            for sock in [*sockets.values(), *apps.values()]:
                sock.close()


if __name__ == "__main__":
    unittest.main()
