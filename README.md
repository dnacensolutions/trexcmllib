# trexcmllib

`trexcmllib` is a small Python library for working with Cisco TRex nodes in CML-style labs.

It has two complementary layers:

- `TrexConsoleLauncher`: open a remote TRex node through a CML terminal server, start the TRex server if needed, and run console CLI batches reliably.
- `TrexCmlLib`: a thin wrapper around the bundled TRex STL Python client for simple port, traffic, stats, and ping workflows.
- `TrexAstfConsoleRunner`: a console-driven ASTF helper for stateful L3 and application traffic profiles.
- `TrexTraffic`: a single high-level class that wraps `TrexConsoleLauncher` and `TrexAstfConsoleRunner` and powers the bundled traffic examples.

This library was built to solve practical lab tasks:

- bootstrap a TRex console from a CML host
- acquire or observe TRex ports
- configure L2 or L3 port state
- send simple L2 or L3 traffic
- read counters and summarize pass/fail results
- report packet-loss counts and percentages in the bundled examples
- package sample scripts so other tools can reuse them

## Status

This repository is structured as an installable Python package and includes:

- package metadata in `pyproject.toml`
- example console-script entrypoints
- GitHub Actions workflows for linting and publishing

The package is designed for publishing to PyPI, but the runtime workflows still depend on external lab infrastructure such as a reachable CML host and a TRex node.

## Installation

Install from a local checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

Build local distributions:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
```

## Dependencies

### Python Package Dependencies

- The published package itself has no mandatory third-party PyPI dependencies for the console automation layer.
- The console layer uses the Python standard library plus a local `ssh` binary.
- The STL layer depends on the TRex client libraries that ship with a `trex-core` checkout.

### Local Machine Requirements

Required for console automation:

- Python 3.10+
- `ssh` in `PATH`
- network reachability to the CML terminal server
- credentials for the CML host

Required for direct STL API usage through `TrexCmlLib`:

- everything above, plus access to a `trex-core/scripts` directory
- if installed outside the repo, `TREX_CORE_SCRIPTS_DIR=/path/to/trex-core/scripts`

### Remote TRex Node Requirements

Required for `TrexConsoleLauncher` and the example scripts:

- `tmux`
- `python3`
- TRex installed and reachable using the expected repo-style layout under `/trex`
- the TRex interactive console modules on the node

Additional requirements for namespace-backed L3 workflows:

- `stack: linux_based` in `trex_cfg.yaml`
- full `iproute2`
- full `sysctl` implementation
- `ethtool`

### macOS Compatibility Note

`TrexCmlLib` may not work directly on macOS because some bundled TRex client dependencies are Linux-oriented, especially `pyzmq-ctypes`. In that case:

- use `TrexConsoleLauncher.run_console_batch(...)`
- or use the example scripts under `trexcmllib.examples`

## Package Layout

```text
trexcmllib/
  __init__.py
  console.py
  stl.py
  traffic.py
  README.md
  examples/
    __init__.py
    common.py
    open_console.py
    run_l2_traffic.py
    run_l2_bidirectional.py
    run_l3_traffic.py
    run_l3_bidirectional.py
    run_ping.py
    run_astf_http.py
    run_astf_udp.py
