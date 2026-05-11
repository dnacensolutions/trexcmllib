"""Shared helpers for trexcmllib example scripts."""

from __future__ import annotations

import re

from trexcmllib import TrexConsoleLauncher


PORT_MAC_RE = re.compile(r"PORT\s+(?P<port>\d+)\s+IFACE\s+(?P<iface>\S+)\s+MAC\s+(?P<mac>[0-9a-f:]{17})", re.IGNORECASE)
METRIC_RE = re.compile(r"^\s*(?P<name>[a-zA-Z0-9_-]+)\s+\|\s+(?P<left>\d+)\s+\|\s+(?P<right>\d+)(?:\s+\|\s+(?P<total>\d+))?\s*$")
ARP_REPLY_RE = re.compile(
    r"Port\s+(?P<port>\d+)\s+-\s+Rec(?:ei|ie)ved ARP reply from:\s+(?P<ip>[0-9.]+),\s+hw:\s+(?P<mac>[0-9a-f:]{17})",
    re.IGNORECASE,
)
ARP_FAILURE_RE = re.compile(r"Could not resolve following ports:\s+\[(?P<ports>[^\]]+)\]", re.IGNORECASE)
PING_SUCCESS_RE = re.compile(
    r"Reply from (?P<ip>[0-9a-f:.]+): bytes=(?P<bytes>\d+), time=(?P<rtt>[0-9.]+)ms, (?P<hop>TTL|hlim)=(?P<ttl>\d+)",
    re.IGNORECASE,
)
PING_TIMEOUT_RE = re.compile(r"Request timed out\.", re.IGNORECASE)
PING_UNREACHABLE_RE = re.compile(r"Reply from (?P<ip>[0-9a-f:.]+): Destination host unreachable", re.IGNORECASE)


def discover_port_macs(launcher: TrexConsoleLauncher) -> dict[int, dict[str, str]]:
    remote_shell = (
        "grep -o 'iface=[^\",]*' /etc/trex_cfg.yaml | "
        "cut -d= -f2 | "
        "nl -v0 -w1 -s' ' | "
        "while read idx iface; do "
        "mac=$(cat /sys/class/net/$iface/address 2>/dev/null); "
        "echo \"PORT $idx IFACE $iface MAC $mac\"; "
        "done"
    )
    output = launcher.run_shell_commands([remote_shell])
    port_macs: dict[int, dict[str, str]] = {}
    for match in PORT_MAC_RE.finditer(output):
        port = int(match.group("port"))
        port_macs[port] = {
            "iface": match.group("iface"),
            "mac": match.group("mac").lower(),
        }
    return port_macs


def parse_summary(output: str) -> dict[str, dict[int | str, int]]:
    metrics: dict[str, dict[int | str, int]] = {}
    for line in output.splitlines():
        match = METRIC_RE.match(line)
        if not match:
            continue
        metric = match.group("name")
        metrics[metric] = {
            0: int(match.group("left")),
            1: int(match.group("right")),
        }
        if match.group("total") is not None:
            metrics[metric]["total"] = int(match.group("total"))
    return metrics


def parse_arp_replies(output: str) -> dict[int, dict[str, str]]:
    replies: dict[int, dict[str, str]] = {}
    for match in ARP_REPLY_RE.finditer(output):
        replies[int(match.group("port"))] = {
            "ip": match.group("ip"),
            "mac": match.group("mac").lower(),
        }
    return replies


def parse_arp_failures(output: str) -> list[int]:
    failures: list[int] = []
    for match in ARP_FAILURE_RE.finditer(output):
        for token in match.group("ports").split(","):
            token = token.strip()
            if token.isdigit():
                failures.append(int(token))
    return failures


def parse_ping_summary(output: str) -> dict[str, object]:
    replies = [
        {
            "ip": match.group("ip"),
            "bytes": int(match.group("bytes")),
            "rtt_ms": float(match.group("rtt")),
            "ttl": int(match.group("ttl")),
            "hop_field": match.group("hop"),
        }
        for match in PING_SUCCESS_RE.finditer(output)
    ]
    unreachable = [match.group("ip") for match in PING_UNREACHABLE_RE.finditer(output)]
    timeouts = len(PING_TIMEOUT_RE.findall(output))
    return {
        "replies": replies,
        "reply_count": len(replies),
        "timeout_count": timeouts,
        "unreachable_count": len(unreachable),
        "unreachable_ips": unreachable,
    }


def loss_count(sent: int, received: int) -> int:
    return max(0, int(sent) - int(received))


def loss_percent(sent: int, received: int) -> float:
    sent = int(sent)
    if sent <= 0:
        return 0.0
    return (loss_count(sent, received) / float(sent)) * 100.0
