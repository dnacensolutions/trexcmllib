#!/usr/bin/env python3
"""Run a simple L3 packet test on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab name, node name, packet count, and the
   L3 configuration for the transmit port.
3. Optionally configure a receive-side port if your topology expects return
   traffic or if you want the example to resolve both ports.
4. The example first configures L3 mode and resolves ARP, then injects raw
   packets using the resolved gateway MAC.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_traffic \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --packets 10 \
      --tx-port 0 \
      --tx-src-ip 192.0.2.10 \
      --tx-next-hop 192.0.2.1 \
      --traffic-dst-ip 198.51.100.10
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
        description="Configure L3 mode, resolve ARP, send L3 packets, and print a traffic summary.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_traffic \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --packets 10 \\\n"
            "    --tx-port 0 \\\n"
            "    --tx-src-ip 192.0.2.10 \\\n"
            "    --tx-next-hop 192.0.2.1 \\\n"
            "    --traffic-dst-ip 198.51.100.10"
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
    parser.add_argument("--packets", type=int, required=True, help="Number of L3 packets to inject from tx-port")
    parser.add_argument("--tx-port", type=int, default=0, help="TRex transmit port (default: 0)")
    parser.add_argument("--rx-port", type=int, default=None, help="Optional receive-side TRex port to also configure and summarize")
    parser.add_argument("--tx-src-ip", required=True, help="Source IPv4 to configure on tx-port")
    parser.add_argument("--tx-next-hop", required=True, help="IPv4 next-hop or peer IP used by tx-port for ARP resolution")
    parser.add_argument("--rx-src-ip", default=None, help="Optional source IPv4 to configure on rx-port")
    parser.add_argument("--rx-next-hop", default=None, help="Optional next-hop or peer IPv4 used by rx-port for ARP resolution")
    parser.add_argument("--traffic-src-ip", default=None, help="IPv4 source used in the injected packet (default: --tx-src-ip)")
    parser.add_argument("--traffic-dst-ip", default=None, help="IPv4 destination used in the injected packet (default: --tx-next-hop)")
    parser.add_argument("--payload-bytes", type=int, default=10, help="UDP payload size in bytes for each injected packet")
    parser.add_argument("--udp-src-port", type=int, default=1025, help="UDP source port for injected packets")
    parser.add_argument("--udp-dst-port", type=int, default=12, help="UDP destination port for injected packets")
    parser.add_argument("--tx-mac", default=None, help="Override the source MAC for tx-port")
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
        "l3",
        packets=args.packets,
        tx_port=args.tx_port,
        tx_src_ip=args.tx_src_ip,
        tx_next_hop=args.tx_next_hop,
        rx_port=args.rx_port,
        rx_src_ip=args.rx_src_ip,
        rx_next_hop=args.rx_next_hop,
        traffic_src_ip=args.traffic_src_ip,
        traffic_dst_ip=args.traffic_dst_ip,
        payload_bytes=args.payload_bytes,
        udp_src_port=args.udp_src_port,
        udp_dst_port=args.udp_dst_port,
        tx_mac=args.tx_mac,
        password=args.password,
    )
    summary = result.summary

    print(f"CML host         : {args.jump_host}")
    print(f"Lab / node       : {args.lab_name} / {args.node_name}")
    print(f"Tx port          : {summary['tx_port']}")
    print(f"Tx source MAC    : {summary['tx_mac']}")
    print(f"Tx source IP     : {summary['tx_src_ip']}")
    print(f"Tx next hop IP   : {summary['tx_next_hop']}")
    print(f"Resolved NH MAC  : {summary.get('resolved_nh_mac', 'n/a')}")
    print(f"Traffic src IP   : {summary.get('traffic_src_ip', 'n/a')}")
    print(f"Traffic dst IP   : {summary.get('traffic_dst_ip', 'n/a')}")
    print(f"Packets asked    : {summary.get('packets_asked', args.packets)}")
    print(f"Packets sent     : {summary.get('packets_sent', 0)}")
    print(f"Bytes sent       : {summary.get('bytes_sent', 0)}")
    print(f"Tx errors        : {summary.get('tx_errors', 0)}")

    if "rx_port" in summary:
        print(f"Rx port          : {summary['rx_port']}")
        print(f"Packets received : {summary.get('packets_received', 0)}")
        print(f"Packet loss      : {summary.get('packet_loss', 0)} ({summary.get('packet_loss_pct', 0.0):.2f}%)")
        print(f"Bytes received   : {summary.get('bytes_received', 0)}")
        print(f"Rx errors        : {summary.get('rx_errors', 0)}")
    else:
        print("Packet loss      : n/a (no receive-side port specified)")

    print(f"Batch success    : {'yes' if summary.get('batch_success', False) else 'no'}")

    if result.success:
        return 0

    if "setup" in result.outputs:
        print("\nFull setup output:\n")
        print(result.outputs["setup"])
    if "traffic" in result.outputs:
        print("\nFull traffic output:\n")
        print(result.outputs["traffic"])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
