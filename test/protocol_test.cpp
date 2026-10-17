#include "protocol.h"
#include <assert.h>
#include <iostream>
#include <random>
#include <string>

using namespace protocol;

static void same(const Packet& left, const Packet& right) {
    assert(left.type == right.type && left.bus == right.bus);
    assert(left.sequence == right.sequence && left.length == right.length);
    assert(memcmp(left.payload, right.payload, left.length) == 0);
}

int main(int argc, char** argv) {
    // Cross-language test interface: decode each Python-generated wire packet,
    // re-encode with the C++ firmware implementation, return identical hex.
    if (argc == 2 && std::string(argv[1]) == "--vectors") {
        std::string hex;
        while (std::getline(std::cin, hex)) {
            assert(hex.size() % 2 == 0 && hex.size() <= maxWire * 2);
            uint8_t wire[maxWire];
            const size_t length = hex.size() / 2;
            for (size_t i = 0; i < length; ++i)
                wire[i] = std::stoul(hex.substr(i * 2, 2), nullptr, 16);
            assert(length > 0 && wire[length - 1] == 0);
            Packet packet;
            assert(decode(wire, length - 1, packet));
            uint8_t encoded[maxWire];
            const size_t encodedLength = encode(packet, encoded);
            const char* digits = "0123456789abcdef";
            for (size_t i = 0; i < encodedLength; ++i)
                std::cout << digits[encoded[i] >> 4] << digits[encoded[i] & 15];
            std::cout << '\n';
        }
        return 0;
    }

    assert(crc16(reinterpret_cast<const uint8_t*>("123456789"), 9) == 0x29b1);
    std::mt19937 random(9234);
    uint8_t wire[maxWire];
    for (unsigned i = 0; i < 20000; ++i) {
        Packet packet;
        packet.type = Received; packet.bus = i % 2;
        packet.sequence = random(); packet.length = i % (maxPayload + 1);
        for (unsigned j = 0; j < packet.length; ++j) packet.payload[j] = random();
        const size_t length = encode(packet, wire);
        assert(length <= maxWire && wire[length - 1] == 0);
        for (size_t j = 0; j + 1 < length; ++j) assert(wire[j] != 0);
        Packet decoded;
        assert(decode(wire, length - 1, decoded)); same(packet, decoded);
        Parser parser;
        for (size_t j = 0; j < length; ++j)
            assert(parser.feed(wire[j], decoded) == (j + 1 == length));
        same(packet, decoded);
        // An arbitrary single-bit error cannot produce a valid CRC packet.
        const size_t position = random() % (length - 1);
        wire[position] ^= 1 << (random() % 8);
        assert(!decode(wire, length - 1, decoded));
    }

    Packet ping; ping.type = Ping; ping.sequence = 42;
    const size_t pingLength = encode(ping, wire);
    Parser parser;
    Packet decoded;
    for (size_t i = 0; i < 1000; ++i) assert(!parser.feed(1, decoded));
    assert(parser.errors == 1);
    assert(!parser.feed(0, decoded));
    for (size_t i = 0; i < pingLength; ++i) parser.feed(wire[i], decoded);
    same(ping, decoded);

    Frame frame; frame.id = 0x1fffffff; frame.flags = Extended | Remote; frame.dlc = 8;
    Packet packet; encodeFrame(packet, frame);
    assert(packet.length == 10 && decodeFrame(packet, frame));
    packet.payload[0] = 0;  // 29-bit ID rejected without the extended flag.
    assert(!decodeFrame(packet, frame));
    packet.payload[0] = Extended | Remote; packet.payload[1] = 9;
    assert(!decodeFrame(packet, frame));
    packet.payload[1] = 8; packet.length = 11;
    assert(!decodeFrame(packet, frame));
    packet.length = 10; packet.payload[0] = 0x80;
    assert(!decodeFrame(packet, frame));

    // Fuzz hostile encoded input under ASan/UBSan, including oversized blocks.
    uint8_t hostile[150];
    for (unsigned i = 0; i < 50000; ++i) {
        const size_t length = random() % sizeof(hostile);
        for (size_t j = 0; j < length; ++j) hostile[j] = random();
        decode(hostile, length, decoded);
        for (size_t j = 0; j < length; ++j) parser.feed(hostile[j], decoded);
        parser.feed(0, decoded);
    }
    std::cout << "C++ protocol checks passed\n";
}
