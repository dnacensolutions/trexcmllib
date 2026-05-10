"""Shared helpers for trexcmllib example scripts."""

from __future__ import annotations

import re

from trexcmllib import TrexConsoleLauncher


PORT_MAC_RE = re.compile(r"PORT\s+(?P<port>\d+)\s+IFACE\s+(?P<iface>\S+)\s+MAC\s+(?P<mac>[0-9a-f:]{17})", re.IGNORECASE)
METRIC_RE = re.compile(r"^\s*(?P<name>[a-zA-Z0-9_-]+)\s+\|\s+(?P<left>\d+)\s+\|\s+(?P<right>\d+)(?:\s+\|\s+(?P<total>\d+))?\s*$")


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
