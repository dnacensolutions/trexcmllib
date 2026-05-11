#!/usr/bin/env python3
"""Run ICMP ping validation on one or more remote TRex links via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, and TRex node name.
3. Add one or more ``--probe`` values in this format:
   ``<port>:<src-ip>:<next-hop-ip>:<dst-ip>``
4. Each probe is executed independently, so one failed port does not block the
   others from being tested.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --count 3 \
      --probe 0:192.0.2.10:192.0.2.1:192.0.2.1

Bidirectional example:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --count 3 \
      --probe 0:192.0.2.10:192.0.2.1:192.0.2.1 \
      --probe 1:198.51.100.10:198.51.100.1:198.51.100.1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from trexcmllib import PingProbe, TrexConsoleConfig, TrexTraffic, parse_probe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ping validation through one or more TRex ports and print per-port results.",
        epilog=(
            "Single-link example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --count 3 \\\n"
            "    --probe 0:192.0.2.10:192.0.2.1:192.0.2.1\n\n"
            "Two-link example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --count 3 \\\n"
            "    --probe 0:192.0.2.10:192.0.2.1:192.0.2.1 \\\n"
            "    --probe 1:198.51.100.10:198.51.100.1:198.51.100.1"
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
    parser.add_argument("--count", type=int, default=3, help="How many ICMP echo requests to send per probe (default: 3)")
    parser.add_argument("--pkt-size", type=int, default=64, help="ICMP packet size in bytes (default: 64)")
    parser.add_argument("--show-raw-output", action="store_true", help="Show full remote console output on failure")
    parser.add_argument(
        "--probe",
        action="append",
        required=True,
        metavar="PORT:SRC_IP:NEXT_HOP_IP:DST_IP",
        help="Ping probe definition. Repeat this option to test multiple links.",
    )
    return parser


def build_probe_commands(probe: PingProbe, *, count: int, pkt_size: int) -> list[str]:
    return [
        f"service -p {probe.port}",
        f"l3 -p {probe.port} --src {probe.src_ip} --dst {probe.next_hop_ip}",
        f"ping -p {probe.port} -d {probe.dst_ip} -s {pkt_size} -n {count}",
        f"service --off -p {probe.port}",
        f"release -p {probe.port}",
    ]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    probes: list[PingProbe] = []
    for probe_text in args.probe:
        try:
            probes.append(parse_probe(probe_text))
        except ValueError as exc:
            parser.error(str(exc))

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
    result = traffic.run("ping", probes=probes, count=args.count, pkt_size=args.pkt_size, password=args.password)

    failures: list[tuple[PingProbe, str]] = []
    for probe_result in result.summary["probe_results"]:
        print(f"Probe            : port {probe_result['port']}")
        print(f"Source IP        : {probe_result['src_ip']}")
        print(f"Next hop IP      : {probe_result['next_hop_ip']}")
        print(f"Ping destination : {probe_result['dst_ip']}")
        print(f"Resolved NH MAC  : {probe_result['resolved_nh_mac']}")
        print(f"Replies          : {probe_result['replies']}/{probe_result['requested_replies']}")
        print(f"Packet loss      : {probe_result['packet_loss']} ({probe_result['packet_loss_pct']:.2f}%)")
        print(f"Timeouts         : {probe_result['timeouts']}")
        print(f"Unreachable      : {probe_result['unreachable']}")
        print(f"L3 resolve fail  : {'yes' if probe_result['l3_resolve_fail'] else 'no'}")
        print(f"Batch success    : {'yes' if probe_result['batch_success'] else 'no'}")
        print(f"Overall result   : {'PASS' if probe_result['success'] else 'FAIL'}")
        print()
        if not probe_result["success"]:
            failures.append((PingProbe(probe_result["port"], probe_result["src_ip"], probe_result["next_hop_ip"], probe_result["dst_ip"]), result.outputs[f"port_{probe_result['port']}"]))

    if result.success:
        return 0

    for probe, output in failures:
        print(f"Commands run for port {probe.port}:")
        for command in build_probe_commands(probe, count=args.count, pkt_size=args.pkt_size):
            print(command)
        print()
        if args.show_raw_output:
            print(f"Full console output for port {probe.port}:\n")
            print(output)
            print()

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
