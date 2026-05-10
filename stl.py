"""Small wrapper around the bundled TRex STL Python client.

Dependencies:
- A ``trex-core`` checkout with the bundled TRex Python client under
  ``scripts/``
- Local Python compatibility with the bundled TRex dependencies

If the package is installed outside the ``trex-core`` repository, set
``TREX_CORE_SCRIPTS_DIR`` to the ``trex-core/scripts`` directory before using
``TrexCmlLib`` or ``configure_trex_python_path``.

On macOS, direct STL imports may fail because some bundled dependencies are
Linux-oriented. When that happens, prefer console CLI automation through
``TrexConsoleLauncher`` instead of the local STL wrapper.
"""

from __future__ import annotations

import html
import os
import sys
import types
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any


_TREX_IMPORTS: dict[str, Any] | None = None
TREX_CORE_SCRIPTS_ENV = "TREX_CORE_SCRIPTS_DIR"


def configure_trex_python_path(base_dir: str | Path | None = None) -> Path:
    """Expose bundled TRex Python dependencies on ``sys.path``."""

    if base_dir is not None:
        scripts_dir = Path(base_dir)
    else:
        env_dir = os.environ.get(TREX_CORE_SCRIPTS_ENV)
        if env_dir:
            scripts_dir = Path(env_dir)
        else:
            scripts_dir = Path(__file__).resolve().parent.parent
    scripts_dir = scripts_dir.resolve()
    paths = [
        scripts_dir / "external_libs" / "texttable-0.8.4",
        scripts_dir / "external_libs" / "pyyaml-3.11" / "python3",
        scripts_dir / "external_libs" / "scapy-2.4.3",
        scripts_dir / "external_libs" / "pyzmq-ctypes",
        scripts_dir / "external_libs" / "simpy-3.0.10",
        scripts_dir / "external_libs" / "trex-openssl",
        scripts_dir / "external_libs" / "dpkt-1.9.1",
        scripts_dir / "external_libs" / "repoze",
        scripts_dir / "automation" / "trex_control_plane" / "interactive",
    ]

    for path in reversed(paths):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

    return scripts_dir


def _install_stdlib_compat_shims() -> None:
    # Bundled Scapy 2.4.3 still imports ``cgi.escape``, which was removed in Python 3.13.
    if "cgi" not in sys.modules:
        cgi = types.ModuleType("cgi")
        cgi.escape = html.escape
        sys.modules["cgi"] = cgi


def _load_trex_imports() -> dict[str, Any]:
    global _TREX_IMPORTS
    if _TREX_IMPORTS is not None:
        return _TREX_IMPORTS

    configure_trex_python_path()
    _install_stdlib_compat_shims()
    try:
        stl_api = import_module("trex.stl.api")
        scapy_all = import_module("scapy.all")
    except (ModuleNotFoundError, OSError) as exc:
        raise RuntimeError(
            "Unable to import the bundled TRex STL client on this host. "
            "On macOS you usually need a Python environment with compatible "
            "client-side dependencies such as pyzmq, while the bundled "
            "pyzmq-ctypes payload is Linux-only. If trexcmllib is installed "
            f"outside a trex-core checkout, set {TREX_CORE_SCRIPTS_ENV} to "
            "the trex-core scripts directory first."
        ) from exc

    _TREX_IMPORTS = {
        "Ether": getattr(stl_api, "Ether"),
        "IP": getattr(stl_api, "IP"),
        "TCP": getattr(stl_api, "TCP"),
        "UDP": getattr(stl_api, "UDP"),
        "Dot1Q": getattr(scapy_all, "Dot1Q"),
        "Raw": getattr(scapy_all, "Raw"),
        "STLClient": getattr(stl_api, "STLClient"),
        "STLPktBuilder": getattr(stl_api, "STLPktBuilder"),
        "STLStream": getattr(stl_api, "STLStream"),
        "STLTXCont": getattr(stl_api, "STLTXCont"),
        "STLTXSingleBurst": getattr(stl_api, "STLTXSingleBurst"),
    }
    return _TREX_IMPORTS