```

## Main API

### `TrexConsoleConfig`

Configuration for connecting to a TRex node through a CML terminal server.

Useful fields:

- `jump_host`
- `user`
- `lab_name`
- `node_name`
- `lab_id`
- `node_id`
- `node_port`
- `console_path`
- `password` or `password_env`
- `readonly`
- `force_acquire`

No real connection target is embedded in the library. Callers are expected to provide the host, user, lab, node, and credentials explicitly.

Console targeting rules:

- provide one lab selector: `lab_name` or `lab_id`
- provide one node selector: `node_name` or `node_id`
- if a name is provided, `trexcmllib` resolves the matching id through the CML API before opening the console
- or pass `console_path` directly if you already know the exact CML terminal path

### `TrexConsoleLauncher`

Primary console automation class.

Useful methods:

- `connect_and_bootstrap()`
- `run_shell_commands(commands)`
- `run_console_batch(commands, ports=[...])`

`run_console_batch` is the most reliable option for Mac-hosted automation in this repo because it drives the TRex console CLI on the node itself instead of depending on local TRex client binary compatibility.

### `TrexCmlLib`

Convenience STL wrapper for direct Python API usage.

Useful methods:

- `connect()`
- `acquire_ports()`
- `configure_port_attributes()`
- `configure_l2_port()`
- `configure_l3_port()`
- `resolve_ports()`
- `set_service_mode()`
- `send_l2_traffic()`
- `send_l3_traffic()`
- `ping()`
- `get_stats()`
- `clear_stats()`
- `stop_traffic()`

### `TrexAstfConsoleRunner`

Console-driven ASTF helper for advanced stateful traffic.

Useful methods:

- `run_profile()`
- `build_start_command()`
- `build_stats_command()`
- `build_stop_command()`
- `validate_metrics()`

### `TrexTraffic`

Unified console-driven traffic API for the bundled examples.

Useful methods:

- `run("l2", ...)`
- `run("l2_bidirectional", ...)`
- `run("l3", ...)`
- `run("l3_bidirectional", ...)`
- `run("ping", ...)`
- `run("astf_http", ...)`
- `run("astf_udp", ...)`

Each call returns a `TrexTrafficResult` with:

- `success`
- `summary`
- `metrics`
- `outputs`

The example scripts under `trexcmllib.examples` are now thin CLI wrappers over `TrexTraffic`.

Traffic run reset behavior:

- `TrexTraffic` defaults to a clean-start model for traffic runs
- before a traffic run starts, the remote TRex server is restarted into the requested mode so stale state from an aborted or unclean prior run does not leak into the next run
- this applies to the `TrexTraffic`-based L2, L3, ping, and ASTF example scripts
- `open_console` is different: it opens an interactive console without forcing that reset unless you implement that behavior yourself
- the example CLIs expose this as `--hard-reset` and `--no-hard-reset`

Important ASTF requirement:

- the remote TRex server must run in ASTF mode, for example `-i --astf`
- unlike STL, ASTF traffic normally depends on routed client/server profile IP ranges between TRex ports
- ASTF UDP examples report packet loss using `udps_sndpkt` versus `udps_rcvpkt`
- ASTF TCP examples report data-packet loss using `tcps_sndpack` versus `tcps_rcvpack`, plus retransmit and drop counters

## Example: Open a Console

```python
from trexcmllib import TrexConsoleConfig, TrexConsoleLauncher

launcher = TrexConsoleLauncher(
    TrexConsoleConfig(
        jump_host="<cml-host>",
        user="<ssh-user>",
        lab_name="<lab-name>",
        node_name="<node-name>",
        readonly=True,
    )
)

launcher.connect_and_bootstrap()
```

## Example: Run a Console Batch

```python
from trexcmllib import TrexConsoleConfig, TrexConsoleLauncher

launcher = TrexConsoleLauncher(
    TrexConsoleConfig(
        jump_host="<cml-host>",
        user="<ssh-user>",
        lab_name="<lab-name>",
        node_name="<node-name>",
        force_acquire=True,
        readonly=False,
    )
)

result = launcher.run_console_batch(
    [
        "service -p 0 1",
        "l2 -p 0 --dst 52:54:00:0d:24:82",
        "l2 -p 1 --dst 52:54:00:17:0f:5c",
        "service --off -p 0 1",
        "clear",
        "pkt -p 0 -s Ether(src='52:54:00:17:0f:5c',dst='52:54:00:0d:24:82')/IP()/UDP()/('x'*10)",
        "stats",
        "release -p 0 1",
    ],
    ports=[0, 1],
)

print(result.success)
print(result.output)
```

## Example: Run Traffic Through One API

```python
from trexcmllib import TrexConsoleConfig, TrexTraffic

