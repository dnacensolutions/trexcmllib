"""Unified traffic helpers built on top of ``TrexConsoleLauncher``.

This module exposes one reusable ``TrexTraffic`` class that can run the same
traffic workflows currently demonstrated by the example scripts:

- unidirectional and bidirectional L2
- unidirectional and bidirectional L3
- ICMP ping validation
- ASTF stateful and application traffic

The class owns the launcher and ASTF runner, executes the console batches, and
returns structured results with summaries, counters, and raw console output.
"""

from __future__ import annotations

import ipaddress
import json
import re
import textwrap
from dataclasses import dataclass, field
from typing import Any

from .astf import TrexAstfConsoleRunner
from .console import TrexConsoleBatchResult, TrexConsoleConfig, TrexConsoleLauncher


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
ASTF_JSON_RE = re.compile(r"__TREXCMLLIB_ASTF_JSON__(?P<json>\{.*\})", re.DOTALL)
ASTF_PREFLIGHT_RE = re.compile(r"__TREXCMLLIB_ASTF_PREFLIGHT__(?P<json>\{.*\})", re.DOTALL)
STL_JSON_RE = re.compile(r"__TREXCMLLIB_STL_JSON__(?P<json>\{.*\})", re.DOTALL)


@dataclass(frozen=True, slots=True)
class PingProbe:
    port: int
    src_ip: str
    next_hop_ip: str
    dst_ip: str


@dataclass(slots=True)
class TrexTrafficResult:
    kind: str
    success: bool
    summary: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, dict[Any, int]] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)


def loss_count(sent: int, received: int) -> int:
    return max(0, int(sent) - int(received))


def loss_percent(sent: int, received: int) -> float:
    sent = int(sent)
    if sent <= 0:
        return 0.0
    return (loss_count(sent, received) / float(sent)) * 100.0


def parse_probe(text: str) -> PingProbe:
    parts = [part.strip() for part in text.split(":")]
    if len(parts) != 4:
        raise ValueError("probe must be PORT:SRC_IP:NEXT_HOP_IP:DST_IP")

    port_text, src_ip, next_hop_ip, dst_ip = parts
    if not port_text.isdigit():
        raise ValueError("probe port must be an integer")

    for label, value in (("src_ip", src_ip), ("next_hop_ip", next_hop_ip), ("dst_ip", dst_ip)):
        try:
            ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError(f"{label} is not a valid IPv4/IPv6 address: {value}") from exc

    return PingProbe(
        port=int(port_text),
        src_ip=src_ip,
        next_hop_ip=next_hop_ip,
        dst_ip=dst_ip,
    )