def _listify_ports(ports: int | Sequence[int] | None) -> list[int] | None:
    if ports is None:
        return None
    if isinstance(ports, int):
        return [ports]
    return list(ports)


def _normalize_vlan(vlan: int | Sequence[int] | None) -> list[int]:
    if vlan is None:
        return []
    if isinstance(vlan, int):
        return [vlan]
    return list(vlan)


def _normalize_ping_record(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record

    status_map = {
        getattr(record, "SUCCESS", object()): "success",
        getattr(record, "TIMEOUT", object()): "timeout",
        getattr(record, "ICMP_TYPE_DEST_UNREACHABLE", object()): "unreachable",
    }
    status = status_map.get(getattr(record, "state", None), "unknown")

    normalized = {
        "formatted_string": str(record),
        "status": status,
    }

    if status == "success":
        normalized.update(
            {
                "src_ip": getattr(record, "responder_ip", None),
                "rtt": getattr(record, "rtt", None),
                "ttl": getattr(record, "ttl", None),
                "pkt_size": getattr(record, "pkt_size", None),
            }
        )
    elif status == "unreachable":
        normalized["src_ip"] = getattr(record, "responder_ip", None)

    return normalized


@dataclass(slots=True)
class TrexTrafficResult:
    ports: list[int]
    stats: dict[str, Any]
    duration: float | None
    count: int | None


class TrexCmlLib:
    """Convenience wrapper for simple TRex STL workflows."""

    def __init__(
        self,
        *,
        server: str = "127.0.0.1",
        sync_port: int = 4501,
        async_port: int = 4500,
        sync_timeout: int | None = 5,
        async_timeout: int | None = 5,
        verbose_level: str = "error",
    ) -> None:
        self.server = server
        self.sync_port = sync_port
        self.async_port = async_port
        self.sync_timeout = sync_timeout
        self.async_timeout = async_timeout
        self.verbose_level = verbose_level
        self.client = None

    def __enter__(self) -> "TrexCmlLib":
        self.connect()
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.disconnect()

    def connect(self) -> "TrexCmlLib":
        if self.client is not None:
            return self

        imports = _load_trex_imports()
        client_cls = imports["STLClient"]
        self.client = client_cls(
            server=self.server,
            sync_port=self.sync_port,
            async_port=self.async_port,
            verbose_level=self.verbose_level,
            sync_timeout=self.sync_timeout,
            async_timeout=self.async_timeout,
        )
        self.client.connect()
        return self

    def disconnect(self, *, release_ports: bool = False, ports: int | Sequence[int] | None = None) -> None:
        if self.client is None:
            return

        try:
            if release_ports:
                acquired = set(self.client.get_acquired_ports())
                requested = set(_listify_ports(ports) or acquired)
                to_release = sorted(acquired.intersection(requested))
                if to_release:
                    self.client.release(ports=to_release)
        finally:
            self.client.disconnect()
            self.client = None

    def ensure_connected(self) -> None:
        if self.client is None:
            raise RuntimeError("TRex client is not connected. Call connect() first.")

    def acquire_ports(self, ports: int | Sequence[int] | None = None, *, force: bool = False) -> list[int]:
        self.ensure_connected()
        requested = _listify_ports(ports) or list(self.client.get_all_ports())
        owned = set(self.client.get_acquired_ports())
        missing = sorted(set(requested) - owned)
        if missing:
            self.client.acquire(ports=missing, force=force)
        return requested

    def release_ports(self, ports: int | Sequence[int] | None = None) -> None:
        self.ensure_connected()
        requested = _listify_ports(ports) or list(self.client.get_acquired_ports())
        if requested:
            self.client.release(ports=requested)

    def get_port_info(self, ports: int | Sequence[int] | None = None) -> list[dict[str, Any]]:
        self.ensure_connected()
        return self.client.get_port_info(ports=ports)

    def get_port_attr(self, port: int) -> dict[str, Any]:
        self.ensure_connected()
        return self.client.get_port_attr(port)

    def reset_ports(self, ports: int | Sequence[int] | None = None, *, restart: bool = False) -> None:
        self.ensure_connected()
        self.client.reset(ports=ports, restart=restart)

    def configure_port_attributes(
        self,
        ports: int | Sequence[int],
        *,
        force_acquire: bool = False,
        promiscuous: bool | None = None,
        link_up: bool | None = None,
        led_on: bool | None = None,
        flow_ctrl: int | None = None,
        multicast: bool | None = None,
        vxlan_fs: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_connected()
        requested = self.acquire_ports(ports, force=force_acquire)
        self.client.set_port_attr(
            ports=requested,
            promiscuous=promiscuous,
            link_up=link_up,
            led_on=led_on,
            flow_ctrl=flow_ctrl,
            multicast=multicast,
            vxlan_fs=vxlan_fs,
        )
        return self.get_port_info(requested)

    def configure_l2_port(
        self,
        port: int,
        dst_mac: str,
        *,
        vlan: int | Sequence[int] | None = None,
        force_acquire: bool = False,
    ) -> dict[str, Any]:
        self.ensure_connected()
        self.acquire_ports(port, force=force_acquire)
        if vlan is not None:
            self.client.set_vlan(ports=port, vlan=_normalize_vlan(vlan))
        self.client.set_l2_mode(port, dst_mac)
        return self.get_port_attr(port)

    def configure_l3_port(
        self,
        port: int,
        src_ipv4: str,
        dst_ipv4: str,
        *,
        vlan: int | Sequence[int] | None = None,
        force_acquire: bool = False,
    ) -> dict[str, Any]:
        self.ensure_connected()
        self.acquire_ports(port, force=force_acquire)
        normalized_vlan = _normalize_vlan(vlan) if vlan is not None else None
        self.client.set_l3_mode(port, src_ipv4, dst_ipv4, vlan=normalized_vlan)
        return self.get_port_attr(port)

    def resolve_ports(
        self,
        ports: int | Sequence[int] | None = None,
        *,
        retries: int = 0,
        verbose: bool = True,
        vlan: int | Sequence[int] | None = None,
    ) -> Any:
        self.ensure_connected()
        normalized_vlan = _normalize_vlan(vlan) if vlan is not None else None
        return self.client.resolve(
            ports=ports,
            retries=retries,
            verbose=verbose,
            vlan=normalized_vlan,
        )

    def set_service_mode(
        self,
        ports: int | Sequence[int],
        *,
        enabled: bool = True,
        filtered: bool = False,
        mask: int | None = None,
        force_acquire: bool = False,
    ) -> None:
        self.ensure_connected()
        requested = self.acquire_ports(ports, force=force_acquire)
        self.client.set_service_mode(ports=requested, enabled=enabled, filtered=filtered, mask=mask)

    def clear_streams(self, ports: int | Sequence[int] | None = None) -> None:
        self.ensure_connected()
        self.client.remove_all_streams(ports=ports)

    def clear_stats(
        self,
        ports: int | Sequence[int] | None = None,
        *,
        clear_global: bool = True,
        clear_flow_stats: bool = True,
        clear_latency_stats: bool = True,
        clear_xstats: bool = True,
    ) -> None:
        self.ensure_connected()
        self.client.clear_stats(
            ports=ports,
            clear_global=clear_global,
            clear_flow_stats=clear_flow_stats,
            clear_latency_stats=clear_latency_stats,
            clear_xstats=clear_xstats,
        )

    def get_stats(self, ports: int | Sequence[int] | None = None, *, sync_now: bool = True) -> dict[str, Any]:
        self.ensure_connected()
        return self.client.get_stats(ports=ports, sync_now=sync_now)

    def stop_traffic(self, ports: int | Sequence[int] | None = None, *, rx_delay_ms: int | None = None) -> None:
        self.ensure_connected()
        self.client.stop(ports=ports, rx_delay_ms=rx_delay_ms)

    def wait_for_traffic(
        self,
        ports: int | Sequence[int] | None = None,
        *,
        timeout: int | float | None = None,
        rx_delay_ms: int | None = None,
    ) -> None:
        self.ensure_connected()
        self.client.wait_on_traffic(ports=ports, timeout=timeout, rx_delay_ms=rx_delay_ms)

    def ping(
        self,
        src_port: int,
        dst_ip: str,
        *,
        pkt_size: int = 64,
        count: int = 5,
        interval_sec: int | float = 1,
        vlan: int | Sequence[int] | None = None,
        force_acquire: bool = False,
        service_mode: bool = True,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        self.ensure_connected()
        self.acquire_ports(src_port, force=force_acquire)
        normalized_vlan = _normalize_vlan(vlan) if vlan is not None else None

        if service_mode:
            with self.client.service_mode([src_port]):
                records = self.client.ping_ip(
                    src_port,
                    dst_ip,
                    pkt_size=pkt_size,
                    count=count,
                    interval_sec=interval_sec,
                    vlan=normalized_vlan,
                    **kwargs,
                )
        else:
            records = self.client.ping_ip(
                src_port,
                dst_ip,
                pkt_size=pkt_size,
                count=count,
                interval_sec=interval_sec,
                vlan=normalized_vlan,
                **kwargs,
            )

        return [_normalize_ping_record(record) for record in records]

    def send_l2_traffic(
        self,
        ports: int | Sequence[int],
        *,
        dst_mac: str | None = None,
        src_mac: str | None = None,
        vlan: int | Sequence[int] | None = None,
        eth_type: int = 0x88B5,
        frame_size: int = 64,
        pps: int | float = 1000,
        count: int | None = None,
        duration: float | None = 10.0,
        force_acquire: bool = False,
        clear_existing: bool = True,
        clear_stats: bool = True,
        wait: bool = True,
    ) -> TrexTrafficResult:
        self.ensure_connected()
        requested = self.acquire_ports(ports, force=force_acquire)

        streams = []
        for port in requested:
            attr = self.get_port_attr(port)
            port_src_mac = src_mac or attr["src_mac"]
            port_dst_mac = dst_mac or attr["dest"]
            if port_dst_mac == "unconfigured":
                raise ValueError(f"port {port} does not have a configured destination MAC")

            packet = self._build_l2_packet(
                src_mac=port_src_mac,
                dst_mac=port_dst_mac,
                vlan=vlan,
                eth_type=eth_type,
                frame_size=frame_size,
            )
            streams.append((port, self._build_stream(packet, pps=pps, count=count)))

        return self._start_streams(
            requested,
            streams,
            duration=duration,
            count=count,
            clear_existing=clear_existing,
            clear_stats_first=clear_stats,
            wait=wait,
        )

    def send_l3_traffic(
        self,
        ports: int | Sequence[int],
        *,
        src_ip: str | None = None,
        dst_ip: str | None = None,
        src_mac: str | None = None,
        dst_mac: str | None = None,
        vlan: int | Sequence[int] | None = None,
        protocol: str = "udp",
        l4_src_port: int = 1025,
        l4_dst_port: int = 12,
        frame_size: int = 64,
        pps: int | float = 1000,
        count: int | None = None,
        duration: float | None = 10.0,
        force_acquire: bool = False,
        clear_existing: bool = True,
        clear_stats: bool = True,
        wait: bool = True,
    ) -> TrexTrafficResult:
        self.ensure_connected()
        requested = self.acquire_ports(ports, force=force_acquire)

        streams = []
        for port in requested:
            attr = self.get_port_attr(port)
            port_src_mac = src_mac or attr["src_mac"]
            port_src_ip = src_ip or attr["src_ipv4"]
            port_dst_ip = dst_ip or attr["dest"]
            port_dst_mac = dst_mac or attr["arp"]

            if port_src_ip in ("-", None):
                raise ValueError(f"port {port} does not have a source IPv4 configured")
            if port_dst_ip in ("unconfigured", "-", None):
                raise ValueError(f"port {port} does not have a destination IPv4 configured")
            if port_dst_mac in ("unresolved", "unconfigured", "-", None):
                raise ValueError(f"port {port} does not have a resolved destination MAC")

            packet = self._build_l3_packet(
                src_mac=port_src_mac,
                dst_mac=port_dst_mac,
                src_ip=port_src_ip,
                dst_ip=port_dst_ip,
                vlan=vlan,
                protocol=protocol,
                l4_src_port=l4_src_port,
                l4_dst_port=l4_dst_port,
                frame_size=frame_size,
            )
            streams.append((port, self._build_stream(packet, pps=pps, count=count)))

        return self._start_streams(
            requested,
            streams,
            duration=duration,
            count=count,
            clear_existing=clear_existing,
            clear_stats_first=clear_stats,
            wait=wait,
        )

    def _build_l2_packet(
        self,
        *,
        src_mac: str,
        dst_mac: str,
        vlan: int | Sequence[int] | None,
        eth_type: int,
        frame_size: int,
    ) -> Any:
        imports = _load_trex_imports()
        packet = imports["Ether"](src=src_mac, dst=dst_mac)
        packet = self._embed_vlan(packet, vlan, eth_type=eth_type)
        packet /= imports["Raw"](b"x" * max(0, frame_size - len(packet)))
        return packet

    def _build_l3_packet(
        self,
        *,
        src_mac: str,
        dst_mac: str,
        src_ip: str,
        dst_ip: str,
        vlan: int | Sequence[int] | None,
        protocol: str,
        l4_src_port: int,
        l4_dst_port: int,
        frame_size: int,
    ) -> Any:
        imports = _load_trex_imports()
        packet = imports["Ether"](src=src_mac, dst=dst_mac)
        packet = self._embed_vlan(packet, vlan, eth_type=0x0800)
        packet /= imports["IP"](src=src_ip, dst=dst_ip)

        protocol_name = protocol.lower()
        if protocol_name == "udp":
            packet /= imports["UDP"](sport=l4_src_port, dport=l4_dst_port)
        elif protocol_name == "tcp":
            packet /= imports["TCP"](sport=l4_src_port, dport=l4_dst_port)
        else:
            raise ValueError("protocol must be either 'udp' or 'tcp'")

        packet /= imports["Raw"](b"x" * max(0, frame_size - len(packet)))
        return packet

    def _embed_vlan(self, packet: Any, vlan: int | Sequence[int] | None, *, eth_type: int) -> Any:
        imports = _load_trex_imports()
        tags = _normalize_vlan(vlan)
        if not tags:
            packet.type = eth_type
            return packet

        for index, tag in enumerate(tags):
            if index == len(tags) - 1:
                packet /= imports["Dot1Q"](vlan=tag, type=eth_type)
            else:
                packet /= imports["Dot1Q"](vlan=tag)
        return packet

    def _build_stream(self, packet: Any, *, pps: int | float, count: int | None) -> Any:
        imports = _load_trex_imports()
        if count is None:
            mode = imports["STLTXCont"](pps=pps)
        else:
            mode = imports["STLTXSingleBurst"](pps=pps, total_pkts=count)
        return imports["STLStream"](
            packet=imports["STLPktBuilder"](pkt=packet),
            mode=mode,
        )

    def _start_streams(
        self,
        ports: list[int],
        port_streams: list[tuple[int, Any]],
        *,
        duration: float | None,
        count: int | None,
        clear_existing: bool,
        clear_stats_first: bool,
        wait: bool,
    ) -> TrexTrafficResult:
        if clear_existing:
            self.clear_streams(ports)
        if clear_stats_first:
            self.clear_stats(ports)

        for port, stream in port_streams:
            self.client.add_streams(stream, ports=port)

        run_duration = -1 if duration is None else duration
        self.client.start(ports=ports, duration=run_duration)

        if wait and (duration is not None or count is not None):
            self.client.wait_on_traffic(ports=ports)

        stats = self.get_stats(ports=ports)
        return TrexTrafficResult(ports=ports, stats=stats, duration=duration, count=count)
