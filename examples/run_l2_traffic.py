#!/usr/bin/env python3
"""Run a simple L2 packet test on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab selector, and node selector.
3. Choose either packet mode with ``--packets`` or stream mode with ``--rate`` and ``--duration``.
4. Optionally pass ``--tx-mac`` and ``--rx-mac`` if MAC auto-discovery is not available.
5. In packet mode, optionally tune ``--packet-pps`` to reduce burst-driven loss.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --packets 10
      --packet-pps 50

Stream CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-id <lab-id> \
      --node-name <node-name> \
      --rate 10kpps \
      --duration 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from trexcmllib import TrexConsoleConfig, TrexTraffic
from trexcmllib.examples.common import add_console_target_args, add_traffic_reset_args, console_target_kwargs, console_target_label, validate_console_target_args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send unidirectional L2 packets and print a traffic summary.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --packets 10\n\n"
            "Stream example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-id <lab-id> \\\n"
            "    --node-name <node-name> \\\n"
            "    --rate 10kpps \\\n"
            "    --duration 10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_console_target_args(parser)
    add_traffic_reset_args(parser)
    parser.add_argument("--packets", type=int, default=None, help="Number of L2 packets to inject from tx-port in packet mode")
    parser.add_argument("--packet-pps", type=int, default=50, help="Burst rate used in packet mode when --packets is provided (default: 50)")
    parser.add_argument("--rate", default=None, help="Optional TRex stream rate, for example 10kpps, 100mbps, or 5%%")
    parser.add_argument("--duration", type=float, default=10.0, help="Stream duration in seconds when --rate is used (default: 10)")
    parser.add_argument("--frame-size", type=int, default=64, help="L2 frame size for stream mode (default: 64)")
    parser.add_argument("--tx-port", type=int, default=0, help="TRex transmit port (default: 0)")
    parser.add_argument("--rx-port", type=int, default=1, help="TRex receive port (default: 1)")
    parser.add_argument("--tx-mac", default=None, help="Override the source MAC for tx-port")
    parser.add_argument("--rx-mac", default=None, help="Override the source MAC for rx-port")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_console_target_args(parser, args)
    if args.rate is None and args.packets is None:
        parser.error("provide --packets for packet mode, or --rate with --duration for stream mode")
    if args.rate is not None and args.duration <= 0:
        parser.error("--duration must be greater than 0 when --rate is used")
    if args.packet_pps < 1:
        parser.error("--packet-pps must be at least 1")

    traffic = TrexTraffic(
        TrexConsoleConfig(
            **console_target_kwargs(args),
            readonly=False,
            force_acquire=True,
        ),
        hard_reset=args.hard_reset,
    )
    result = traffic.run(
        "l2",
        packets=args.packets,
        tx_port=args.tx_port,
        rx_port=args.rx_port,
        tx_mac=args.tx_mac,
        rx_mac=args.rx_mac,
        rate=args.rate,
        duration=args.duration,
        frame_size=args.frame_size,
        packet_pps=args.packet_pps,
        password=args.password,
    )
    summary = result.summary
    lab_label, node_label = console_target_label(args)

    print(f"CML host        : {args.jump_host}")
    print(f"Lab / node      : {lab_label} / {node_label}")
    print(f"Traffic mode    : {summary.get('mode', 'packet')}")
    print(f"Ports           : tx={summary['tx_port']} rx={summary['rx_port']}")
    print(f"Port MACs       : tx={summary['tx_mac']} rx={summary['rx_mac']}")
    if summary.get("mode") == "stream":
        print(f"Rate            : {summary.get('rate', 'n/a')}")
        print(f"Duration        : {summary.get('duration', 0)}")
        print(f"Frame size      : {summary.get('frame_size', 0)}")
    else:
        print(f"Packets asked   : {summary['packets_asked']}")
        print(f"Packet PPS      : {summary.get('packet_pps', args.packet_pps)}")
    print(f"Packets sent    : {summary['packets_sent']}")
    print(f"Packets received: {summary['packets_received']}")
    print(f"Packet loss     : {summary['packet_loss']} ({summary['packet_loss_pct']:.2f}%)")
    print(f"Bytes sent      : {summary['bytes_sent']}")
    print(f"Bytes received  : {summary['bytes_received']}")
    print(f"Tx errors       : {summary['tx_errors']}")
    print(f"Rx errors       : {summary['rx_errors']}")
    print(f"Batch success   : {'yes' if summary['batch_success'] else 'no'}")

    if result.success:
        return 0

    print("\nFull console output:\n")
    print(result.outputs["traffic"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
