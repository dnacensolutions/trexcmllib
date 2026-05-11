#!/usr/bin/env python3
"""Run ASTF HTTP application traffic on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, and node name.
3. The script will start the remote TRex server in ASTF mode, run the HTTP
   ASTF profile, wait for completion, and print client/server TCP counters.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_astf_http \
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run ASTF HTTP application traffic and print a TCP stateful summary.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_astf_http \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --duration 10 \\\n"
            "    --multiplier 100"
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
    parser.add_argument("--profile", default="astf/http_simple.py", help="ASTF HTTP profile path (default: astf/http_simple.py)")
    parser.add_argument("--profile-id", default="http", help="ASTF profile id used for dynamic profile stats (default: http)")
    parser.add_argument("--multiplier", default="100", help="ASTF multiplier passed to start -m (default: 100)")
    parser.add_argument("--duration", type=float, default=10.0, help="Traffic duration in seconds (default: 10)")
    parser.add_argument("--latency-pps", type=int, default=None, help="Optional ASTF latency rate in packets per second")
    parser.add_argument("--ipv6", action="store_true", help="Run the ASTF profile in IPv6 mode")
    return parser
def main() -> int:
    args = build_parser().parse_args()
    traffic = TrexTraffic(
        TrexConsoleConfig(
            jump_host=args.jump_host,
            user=args.user,
            lab_name=args.lab_name,
            node_name=args.node_name,
            node_port=str(args.node_port),
            password=args.password,
            password_env=args.password_env,
            server_mode="astf",
            readonly=False,
            force_acquire=False,
            server_wait=6.0,
        )
    )
    result = traffic.run(
        "astf_http",
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
    print(f"Client retransmits    : {summary.get('client_retransmits', 0)}")
    print(f"Server retransmits    : {summary.get('server_retransmits', 0)}")
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
