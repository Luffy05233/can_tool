#!/usr/bin/env python3
"""Observe both boards and query status repeatedly on one serial connection.

Only GET_STATUS commands are sent; this does not enable or transmit CAN traffic.
"""
import argparse
import sys
import time

from can_protocol import Type, decode_status
from dualcan import AdapterError, BUS_NAMES, Client


def check(client, rounds):
    latest = {}
    first = {}
    failed = False

    def observe(packet):
        if packet.type != Type.STATUS or packet.bus not in BUS_NAMES:
            return
        try:
            status = decode_status(packet.payload)
        except ValueError:
            client.parser.errors += 1
            return
        latest[packet.bus] = status
        first.setdefault(packet.bus, status)

    def listen(seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            client.pump()

    def summary(label):
        print(label, flush=True)
        for bus, name in BUS_NAMES.items():
            if bus not in latest:
                print(f"  {name}: no status received", flush=True)
                continue
            start = first[bus]['invalid_packets']
            end = latest[bus]['invalid_packets']
            print(f"  {name}: invalid_packets {start} -> {end}", flush=True)
        print(f"  PC malformed packets: {client.parser.errors}", flush=True)

    client.on_packet = observe
    print("USB stays open throughout. Listening for 5 seconds before requests...", flush=True)
    listen(5)
    summary("Passive baseline (unsolicited status):")
    for attempt in range(1, rounds + 1):
        for bus, name in BUS_NAMES.items():
            try:
                status = decode_status(client.command(Type.GET_STATUS, bus).payload)
                print(f"{attempt} {name}: OK, {status['state']}, "
                      f"invalid_packets={status['invalid_packets']}, "
                      f"peer_online={status['peer_online']}", flush=True)
            except (AdapterError, ValueError) as error:
                failed = True
                print(f"{attempt} {name}: FAILED: {error}", flush=True)
        print(f"  PC malformed packets: {client.parser.errors}", flush=True)
        listen(1)
    print("Listening for 5 more seconds without requests...", flush=True)
    before_idle = {bus: status['invalid_packets'] for bus, status in latest.items()}
    listen(5)
    summary("Whole-session counter range (a decrease can indicate a reset):")
    for bus, start in before_idle.items():
        print(f"  Final idle {BUS_NAMES[bus]}: invalid_packets "
              f"{start} -> {latest[bus]['invalid_packets']}", flush=True)
    return int(failed or client.parser.errors or any(
        latest[bus]['invalid_packets'] != status['invalid_packets']
        for bus, status in first.items()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--baud', type=int, default=57600)
    parser.add_argument('--rounds', type=int, default=5)
    args = parser.parse_args()
    if args.baud <= 0 or args.rounds <= 0:
        parser.error('--baud and --rounds must be positive')
    try:
        import serial
    except ImportError:
        print('Run with the PlatformIO Python environment (pyserial required).', file=sys.stderr)
        return 1
    port = serial.Serial(port=None, baudrate=args.baud, timeout=0.05, write_timeout=1)
    port.dtr = False
    port.rts = False
    port.port = args.port
    try:
        with port:
            time.sleep(2)
            port.reset_input_buffer()
            return check(Client(port), args.rounds)
    except KeyboardInterrupt:
        return 130
    except (OSError, serial.SerialException) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
