#include <Arduino.h>
#include <atomic>
#include "driver/twai.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "config.h"
#include "protocol.h"

using namespace protocol;

namespace {
std::atomic<uint32_t> invalidPackets{0}, transportDrops{0}, peerSeenMs{0};
std::atomic<bool> peerSeen{false};
QueueHandle_t commands = nullptr;

// UART writers can block without blocking CAN reception or command parsing.
// Control responses have a separate queue, ahead of captured frames.
class Output {
public:
    bool begin(uart_port_t port, uint32_t baud, int tx, int rx) {
        port_ = port;
        uart_config_t settings = {};
        settings.baud_rate = baud; settings.data_bits = UART_DATA_8_BITS;
        settings.parity = UART_PARITY_DISABLE; settings.stop_bits = UART_STOP_BITS_1;
        settings.flow_ctrl = UART_HW_FLOWCTRL_DISABLE; settings.source_clk = UART_SCLK_APB;
        if (uart_param_config(port, &settings) != ESP_OK ||
            uart_set_pin(port, tx, rx, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) != ESP_OK ||
            uart_driver_install(port, 8192, 0, 0, nullptr, 0) != ESP_OK) return false;
        control_ = xQueueCreate(32, sizeof(Packet));
        frames_ = xQueueCreate(256, sizeof(Packet));
        return control_ && frames_ &&
               xTaskCreate(writer, "uart-output", 3072, this, 2, nullptr) == pdPASS;
    }
    bool send(const Packet& packet) {
        const QueueHandle_t queue = packet.type == Received ? frames_ : control_;
        if (!queue || xQueueSend(queue, &packet, 0) != pdTRUE) {
            ++transportDrops; return false;
        }
        return true;
    }
private:
    static void writer(void* context) {
        auto& self = *static_cast<Output*>(context);
        Packet packet;
        uint8_t wire[maxWire];
        for (;;) {
            if (xQueueReceive(self.control_, &packet, 0) != pdTRUE &&
                xQueueReceive(self.frames_, &packet, 1) != pdTRUE) continue;
            const size_t length = encode(packet, wire);
            if (!length || uart_write_bytes(self.port_, wire, length) != int(length))
                ++transportDrops;
        }
    }
    uart_port_t port_ = UART_NUM_2;
    QueueHandle_t control_ = nullptr, frames_ = nullptr;
};

Output linkOutput, pcOutput;
Output& upstream() { return config::master ? pcOutput : linkOutput; }

void reply(const Packet& command, Result result, esp_err_t error = ESP_OK, uint8_t type = Ack) {
    Packet packet;
    packet.type = type; packet.bus = command.bus; packet.sequence = command.sequence;
    packet.length = 6; packet.payload[0] = command.type; packet.payload[1] = result;
    write32(packet.payload + 2, static_cast<uint32_t>(error));
    upstream().send(packet);
}

bool validCommand(const Packet& packet) {
    Frame frame;
    switch (packet.type) {
        case Transmit: return decodeFrame(packet, frame) && frame.timestampUs == 0;
        case SetMode: return packet.length == 1 && packet.payload[0] <= Stopped;
        case GetStatus: case Ping: return packet.length == 0;
        default: return false;
    }
}

// This task owns every TWAI call, including stop/uninstall and alert handling.
class CanChannel {
public:
    void run() {
        configure(Listen);
        sendStatus(0);
        uint32_t lastStatus = millis();
        for (;;) {
            serviceAlerts();
            const uint32_t now = millis();
            if (pendingTx_ && uint32_t(now - txStartedMs_) >= config::transmitTimeoutMs) {
                finishTx(Timeout, ESP_ERR_TIMEOUT);
                configure(Listen);
            }
            if (mode_ == Normal && uint32_t(now - lastHostMs_) >= config::activeTimeoutMs) {
                finishTx(Cancelled);
                configure(Listen);
            }
            Packet command;
            for (unsigned i = 0; i < 16 && xQueueReceive(commands, &command, 0) == pdTRUE; ++i) {
                serviceAlerts();
                handle(command);
            }
            if (installed_ && mode_ != Stopped) {
                twai_message_t message;
                for (unsigned i = 0; i < 128 && twai_receive(&message, 0) == ESP_OK; ++i) {
                    if (message.data_length_code > 8) { ++invalidPackets; continue; }
                    Packet packet;
                    packet.type = Received; packet.bus = config::localBus;
                    Frame frame;
                    frame.flags = (message.extd ? Extended : 0) | (message.rtr ? Remote : 0);
                    frame.dlc = message.data_length_code; frame.id = message.identifier;
                    frame.timestampUs = micros();  // dequeue time, local board clock
                    memcpy(frame.data, message.data, sizeof(frame.data));
                    encodeFrame(packet, frame); ++rxFrames_;
                    upstream().send(packet);
                }
            }
            if (uint32_t(now - lastStatus) >= config::statusIntervalMs) {
                sendStatus(0); lastStatus = now;
            }
            vTaskDelay(1);
        }
    }
private:
    esp_err_t configure(Mode next) {
        if (installed_) {
            twai_status_info_t status = {};
            esp_err_t error = twai_get_status_info(&status);
            if (error != ESP_OK) return lastError_ = error;
            // Bus-off recovery is explicit: reinstall into the requested mode.
            if (status.state == TWAI_STATE_RECOVERING) return lastError_ = ESP_ERR_INVALID_STATE;
            if (status.state == TWAI_STATE_RUNNING && (error = twai_stop()) != ESP_OK)
                return lastError_ = error;
            if ((error = twai_get_status_info(&status)) != ESP_OK) return lastError_ = error;
            if ((error = twai_driver_uninstall()) != ESP_OK) return lastError_ = error;
            missed_ += status.rx_missed_count + status.msgs_to_rx;
            overruns_ += status.rx_overrun_count;
            txFailed_ += status.tx_failed_count; busErrors_ += status.bus_error_count;
            arbitrationLost_ += status.arb_lost_count;
            installed_ = false;
        }
        mode_ = Stopped;
        if (next == Stopped) return lastError_ = ESP_OK;
        twai_general_config_t general = TWAI_GENERAL_CONFIG_DEFAULT(
            static_cast<gpio_num_t>(CAN_TX_GPIO), static_cast<gpio_num_t>(CAN_RX_GPIO),
            next == Normal ? TWAI_MODE_NORMAL : TWAI_MODE_LISTEN_ONLY);
        general.tx_queue_len = 0;  // exactly one in-flight TX for correlated results
        general.rx_queue_len = 256;
        general.alerts_enabled = TWAI_ALERT_TX_SUCCESS | TWAI_ALERT_TX_FAILED | TWAI_ALERT_BUS_OFF;
        twai_timing_config_t timing = TWAI_TIMING_CONFIG_125KBITS();
        if (!config::master) timing = TWAI_TIMING_CONFIG_500KBITS();
        twai_filter_config_t filter = TWAI_FILTER_CONFIG_ACCEPT_ALL();
        esp_err_t error = twai_driver_install(&general, &timing, &filter);
        if (error != ESP_OK) return lastError_ = error;
        installed_ = true;
        error = twai_start();
        if (error == ESP_OK) mode_ = next;
        return lastError_ = error;
    }
    void finishTx(Result result, esp_err_t error = ESP_OK) {
        if (!pendingTx_) return;
        reply(txCommand_, result, error, TxResult); pendingTx_ = false;
    }
    void serviceAlerts() {
        if (!installed_) return;
        uint32_t alerts = 0;
        if (twai_read_alerts(&alerts, 0) != ESP_OK) return;
        if (alerts & TWAI_ALERT_TX_SUCCESS) finishTx(Ok);
        else if (alerts & (TWAI_ALERT_TX_FAILED | TWAI_ALERT_BUS_OFF)) finishTx(DriverError, ESP_FAIL);
        if (alerts & TWAI_ALERT_BUS_OFF) { lastError_ = ESP_FAIL; sendStatus(0); }
    }
    void handle(const Packet& command) {
        if (command.sequence) lastHostMs_ = millis();
        switch (command.type) {
            case Ping: reply(command, Ok); return;
            case GetStatus: sendStatus(command.sequence); return;
            case SetMode: {
                if (pendingTx_) { reply(command, Busy); return; }
                const Mode next = static_cast<Mode>(command.payload[0]);
                twai_status_info_t status = {};
                if (next == mode_ && (next == Stopped ||
                    (installed_ && twai_get_status_info(&status) == ESP_OK && status.state == TWAI_STATE_RUNNING))) {
                    reply(command, Ok); return;
                }
                const esp_err_t error = configure(next);
                reply(command, error == ESP_OK ? Ok : DriverError, error); return;
            }
            case Transmit: {
                if (mode_ != Normal) { reply(command, ReadOnly); return; }
                if (pendingTx_) { reply(command, Busy); return; }
                Frame frame;
                if (!decodeFrame(command, frame)) { reply(command, Invalid); return; }
                twai_message_t message = {};
                message.identifier = frame.id; message.data_length_code = frame.dlc;
                message.extd = (frame.flags & Extended) != 0; message.rtr = (frame.flags & Remote) != 0;
                message.ss = 1;  // single-shot: no indefinite retries on a faulty bus
                memcpy(message.data, frame.data, sizeof(message.data));
                const esp_err_t error = twai_transmit(&message, 0);
                lastError_ = error;
                if (error != ESP_OK) { reply(command, DriverError, error); return; }
                txCommand_ = command; pendingTx_ = true; txStartedMs_ = millis(); ++txQueued_;
                reply(command, Ok); return;
            }
            default: reply(command, Invalid); return;
        }
    }
    void sendStatus(uint16_t sequence) {
        twai_status_info_t status = {};
        const bool valid = installed_ && twai_get_status_info(&status) == ESP_OK;
        Packet packet;
        packet.type = Status; packet.bus = config::localBus; packet.sequence = sequence; packet.length = 56;
        packet.payload[0] = mode_;
        packet.payload[1] = valid ? static_cast<uint8_t>(status.state) :
            (mode_ == Stopped && lastError_ == ESP_OK ? 0 : 0xff);
        packet.payload[2] = config::master ?
            (peerSeen && uint32_t(millis() - peerSeenMs.load()) < config::peerTimeoutMs ? 1 : 0) : 0xff;
        packet.payload[3] = config::master ? 1 : 2;
        const uint32_t fields[] = {
            config::bitrate, rxFrames_, txQueued_, txFailed_ + status.tx_failed_count,
            missed_ + status.rx_missed_count, overruns_ + status.rx_overrun_count,
            transportDrops.load(), invalidPackets.load(), busErrors_ + status.bus_error_count,
            arbitrationLost_ + status.arb_lost_count, status.tx_error_counter,
            status.rx_error_counter, static_cast<uint32_t>(lastError_)
        };
        for (unsigned i = 0; i < 13; ++i) write32(packet.payload + 4 + i * 4, fields[i]);
        upstream().send(packet);
    }
    bool installed_ = false, pendingTx_ = false;
    Mode mode_ = Stopped;
    Packet txCommand_;
    uint32_t txStartedMs_ = 0, lastHostMs_ = 0;
    uint32_t rxFrames_ = 0, txQueued_ = 0, txFailed_ = 0, missed_ = 0, overruns_ = 0;
    uint32_t busErrors_ = 0, arbitrationLost_ = 0;
    esp_err_t lastError_ = ESP_OK;
};

CanChannel canChannel;
void canTask(void*) { canChannel.run(); }

struct Pending {
    bool used = false;
    uint16_t sequence = 0;
    uint8_t type = 0;
    uint32_t startedMs = 0;
};
Pending pending[16];
Parser pcParser, linkParser;
bool bootReady = false;

void acceptCommand(const Packet& packet, bool fromPc) {
    if (packet.bus > 1) { ++invalidPackets; reply(packet, WrongBus); return; }
    if (!validCommand(packet) || (!packet.sequence &&
        (fromPc || packet.type != GetStatus))) {
        ++invalidPackets; reply(packet, Invalid); return;
    }
    if (packet.bus == config::localBus) {
        if (xQueueSend(commands, &packet, 0) != pdTRUE) reply(packet, Busy);
        return;
    }
    if (!config::master || !fromPc) { ++invalidPackets; reply(packet, WrongBus); return; }
    Pending* available = nullptr;
    for (auto& item : pending) {
        if (item.used && item.sequence == packet.sequence) { reply(packet, Busy); return; }
        if (!item.used && !available) available = &item;
    }
    if (!available) { reply(packet, Busy); return; }
    if (!linkOutput.send(packet)) { reply(packet, Busy); return; }
    available->used = true; available->sequence = packet.sequence;
    available->type = packet.type; available->startedMs = millis();
}

void acceptSlavePacket(const Packet& packet) {
    Frame frame;
    const bool valid = packet.bus == 1 && (
        (packet.type == Received && packet.sequence == 0 && decodeFrame(packet, frame)) ||
        (packet.type == Status && packet.length == 56 && packet.payload[0] <= Stopped &&
            (packet.payload[1] <= 3 || packet.payload[1] == 0xff) && packet.payload[3] == 2) ||
        ((packet.type == Ack || packet.type == TxResult) && packet.length == 6 &&
            packet.payload[0] >= Transmit && packet.payload[0] <= Ping && packet.payload[1] <= Cancelled));
    if (!valid) { ++invalidPackets; return; }
    peerSeenMs = millis(); peerSeen = true;
    if (packet.sequence && (packet.type == Ack || packet.type == Status)) {
        for (auto& item : pending) {
            if (item.used && item.sequence == packet.sequence &&
                ((packet.type == Status && item.type == GetStatus) ||
                 (packet.type == Ack && packet.payload[0] == item.type))) item.used = false;
        }
    }
    pcOutput.send(packet);
}

void pollUart(uart_port_t port, Parser& parser, bool pc) {
    uint8_t bytes[1024];
    const int count = uart_read_bytes(port, bytes, sizeof(bytes), 0);
    const uint32_t previousErrors = parser.errors;
    Packet packet;
    for (int i = 0; i < count; ++i) {
        if (!parser.feed(bytes[i], packet)) continue;
        if (!pc && config::master) acceptSlavePacket(packet);
        else acceptCommand(packet, pc);
    }
    invalidPackets.fetch_add(parser.errors - previousErrors);
}
}  // namespace

