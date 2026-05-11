#!/usr/bin/env python3
"""Run a simple bidirectional L2 packet test on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, node name, and packet count.
3. Optionally pass ``--port-a-mac`` and ``--port-b-mac`` if MAC auto-discovery is not available.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_bidirectional \
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
        description="Send bidirectional L2 packets and print per-port and total counters.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_bidirectional \\\n"
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
    parser.add_argument("--packets", type=int, required=True, help="Number of packets to inject from each port")
    parser.add_argument("--port-a", type=int, default=0, help="First TRex port (default: 0)")
    parser.add_argument("--port-b", type=int, default=1, help="Second TRex port (default: 1)")
    parser.add_argument("--port-a-mac", default=None, help="Override the source MAC for port-a")
    parser.add_argument("--port-b-mac", default=None, help="Override the source MAC for port-b")
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
        "l2_bidirectional",
        packets=args.packets,
        port_a=args.port_a,
        port_b=args.port_b,
        port_a_mac=args.port_a_mac,
        port_b_mac=args.port_b_mac,
        password=args.password,
    )
    summary = result.summary

    print(f"CML host          : {args.jump_host}")
    print(f"Lab / node        : {args.lab_name} / {args.node_name}")
    print(f"Ports             : a={summary['port_a']} b={summary['port_b']}")
    print(f"Port MACs         : a={summary['port_a_mac']} b={summary['port_b_mac']}")
    print(f"Packets per port  : {summary['packets_per_port']}")
    print(f"Expected total tx : {summary['expected_total']}")
    print(f"Expected total rx : {summary['expected_total']}")
    print(f"Port {summary['port_a']} sent     : {summary['port_a_sent']}")
    print(f"Port {summary['port_a']} received : {summary['port_a_received']}")
    print(f"Port {summary['port_b']} sent     : {summary['port_b_sent']}")
    print(f"Port {summary['port_b']} received : {summary['port_b_received']}")
    print(f"Loss {summary['port_a']}->{summary['port_b']}     : {summary['loss_a_to_b']} ({summary['loss_a_to_b_pct']:.2f}%)")
    print(f"Loss {summary['port_b']}->{summary['port_a']}     : {summary['loss_b_to_a']} ({summary['loss_b_to_a_pct']:.2f}%)")
    print(f"Total sent        : {summary['total_sent']}")
    print(f"Total received    : {summary['total_received']}")
    print(f"Total loss        : {summary['total_loss']} ({summary['total_loss_pct']:.2f}%)")
    print(f"Port {summary['port_a']} tx bytes : {summary['port_a_tx_bytes']}")
    print(f"Port {summary['port_a']} rx bytes : {summary['port_a_rx_bytes']}")
    print(f"Port {summary['port_b']} tx bytes : {summary['port_b_tx_bytes']}")
    print(f"Port {summary['port_b']} rx bytes : {summary['port_b_rx_bytes']}")
    print(f"Port {summary['port_a']} errors   : tx={summary['port_a_tx_errors']} rx={summary['port_a_rx_errors']}")
    print(f"Port {summary['port_b']} errors   : tx={summary['port_b_tx_errors']} rx={summary['port_b_rx_errors']}")
    print(f"Batch success     : {'yes' if summary['batch_success'] else 'no'}")

    if result.success:
        return 0

    print("\nFull console output:\n")
    print(result.outputs["traffic"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