traffic = TrexTraffic(
    TrexConsoleConfig(
        jump_host="<cml-host>",
        user="<ssh-user>",
        lab_name="<lab-name>",
        node_name="<node-name>",
        readonly=False,
        force_acquire=True,
    )
)

# Disable the default clean-start restart only if you explicitly want to reuse
# the current remote TRex server state.
# traffic = TrexTraffic(config, hard_reset=False)

result = traffic.run(
    "l2",
    packets=10,
    tx_port=0,
    rx_port=1,
)

print(result.success)
print(result.summary["packet_loss"])
print(result.outputs["traffic"])
```

## Example: Run Unidirectional L3 Traffic

```python
from trexcmllib import TrexConsoleConfig, TrexTraffic

traffic = TrexTraffic(
    TrexConsoleConfig(
        jump_host="<cml-host>",
        user="<ssh-user>",
        lab_name="<lab-name>",
        node_name="<node-name>",
        readonly=False,
        force_acquire=True,
    )
)

result = traffic.run(
    "l3",
    packets=10,
    tx_port=0,
    tx_src_ip="192.0.2.10",
    tx_next_hop="192.0.2.1",
    traffic_dst_ip="198.51.100.10",
)

print(result.success)
print(result.summary["resolved_nh_mac"])
print(result.summary["packets_sent"])
print(result.outputs["setup"])
print(result.outputs["traffic"])
```

## Example: Run Ping Validation

```python
from trexcmllib import PingProbe, TrexConsoleConfig, TrexTraffic

traffic = TrexTraffic(
    TrexConsoleConfig(
        jump_host="<cml-host>",
        user="<ssh-user>",
        lab_name="<lab-name>",
        node_name="<node-name>",
        readonly=False,
        force_acquire=True,
    )
)

result = traffic.run(
    "ping",
    count=3,
    pkt_size=64,
    probes=[
        PingProbe(
            port=0,
            src_ip="192.0.2.10",
            next_hop_ip="192.0.2.1",
            dst_ip="192.0.2.1",
        ),
    ],
)

print(result.success)
print(result.summary["probe_results"][0]["resolved_nh_mac"])
print(result.summary["probe_results"][0]["replies"])
print(result.outputs["port_0"])
```

## Example: Run Bidirectional L3 Traffic

```python
from trexcmllib import TrexConsoleConfig, TrexTraffic

traffic = TrexTraffic(
    TrexConsoleConfig(
        jump_host="<cml-host>",
        user="<ssh-user>",
        lab_name="<lab-name>",
        node_name="<node-name>",
        readonly=False,
        force_acquire=True,
    )
)

result = traffic.run(
    "l3_bidirectional",
    packets=10,
    port_a=0,
    port_b=1,
    port_a_src_ip="192.0.2.10",
    port_b_src_ip="192.0.2.20",
    port_a_next_hop_ip="192.0.2.1",
    port_b_next_hop_ip="192.0.2.2",
    traffic_a_dst_ip="198.51.100.10",
    traffic_b_dst_ip="198.51.100.20",
)