void setup() {
    esp_log_level_set("*", ESP_LOG_NONE);
    // Keep CAN TX recessive until the driver is ready.
    digitalWrite(CAN_TX_GPIO, HIGH); pinMode(CAN_TX_GPIO, OUTPUT);
    if (!linkOutput.begin(UART_NUM_2, LINK_BAUD, LINK_TX_GPIO, LINK_RX_GPIO)) return;
    if (config::master && !pcOutput.begin(UART_NUM_0, PC_BAUD, 1, 3)) return;
    commands = xQueueCreate(32, sizeof(Packet));
    if (!commands || xTaskCreate(canTask, "can-channel", 4096, nullptr, 3, nullptr) != pdPASS) return;
    bootReady = true;
}

void loop() {
    if (!bootReady) { delay(1000); return; }
    if (config::master) pollUart(UART_NUM_0, pcParser, true);
    pollUart(UART_NUM_2, linkParser, false);
    if (config::master) {
        const uint32_t now = millis();
        for (auto& item : pending) {
            if (!item.used || uint32_t(now - item.startedMs) < config::commandTimeoutMs) continue;
            Packet command; command.bus = 1; command.type = item.type; command.sequence = item.sequence;
            reply(command, LinkTimeout, ESP_ERR_TIMEOUT); item.used = false;
        }
    }
    delay(1);
}
