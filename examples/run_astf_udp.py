#!/usr/bin/env python3
"""Run ASTF UDP stateful traffic on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, and node name.
3. The script will start the remote TRex server in ASTF mode, run the UDP
   ASTF profile, wait for completion, and print client/server UDP counters.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_astf_udp \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --duration 10 \
      --multiplier 100
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from trexcmllib import TrexConsoleConfig, TrexTraffic
from trexcmllib.examples.common import add_console_target_args, add_traffic_reset_args, console_target_kwargs, validate_console_target_args


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ASTF UDP stateful traffic and print a UDP stateful summary.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_astf_udp \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --duration 10 \\\n"
            "    --multiplier 100"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_console_target_args(parser)
    add_traffic_reset_args(parser)
    parser.add_argument("--profile", default="astf/udp_pcap.py", help="ASTF UDP profile path (default: astf/udp_pcap.py)")
    parser.add_argument("--profile-id", default="udp", help="ASTF profile id used for dynamic profile stats (default: udp)")
    parser.add_argument("--multiplier", default="100", help="ASTF multiplier passed to start -m (default: 100)")
    parser.add_argument("--duration", type=float, default=10.0, help="Traffic duration in seconds (default: 10)")
    parser.add_argument("--latency-pps", type=int, default=None, help="Optional ASTF latency rate in packets per second")
    parser.add_argument("--ipv6", action="store_true", help="Run the ASTF profile in IPv6 mode")
    return parser
def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_console_target_args(parser, args)
    traffic = TrexTraffic(
        TrexConsoleConfig(
            **console_target_kwargs(args),
            server_mode="astf",
            readonly=False,
            force_acquire=False,
            server_wait=6.0,
        ),
        hard_reset=args.hard_reset,
    )
    result = traffic.run(
        "astf_udp",
        profile=args.profile,
        profile_id=args.profile_id,
        multiplier=args.multiplier,
        duration=args.duration,
        latency_pps=args.latency_pps,
        ipv6=args.ipv6,
        password=args.password,
    )
    summary = result.summary

    print(f"CML host              : {args.jump_host}")
    print(f"Lab / node            : {args.lab_name} / {args.node_name}")
    print(f"TRex server mode      : astf")
    print(f"Profile               : {summary['profile']}")
    print(f"Profile id            : {summary['profile_id']}")
    print(f"Multiplier            : {summary['multiplier']}")
    print(f"Duration              : {summary['duration']}")
    print(f"Client connects       : {summary.get('client_connects', 0)}")
    print(f"Server connects       : {summary.get('server_connects', 0)}")
    print(f"Client->Server sent   : {summary.get('client_to_server_sent', 0)}")
    print(f"Client->Server recv   : {summary.get('client_to_server_received', 0)}")
    print(f"Client->Server loss   : {summary.get('client_to_server_loss', 0)} ({summary.get('client_to_server_loss_pct', 0.0):.2f}%)")
    print(f"Server->Client sent   : {summary.get('server_to_client_sent', 0)}")
    print(f"Server->Client recv   : {summary.get('server_to_client_received', 0)}")
    print(f"Server->Client loss   : {summary.get('server_to_client_loss', 0)} ({summary.get('server_to_client_loss_pct', 0.0):.2f}%)")
    print(f"Client bytes sent     : {summary.get('client_bytes_sent', 0)}")
    print(f"Server bytes received : {summary.get('server_bytes_received', 0)}")
    print(f"Server bytes sent     : {summary.get('server_bytes_sent', 0)}")
    print(f"Client bytes received : {summary.get('client_bytes_received', 0)}")
    print(f"Client drops          : {summary.get('client_drops', 0)}")
    print(f"Server drops          : {summary.get('server_drops', 0)}")
    print(f"Start batch success   : {'yes' if summary.get('start_batch_success', False) else 'no'}")
    print(f"Stats batch success   : {'yes' if summary.get('stats_batch_success', False) else 'no'}")
    if summary.get("missing_assets"):
        print(f"Missing assets        : {', '.join(summary['missing_assets'])}")
    if summary.get("schema_dir"):
        print(f"Schema directory      : {summary['schema_dir']}")
    if summary.get("resolved_profile"):
        print(f"Resolved profile      : {summary['resolved_profile']}")
    if summary.get("error"):
        print(f"Error                 : {summary['error']}")
    print(f"Overall result        : {'PASS' if result.success else 'FAIL'}")

    if result.success:
        return 0

    print("\nFull ASTF output:\n")
    print(result.outputs.get("remote", ""))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
