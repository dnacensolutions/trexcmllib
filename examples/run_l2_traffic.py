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

from trexcmllib import TrexConsoleConfig, TrexConsoleLauncher
from trexcmllib.examples.common import discover_port_macs, parse_summary


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


def build_l2_batch(*, tx_port: int, rx_port: int, tx_mac: str, rx_mac: str, packets: int) -> list[str]:
    if packets < 1:
        raise ValueError("--packets must be at least 1")

    commands = [
        f"service -p {tx_port} {rx_port}",
        f"l2 -p {tx_port} --dst {rx_mac}",
        f"l2 -p {rx_port} --dst {tx_mac}",
        f"service --off -p {tx_port} {rx_port}",
        "clear",
    ]
    packet_cmd = f"pkt -p {tx_port} -s Ether(src='{tx_mac}',dst='{rx_mac}')/IP()/UDP()/('x'*10)"
    commands.extend([packet_cmd] * packets)
    commands.extend(["stats", f"release -p {tx_port} {rx_port}"])
    return commands


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    cfg = TrexConsoleConfig(
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
    launcher = TrexConsoleLauncher(cfg)

    tx_mac = args.tx_mac.lower() if args.tx_mac else None
    rx_mac = args.rx_mac.lower() if args.rx_mac else None

    if tx_mac is None or rx_mac is None:
        port_macs = discover_port_macs(launcher)
        try:
            tx_mac = tx_mac or port_macs[args.tx_port]["mac"]
            rx_mac = rx_mac or port_macs[args.rx_port]["mac"]
        except KeyError as exc:
            parser.error(
                f"could not auto-discover MAC for port {exc.args[0]}; "
                "pass --tx-mac and --rx-mac explicitly for this node"
            )

    result = launcher.run_console_batch(
        build_l2_batch(
            tx_port=args.tx_port,
            rx_port=args.rx_port,
            tx_mac=tx_mac,
            rx_mac=rx_mac,
            packets=args.packets,
        ),
        password=args.password,
        ports=[args.tx_port, args.rx_port],
        force_acquire=True,
        readonly=False,
        timeout=max(40.0, float(args.packets) * 1.5),
    )

    metrics = parse_summary(result.output)
    tx_packets = metrics.get("opackets", {}).get(args.tx_port, 0)
    rx_packets = metrics.get("ipackets", {}).get(args.rx_port, 0)
    tx_bytes = metrics.get("obytes", {}).get(args.tx_port, 0)
    rx_bytes = metrics.get("ibytes", {}).get(args.rx_port, 0)
    tx_errors = metrics.get("oerrors", {}).get(args.tx_port, 0)
    rx_errors = metrics.get("ierrors", {}).get(args.rx_port, 0)

    print(f"CML host        : {args.jump_host}")
    print(f"Lab / node      : {args.lab_name} / {args.node_name}")
    print(f"Ports           : tx={args.tx_port} rx={args.rx_port}")
    print(f"Port MACs       : tx={tx_mac} rx={rx_mac}")
    print(f"Packets asked   : {args.packets}")
    print(f"Packets sent    : {tx_packets}")
    print(f"Packets received: {rx_packets}")
    print(f"Bytes sent      : {tx_bytes}")
    print(f"Bytes received  : {rx_bytes}")
    print(f"Tx errors       : {tx_errors}")
    print(f"Rx errors       : {rx_errors}")
    print(f"Batch success   : {'yes' if result.success else 'no'}")

    if result.success and tx_packets == args.packets and rx_packets == args.packets and tx_errors == 0 and rx_errors == 0:
        return 0

    print("\nFull console output:\n")
    print(result.output)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