print(result.success)
print(result.summary["loss_a_to_b"])
print(result.summary["loss_b_to_a"])
print(result.outputs["setup"])
print(result.outputs["traffic"])
```

## Example Scripts

These examples can be run as modules when the parent directory of this repository is on `PYTHONPATH`, or by using the installed console scripts after `pip install`.

All example scripts support the same CML target selection model:

- one lab selector with `--lab-name` or `--lab-id`
- one node selector with `--node-name` or `--node-id`
- names are resolved to ids through the CML API before the console path is opened
- `--node-port` remains optional and defaults to `0`

For all examples below:

- you must provide `--cml-host` and `--user`
- you must provide one lab selector and one node selector
- you can provide the SSH secret either with `--password` or through the password environment variable

## Traffic Parameters

Current traffic customization support:

- `run_l2_traffic` and `run_l2_bidirectional`
  - packet mode: supported with `--packets`
  - stream mode: supported with `--rate` and `--duration`
  - stream frame size: supported with `--frame-size`
- `run_l3_traffic` and `run_l3_bidirectional`
  - packet mode: supported with `--packets`
  - stream mode: supported with `--rate` and `--duration`
  - packet and stream payload size: supported with `--payload-bytes`
- `run_ping`
  - ping count: supported with `--count`
  - packet size: supported with `--pkt-size`
- `run_astf_http` and `run_astf_udp`
  - duration: supported with `--duration`
  - traffic rate/load: supported with `--multiplier`

Stream rate format:

- stream mode accepts TRex rate strings such as `10kpps`, `100mbps`, or `5%`
- L2 and L3 stream mode uses sustained STL streams on the TRex node instead of repeated `pkt` injections

Clean-start behavior:

- the traffic example scripts use `TrexTraffic`, which restarts the remote TRex server before each run by default
- this is intentional so a previously aborted run does not leave stale ports, streams, or server mode behind
- interactive `open_console` usage does not force that restart by default
- use `--no-hard-reset` only when you explicitly want to reuse the current remote TRex server state

### Open Console

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.open_console \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name>
```

### Unidirectional L2 Traffic

Mandatory parameters:

- `--cml-host`
- `--user`
- one lab selector: `--lab-name` or `--lab-id`
- one node selector: `--node-name` or `--node-id`
- either `--packets`, or both `--rate` and `--duration`

Optional parameters:

- `--node-port`
- `--rate`
- `--duration`
- `--frame-size`
- `--tx-port`
- `--rx-port`
- `--tx-mac`
- `--rx-mac`
- `--password` or `--password-env`

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --packets 10
```

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-id <lab-id> \
  --node-id <node-id> \
  --rate 10kpps \
  --duration 10 \
  --frame-size 256
```

### Bidirectional L2 Traffic

Mandatory parameters:

- `--cml-host`
- `--user`
- one lab selector: `--lab-name` or `--lab-id`
- one node selector: `--node-name` or `--node-id`
- either `--packets`, or both `--rate` and `--duration`

Optional parameters:

- `--node-port`
- `--rate`
- `--duration`
- `--frame-size`
- `--port-a`
- `--port-b`
- `--port-a-mac`
- `--port-b-mac`
- `--password` or `--password-env`

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_bidirectional \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --packets 10
```

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_bidirectional \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-id <lab-id> \
  --node-id <node-id> \
  --rate 10kpps \
  --duration 10
```

### L3 Traffic

Mandatory parameters:

- `--cml-host`
- `--user`
- one lab selector: `--lab-name` or `--lab-id`
- one node selector: `--node-name` or `--node-id`
- `--tx-src-ip`
- `--tx-next-hop`
- either `--packets`, or both `--rate` and `--duration`

Optional parameters:

- `--node-port`
- `--rate`
- `--duration`
- `--tx-port`
- `--rx-port`
- `--rx-src-ip`
- `--rx-next-hop`
- `--traffic-src-ip`
- `--traffic-dst-ip`
- `--payload-bytes`
- `--udp-src-port`
- `--udp-dst-port`
- `--tx-mac`
- `--password` or `--password-env`

```bash
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
```

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_traffic \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-id <lab-id> \
  --node-id <node-id> \
  --tx-port 0 \
  --tx-src-ip 192.0.2.10 \
  --tx-next-hop 192.0.2.1 \
  --traffic-dst-ip 198.51.100.10 \
  --rate 10kpps \
  --duration 10
