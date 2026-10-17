#pragma once

// Shared, allocation-free protocol. This header also builds on a Linux host.
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace protocol {
constexpr uint8_t version = 1;
constexpr size_t maxPayload = 64;
constexpr size_t maxRaw = 6 + maxPayload + 2;
constexpr size_t maxEncoded = maxRaw + 1;  // COBS, excludes delimiter
constexpr size_t maxWire = maxEncoded + 1;
enum Type : uint8_t {
    Transmit = 1, SetMode = 2, GetStatus = 3, Ping = 4,
    Ack = 0x80, Received = 0x81, Status = 0x82, TxResult = 0x83
};
enum Mode : uint8_t { Listen = 0, Normal = 1, Stopped = 2 };
enum Result : uint8_t {
    Ok = 0, Invalid = 1, WrongBus = 2, ReadOnly = 3, Busy = 4,
    DriverError = 5, LinkTimeout = 6, Timeout = 7, Cancelled = 8
};
enum FrameFlag : uint8_t { Extended = 1, Remote = 2 };
struct Packet {
    uint8_t type = 0, bus = 0, length = 0;
    uint16_t sequence = 0;
    uint8_t payload[maxPayload] = {};
};
struct Frame {
    uint8_t flags = 0, dlc = 0;
    uint32_t id = 0, timestampUs = 0;
    uint8_t data[8] = {};
};
inline uint16_t read16(const uint8_t* p) {
    return uint16_t(p[0]) | (uint16_t(p[1]) << 8);
}
inline uint32_t read32(const uint8_t* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) |
           (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}
inline void write16(uint8_t* p, uint16_t value) {
    p[0] = value; p[1] = value >> 8;
}
inline void write32(uint8_t* p, uint32_t value) {
    for (unsigned i = 0; i < 4; ++i) p[i] = value >> (8 * i);
}
inline uint16_t crc16(const uint8_t* data, size_t length) {
    uint16_t crc = 0xffff;
    for (size_t i = 0; i < length; ++i) {
        crc ^= uint16_t(data[i]) << 8;
        for (unsigned bit = 0; bit < 8; ++bit)
            crc = (crc & 0x8000) ? uint16_t((crc << 1) ^ 0x1021) : uint16_t(crc << 1);
    }
    return crc;
}
inline bool decodeFrame(const Packet& packet, Frame& frame) {
    if (packet.length < 10) return false;
    frame.flags = packet.payload[0];
    frame.dlc = packet.payload[1];
    frame.id = read32(packet.payload + 2);
    frame.timestampUs = read32(packet.payload + 6);
    if ((frame.flags & ~(Extended | Remote)) || frame.dlc > 8 ||
        frame.id > ((frame.flags & Extended) ? 0x1fffffffU : 0x7ffU)) return false;
    const size_t dataLength = (frame.flags & Remote) ? 0 : frame.dlc;
    if (packet.length != 10 + dataLength) return false;
    memset(frame.data, 0, sizeof(frame.data));
    memcpy(frame.data, packet.payload + 10, dataLength);
    return true;
}
inline void encodeFrame(Packet& packet, const Frame& frame) {
    const size_t dataLength = (frame.flags & Remote) ? 0 : frame.dlc;
    packet.length = 10 + dataLength;
    packet.payload[0] = frame.flags;
    packet.payload[1] = frame.dlc;
    write32(packet.payload + 2, frame.id);
    write32(packet.payload + 6, frame.timestampUs);
    memcpy(packet.payload + 10, frame.data, dataLength);
}
inline size_t encode(const Packet& packet, uint8_t* wire) {
    if (packet.length > maxPayload) return 0;
    uint8_t raw[maxRaw];
    raw[0] = version; raw[1] = packet.type; raw[2] = packet.bus;
    write16(raw + 3, packet.sequence); raw[5] = packet.length;
    memcpy(raw + 6, packet.payload, packet.length);
    const size_t length = 6 + packet.length;
    write16(raw + length, crc16(raw, length));
    size_t output = 1, codePosition = 0;
    uint8_t code = 1;
    for (size_t i = 0; i < length + 2; ++i) {
        if (raw[i] == 0) {
            wire[codePosition] = code; codePosition = output++; code = 1;
        } else {
            wire[output++] = raw[i]; ++code;
        }
    }
    wire[codePosition] = code;
    wire[output++] = 0;
    return output;
}
inline bool decode(const uint8_t* encoded, size_t length, Packet& packet) {
    if (length == 0 || length > maxEncoded) return false;
    uint8_t raw[maxRaw];
    size_t input = 0, output = 0;
    while (input < length) {
        const uint8_t code = encoded[input++];
        if (!code || size_t(code - 1) > length - input ||
            size_t(code - 1) > maxRaw - output) return false;
        for (unsigned i = 1; i < code; ++i) {
            if (encoded[input] == 0) return false;
            raw[output++] = encoded[input++];
        }
        if (code != 255 && input < length) {
            if (output == maxRaw) return false;
            raw[output++] = 0;
        }
    }
    if (output < 8 || raw[0] != version || raw[5] > maxPayload ||
        output != size_t(raw[5]) + 8 || read16(raw + output - 2) != crc16(raw, output - 2))
        return false;
    packet.type = raw[1]; packet.bus = raw[2]; packet.sequence = read16(raw + 3);
    packet.length = raw[5];
    memcpy(packet.payload, raw + 6, packet.length);
    return true;
}
class Parser {
public:
    uint32_t errors = 0;
    bool feed(uint8_t byte, Packet& packet) {
        if (byte == 0) {
            const bool ready = !discard_ && used_ && decode(buffer_, used_, packet);
            if (!discard_ && used_ && !ready) ++errors;
            used_ = 0; discard_ = false;
            return ready;
        }
        if (discard_) return false;
        if (used_ == maxEncoded) { ++errors; used_ = 0; discard_ = true; }
        else buffer_[used_++] = byte;
        return false;
    }
private:
    uint8_t buffer_[maxEncoded] = {};
    size_t used_ = 0;
    bool discard_ = false;
};
}  // namespace protocol
