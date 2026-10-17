#pragma once
#include <stdint.h>

#ifndef ADAPTER_MASTER
#error "Choose the PlatformIO master or slave environment"
#endif
#ifndef CAN_TX_GPIO
#define CAN_TX_GPIO 25
#endif
#ifndef CAN_RX_GPIO
#define CAN_RX_GPIO 26
#endif
#ifndef LINK_TX_GPIO
#define LINK_TX_GPIO 17
#endif
#ifndef LINK_RX_GPIO
#define LINK_RX_GPIO 16
#endif
#ifndef LINK_BAUD
#define LINK_BAUD 115200
#endif
#ifndef PC_BAUD
#define PC_BAUD 57600
#endif

namespace config {
constexpr bool master = ADAPTER_MASTER != 0;
constexpr uint8_t localBus = master ? 0 : 1;
constexpr uint32_t bitrate = master ? 125000 : 500000;
constexpr uint32_t statusIntervalMs = 1000;
constexpr uint32_t peerTimeoutMs = 2500;
constexpr uint32_t commandTimeoutMs = 1500;
constexpr uint32_t activeTimeoutMs = 3000;
constexpr uint32_t transmitTimeoutMs = 500;
static_assert(CAN_TX_GPIO != CAN_RX_GPIO, "CAN pins must differ");
static_assert(LINK_TX_GPIO != LINK_RX_GPIO, "UART pins must differ");
static_assert(CAN_TX_GPIO != LINK_TX_GPIO && CAN_TX_GPIO != LINK_RX_GPIO &&
              CAN_RX_GPIO != LINK_TX_GPIO && CAN_RX_GPIO != LINK_RX_GPIO,
              "CAN and UART pins must not overlap");
}  // namespace config