```

### Bidirectional L3 Traffic

Mandatory parameters:

- `--cml-host`
- `--user`
- one lab selector: `--lab-name` or `--lab-id`
- one node selector: `--node-name` or `--node-id`
- `--port-a-src-ip`
- `--port-b-src-ip`
- `--traffic-a-dst-ip`
- `--traffic-b-dst-ip`
- either `--packets`, or both `--rate` and `--duration`
- either both `--port-a-next-hop-ip` and `--port-b-next-hop-ip`
- or both `--port-a-next-hop-mac` and `--port-b-next-hop-mac`

Optional parameters:

- `--node-port`
- `--rate`
- `--duration`
- `--port-a`
- `--port-b`
- `--payload-bytes`
- `--udp-src-port`
- `--udp-dst-port`
- `--port-a-mac`
- `--port-b-mac`
- `--password` or `--password-env`

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_bidirectional \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --packets 10 \
  --port-a-src-ip 192.0.2.10 \
  --port-b-src-ip 192.0.2.20 \
  --port-a-next-hop-ip 192.0.2.1 \
  --port-b-next-hop-ip 192.0.2.2 \
  --traffic-a-dst-ip 198.51.100.10 \
  --traffic-b-dst-ip 198.51.100.20
```

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l3_bidirectional \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-id <lab-id> \
  --node-id <node-id> \
  --port-a-src-ip 192.0.2.10 \
  --port-b-src-ip 192.0.2.20 \
  --port-a-next-hop-ip 192.0.2.1 \
  --port-b-next-hop-ip 192.0.2.2 \
  --traffic-a-dst-ip 198.51.100.10 \
  --traffic-b-dst-ip 198.51.100.20 \
  --rate 10kpps \
  --duration 10
```

### Ping Validation

Mandatory parameters:

- `--cml-host`
- `--user`
- one lab selector: `--lab-name` or `--lab-id`
- one node selector: `--node-name` or `--node-id`
- at least one `--probe`

Optional parameters:

- `--node-port`
- `--count`
- `--pkt-size`
- `--show-raw-output`
- `--password` or `--password-env`

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --count 3 \
  --probe 0:192.0.2.10:192.0.2.1:192.0.2.1
```

The `--probe` format is:

```text
PORT:SRC_IP:NEXT_HOP_IP:DST_IP
```

Meaning:

- `PORT`: TRex port id
- `SRC_IP`: source IP configured on that TRex port
- `NEXT_HOP_IP`: gateway / next-hop TRex must ARP-resolve on that port
- `DST_IP`: final ICMP destination carried in the ping packet

Examples:

- ping the gateway itself:

```bash
--probe 0:192.0.2.10:192.0.2.1:192.0.2.1
```

- ping a remote host through the gateway:

```bash
--probe 0:192.0.2.10:192.0.2.1:198.51.100.10
```

Important:

- the third field is the next hop, not the final ping destination
- the `l3 -p ... --dst ...` command uses `NEXT_HOP_IP`
- the `ping -d ...` command uses `DST_IP`

Default behavior:

- prints per-port ping results
- on failure, prints only the TRex CLI commands that were run for that probe
- hides the full remote bootstrap and console log unless explicitly requested

To include the full raw remote output for debugging:

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --count 3 \
  --probe 0:192.0.2.10:192.0.2.1:192.0.2.1 \
  --show-raw-output
```

To validate both links, repeat `--probe`:

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_ping \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --count 3 \
  --probe 0:192.0.2.10:192.0.2.1:192.0.2.1 \
  --probe 1:198.51.100.10:198.51.100.1:198.51.100.1
```

### ASTF HTTP Application Traffic

Mandatory parameters:

- `--cml-host`
- `--user`
- either `--lab-name` and `--node-name`, or `--lab-id` and `--node-id`

Optional parameters:

- `--node-port`
- `--profile`
- `--profile-id`
- `--duration`
- `--multiplier`
- `--latency-pps`
- `--ipv6`
- `--password` or `--password-env`

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_astf_http \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --duration 10 \
  --multiplier 100
```

### ASTF UDP Stateful Traffic

Mandatory parameters:

- `--cml-host`
- `--user`
- either `--lab-name` and `--node-name`, or `--lab-id` and `--node-id`

Optional parameters:

- `--node-port`
- `--profile`
- `--profile-id`
- `--duration`
- `--multiplier`
- `--latency-pps`
- `--ipv6`
- `--password` or `--password-env`

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_astf_udp \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --duration 10 \
  --multiplier 100
```

