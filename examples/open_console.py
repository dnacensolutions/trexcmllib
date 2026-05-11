#!/usr/bin/env python3
"""Open a remote CML TRex node console and land on a live ``trex>`` prompt.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, and node name explicitly.
3. Optionally choose `--server-mode astf` when you want an ASTF-capable TRex console.
4. Run the script directly or as a module.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.open_console \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --server-mode stl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[2]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from trexcmllib import SessionError, TrexConsoleConfig, TrexConsoleLauncher


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open a TRex console on a remote CML-hosted node.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.open_console \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --server-mode stl"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.set_defaults(readonly=True)
    parser.add_argument("--cml-host", "--jump-host", dest="jump_host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--lab-name", required=True)
    parser.add_argument("--node-name", required=True)
    parser.add_argument("--node-port", default="0")
    parser.add_argument("--console-path")
    parser.add_argument("--password-env", default="TREXCMLLIB_PASSWORD")
    parser.add_argument("--password")
    parser.add_argument("--server-mode", choices=("stl", "astf"), default="stl")
    parser.add_argument("--connect-timeout", type=float, default=30.0)
    parser.add_argument("--command-timeout", type=float, default=20.0)
    parser.add_argument("--console-timeout", type=float, default=40.0)
    parser.add_argument("--server-wait", type=float, default=4.0)
    parser.add_argument("--exit-after-prompt", action="store_true")
    parser.add_argument("--acquire", dest="readonly", action="store_false")
    parser.add_argument("--readonly", dest="readonly", action="store_true")
    parser.add_argument("--force-acquire", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    launcher = TrexConsoleLauncher(
        TrexConsoleConfig(
            jump_host=args.jump_host,
            user=args.user,
            lab_name=args.lab_name,
            node_name=args.node_name,
            node_port=args.node_port,
            console_path=args.console_path,
            password_env=args.password_env,
            password=args.password,
            server_mode=args.server_mode,
            connect_timeout=args.connect_timeout,
            command_timeout=args.command_timeout,
            console_timeout=args.console_timeout,
            server_wait=args.server_wait,
            readonly=args.readonly,
            force_acquire=args.force_acquire,
            exit_after_prompt=args.exit_after_prompt,
        )
    )
    try:
        launcher.connect_and_bootstrap()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except SessionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
