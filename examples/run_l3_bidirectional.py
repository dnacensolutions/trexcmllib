#!/usr/bin/env python3
"""Run bidirectional L3 traffic on a remote TRex node via the console CLI.

How to use:
1. Export the SSH password in ``TREXCMLLIB_PASSWORD`` or pass ``--password``.
2. Provide the CML host, SSH user, lab selector, node selector, and the traffic endpoints.
3. Provide per-port source IPs and traffic destination IPs.
4. Choose one of these next-hop modes:
   - ARP mode: provide ``--port-a-next-hop-ip`` and ``--port-b-next-hop-ip``
   - static MAC mode: provide ``--port-a-next-hop-mac`` and
     ``--port-b-next-hop-mac``
5. Choose either packet mode with ``--packets`` or stream mode with ``--rate`` and ``--duration``.
6. In packet mode, optionally tune ``--packet-pps`` to reduce burst-driven loss.

Example CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_bidirectional \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-name <lab-name> \
      --node-name <node-name> \
      --packets 10 \
      --packet-pps 50 \
      --port-a-src-ip 192.0.2.10 \
      --port-b-src-ip 192.0.2.20 \
      --port-a-next-hop-ip 192.0.2.1 \
      --port-b-next-hop-ip 192.0.2.2 \
      --traffic-a-dst-ip 198.51.100.10 \
      --traffic-b-dst-ip 198.51.100.20

Stream CLI:
    TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_bidirectional \
      --cml-host <cml-host> \
      --user <ssh-user> \
      --lab-id <lab-id> \
      --node-name <node-name> \
      --port-a-src-ip 192.0.2.10 \
      --port-b-src-ip 192.0.2.20 \
      --port-a-next-hop-ip 192.0.2.1 \
      --port-b-next-hop-ip 192.0.2.2 \
      --traffic-a-dst-ip 198.51.100.10 \
      --traffic-b-dst-ip 198.51.100.20 \
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
        description="Send bidirectional L3 packets and print per-port and total counters.",
        epilog=(
            "Example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_bidirectional \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-name <lab-name> \\\n"
            "    --node-name <node-name> \\\n"
            "    --packets 10 \\\n"
            "    --port-a-src-ip 192.0.2.10 \\\n"
            "    --port-b-src-ip 192.0.2.20 \\\n"
            "    --port-a-next-hop-ip 192.0.2.1 \\\n"
            "    --port-b-next-hop-ip 192.0.2.2 \\\n"
            "    --traffic-a-dst-ip 198.51.100.10 \\\n"
            "    --traffic-b-dst-ip 198.51.100.20\n\n"
            "Stream example:\n"
            "  TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_bidirectional \\\n"
            "    --cml-host <cml-host> \\\n"
            "    --user <ssh-user> \\\n"
            "    --lab-id <lab-id> \\\n"
            "    --node-name <node-name> \\\n"
            "    --port-a-src-ip 192.0.2.10 \\\n"
            "    --port-b-src-ip 192.0.2.20 \\\n"
            "    --port-a-next-hop-ip 192.0.2.1 \\\n"
            "    --port-b-next-hop-ip 192.0.2.2 \\\n"
            "    --traffic-a-dst-ip 198.51.100.10 \\\n"
            "    --traffic-b-dst-ip 198.51.100.20 \\\n"
            "    --rate 10kpps \\\n"
            "    --duration 10"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_console_target_args(parser)
    add_traffic_reset_args(parser)
    parser.add_argument("--packets", type=int, default=None, help="Number of L3 packets to inject from each port in packet mode")
    parser.add_argument("--packet-pps", type=int, default=50, help="Burst rate used in packet mode when --packets is provided (default: 50)")
    parser.add_argument("--rate", default=None, help="Optional TRex stream rate, for example 10kpps, 100mbps, or 5%%")
    parser.add_argument("--duration", type=float, default=10.0, help="Stream duration in seconds when --rate is used (default: 10)")
    parser.add_argument("--port-a", type=int, default=0, help="First TRex port (default: 0)")
    parser.add_argument("--port-b", type=int, default=1, help="Second TRex port (default: 1)")
    parser.add_argument("--port-a-src-ip", required=True, help="Source IPv4 used on port-a")
    parser.add_argument("--port-b-src-ip", required=True, help="Source IPv4 used on port-b")
    parser.add_argument("--port-a-next-hop-ip", default=None, help="ARP next-hop IPv4 for port-a")
    parser.add_argument("--port-b-next-hop-ip", default=None, help="ARP next-hop IPv4 for port-b")
    parser.add_argument("--port-a-next-hop-mac", default=None, help="Static next-hop MAC override for port-a")
    parser.add_argument("--port-b-next-hop-mac", default=None, help="Static next-hop MAC override for port-b")
    parser.add_argument("--traffic-a-dst-ip", required=True, help="IPv4 destination used by packets sent from port-a")
    parser.add_argument("--traffic-b-dst-ip", required=True, help="IPv4 destination used by packets sent from port-b")
    parser.add_argument("--payload-bytes", type=int, default=10, help="UDP payload size in bytes for each injected packet")
    parser.add_argument("--udp-src-port", type=int, default=1025, help="UDP source port for injected packets")
    parser.add_argument("--udp-dst-port", type=int, default=12, help="UDP destination port for injected packets")
    parser.add_argument("--port-a-mac", default=None, help="Override the source MAC for port-a")
    parser.add_argument("--port-b-mac", default=None, help="Override the source MAC for port-b")
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
        "l3_bidirectional",
        packets=args.packets,
        port_a=args.port_a,
        port_b=args.port_b,
        port_a_src_ip=args.port_a_src_ip,
        port_b_src_ip=args.port_b_src_ip,
        port_a_next_hop_ip=args.port_a_next_hop_ip,
        port_b_next_hop_ip=args.port_b_next_hop_ip,
        port_a_next_hop_mac=args.port_a_next_hop_mac,
        port_b_next_hop_mac=args.port_b_next_hop_mac,
        traffic_a_dst_ip=args.traffic_a_dst_ip,
        traffic_b_dst_ip=args.traffic_b_dst_ip,
        payload_bytes=args.payload_bytes,
        udp_src_port=args.udp_src_port,
        udp_dst_port=args.udp_dst_port,
        port_a_mac=args.port_a_mac,
        port_b_mac=args.port_b_mac,
        rate=args.rate,
        duration=args.duration,
        packet_pps=args.packet_pps,
        password=args.password,
    )
    summary = result.summary
    lab_label, node_label = console_target_label(args)

    print(f"CML host          : {args.jump_host}")
    print(f"Lab / node        : {lab_label} / {node_label}")
    print(f"Traffic mode      : {summary.get('mode', 'packet')}")
    print(f"Ports             : a={summary.get('port_a', args.port_a)} b={summary.get('port_b', args.port_b)}")
    print(f"Port MACs         : a={summary.get('port_a_mac', 'n/a')} b={summary.get('port_b_mac', 'n/a')}")
    print(f"Port A src IP     : {summary.get('port_a_src_ip', args.port_a_src_ip)}")
    print(f"Port B src IP     : {summary.get('port_b_src_ip', args.port_b_src_ip)}")
    print(f"Port A NH MAC     : {summary.get('port_a_next_hop_mac', 'n/a')}")
    print(f"Port B NH MAC     : {summary.get('port_b_next_hop_mac', 'n/a')}")
    print(f"Port A dst IP     : {summary.get('traffic_a_dst_ip', args.traffic_a_dst_ip)}")
    print(f"Port B dst IP     : {summary.get('traffic_b_dst_ip', args.traffic_b_dst_ip)}")
    if summary.get("mode") == "stream":
        print(f"Rate              : {summary.get('rate', 'n/a')}")
        print(f"Duration          : {summary.get('duration', 0)}")
    else:
        print(f"Packets per port  : {summary.get('packets_per_port', args.packets)}")
        print(f"Packet PPS        : {summary.get('packet_pps', args.packet_pps)}")
    print(f"Port {summary.get('port_a', args.port_a)} sent     : {summary.get('port_a_sent', 0)}")
    print(f"Port {summary.get('port_a', args.port_a)} received : {summary.get('port_a_received', 0)}")
    print(f"Port {summary.get('port_b', args.port_b)} sent     : {summary.get('port_b_sent', 0)}")
    print(f"Port {summary.get('port_b', args.port_b)} received : {summary.get('port_b_received', 0)}")
    print(f"Loss {summary.get('port_a', args.port_a)}->{summary.get('port_b', args.port_b)}     : {summary.get('loss_a_to_b', 0)} ({summary.get('loss_a_to_b_pct', 0.0):.2f}%)")
    print(f"Loss {summary.get('port_b', args.port_b)}->{summary.get('port_a', args.port_a)}     : {summary.get('loss_b_to_a', 0)} ({summary.get('loss_b_to_a_pct', 0.0):.2f}%)")
    print(f"Total sent        : {summary.get('total_sent', 0)}")
    print(f"Total received    : {summary.get('total_received', 0)}")
    print(f"Total loss        : {summary.get('total_loss', 0)} ({summary.get('total_loss_pct', 0.0):.2f}%)")
    print(f"Port {summary.get('port_a', args.port_a)} tx bytes : {summary.get('port_a_tx_bytes', 0)}")
    print(f"Port {summary.get('port_a', args.port_a)} rx bytes : {summary.get('port_a_rx_bytes', 0)}")
    print(f"Port {summary.get('port_b', args.port_b)} tx bytes : {summary.get('port_b_tx_bytes', 0)}")
    print(f"Port {summary.get('port_b', args.port_b)} rx bytes : {summary.get('port_b_rx_bytes', 0)}")
    print(f"Port {summary.get('port_a', args.port_a)} errors   : tx={summary.get('port_a_tx_errors', 0)} rx={summary.get('port_a_rx_errors', 0)}")
    print(f"Port {summary.get('port_b', args.port_b)} errors   : tx={summary.get('port_b_tx_errors', 0)} rx={summary.get('port_b_rx_errors', 0)}")
    print(f"Batch success     : {'yes' if summary['batch_success'] else 'no'}")

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