### Installed Console Scripts

If the package is installed, the same examples are exposed as console scripts:

```bash
trexcmllib-open-console
trexcmllib-l2-traffic
trexcmllib-l2-bidirectional
trexcmllib-l3-traffic
trexcmllib-l3-bidirectional
trexcmllib-ping
trexcmllib-astf-http
trexcmllib-astf-udp
```

## Environment Notes

### Console Path

The console launcher expects access like:

```bash
ssh -tt <ssh-user>@<cml-host> "open /<lab-name>/<node-name>/<node-port>"
```

### Password Handling

Preferred:

```bash
export TREXCMLLIB_PASSWORD='your-password'
```

Or pass `password=` into `TrexConsoleConfig`.

### Local Host Compatibility

`TrexCmlLib` uses the bundled TRex STL client from this repo. On macOS, direct STL imports may fail because some bundled dependencies are Linux-oriented. In those cases:

- prefer `TrexConsoleLauncher.run_console_batch(...)`
- or use the example scripts under `trexcmllib/examples/`

If `trexcmllib` is installed outside the `trex-core` tree and you want to use `TrexCmlLib`, point it at the TRex repo scripts directory:

```bash
export TREX_CORE_SCRIPTS_DIR=/path/to/trex-core/scripts
```

### TRex Linux-Based Stack

Namespace-backed L3 workflows require:

- `stack: linux_based` in `trex_cfg.yaml`
- a host image with full `iproute2`
- a full `sysctl` implementation
- `ethtool`

If those are missing, L2 CLI traffic can still work while namespace/L3 automation fails.

For the `run_l3_traffic` example specifically:

- the transmit port next hop must answer ARP
- the chosen traffic destination must make sense for your topology
- if you provide an `--rx-port`, any receive-side counters depend on an actual return or forwarding path in the lab

For the `run_l3_bidirectional` example:

- you can use ARP mode with `--port-a-next-hop-ip` and `--port-b-next-hop-ip`
- or use explicit MAC mode with `--port-a-next-hop-mac` and `--port-b-next-hop-mac`
- explicit MAC mode is useful for loopback or lab validation when you want IP traffic counters without depending on ARP

For the `run_ping` example:

- each `--probe` is `PORT:SRC_IP:NEXT_HOP_IP:DST_IP`
- the third field is the gateway / next-hop TRex must resolve on that port
- the fourth field is the final ICMP destination
- the next hop must answer ARP on that specific TRex link
- the destination must answer ICMP through that same path
- if a TRex port is connected only to a local loop or an otherwise empty switch segment, ping validation will fail at L3 resolution because there is no real remote endpoint
- by default, failures show only the CLI commands that were executed; use `--show-raw-output` to print the full remote console session

For the ASTF examples:

- the remote TRex server must be started in ASTF mode, not STL mode
- the client and server IP ranges embedded in the ASTF profile must be routable between the participating TRex ports
- `run_astf_http.py` defaults to `astf/http_simple.py`
- `run_astf_udp.py` defaults to `astf/udp_pcap.py`
- these examples validate stateful counters such as `tcps_connects` or `udps_connects` and byte symmetry between client and server

## Publishing

This repository includes a GitHub Actions workflow for PyPI Trusted Publishing.

Recommended flow:

1. Create the project on PyPI and TestPyPI.
2. Configure Trusted Publishers on both indexes for this GitHub repository and workflow file.
3. Run the workflow manually to publish to TestPyPI.
4. Verify installation from TestPyPI.
5. Create a GitHub release to publish to PyPI.

Manual build and upload remains available if you prefer `twine`:

```bash
python -m pip install --upgrade build twine
python -m build
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*
```

## Recommended Next Steps

- add automated tests for output parsing and batch success detection
- add CI for `py_compile`, packaging, and example `--help` smoke tests
- decide whether the top-level repo scripts should remain wrappers or move entirely under the package
- document the supported TRex server images and required node-side tools more formally
