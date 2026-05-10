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

from trexcmllib import TrexConsoleConfig, TrexConsoleLauncher
from trexcmllib.examples.common import discover_port_macs, parse_summary


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


def build_l2_bidirectional_batch(*, port_a: int, port_b: int, port_a_mac: str, port_b_mac: str, packets: int) -> list[str]:
    if packets < 1:
        raise ValueError("--packets must be at least 1")

    commands = [
        f"service -p {port_a} {port_b}",
        f"l2 -p {port_a} --dst {port_b_mac}",
        f"l2 -p {port_b} --dst {port_a_mac}",
        f"service --off -p {port_a} {port_b}",
        "clear",
    ]

    pkt_a = f"pkt -p {port_a} -s Ether(src='{port_a_mac}',dst='{port_b_mac}')/IP()/UDP()/('x'*10)"
    pkt_b = f"pkt -p {port_b} -s Ether(src='{port_b_mac}',dst='{port_a_mac}')/IP()/UDP()/('x'*10)"
    for _ in range(packets):
        commands.append(pkt_a)
        commands.append(pkt_b)

    commands.extend(["stats", f"release -p {port_a} {port_b}"])
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

    port_a_mac = args.port_a_mac.lower() if args.port_a_mac else None
    port_b_mac = args.port_b_mac.lower() if args.port_b_mac else None

    if port_a_mac is None or port_b_mac is None:
        port_macs = discover_port_macs(launcher)
        try:
            port_a_mac = port_a_mac or port_macs[args.port_a]["mac"]
            port_b_mac = port_b_mac or port_macs[args.port_b]["mac"]
        except KeyError as exc:
            parser.error(
                f"could not auto-discover MAC for port {exc.args[0]}; "
                "pass --port-a-mac and --port-b-mac explicitly for this node"
            )

    result = launcher.run_console_batch(
        build_l2_bidirectional_batch(
            port_a=args.port_a,
            port_b=args.port_b,
            port_a_mac=port_a_mac,
            port_b_mac=port_b_mac,
            packets=args.packets,
        ),
        password=args.password,
        ports=[args.port_a, args.port_b],
        force_acquire=True,
        readonly=False,
        timeout=max(40.0, float(args.packets) * 3.0),
    )

    metrics = parse_summary(result.output)

    a_tx = metrics.get("opackets", {}).get(args.port_a, 0)
    a_rx = metrics.get("ipackets", {}).get(args.port_a, 0)
    b_tx = metrics.get("opackets", {}).get(args.port_b, 0)
    b_rx = metrics.get("ipackets", {}).get(args.port_b, 0)
    a_tx_bytes = metrics.get("obytes", {}).get(args.port_a, 0)
    a_rx_bytes = metrics.get("ibytes", {}).get(args.port_a, 0)
    b_tx_bytes = metrics.get("obytes", {}).get(args.port_b, 0)
    b_rx_bytes = metrics.get("ibytes", {}).get(args.port_b, 0)
    a_oerrors = metrics.get("oerrors", {}).get(args.port_a, 0)
    a_ierrors = metrics.get("ierrors", {}).get(args.port_a, 0)
    b_oerrors = metrics.get("oerrors", {}).get(args.port_b, 0)
    b_ierrors = metrics.get("ierrors", {}).get(args.port_b, 0)

    expected_total = args.packets * 2
    sent_total = a_tx + b_tx
    received_total = a_rx + b_rx

    print(f"CML host          : {args.jump_host}")
    print(f"Lab / node        : {args.lab_name} / {args.node_name}")
    print(f"Ports             : a={args.port_a} b={args.port_b}")
    print(f"Port MACs         : a={port_a_mac} b={port_b_mac}")
    print(f"Packets per port  : {args.packets}")
    print(f"Expected total tx : {expected_total}")
    print(f"Expected total rx : {expected_total}")
    print(f"Port {args.port_a} sent     : {a_tx}")
    print(f"Port {args.port_a} received : {a_rx}")
    print(f"Port {args.port_b} sent     : {b_tx}")
    print(f"Port {args.port_b} received : {b_rx}")
    print(f"Total sent        : {sent_total}")
    print(f"Total received    : {received_total}")
    print(f"Port {args.port_a} tx bytes : {a_tx_bytes}")
    print(f"Port {args.port_a} rx bytes : {a_rx_bytes}")
    print(f"Port {args.port_b} tx bytes : {b_tx_bytes}")
    print(f"Port {args.port_b} rx bytes : {b_rx_bytes}")
    print(f"Port {args.port_a} errors   : tx={a_oerrors} rx={a_ierrors}")
    print(f"Port {args.port_b} errors   : tx={b_oerrors} rx={b_ierrors}")
    print(f"Batch success     : {'yes' if result.success else 'no'}")

    if (
        result.success
        and a_tx == args.packets
        and a_rx == args.packets
        and b_tx == args.packets
        and b_rx == args.packets
        and a_oerrors == 0
        and a_ierrors == 0
        and b_oerrors == 0
        and b_ierrors == 0
    ):
        return 0

    print("\nFull console output:\n")
    print(result.output)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
