import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from can_protocol import (Frame, Mode, Packet, Parser, Result, Type, cobs_encode,
                          crc16, decode, decode_frame, decode_status, encode, encode_frame)
from dualcan import AdapterError, Client, arguments


def response(command, kind=Type.ACK, result=Result.OK):
    return Packet(kind, command.bus, command.sequence, struct.pack("<BBi", command.type, result, 0))


class FakePort:
    """A fragmented serial peer that can put CAN traffic between responses."""
    def __init__(self, on_write):
        self.incoming = bytearray()
        self.on_write = on_write
        self.writes = []

    @property
    def in_waiting(self):
        return min(3, len(self.incoming))

    def read(self, length):
        data = bytes(self.incoming[:length])
        del self.incoming[:length]
        return data

    def write(self, wire):
        packet = decode(wire[:-1])
        self.writes.append(packet)
        for reply in self.on_write(packet):
            self.incoming.extend(encode(reply))
        return len(wire)


class ProtocolTests(unittest.TestCase):
    def test_crc_reference(self):
        self.assertEqual(crc16(b"123456789"), 0x29B1)

    def test_all_lengths_and_fragmented_stream(self):
        packets = [Packet(Type.RECEIVED, length % 2, length, bytes(range(length)))
                   for length in range(65)]
        wire = b"\x00\x00" + b"".join(encode(packet) for packet in packets)
        parser = Parser()
        result = []
        for byte in wire:
            result.extend(parser.feed(bytes([byte])))
        self.assertEqual(result, packets)
        self.assertEqual(parser.errors, 0)

    def test_corrupt_truncated_and_overlong_stream_recovers(self):
        valid = encode(Packet(Type.PING, 0, 123))
        corrupted = bytearray(valid)
        corrupted[-2] ^= 1
        parser = Parser()
        stream = b"\x01" * 2000 + b"\x00" + bytes(corrupted) + valid[:-3] + b"\x00" + valid
        self.assertEqual(parser.feed(stream), [Packet(Type.PING, 0, 123)])
        self.assertEqual(parser.errors, 3)

    def test_invalid_header_even_with_valid_crc(self):
        for raw in (b"\x02\x04\x00\x01\x00\x00", b"\x01\x04\x00\x01\x00\x01"):
            wire = cobs_encode(raw + struct.pack("<H", crc16(raw)))
            with self.assertRaises(ValueError):
                decode(wire)

    def test_can_frames_and_rejections(self):
        frames = [Frame(0x7FF, b"\x00\xFF", dlc=2),
                  Frame(0x1FFFFFFF, extended=True, remote=True, dlc=8), Frame(0)]
        for frame in frames:
            self.assertEqual(decode_frame(encode_frame(frame)), frame)
        for frame in (Frame(0x800), Frame(0, dlc=9), Frame(0, b"x", remote=True, dlc=1),
                      Frame(0, b"x", dlc=0), Frame(0x20000000, extended=True)):
            with self.assertRaises(ValueError):
                encode_frame(frame)
        with self.assertRaises(ValueError):
            decode_frame(b"\x80\x00" + b"\x00" * 8)

    def test_status_signed_error_and_peer(self):
        status = decode_status(bytes([Mode.LISTEN, 1, 1, 1]) + struct.pack("<12Ii", *range(12), -1))
        self.assertEqual(status["last_error"], -1)
        self.assertTrue(status["peer_online"])
        self.assertEqual(status["mode"], "listen")

    @unittest.skipUnless(os.environ.get("CPP_PROTOCOL_TEST"), "set CPP_PROTOCOL_TEST for C++ interop")
    def test_python_cpp_interoperability(self):
        rng = random.Random(312)
        packets = [Packet(Type.RECEIVED, i % 2, rng.randrange(65536),
                          bytes(rng.randrange(256) for _ in range(i % 65))) for i in range(300)]
        vectors = [encode(packet).hex() for packet in packets]
        result = subprocess.run([os.environ["CPP_PROTOCOL_TEST"], "--vectors"],
                                input="\n".join(vectors) + "\n", text=True,
                                capture_output=True, check=True)
        self.assertEqual(result.stdout.splitlines(), vectors)


class ClientTests(unittest.TestCase):
    def test_two_stage_tx_result_with_interleaved_rx(self):
        received = Packet(Type.RECEIVED, 0, payload=encode_frame(Frame(0x123, b"\xAA", dlc=1)))
        port = FakePort(lambda command: [received, response(command), response(command, Type.TX_RESULT)])
        client = Client(port, timeout=0.1)
        observed = []
        client.on_packet = observed.append
        client.transmit(1, Frame(0x456, b"\x01\x02", dlc=2))
        self.assertIn(received, observed)
        self.assertEqual(port.writes[0].bus, 1)
        self.assertEqual(port.writes[0].type, Type.TRANSMIT)

    def test_queued_tx_is_not_reported_as_success(self):
        client = Client(FakePort(lambda command: [response(command)]), timeout=0.01)
        with self.assertRaisesRegex(AdapterError, "timed out"):
            client.transmit(0, Frame(0))

    def test_failed_tx_and_missing_slave(self):
        port = FakePort(lambda command: [response(command), response(command, Type.TX_RESULT, Result.DRIVER_ERROR)])
        with self.assertRaisesRegex(AdapterError, "DRIVER_ERROR"):
            Client(port, timeout=0.1).transmit(1, Frame(0))
        client = Client(FakePort(lambda command: [response(command, result=Result.LINK_TIMEOUT)]), timeout=0.1)
        with self.assertRaisesRegex(AdapterError, "LINK_TIMEOUT"):
            client.command(Type.GET_STATUS, 1)

    def test_bus_and_sequence_correlation(self):
        def replies(command):
            wrong_bus = Packet(Type.ACK, 1, command.sequence, response(command).payload)
            old_sequence = Packet(Type.ACK, 0, 65535, response(command).payload)
            return [wrong_bus, old_sequence, response(command)]
        client = Client(FakePort(replies), timeout=0.1)
        client.command(Type.PING, 0)
        self.assertEqual(len(client.responses), 2)
        client.sequence = 65535
        request = client.request(Type.PING, 0)
        self.assertEqual(request.sequence, 1)

    def test_remote_frame_cli(self):
        args = arguments(["--port", "/dev/test", "send", "--bus", "hs", "--id", "18DAF110",
                          "--extended", "--rtr", "--dlc", "8"])
        self.assertEqual(args.frame, Frame(0x18DAF110, extended=True, remote=True, dlc=8))


if __name__ == "__main__":
    unittest.main()
