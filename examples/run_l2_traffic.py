#!/usr/bin/env python3
"""Run a simple L2 packet test on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, node name, and packet count.
3. Optionally pass ``--tx-mac`` and ``--rx-mac`` if MAC auto-discovery is not available.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --packets 10
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from trexcmllib import TrexConsoleConfig, TrexTraffic


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
            "    --packets 10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cml-host", "--jump-host", dest="jump_host", required=True, help="CML terminal server hostname or IP")
    parser.add_argument("--lab-name", required=True, help="CML lab name")
    parser.add_argument("--node-name", required=True, help="TRex node name in the lab")
    parser.add_argument("--node-port", default="0", help="CML console line index (default: 0)")
    parser.add_argument("--user", required=True, help="SSH username for the CML host")
    parser.add_argument("--password", default=None, help="SSH password for the CML host")
    parser.add_argument("--password-env", default="TREXCMLLIB_PASSWORD", help="Environment variable used for the SSH password")
    parser.add_argument("--packets", type=int, required=True, help="Number of L2 packets to inject from tx-port")
    parser.add_argument("--tx-port", type=int, default=0, help="TRex transmit port (default: 0)")
    parser.add_argument("--rx-port", type=int, default=1, help="TRex receive port (default: 1)")
    parser.add_argument("--tx-mac", default=None, help="Override the source MAC for tx-port")
    parser.add_argument("--rx-mac", default=None, help="Override the source MAC for rx-port")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    traffic = TrexTraffic(
        TrexConsoleConfig(
            jump_host=args.jump_host,
            user=args.user,
            lab_name=args.lab_name,
            node_name=args.node_name,
            node_port=str(args.node_port),
            password=args.password,
            password_env=args.password_env,
            readonly=False,
            force_acquire=True,
        )
    )
    result = traffic.run(
        "l2",
        packets=args.packets,
        tx_port=args.tx_port,
        rx_port=args.rx_port,
        tx_mac=args.tx_mac,
        rx_mac=args.rx_mac,
        password=args.password,
    )
    summary = result.summary

    print(f"CML host        : {args.jump_host}")
    print(f"Lab / node      : {args.lab_name} / {args.node_name}")
    print(f"Ports           : tx={summary['tx_port']} rx={summary['rx_port']}")
    print(f"Port MACs       : tx={summary['tx_mac']} rx={summary['rx_mac']}")
    print(f"Packets asked   : {summary['packets_asked']}")
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
