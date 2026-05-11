"""Console-driven helpers for TRex ASTF stateful and application traffic.

This module intentionally builds on ``TrexConsoleLauncher`` instead of the
local ASTF Python client so it can reuse the same remote-node execution model
as the working L2/L3 examples.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from .console import TrexConsoleBatchResult, TrexConsoleLauncher


ASTF_INT_METRIC_RE = re.compile(
    r"^\s*(?P<name>[a-zA-Z0-9_-]+)\s+\|\s+(?P<client>\d+)\s+\|\s+(?P<server>\d+)\s+\|",
    re.MULTILINE,
)


def parse_astf_numeric_stats(output: str) -> dict[str, dict[str, int]]:
    metrics: dict[str, dict[str, int]] = {}
    for match in ASTF_INT_METRIC_RE.finditer(output):
        metrics[match.group("name")] = {
            "client": int(match.group("client")),
            "server": int(match.group("server")),
        }
    return metrics


@dataclass(slots=True)
class TrexAstfProfileRunResult:
    profile: str
    profile_id: str | None
    multiplier: str | int | float
    duration: float
    metrics: dict[str, dict[str, int]]
    start_result: TrexConsoleBatchResult
    stats_result: TrexConsoleBatchResult
    success: bool


class TrexAstfConsoleRunner:
    """Run ASTF profiles through the remote TRex console."""

    def __init__(self, launcher: TrexConsoleLauncher) -> None:
        self.launcher = launcher

    @staticmethod
    def build_start_command(
        *,
        profile: str,
        multiplier: str | int | float,
        duration: float,
        profile_id: str | None = None,
        latency_pps: int | None = None,
        ipv6: bool = False,
        nc: bool = True,
        tunables: dict[str, object] | None = None,
    ) -> str:
        parts = [
            "start",
            "-f",
            profile,
            "-m",
            str(multiplier),
            "-d",
            str(duration),
        ]
        if nc:
            parts.append("--nc")
        if latency_pps is not None:
            parts.extend(["-l", str(latency_pps)])
        if ipv6:
            parts.append("--ipv6")
        if profile_id:
            parts.extend(["--pid", profile_id])
        if tunables:
            encoded = ",".join(f"{key}={value}" for key, value in tunables.items())
            parts.extend(["-t", encoded])
        return " ".join(parts)

    @staticmethod
    def build_stats_command(*, profile_id: str | None = None) -> str:
        if profile_id:
            return f"stats -a --pid {profile_id}"
        return "stats -a"

    @staticmethod
    def build_stop_command(*, profile_id: str | None = None, remove: bool = True) -> str:
        parts = ["stop"]
        if profile_id:
            parts.extend(["--pid", profile_id])
        if remove:
            parts.append("--remove")
        return " ".join(parts)

    @staticmethod
    def _metric(metrics: dict[str, dict[str, int]], name: str, side: str) -> int:
        return metrics.get(name, {}).get(side, 0)

    def validate_metrics(self, metrics: dict[str, dict[str, int]], *, expected_transport: str = "any") -> bool:
        tcp_connects_client = self._metric(metrics, "tcps_connects", "client")
        tcp_connects_server = self._metric(metrics, "tcps_connects", "server")
        tcp_client_sent = self._metric(metrics, "tcps_sndbyte", "client")
        tcp_server_recv = self._metric(metrics, "tcps_rcvbyte", "server")
        tcp_server_sent = self._metric(metrics, "tcps_sndbyte", "server")
        tcp_client_recv = self._metric(metrics, "tcps_rcvbyte", "client")

        udp_connects_client = self._metric(metrics, "udps_connects", "client")
        udp_connects_server = self._metric(metrics, "udps_connects", "server")
        udp_client_sent = self._metric(metrics, "udps_sndbyte", "client")
        udp_server_recv = self._metric(metrics, "udps_rcvbyte", "server")
        udp_server_sent = self._metric(metrics, "udps_sndbyte", "server")
        udp_client_recv = self._metric(metrics, "udps_rcvbyte", "client")

        tcp_ok = (
            tcp_connects_client > 0
            and tcp_connects_server > 0
            and tcp_client_sent > 0
            and tcp_server_sent > 0
            and tcp_client_sent == tcp_server_recv
            and tcp_server_sent == tcp_client_recv
        )
        udp_ok = (
            udp_connects_client > 0
            and udp_connects_server > 0
            and udp_client_sent > 0
            and udp_server_sent > 0
            and udp_client_sent == udp_server_recv
            and udp_server_sent == udp_client_recv
        )

        transport = expected_transport.lower()
        if transport == "tcp":
            return tcp_ok
        if transport == "udp":
            return udp_ok
        return tcp_ok or udp_ok

    def run_profile(
        self,
        *,
        profile: str,
        multiplier: str | int | float = 100,
        duration: float = 10.0,
        profile_id: str | None = None,
        latency_pps: int | None = None,
        ipv6: bool = False,
        nc: bool = True,
        tunables: dict[str, object] | None = None,
        expected_transport: str = "any",
        settle_time: float = 1.0,
        password: str | None = None,
    ) -> TrexAstfProfileRunResult:
        start_result = self.launcher.run_console_batch(
            [
                "clear",
                self.build_start_command(
                    profile=profile,
                    multiplier=multiplier,
                    duration=duration,
                    profile_id=profile_id,
                    latency_pps=latency_pps,
                    ipv6=ipv6,
                    nc=nc,
                    tunables=tunables,
                ),
            ],
            password=password,
            force_acquire=False,
            readonly=False,
            timeout=max(60.0, float(duration) + 30.0),
        )

        # ASTF start is asynchronous from the console batch perspective.
        time.sleep(max(0.0, float(duration)) + max(0.0, float(settle_time)))

        stats_result = self.launcher.run_console_batch(
            [
                self.build_stats_command(profile_id=profile_id),
                self.build_stop_command(profile_id=profile_id, remove=True),
            ],
            password=password,
            force_acquire=False,
            readonly=False,
            timeout=60.0,
        )

        metrics = parse_astf_numeric_stats(stats_result.output)
        success = (
            start_result.success
            and stats_result.success
            and self.validate_metrics(metrics, expected_transport=expected_transport)
        )

        return TrexAstfProfileRunResult(
            profile=profile,
            profile_id=profile_id,
            multiplier=multiplier,
            duration=duration,
            metrics=metrics,
            start_result=start_result,
            stats_result=stats_result,
            success=success,
        )