class TrexTraffic:
    """Unified API for the console-driven TRex traffic examples."""

    def __init__(
        self,
        config: TrexConsoleConfig | None = None,
        *,
        launcher: TrexConsoleLauncher | None = None,
        hard_reset: bool = True,
    ) -> None:
        if launcher is None:
            if config is None:
                raise ValueError("either config or launcher is required")
            launcher = TrexConsoleLauncher(config)
        launcher.config.hard_reset = hard_reset
        self.launcher = launcher
        self.astf_runner = TrexAstfConsoleRunner(launcher)

    def run(self, kind: str, /, **kwargs: Any) -> TrexTrafficResult:
        normalized = kind.lower()
        original_hard_reset = self.launcher.config.hard_reset
        self.launcher.ensure_server_running(password=kwargs.get("password"))
        self.launcher._server_ready_for_run = True
        self.launcher._needs_acquire_settle = bool(original_hard_reset)
        self.launcher.config.hard_reset = False
        try:
            if normalized == "l2":
                return self.run_l2(**kwargs)
            if normalized in {"l2_bidirectional", "l2-bidirectional"}:
                return self.run_l2_bidirectional(**kwargs)
            if normalized == "l3":
                return self.run_l3(**kwargs)
            if normalized in {"l3_bidirectional", "l3-bidirectional"}:
                return self.run_l3_bidirectional(**kwargs)
            if normalized == "ping":
                return self.run_ping(**kwargs)
            if normalized in {"astf", "astf_profile", "astf-profile"}:
                return self.run_astf_profile(**kwargs)
            if normalized in {"astf_http", "astf-http"}:
                return self.run_astf_http(**kwargs)
            if normalized in {"astf_udp", "astf-udp"}:
                return self.run_astf_udp(**kwargs)
            raise ValueError(f"unsupported traffic kind: {kind}")
        finally:
            self.launcher._server_ready_for_run = False
            self.launcher._needs_acquire_settle = False
            self.launcher.config.hard_reset = original_hard_reset

    def discover_port_macs(self, *, password: str | None = None) -> dict[int, dict[str, str]]:
        remote_shell = (
            "grep -o 'iface=[^\",]*' /etc/trex_cfg.yaml | "
            "cut -d= -f2 | "
            "nl -v0 -w1 -s' ' | "
            "while read idx iface; do "
            "mac=$(cat /sys/class/net/$iface/address 2>/dev/null); "
            "echo \"PORT $idx IFACE $iface MAC $mac\"; "
            "done"
        )
        output = self.launcher.run_shell_commands([remote_shell], password=password)
        port_macs: dict[int, dict[str, str]] = {}
        for match in PORT_MAC_RE.finditer(output):
            port = int(match.group("port"))
            port_macs[port] = {
                "iface": match.group("iface"),
                "mac": match.group("mac").lower(),
            }
        return port_macs

    @staticmethod
    def parse_summary(output: str) -> dict[str, dict[Any, int]]:
        metrics: dict[str, dict[Any, int]] = {}
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

    @staticmethod
    def parse_arp_replies(output: str) -> dict[int, dict[str, str]]:
        replies: dict[int, dict[str, str]] = {}
        for match in ARP_REPLY_RE.finditer(output):
            replies[int(match.group("port"))] = {
                "ip": match.group("ip"),
                "mac": match.group("mac").lower(),
            }
        return replies

    @staticmethod
    def parse_arp_failures(output: str) -> list[int]:
        failures: list[int] = []
        for match in ARP_FAILURE_RE.finditer(output):
            for token in match.group("ports").split(","):
                token = token.strip()
                if token.isdigit():
                    failures.append(int(token))
        return failures

    @staticmethod
    def parse_ping_summary(output: str) -> dict[str, Any]:
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

    @staticmethod
    def _metrics_from_port_stats(port_stats: dict[str, Any]) -> dict[str, dict[Any, int]]:
        metrics: dict[str, dict[Any, int]] = {}
        for port_key, values in port_stats.items():
            if not isinstance(values, dict):
                continue
            try:
                port = int(port_key)
            except (TypeError, ValueError):
                continue
            for metric, value in values.items():
                if isinstance(value, (int, float)):
                    metrics.setdefault(metric, {})[port] = int(value)
        return metrics

    def _run_remote_stl_streams(
        self,
        *,
        ports: list[int],
        stream_specs: list[dict[str, Any]],
        rate: str | None = None,
        duration: float | None = None,
        count: int | None = None,
        packet_pps: int = 50,
        password: str | None = None,
    ) -> tuple[bool, dict[str, Any], dict[str, dict[Any, int]], str]:
        remote_script = textwrap.dedent(
            f"""
            import json
            import os
            import shutil
            import sys
            import types

            dist = types.ModuleType("distutils")
            spawn = types.ModuleType("distutils.spawn")
            spawn.find_executable = shutil.which
            dist.spawn = spawn
            sys.modules["distutils"] = dist
            sys.modules["distutils.spawn"] = spawn
            sys.path.insert(0, os.getcwd())

            payload = {{"success": False, "error": None, "port_stats": {{}}}}
            client = None
            try:
                from trex.stl.api import IP, TCP, UDP, Ether, Raw, STLClient, STLPktBuilder, STLStream, STLTXCont, STLTXSingleBurst

                ports = {ports!r}
                stream_specs = json.loads({json.dumps(json.dumps(stream_specs))})
                rate = {rate!r}
                duration = {float(duration) if duration is not None else None!r}
                count = {count!r}
                packet_pps = {int(packet_pps)!r}

                client = STLClient(server="127.0.0.1")
                client.connect()
                client.acquire(ports=ports, force=True)
                client.remove_all_streams(ports=ports)
                client.clear_stats(ports=ports)

                for spec in stream_specs:
                    if spec["kind"] == "l2":
                        packet = Ether(src=spec["src_mac"], dst=spec["dst_mac"], type=spec["eth_type"])
                    else:
                        packet = Ether(src=spec["src_mac"], dst=spec["dst_mac"])
                        packet /= IP(src=spec["src_ip"], dst=spec["dst_ip"])
                        if spec["protocol"] == "tcp":
                            packet /= TCP(sport=spec["udp_src_port"], dport=spec["udp_dst_port"])
                        else:
                            packet /= UDP(sport=spec["udp_src_port"], dport=spec["udp_dst_port"])

                    pad_len = max(0, int(spec["frame_size"]) - len(packet))
                    if pad_len:
                        packet /= Raw(b"x" * pad_len)

                    if count is None:
                        mode = STLTXCont(pps=1)
                    else:
                        mode = STLTXSingleBurst(pps=packet_pps, total_pkts=count)
                    stream = STLStream(packet=STLPktBuilder(pkt=packet), mode=mode)
                    client.add_streams(stream, ports=spec["port"])

                if count is None:
                    client.start(ports=ports, mult=rate, duration=duration)
                    wait_timeout = max(60.0, duration + 30.0)
                else:
                    client.start(ports=ports)
                    wait_timeout = max(60.0, float(count) / 1000.0 + 30.0)
                client.wait_on_traffic(ports=ports, timeout=wait_timeout)
                raw_stats = client.get_stats(ports=ports, sync_now=True)
                for port in ports:
                    values = raw_stats.get(port) or raw_stats.get(str(port)) or {{}}
                    payload["port_stats"][str(port)] = {{
                        key: int(value)
                        for key, value in values.items()
                        if isinstance(value, (int, float))
                    }}
                payload["success"] = True
            except Exception as exc:  # pragma: no cover - remote node only
                payload["error"] = str(exc)
            finally:
                if client is not None:
                    try:
                        client.stop(ports=ports)
                    except Exception:
                        pass
                    try:
                        client.release(ports=ports)
                    except Exception:
                        pass
                    try:
                        client.disconnect()
                    except Exception:
                        pass

            print("__TREXCMLLIB_STL_JSON__" + json.dumps(payload))
            """
        )
        output = self.launcher.run_remote_python(
            remote_script,
            password=password,
            timeout=max(90.0, (float(duration) if duration is not None else 0.0) + 60.0),
            workdir="/trex/automation/trex_control_plane/interactive",
        )
        match = STL_JSON_RE.search(output)
        if not match:
            return False, {"error": "failed to parse remote STL stream output"}, {}, output
        payload = json.loads(match.group("json"))
        metrics = self._metrics_from_port_stats(payload.get("port_stats", {}))
        return bool(payload.get("success")), payload, metrics, output

    def _resolve_port_mac(self, port: int, override: str | None, *, password: str | None = None) -> str:
        if override:
            return override.lower()
        port_macs = self.discover_port_macs(password=password)
        try:
            return port_macs[port]["mac"]
        except KeyError as exc:
            raise ValueError(f"could not auto-discover MAC for port {exc.args[0]}") from exc

    def _resolve_two_port_macs(
        self,
        port_a: int,
        port_b: int,
        port_a_mac: str | None,
        port_b_mac: str | None,
        *,
        password: str | None = None,
    ) -> tuple[str, str]:
        if port_a_mac and port_b_mac:
            return port_a_mac.lower(), port_b_mac.lower()
        port_macs = self.discover_port_macs(password=password)
        try:
            return (
                (port_a_mac or port_macs[port_a]["mac"]).lower(),
                (port_b_mac or port_macs[port_b]["mac"]).lower(),
            )
        except KeyError as exc:
            raise ValueError(f"could not auto-discover MAC for port {exc.args[0]}") from exc

    def _preflight_remote_astf(self, profile: str, *, password: str | None = None) -> tuple[dict[str, Any], str]:
        remote_script = textwrap.dedent(
            f"""
            import json
            import os

            profile = {profile!r}
            roots = []
            for root in ('/trex', os.path.realpath('/trex')):
                if root and root not in roots and os.path.isdir(root):
                    roots.append(root)

            schema_path = None
            for root in roots:
                for current_root, _, files in os.walk(root):
                    if 'astf_schema.json' in files:
                        schema_path = os.path.join(current_root, 'astf_schema.json')
                        break
                if schema_path:
                    break

            if os.path.isabs(profile):
                profile_path = profile if os.path.exists(profile) else None
            else:
                profile_path = None
                for root in roots:
                    candidates = (
                        os.path.join(root, profile),
                        os.path.join(root, 'scripts', profile),
                    )
                    for candidate in candidates:
                        if os.path.exists(candidate):
                            profile_path = candidate
                            break
                    if profile_path:
                        break

            payload = {{
                'schema_path': schema_path,
                'schema_dir': os.path.dirname(schema_path) if schema_path else None,
                'profile_path': profile_path,
                'search_roots': roots,
            }}
            print("__TREXCMLLIB_ASTF_PREFLIGHT__" + json.dumps(payload))
            """
        )
        command = (
            "python3 - <<'INNER'\n"
            + remote_script.rstrip()
            + "\nINNER"
        )
        output = self.launcher.run_shell_commands([command], password=password, timeout=60.0)
        match = ASTF_PREFLIGHT_RE.search(output)
        if not match:
            raise RuntimeError("failed to parse ASTF preflight output")
        return json.loads(match.group("json")), output

    def run_l2(
        self,
        *,
        packets: int | None = None,
        tx_port: int = 0,
        rx_port: int = 1,
        tx_mac: str | None = None,
        rx_mac: str | None = None,
        rate: str | None = None,
        duration: float = 10.0,
        frame_size: int = 64,
        packet_pps: int = 50,
        password: str | None = None,
    ) -> TrexTrafficResult:
        if rate is None:
            if packets is None or packets < 1:
                raise ValueError("packets must be at least 1 when rate is not provided")
        elif duration <= 0:
            raise ValueError("duration must be greater than 0 when rate is provided")
        if packet_pps < 1:
            raise ValueError("packet_pps must be at least 1")

        tx_mac, rx_mac = self._resolve_two_port_macs(tx_port, rx_port, tx_mac, rx_mac, password=password)
        setup = [
            f"service -p {tx_port} {rx_port}",
            f"l2 -p {tx_port} --dst {rx_mac}",
            f"l2 -p {rx_port} --dst {tx_mac}",
            f"service --off -p {tx_port} {rx_port}",
        ]
        setup_batch = self.launcher.run_console_batch(
            setup,
            password=password,
            ports=[tx_port, rx_port],
            force_acquire=True,
            readonly=False,
            timeout=40.0,
        )
        if not setup_batch.success:
            return TrexTrafficResult(
                "l2",
                False,
                {
                    "mode": "stream" if rate is not None else "packet",
                    "tx_port": tx_port,
                    "rx_port": rx_port,
                    "tx_mac": tx_mac,
                    "rx_mac": rx_mac,
                    "batch_success": False,
                },
                {},
                {"setup": setup_batch.output},
            )

        if rate is not None:
            remote_success, payload, metrics, remote_output = self._run_remote_stl_streams(
                ports=[tx_port],
                stream_specs=[
                    {
                        "kind": "l2",
                        "port": tx_port,
                        "src_mac": tx_mac,
                        "dst_mac": rx_mac,
                        "eth_type": 0x88B5,
                        "frame_size": frame_size,
                        "udp_src_port": 0,
                        "udp_dst_port": 0,
                    }
                ],
                rate=rate,
                duration=duration,
                password=password,
            )
            tx_packets = metrics.get("opackets", {}).get(tx_port, 0)
            rx_packets = metrics.get("ipackets", {}).get(rx_port, 0)
            tx_bytes = metrics.get("obytes", {}).get(tx_port, 0)
            rx_bytes = metrics.get("ibytes", {}).get(rx_port, 0)
            tx_errors = metrics.get("oerrors", {}).get(tx_port, 0)
            rx_errors = metrics.get("ierrors", {}).get(rx_port, 0)
            summary = {
                "mode": "stream",
                "rate": rate,
                "duration": duration,
                "frame_size": frame_size,
                "tx_port": tx_port,
                "rx_port": rx_port,
                "tx_mac": tx_mac,
                "rx_mac": rx_mac,
                "packets_sent": tx_packets,
                "packets_received": rx_packets,
                "packet_loss": loss_count(tx_packets, rx_packets),
                "packet_loss_pct": loss_percent(tx_packets, rx_packets),
                "bytes_sent": tx_bytes,
                "bytes_received": rx_bytes,
                "tx_errors": tx_errors,
                "rx_errors": rx_errors,
                "batch_success": remote_success,
            }
            if payload.get("error"):
                summary["error"] = payload["error"]
            success = remote_success and tx_packets > 0 and rx_packets > 0 and tx_errors == 0 and rx_errors == 0
            return TrexTrafficResult("l2", success, summary, metrics, {"setup": setup_batch.output, "traffic": remote_output})

        commands = ["clear"]
        packet_cmd = f"pkt -p {tx_port} -s Ether(src='{tx_mac}',dst='{rx_mac}')/IP()/UDP()/('x'*10)"
        commands.extend([packet_cmd] * int(packets))
        commands.extend(["stats", f"release -p {tx_port} {rx_port}"])
        batch = self.launcher.run_console_batch(
            commands,
            password=password,
            ports=[tx_port, rx_port],
            force_acquire=True,
            readonly=False,
            timeout=max(40.0, float(packets) * 1.5),
        )

        metrics = self.parse_summary(batch.output)
        tx_packets = metrics.get("opackets", {}).get(tx_port, 0)
        rx_packets = metrics.get("ipackets", {}).get(rx_port, 0)
        tx_bytes = metrics.get("obytes", {}).get(tx_port, 0)
        rx_bytes = metrics.get("ibytes", {}).get(rx_port, 0)
        tx_errors = metrics.get("oerrors", {}).get(tx_port, 0)
        rx_errors = metrics.get("ierrors", {}).get(rx_port, 0)
        summary = {
            "mode": "packet",
            "tx_port": tx_port,
            "rx_port": rx_port,
            "tx_mac": tx_mac,
            "rx_mac": rx_mac,
            "packet_pps": packet_pps,
            "packets_asked": int(packets),
            "packets_sent": tx_packets,
            "packets_received": rx_packets,
            "packet_loss": loss_count(tx_packets, rx_packets),
            "packet_loss_pct": loss_percent(tx_packets, rx_packets),
            "bytes_sent": tx_bytes,
            "bytes_received": rx_bytes,
            "tx_errors": tx_errors,
            "rx_errors": rx_errors,
            "batch_success": batch.success,
        }
        success = batch.success and tx_packets == packets and rx_packets == packets and tx_errors == 0 and rx_errors == 0
        return TrexTrafficResult("l2", success, summary, metrics, {"setup": setup_batch.output, "traffic": batch.output})

    def run_l2_bidirectional(
        self,
        *,
        packets: int | None = None,
        port_a: int = 0,
        port_b: int = 1,
        port_a_mac: str | None = None,
        port_b_mac: str | None = None,
        rate: str | None = None,
        duration: float = 10.0,
        frame_size: int = 64,
        packet_pps: int = 50,
        password: str | None = None,
    ) -> TrexTrafficResult:
        if rate is None:
            if packets is None or packets < 1:
                raise ValueError("packets must be at least 1 when rate is not provided")
        elif duration <= 0:
            raise ValueError("duration must be greater than 0 when rate is provided")
        if packet_pps < 1:
            raise ValueError("packet_pps must be at least 1")

        port_a_mac, port_b_mac = self._resolve_two_port_macs(port_a, port_b, port_a_mac, port_b_mac, password=password)
        setup = [
            f"service -p {port_a} {port_b}",
            f"l2 -p {port_a} --dst {port_b_mac}",
            f"l2 -p {port_b} --dst {port_a_mac}",
            f"service --off -p {port_a} {port_b}",
        ]
        setup_batch = self.launcher.run_console_batch(
            setup,
            password=password,
            ports=[port_a, port_b],
            force_acquire=True,
            readonly=False,
            timeout=40.0,
        )
        if not setup_batch.success:
            return TrexTrafficResult(
                "l2_bidirectional",
                False,
                {
                    "mode": "stream" if rate is not None else "packet",
                    "port_a": port_a,
                    "port_b": port_b,
                    "port_a_mac": port_a_mac,
                    "port_b_mac": port_b_mac,
                    "batch_success": False,
                },
                {},
                {"setup": setup_batch.output},
            )

        if rate is not None:
            remote_success, payload, metrics, remote_output = self._run_remote_stl_streams(
                ports=[port_a, port_b],
                stream_specs=[
                    {
                        "kind": "l2",
                        "port": port_a,
                        "src_mac": port_a_mac,
                        "dst_mac": port_b_mac,
                        "eth_type": 0x88B5,
                        "frame_size": frame_size,
                        "udp_src_port": 0,
                        "udp_dst_port": 0,
                    },
                    {
                        "kind": "l2",
                        "port": port_b,
                        "src_mac": port_b_mac,
                        "dst_mac": port_a_mac,
                        "eth_type": 0x88B5,
                        "frame_size": frame_size,
                        "udp_src_port": 0,
                        "udp_dst_port": 0,
                    },
                ],
                rate=rate,
                duration=duration,
                password=password,
            )
            a_tx = metrics.get("opackets", {}).get(port_a, 0)
            a_rx = metrics.get("ipackets", {}).get(port_a, 0)
            b_tx = metrics.get("opackets", {}).get(port_b, 0)
            b_rx = metrics.get("ipackets", {}).get(port_b, 0)
            a_tx_bytes = metrics.get("obytes", {}).get(port_a, 0)
            a_rx_bytes = metrics.get("ibytes", {}).get(port_a, 0)
            b_tx_bytes = metrics.get("obytes", {}).get(port_b, 0)
            b_rx_bytes = metrics.get("ibytes", {}).get(port_b, 0)
            a_oerrors = metrics.get("oerrors", {}).get(port_a, 0)
            a_ierrors = metrics.get("ierrors", {}).get(port_a, 0)
            b_oerrors = metrics.get("oerrors", {}).get(port_b, 0)
            b_ierrors = metrics.get("ierrors", {}).get(port_b, 0)
            sent_total = a_tx + b_tx
            received_total = a_rx + b_rx
            summary = {
                "mode": "stream",
                "rate": rate,
                "duration": duration,
                "frame_size": frame_size,
                "port_a": port_a,
                "port_b": port_b,
                "port_a_mac": port_a_mac,
                "port_b_mac": port_b_mac,
                "port_a_sent": a_tx,
                "port_a_received": a_rx,
                "port_b_sent": b_tx,
                "port_b_received": b_rx,
                "port_a_tx_bytes": a_tx_bytes,
                "port_a_rx_bytes": a_rx_bytes,
                "port_b_tx_bytes": b_tx_bytes,
                "port_b_rx_bytes": b_rx_bytes,
                "loss_a_to_b": loss_count(a_tx, b_rx),
                "loss_a_to_b_pct": loss_percent(a_tx, b_rx),
                "loss_b_to_a": loss_count(b_tx, a_rx),
                "loss_b_to_a_pct": loss_percent(b_tx, a_rx),
                "total_sent": sent_total,
                "total_received": received_total,
                "total_loss": loss_count(sent_total, received_total),
                "total_loss_pct": loss_percent(sent_total, received_total),
                "port_a_tx_errors": a_oerrors,
                "port_a_rx_errors": a_ierrors,
                "port_b_tx_errors": b_oerrors,
                "port_b_rx_errors": b_ierrors,
                "batch_success": remote_success,
            }
            if payload.get("error"):
                summary["error"] = payload["error"]
            success = remote_success and a_tx > 0 and a_rx > 0 and b_tx > 0 and b_rx > 0 and a_oerrors == 0 and a_ierrors == 0 and b_oerrors == 0 and b_ierrors == 0
            return TrexTrafficResult("l2_bidirectional", success, summary, metrics, {"setup": setup_batch.output, "traffic": remote_output})

        commands = ["clear"]
        pkt_a = f"pkt -p {port_a} -s Ether(src='{port_a_mac}',dst='{port_b_mac}')/IP()/UDP()/('x'*10)"
        pkt_b = f"pkt -p {port_b} -s Ether(src='{port_b_mac}',dst='{port_a_mac}')/IP()/UDP()/('x'*10)"
        for _ in range(int(packets)):
            commands.append(pkt_a)
            commands.append(pkt_b)
        commands.extend(["stats", f"release -p {port_a} {port_b}"])
        batch = self.launcher.run_console_batch(
            commands,
            password=password,
            ports=[port_a, port_b],
            force_acquire=True,
            readonly=False,
            timeout=max(40.0, float(packets) * 3.0),
        )

        metrics = self.parse_summary(batch.output)
        a_tx = metrics.get("opackets", {}).get(port_a, 0)
        a_rx = metrics.get("ipackets", {}).get(port_a, 0)
        b_tx = metrics.get("opackets", {}).get(port_b, 0)
        b_rx = metrics.get("ipackets", {}).get(port_b, 0)
        a_tx_bytes = metrics.get("obytes", {}).get(port_a, 0)
        a_rx_bytes = metrics.get("ibytes", {}).get(port_a, 0)
        b_tx_bytes = metrics.get("obytes", {}).get(port_b, 0)
        b_rx_bytes = metrics.get("ibytes", {}).get(port_b, 0)
        a_oerrors = metrics.get("oerrors", {}).get(port_a, 0)
        a_ierrors = metrics.get("ierrors", {}).get(port_a, 0)
        b_oerrors = metrics.get("oerrors", {}).get(port_b, 0)
        b_ierrors = metrics.get("ierrors", {}).get(port_b, 0)
        sent_total = a_tx + b_tx
        received_total = a_rx + b_rx
        summary = {
            "mode": "packet",
            "port_a": port_a,
            "port_b": port_b,
            "port_a_mac": port_a_mac,
            "port_b_mac": port_b_mac,
            "packet_pps": packet_pps,
            "packets_per_port": int(packets),
            "expected_total": int(packets) * 2,
            "port_a_sent": a_tx,
            "port_a_received": a_rx,
            "port_b_sent": b_tx,
            "port_b_received": b_rx,
            "port_a_tx_bytes": a_tx_bytes,
            "port_a_rx_bytes": a_rx_bytes,
            "port_b_tx_bytes": b_tx_bytes,
            "port_b_rx_bytes": b_rx_bytes,
            "loss_a_to_b": loss_count(a_tx, b_rx),
            "loss_a_to_b_pct": loss_percent(a_tx, b_rx),
            "loss_b_to_a": loss_count(b_tx, a_rx),
            "loss_b_to_a_pct": loss_percent(b_tx, a_rx),
            "total_sent": sent_total,
            "total_received": received_total,
            "total_loss": loss_count(sent_total, received_total),
            "total_loss_pct": loss_percent(sent_total, received_total),
            "port_a_tx_errors": a_oerrors,
            "port_a_rx_errors": a_ierrors,
            "port_b_tx_errors": b_oerrors,
            "port_b_rx_errors": b_ierrors,
            "batch_success": batch.success,
        }
        success = (
            batch.success
            and a_tx == packets
            and a_rx == packets
            and b_tx == packets
            and b_rx == packets
            and a_oerrors == 0
            and a_ierrors == 0
            and b_oerrors == 0
            and b_ierrors == 0
        )
        return TrexTrafficResult("l2_bidirectional", success, summary, metrics, {"setup": setup_batch.output, "traffic": batch.output})

    def run_l3(
        self,
        *,
        packets: int | None = None,
        tx_port: int = 0,
        tx_src_ip: str,
        tx_next_hop: str,
        rx_port: int | None = None,
        rx_src_ip: str | None = None,
        rx_next_hop: str | None = None,
        traffic_src_ip: str | None = None,
        traffic_dst_ip: str | None = None,
        payload_bytes: int = 10,
        udp_src_port: int = 1025,
        udp_dst_port: int = 12,
        tx_mac: str | None = None,
        rate: str | None = None,
        duration: float = 10.0,
        packet_pps: int = 50,
        password: str | None = None,
    ) -> TrexTrafficResult:
        if rate is None:
            if packets is None or packets < 1:
                raise ValueError("packets must be at least 1 when rate is not provided")
        elif duration <= 0:
            raise ValueError("duration must be greater than 0 when rate is provided")
        if packet_pps < 1:
            raise ValueError("packet_pps must be at least 1")
        tx_mac = self._resolve_port_mac(tx_port, tx_mac, password=password)
        ports = [tx_port]
        setup = [f"service -p {tx_port}"]
        if rx_port is not None:
            if not rx_src_ip or not rx_next_hop:
                raise ValueError("rx_src_ip and rx_next_hop are required when rx_port is provided")
            ports.append(rx_port)
            setup[0] = f"service -p {tx_port} {rx_port}"
        setup.append(f"l3 -p {tx_port} --src {tx_src_ip} --dst {tx_next_hop}")
        if rx_port is not None:
            setup.append(f"l3 -p {rx_port} --src {rx_src_ip} --dst {rx_next_hop}")
        setup.append("arp -p " + " ".join(str(port) for port in ports))
        setup.append("service --off -p " + " ".join(str(port) for port in ports))
        setup_batch = self.launcher.run_console_batch(
            setup,
            password=password,
            ports=ports,
            force_acquire=True,
            readonly=False,
            timeout=60.0,
            delay_after_acquire=self.launcher.config.acquire_settle_time,
        )
        arp_replies = self.parse_arp_replies(setup_batch.output)
        tx_reply = arp_replies.get(tx_port)
        if not setup_batch.success or not tx_reply:
            summary: dict[str, Any] = {
                "mode": "stream" if rate is not None else "packet",
                "tx_port": tx_port,
                "tx_mac": tx_mac,
                "tx_src_ip": tx_src_ip,
                "tx_next_hop": tx_next_hop,
                "traffic_src_ip": traffic_src_ip or tx_src_ip,
                "traffic_dst_ip": traffic_dst_ip or tx_next_hop,
                "batch_success": setup_batch.success,
                "resolved_nh_mac": tx_reply["mac"] if tx_reply else None,
                "error": "setup failed before traffic start",
            }
            if rate is not None:
                summary.update({"rate": rate, "duration": duration})
            else:
                summary["packets_asked"] = int(packets) if packets is not None else None
            return TrexTrafficResult(
                "l3",
                False,
                summary,
                {},
                {"setup": setup_batch.output},
            )

        traffic_src_ip = traffic_src_ip or tx_src_ip
        traffic_dst_ip = traffic_dst_ip or tx_next_hop
        if rate is not None:
            stream_specs = [
                {
                    "kind": "l3",
                    "port": tx_port,
                    "src_mac": tx_mac,
                    "dst_mac": tx_reply["mac"],
                    "src_ip": traffic_src_ip,
                    "dst_ip": traffic_dst_ip,
                    "protocol": "udp",
                    "udp_src_port": udp_src_port,
                    "udp_dst_port": udp_dst_port,
                    "frame_size": 14 + 20 + 8 + payload_bytes,
                }
            ]
            remote_ports = [tx_port]
            if rx_port is not None:
                remote_ports.append(rx_port)
            remote_success, payload, metrics, remote_output = self._run_remote_stl_streams(
                ports=remote_ports,
                stream_specs=stream_specs,
                rate=rate,
                duration=duration,
                password=password,
            )
            tx_packets = metrics.get("opackets", {}).get(tx_port, 0)
            tx_bytes = metrics.get("obytes", {}).get(tx_port, 0)
            tx_errors = metrics.get("oerrors", {}).get(tx_port, 0)
            summary = {
                "mode": "stream",
                "rate": rate,
                "duration": duration,
                "tx_port": tx_port,
                "tx_mac": tx_mac,
                "tx_src_ip": tx_src_ip,
                "tx_next_hop": tx_next_hop,
                "resolved_nh_mac": tx_reply["mac"],
                "traffic_src_ip": traffic_src_ip,
                "traffic_dst_ip": traffic_dst_ip,
                "packets_sent": tx_packets,
                "bytes_sent": tx_bytes,
                "tx_errors": tx_errors,
                "batch_success": remote_success,
            }
            success = remote_success and tx_packets > 0 and tx_errors == 0
            if rx_port is not None:
                rx_packets = metrics.get("ipackets", {}).get(rx_port, 0)
                rx_bytes = metrics.get("ibytes", {}).get(rx_port, 0)
                rx_errors = metrics.get("ierrors", {}).get(rx_port, 0)
                summary.update(
                    {
                        "rx_port": rx_port,
                        "packets_received": rx_packets,
                        "bytes_received": rx_bytes,
                        "rx_errors": rx_errors,
                        "packet_loss": loss_count(tx_packets, rx_packets),
                        "packet_loss_pct": loss_percent(tx_packets, rx_packets),
                    }
                )
                success = success and rx_packets > 0 and rx_errors == 0
            if payload.get("error"):
                summary["error"] = payload["error"]
            return TrexTrafficResult("l3", success, summary, metrics, {"setup": setup_batch.output, "traffic": remote_output})

        remote_success, payload, metrics, remote_output = self._run_remote_stl_streams(
            ports=ports,
            stream_specs=[
                {
                    "kind": "l3",
                    "port": tx_port,
                    "src_mac": tx_mac,
                    "dst_mac": tx_reply["mac"],
                    "src_ip": traffic_src_ip,
                    "dst_ip": traffic_dst_ip,
                    "protocol": "udp",
                    "udp_src_port": udp_src_port,
                    "udp_dst_port": udp_dst_port,
                    "frame_size": 14 + 20 + 8 + payload_bytes,
                }
            ],
            count=int(packets),
            packet_pps=packet_pps,
            password=password,
        )
        tx_packets = metrics.get("opackets", {}).get(tx_port, 0)
        tx_bytes = metrics.get("obytes", {}).get(tx_port, 0)
        tx_errors = metrics.get("oerrors", {}).get(tx_port, 0)
        summary: dict[str, Any] = {
            "mode": "packet",
            "tx_port": tx_port,
            "tx_mac": tx_mac,
            "tx_src_ip": tx_src_ip,
            "tx_next_hop": tx_next_hop,
            "resolved_nh_mac": tx_reply["mac"],
            "traffic_src_ip": traffic_src_ip,
            "traffic_dst_ip": traffic_dst_ip,
            "packet_pps": packet_pps,
            "packets_asked": int(packets),
            "packets_sent": tx_packets,
            "bytes_sent": tx_bytes,
            "tx_errors": tx_errors,
            "batch_success": remote_success,
        }
        if payload.get("error"):
            summary["error"] = payload["error"]
        success = remote_success and tx_packets == packets and tx_errors == 0
        if rx_port is not None:
            rx_packets = metrics.get("ipackets", {}).get(rx_port, 0)
            rx_bytes = metrics.get("ibytes", {}).get(rx_port, 0)
            rx_errors = metrics.get("ierrors", {}).get(rx_port, 0)
            summary.update(
                {
                    "rx_port": rx_port,
                    "packets_received": rx_packets,
                    "bytes_received": rx_bytes,
                    "rx_errors": rx_errors,
                    "packet_loss": loss_count(tx_packets, rx_packets),
                    "packet_loss_pct": loss_percent(tx_packets, rx_packets),
                }
            )
            success = success and rx_packets == packets and rx_errors == 0
        return TrexTrafficResult(
            "l3",
            success,
            summary,
            metrics,
            {"setup": setup_batch.output, "traffic": remote_output},
        )

    def run_l3_bidirectional(
        self,
        *,
        packets: int | None = None,
        port_a_src_ip: str,
        port_b_src_ip: str,
        traffic_a_dst_ip: str,
        traffic_b_dst_ip: str,
        port_a: int = 0,
        port_b: int = 1,
        port_a_next_hop_ip: str | None = None,
        port_b_next_hop_ip: str | None = None,
        port_a_next_hop_mac: str | None = None,
        port_b_next_hop_mac: str | None = None,
        payload_bytes: int = 10,
        udp_src_port: int = 1025,
        udp_dst_port: int = 12,
        port_a_mac: str | None = None,
        port_b_mac: str | None = None,
        rate: str | None = None,
        duration: float = 10.0,
        packet_pps: int = 50,
        password: str | None = None,
    ) -> TrexTrafficResult:
        if rate is None:
            if packets is None or packets < 1:
                raise ValueError("packets must be at least 1 when rate is not provided")
        elif duration <= 0:
            raise ValueError("duration must be greater than 0 when rate is provided")
        if packet_pps < 1:
            raise ValueError("packet_pps must be at least 1")

        port_a_mac, port_b_mac = self._resolve_two_port_macs(port_a, port_b, port_a_mac, port_b_mac, password=password)
        setup_batch: TrexConsoleBatchResult | None = None

        if port_a_next_hop_mac and port_b_next_hop_mac:
            port_a_next_hop_mac = port_a_next_hop_mac.lower()
            port_b_next_hop_mac = port_b_next_hop_mac.lower()
            setup_batch = self.launcher.run_console_batch(
                [
                    f"service -p {port_a} {port_b}",
                    f"l2 -p {port_a} --dst {port_a_next_hop_mac}",
                    f"l2 -p {port_b} --dst {port_b_next_hop_mac}",
                    f"service --off -p {port_a} {port_b}",
                ],
                password=password,
                ports=[port_a, port_b],
                force_acquire=True,
                readonly=False,
                timeout=40.0,
            )
        else:
            if not port_a_next_hop_ip or not port_b_next_hop_ip:
                raise ValueError("provide either both next-hop IPs or both next-hop MACs")
            setup_batch = self.launcher.run_console_batch(
                [
                    f"service -p {port_a} {port_b}",
                    f"l3 -p {port_a} --src {port_a_src_ip} --dst {port_a_next_hop_ip}",
                    f"l3 -p {port_b} --src {port_b_src_ip} --dst {port_b_next_hop_ip}",
                    f"arp -p {port_a} {port_b}",
                    f"service --off -p {port_a} {port_b}",
                ],
                password=password,
                ports=[port_a, port_b],
                force_acquire=True,
                readonly=False,
                timeout=60.0,
                delay_after_acquire=self.launcher.config.acquire_settle_time,
            )
            arp_replies = self.parse_arp_replies(setup_batch.output)
            try:
                port_a_next_hop_mac = arp_replies[port_a]["mac"]
                port_b_next_hop_mac = arp_replies[port_b]["mac"]
            except KeyError:
                summary: dict[str, Any] = {
                    "mode": "stream" if rate is not None else "packet",
                    "port_a": port_a,
                    "port_b": port_b,
                    "port_a_mac": port_a_mac,
                    "port_b_mac": port_b_mac,
                    "port_a_src_ip": port_a_src_ip,
                    "port_b_src_ip": port_b_src_ip,
                    "traffic_a_dst_ip": traffic_a_dst_ip,
                    "traffic_b_dst_ip": traffic_b_dst_ip,
                    "port_a_next_hop_mac": port_a_next_hop_mac,
                    "port_b_next_hop_mac": port_b_next_hop_mac,
                    "batch_success": setup_batch.success,
                    "error": "setup failed before traffic start",
                }
                if rate is not None:
                    summary.update({"rate": rate, "duration": duration})
                else:
                    summary["packets_per_port"] = int(packets) if packets is not None else None
                return TrexTrafficResult(
                    "l3_bidirectional",
                    False,
                    summary,
                    {},
                    {"setup": setup_batch.output},
                )

        if not setup_batch.success:
            summary = {
                "mode": "stream" if rate is not None else "packet",
                "port_a": port_a,
                "port_b": port_b,
                "port_a_mac": port_a_mac,
                "port_b_mac": port_b_mac,
                "port_a_src_ip": port_a_src_ip,
                "port_b_src_ip": port_b_src_ip,
                "traffic_a_dst_ip": traffic_a_dst_ip,
                "traffic_b_dst_ip": traffic_b_dst_ip,
                "port_a_next_hop_mac": port_a_next_hop_mac,
                "port_b_next_hop_mac": port_b_next_hop_mac,
                "batch_success": False,
                "error": "setup failed before traffic start",
            }
            if rate is not None:
                summary.update({"rate": rate, "duration": duration})
            else:
                summary["packets_per_port"] = int(packets) if packets is not None else None
            return TrexTrafficResult(
                "l3_bidirectional",
                False,
                summary,
                {},
                {"setup": setup_batch.output},
            )

        if rate is not None:
            remote_success, payload, metrics, remote_output = self._run_remote_stl_streams(
                ports=[port_a, port_b],
                stream_specs=[
                    {
                        "kind": "l3",
                        "port": port_a,
                        "src_mac": port_a_mac,
                        "dst_mac": port_a_next_hop_mac,
                        "src_ip": port_a_src_ip,
                        "dst_ip": traffic_a_dst_ip,
                        "protocol": "udp",
                        "udp_src_port": udp_src_port,
                        "udp_dst_port": udp_dst_port,
                        "frame_size": 14 + 20 + 8 + payload_bytes,
                    },
                    {
                        "kind": "l3",
                        "port": port_b,
                        "src_mac": port_b_mac,
                        "dst_mac": port_b_next_hop_mac,
                        "src_ip": port_b_src_ip,
                        "dst_ip": traffic_b_dst_ip,
                        "protocol": "udp",
                        "udp_src_port": udp_src_port,
                        "udp_dst_port": udp_dst_port,
                        "frame_size": 14 + 20 + 8 + payload_bytes,
                    },
                ],
                rate=rate,
                duration=duration,
                password=password,
            )
            a_tx = metrics.get("opackets", {}).get(port_a, 0)
            a_rx = metrics.get("ipackets", {}).get(port_a, 0)
            b_tx = metrics.get("opackets", {}).get(port_b, 0)
            b_rx = metrics.get("ipackets", {}).get(port_b, 0)
            a_tx_bytes = metrics.get("obytes", {}).get(port_a, 0)
            a_rx_bytes = metrics.get("ibytes", {}).get(port_a, 0)
            b_tx_bytes = metrics.get("obytes", {}).get(port_b, 0)
            b_rx_bytes = metrics.get("ibytes", {}).get(port_b, 0)
            a_oerrors = metrics.get("oerrors", {}).get(port_a, 0)
            a_ierrors = metrics.get("ierrors", {}).get(port_a, 0)
            b_oerrors = metrics.get("oerrors", {}).get(port_b, 0)
            b_ierrors = metrics.get("ierrors", {}).get(port_b, 0)
            sent_total = a_tx + b_tx
            received_total = a_rx + b_rx
            summary = {
                "mode": "stream",
                "rate": rate,
                "duration": duration,
                "port_a": port_a,
                "port_b": port_b,
                "port_a_mac": port_a_mac,
                "port_b_mac": port_b_mac,
                "port_a_next_hop_mac": port_a_next_hop_mac,
                "port_b_next_hop_mac": port_b_next_hop_mac,
                "port_a_src_ip": port_a_src_ip,
                "port_b_src_ip": port_b_src_ip,
                "traffic_a_dst_ip": traffic_a_dst_ip,
                "traffic_b_dst_ip": traffic_b_dst_ip,
                "port_a_sent": a_tx,
                "port_a_received": a_rx,
                "port_b_sent": b_tx,
                "port_b_received": b_rx,
                "port_a_tx_bytes": a_tx_bytes,
                "port_a_rx_bytes": a_rx_bytes,
                "port_b_tx_bytes": b_tx_bytes,
                "port_b_rx_bytes": b_rx_bytes,
                "loss_a_to_b": loss_count(a_tx, b_rx),
                "loss_a_to_b_pct": loss_percent(a_tx, b_rx),
                "loss_b_to_a": loss_count(b_tx, a_rx),
                "loss_b_to_a_pct": loss_percent(b_tx, a_rx),
                "total_sent": sent_total,
                "total_received": received_total,
                "total_loss": loss_count(sent_total, received_total),
                "total_loss_pct": loss_percent(sent_total, received_total),
                "port_a_tx_errors": a_oerrors,
                "port_a_rx_errors": a_ierrors,
                "port_b_tx_errors": b_oerrors,
                "port_b_rx_errors": b_ierrors,
                "batch_success": remote_success,
            }
            if payload.get("error"):
                summary["error"] = payload["error"]
            success = remote_success and a_tx > 0 and a_rx > 0 and b_tx > 0 and b_rx > 0 and a_oerrors == 0 and a_ierrors == 0 and b_oerrors == 0 and b_ierrors == 0
            return TrexTrafficResult(
                "l3_bidirectional",
                success,
                summary,
                metrics,
                {"setup": setup_batch.output, "traffic": remote_output},
            )

        remote_success, payload, metrics, remote_output = self._run_remote_stl_streams(
            ports=[port_a, port_b],
            stream_specs=[
                {
                    "kind": "l3",
                    "port": port_a,
                    "src_mac": port_a_mac,
                    "dst_mac": port_a_next_hop_mac,
                    "src_ip": port_a_src_ip,
                    "dst_ip": traffic_a_dst_ip,
                    "protocol": "udp",
                    "udp_src_port": udp_src_port,
                    "udp_dst_port": udp_dst_port,
                    "frame_size": 14 + 20 + 8 + payload_bytes,
                },
                {
                    "kind": "l3",
                    "port": port_b,
                    "src_mac": port_b_mac,
                    "dst_mac": port_b_next_hop_mac,
                    "src_ip": port_b_src_ip,
                    "dst_ip": traffic_b_dst_ip,
                    "protocol": "udp",
                    "udp_src_port": udp_src_port,
                    "udp_dst_port": udp_dst_port,
                    "frame_size": 14 + 20 + 8 + payload_bytes,
                },
            ],
            count=int(packets),
            packet_pps=packet_pps,
            password=password,
        )
        a_tx = metrics.get("opackets", {}).get(port_a, 0)
        a_rx = metrics.get("ipackets", {}).get(port_a, 0)
        b_tx = metrics.get("opackets", {}).get(port_b, 0)
        b_rx = metrics.get("ipackets", {}).get(port_b, 0)
        a_tx_bytes = metrics.get("obytes", {}).get(port_a, 0)
        a_rx_bytes = metrics.get("ibytes", {}).get(port_a, 0)
        b_tx_bytes = metrics.get("obytes", {}).get(port_b, 0)
        b_rx_bytes = metrics.get("ibytes", {}).get(port_b, 0)
        a_oerrors = metrics.get("oerrors", {}).get(port_a, 0)
        a_ierrors = metrics.get("ierrors", {}).get(port_a, 0)
        b_oerrors = metrics.get("oerrors", {}).get(port_b, 0)
        b_ierrors = metrics.get("ierrors", {}).get(port_b, 0)
        sent_total = a_tx + b_tx
        received_total = a_rx + b_rx
        summary = {
            "mode": "packet",
            "port_a": port_a,
            "port_b": port_b,
            "port_a_mac": port_a_mac,
            "port_b_mac": port_b_mac,
            "port_a_next_hop_mac": port_a_next_hop_mac,
            "port_b_next_hop_mac": port_b_next_hop_mac,
            "port_a_src_ip": port_a_src_ip,
            "port_b_src_ip": port_b_src_ip,
            "traffic_a_dst_ip": traffic_a_dst_ip,
            "traffic_b_dst_ip": traffic_b_dst_ip,
            "packet_pps": packet_pps,
            "packets_per_port": int(packets),
            "port_a_sent": a_tx,
            "port_a_received": a_rx,
            "port_b_sent": b_tx,
            "port_b_received": b_rx,
            "port_a_tx_bytes": a_tx_bytes,
            "port_a_rx_bytes": a_rx_bytes,
            "port_b_tx_bytes": b_tx_bytes,
            "port_b_rx_bytes": b_rx_bytes,
            "loss_a_to_b": loss_count(a_tx, b_rx),
            "loss_a_to_b_pct": loss_percent(a_tx, b_rx),
            "loss_b_to_a": loss_count(b_tx, a_rx),
            "loss_b_to_a_pct": loss_percent(b_tx, a_rx),
            "total_sent": sent_total,
            "total_received": received_total,
            "total_loss": loss_count(sent_total, received_total),
            "total_loss_pct": loss_percent(sent_total, received_total),
            "port_a_tx_errors": a_oerrors,
            "port_a_rx_errors": a_ierrors,
            "port_b_tx_errors": b_oerrors,
            "port_b_rx_errors": b_ierrors,
            "batch_success": remote_success,
        }
        if payload.get("error"):
            summary["error"] = payload["error"]
        success = (
            remote_success
            and a_tx == packets
            and a_rx == packets
            and b_tx == packets
            and b_rx == packets
            and a_oerrors == 0
            and a_ierrors == 0
            and b_oerrors == 0
            and b_ierrors == 0
        )
        return TrexTrafficResult(
            "l3_bidirectional",
            success,
            summary,
            metrics,
            {"setup": setup_batch.output, "traffic": remote_output},
        )

    def run_ping(
        self,
        *,
        probes: list[PingProbe] | tuple[PingProbe, ...],
        count: int = 3,
        pkt_size: int = 64,
        password: str | None = None,
    ) -> TrexTrafficResult:
        if count < 1:
            raise ValueError("count must be at least 1")
        if pkt_size < 64:
            raise ValueError("pkt_size must be at least 64")

        probe_summaries: list[dict[str, Any]] = []
        outputs: dict[str, str] = {}
        overall_success = True
        for probe in probes:
            batch = self.launcher.run_console_batch(
                [
                    f"service -p {probe.port}",
                    f"l3 -p {probe.port} --src {probe.src_ip} --dst {probe.next_hop_ip}",
                    f"ping -p {probe.port} -d {probe.dst_ip} -s {pkt_size} -n {count}",
                    f"service --off -p {probe.port}",
                    f"release -p {probe.port}",
                ],
                password=password,
                ports=[probe.port],
                force_acquire=True,
                readonly=False,
                timeout=max(60.0, float(count) * 5.0 + 10.0),
                delay_after_acquire=self.launcher.config.acquire_settle_time,
            )
            outputs[f"port_{probe.port}"] = batch.output
            arp_replies = self.parse_arp_replies(batch.output)
            arp_failures = self.parse_arp_failures(batch.output)
            ping = self.parse_ping_summary(batch.output)
            reply_count = int(ping["reply_count"])
            timeout_count = int(ping["timeout_count"])
            unreachable_count = int(ping["unreachable_count"])
            resolved_mac = arp_replies.get(probe.port, {}).get("mac", "n/a")
            l3_resolve_failed = probe.port in arp_failures
            passed = batch.success and reply_count == count and timeout_count == 0 and unreachable_count == 0
            probe_summary = {
                "port": probe.port,
                "src_ip": probe.src_ip,
                "next_hop_ip": probe.next_hop_ip,
                "dst_ip": probe.dst_ip,
                "resolved_nh_mac": resolved_mac,
                "replies": reply_count,
                "requested_replies": count,
                "packet_loss": loss_count(count, reply_count),
                "packet_loss_pct": loss_percent(count, reply_count),
                "timeouts": timeout_count,
                "unreachable": unreachable_count,
                "l3_resolve_fail": l3_resolve_failed,
                "batch_success": batch.success,
                "success": passed,
            }
            probe_summaries.append(probe_summary)
            overall_success = overall_success and passed

        return TrexTrafficResult(
            "ping",
            overall_success,
            {
                "count": count,
                "pkt_size": pkt_size,
                "probe_results": probe_summaries,
            },
            {},
            outputs,
        )

    def run_astf_profile(
        self,
        *,
        profile: str,
        expected_transport: str = "any",
        multiplier: str | int | float = 100,
        duration: float = 10.0,
        profile_id: str | None = None,
        latency_pps: int | None = None,
        ipv6: bool = False,
        nc: bool = True,
        tunables: dict[str, object] | None = None,
        settle_time: float = 1.0,
        password: str | None = None,
    ) -> TrexTrafficResult:
        preflight, preflight_output = self._preflight_remote_astf(profile, password=password)
        resolved_schema_dir = preflight.get("schema_dir")
        resolved_profile = preflight.get("profile_path")
        if not resolved_schema_dir or not resolved_profile:
            missing = []
            if not resolved_schema_dir:
                missing.append("astf_schema.json")
            if not resolved_profile:
                missing.append(profile)
            return TrexTrafficResult(
                "astf_profile",
                False,
                {
                    "profile": profile,
                    "profile_id": profile_id,
                    "multiplier": multiplier,
                    "duration": duration,
                    "transport": expected_transport.lower(),
                    "start_batch_success": False,
                    "stats_batch_success": False,
                    "missing_assets": missing,
                    "schema_dir": resolved_schema_dir,
                    "resolved_profile": resolved_profile,
                    "search_roots": preflight.get("search_roots", []),
                    "error": "missing required ASTF assets on the remote TRex node",
                },
                {},
                {"preflight": preflight_output, "remote": preflight_output},
            )

        self.launcher.config.server_workdir = resolved_schema_dir
        self.launcher.ensure_server_running(password=password)
        remote_script = textwrap.dedent(
            f"""
            import json
            import os
            import shutil
            import sys
            import types

            dist = types.ModuleType("distutils")
            spawn = types.ModuleType("distutils.spawn")
            spawn.find_executable = shutil.which
            dist.spawn = spawn
            sys.modules["distutils"] = dist
            sys.modules["distutils.spawn"] = spawn

            from trex.astf.api import ASTFClient

            profile = {resolved_profile!r}

            client = ASTFClient(server='127.0.0.1')
            client.connect()
            try:
                client.reset()
                client.load_profile(profile, tunables={json.dumps(tunables or {})}, pid_input={profile_id!r})
                client.clear_stats()
                client.start(
                    mult={multiplier!r},
                    duration={float(duration)!r},
                    nc={bool(nc)!r},
                    latency_pps={int(latency_pps or 0)!r},
                    ipv6={bool(ipv6)!r},
                    pid_input={profile_id!r},
                )
                client.wait_on_traffic(timeout={max(60.0, float(duration) + float(settle_time) + 30.0)!r}, profile_id={profile_id!r})
                stats = client.get_stats(skip_zero=False, pid_input={profile_id!r})
                print("__TREXCMLLIB_ASTF_JSON__" + json.dumps(stats["traffic"]))
            finally:
                client.disconnect()
            """
        )
        command = (
            "cd /trex/automation/trex_control_plane/interactive && "
            "python3 - <<'INNER'\n"
            + remote_script.rstrip()
            + "\nINNER"
        )
        output = self.launcher.run_shell_commands(
            [command],
            password=password,
            timeout=max(90.0, float(duration) + float(settle_time) + 60.0),
        )

        match = ASTF_JSON_RE.search(output)
        if not match:
            return TrexTrafficResult(
                "astf_profile",
                False,
                {
                    "profile": profile,
                    "profile_id": profile_id,
                    "multiplier": multiplier,
                    "duration": duration,
                    "transport": expected_transport.lower(),
                    "start_batch_success": False,
                    "stats_batch_success": False,
                },
                {},
                {"remote": output},
            )

        parsed_stats = json.loads(match.group("json"))
        metrics: dict[str, dict[Any, int]] = {
            key: {side: int(value) for side, value in values.items()}
            for key, values in parsed_stats.items()
            if isinstance(values, dict)
        }

        transport = expected_transport.lower()
        if transport == "udp":
            forward_sent = metrics.get("udps_sndpkt", {}).get("client", 0)
            forward_received = metrics.get("udps_rcvpkt", {}).get("server", 0)
            reverse_sent = metrics.get("udps_sndpkt", {}).get("server", 0)
            reverse_received = metrics.get("udps_rcvpkt", {}).get("client", 0)
            drop_client = metrics.get("udps_keepdrops", {}).get("client", 0)
            drop_server = metrics.get("udps_keepdrops", {}).get("server", 0)
        else:
            forward_sent = metrics.get("tcps_sndpack", {}).get("client", 0)
            forward_received = metrics.get("tcps_rcvpack", {}).get("server", 0)
            reverse_sent = metrics.get("tcps_sndpack", {}).get("server", 0)
            reverse_received = metrics.get("tcps_rcvpack", {}).get("client", 0)
            drop_client = metrics.get("tcps_drops", {}).get("client", 0)
            drop_server = metrics.get("tcps_drops", {}).get("server", 0)

        summary = {
            "profile": profile,
            "profile_id": profile_id,
            "multiplier": multiplier,
            "duration": duration,
            "transport": transport,
            "client_connects": metrics.get(f"{transport}s_connects", {}).get("client", 0) if transport in {"tcp", "udp"} else 0,
            "server_connects": metrics.get(f"{transport}s_connects", {}).get("server", 0) if transport in {"tcp", "udp"} else 0,
            "client_to_server_sent": forward_sent,
            "client_to_server_received": forward_received,
            "client_to_server_loss": loss_count(forward_sent, forward_received),
            "client_to_server_loss_pct": loss_percent(forward_sent, forward_received),
            "server_to_client_sent": reverse_sent,
            "server_to_client_received": reverse_received,
            "server_to_client_loss": loss_count(reverse_sent, reverse_received),
            "server_to_client_loss_pct": loss_percent(reverse_sent, reverse_received),
            "client_bytes_sent": metrics.get(f"{transport}s_sndbyte", {}).get("client", 0) if transport in {"tcp", "udp"} else 0,
            "server_bytes_received": metrics.get(f"{transport}s_rcvbyte", {}).get("server", 0) if transport in {"tcp", "udp"} else 0,
            "server_bytes_sent": metrics.get(f"{transport}s_sndbyte", {}).get("server", 0) if transport in {"tcp", "udp"} else 0,
            "client_bytes_received": metrics.get(f"{transport}s_rcvbyte", {}).get("client", 0) if transport in {"tcp", "udp"} else 0,
            "client_retransmits": metrics.get("tcps_sndrexmitpack", {}).get("client", 0) if transport == "tcp" else 0,
            "server_retransmits": metrics.get("tcps_sndrexmitpack", {}).get("server", 0) if transport == "tcp" else 0,
            "client_drops": drop_client,
            "server_drops": drop_server,
            "start_batch_success": True,
            "stats_batch_success": True,
        }
        return TrexTrafficResult(
            "astf_profile",
            self.astf_runner.validate_metrics(metrics, expected_transport=expected_transport),
            summary,
            metrics,
            {"remote": output},
        )

    def run_astf_http(self, **kwargs: Any) -> TrexTrafficResult:
        kwargs.setdefault("profile", "astf/http_simple.py")
        kwargs.setdefault("profile_id", "http")
        kwargs.setdefault("expected_transport", "tcp")
        result = self.run_astf_profile(**kwargs)
        result.kind = "astf_http"
        return result

    def run_astf_udp(self, **kwargs: Any) -> TrexTrafficResult:
        kwargs.setdefault("profile", "astf/udp_pcap.py")
        kwargs.setdefault("profile_id", "udp")
        kwargs.setdefault("expected_transport", "udp")
        result = self.run_astf_profile(**kwargs)
        result.kind = "astf_udp"
        return result
