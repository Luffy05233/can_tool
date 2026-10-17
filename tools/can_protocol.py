"""Version 1 of the USB/UART protocol; no third-party dependencies."""
from dataclasses import dataclass
from enum import IntEnum
import struct

VERSION = 1
MAX_PAYLOAD = 64
MAX_ENCODED = 73


class Type(IntEnum):
    TRANSMIT = 1
    SET_MODE = 2
    GET_STATUS = 3
    PING = 4
    ACK = 0x80
    RECEIVED = 0x81
    STATUS = 0x82
    TX_RESULT = 0x83


class Mode(IntEnum):
    LISTEN = 0
    NORMAL = 1
    STOPPED = 2


class Result(IntEnum):
    OK = 0
    INVALID = 1
    WRONG_BUS = 2
    READ_ONLY = 3
    BUSY = 4
    DRIVER_ERROR = 5
    LINK_TIMEOUT = 6
    TIMEOUT = 7
    CANCELLED = 8


@dataclass(frozen=True)
class Packet:
    type: int
    bus: int
    sequence: int = 0
    payload: bytes = b""


@dataclass(frozen=True)
class Frame:
    id: int
    data: bytes = b""
    extended: bool = False
    remote: bool = False
    dlc: int = 0
    timestamp_us: int = 0


def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x1021 if crc & 0x8000 else 0)) & 0xFFFF
    return crc


def cobs_encode(raw: bytes) -> bytes:
    if len(raw) > 72:
        raise ValueError("packet is too long")
    encoded = bytearray(b"\x00")
    code_position, code = 0, 1
    for byte in raw:
        if byte == 0:
            encoded[code_position] = code
            code_position, code = len(encoded), 1
            encoded.append(0)
        else:
            encoded.append(byte)
            code += 1
    encoded[code_position] = code
    return bytes(encoded)


def cobs_decode(encoded: bytes) -> bytes:
    if not encoded or len(encoded) > MAX_ENCODED or 0 in encoded:
        raise ValueError("invalid COBS packet")
    raw = bytearray()
    index = 0
    while index < len(encoded):
        code = encoded[index]
        index += 1
        end = index + code - 1
        if end > len(encoded):
            raise ValueError("truncated COBS packet")
        raw.extend(encoded[index:end])
        index = end
        if code != 255 and index < len(encoded):
            raw.append(0)
        if len(raw) > 72:
            raise ValueError("decoded packet is too long")
    return bytes(raw)


def encode(packet: Packet) -> bytes:
    if len(packet.payload) > MAX_PAYLOAD:
        raise ValueError("payload is too long")
    raw = struct.pack("<BBBHB", VERSION, packet.type, packet.bus, packet.sequence, len(packet.payload))
    raw += packet.payload
    return cobs_encode(raw + struct.pack("<H", crc16(raw))) + b"\x00"


def decode(encoded: bytes) -> Packet:
    raw = cobs_decode(encoded)
    if len(raw) < 8:
        raise ValueError("short packet")
    version, kind, bus, sequence, length = struct.unpack_from("<BBBHB", raw)
    if version != VERSION or length > MAX_PAYLOAD or len(raw) != length + 8:
        raise ValueError("unsupported version or bad length")
    if struct.unpack_from("<H", raw, len(raw) - 2)[0] != crc16(raw[:-2]):
        raise ValueError("CRC mismatch")
    return Packet(kind, bus, sequence, raw[6:-2])


class Parser:
    def __init__(self):
        self.buffer = bytearray()
        self.discard = False
        self.errors = 0

    def feed(self, data: bytes) -> list[Packet]:
        packets = []
        for byte in data:
            if byte == 0:
                if self.buffer and not self.discard:
                    try:
                        packets.append(decode(bytes(self.buffer)))
                    except ValueError:
                        self.errors += 1
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                if len(self.buffer) == MAX_ENCODED:
                    self.errors += 1
                    self.buffer.clear()
                    self.discard = True
                else:
                    self.buffer.append(byte)
        return packets


def encode_frame(frame: Frame) -> bytes:
    if not 0 <= frame.id <= (0x1FFFFFFF if frame.extended else 0x7FF):
        raise ValueError("CAN ID is out of range; use --extended for 29-bit IDs")
    if not 0 <= frame.dlc <= 8:
        raise ValueError("DLC must be 0..8")
    if (frame.remote and frame.data) or (not frame.remote and len(frame.data) != frame.dlc):
        raise ValueError("data length does not match the frame type/DLC")
    flags = int(frame.extended) | (int(frame.remote) << 1)
    return struct.pack("<BBII", flags, frame.dlc, frame.id, frame.timestamp_us) + frame.data


def decode_frame(payload: bytes) -> Frame:
    if len(payload) < 10:
        raise ValueError("short CAN frame")
    flags, dlc, can_id, timestamp = struct.unpack_from("<BBII", payload)
    if flags & ~3:
        raise ValueError("unsupported frame flags")
    frame = Frame(can_id, payload[10:], bool(flags & 1), bool(flags & 2), dlc, timestamp)
    encode_frame(frame)  # Check ID, DLC, and the RTR data rule.
    return frame


STATUS_FIELDS = (
    "bitrate", "rx_frames", "tx_queued", "tx_failed", "rx_missed", "rx_overrun",
    "transport_dropped", "invalid_packets", "bus_errors", "arbitration_lost",
    "tx_error_counter", "rx_error_counter", "last_error",
)


def decode_status(payload: bytes) -> dict:
    if len(payload) != 56:
        raise ValueError("invalid status size")
    mode, state, peer, role = payload[:4]
    if mode > 2 or state not in (0, 1, 2, 3, 255) or role not in (1, 2):
        raise ValueError("invalid status fields")
    result = dict(zip(STATUS_FIELDS, struct.unpack_from("<12Ii", payload, 4)))
    result.update(mode=Mode(mode).name.lower(),
                  state={0: "stopped", 1: "running", 2: "bus_off", 3: "recovering", 255: "unavailable"}[state],
                  role="master" if role == 1 else "slave", peer_online=None if peer == 255 else bool(peer))
    return result
