# trexcmllib

`trexcmllib` is a small Python library for working with Cisco TRex nodes in CML-style labs.

It has two complementary layers:

- `TrexConsoleLauncher`: open a remote TRex node through a CML terminal server, start the TRex server if needed, and run console CLI batches reliably.
- `TrexCmlLib`: a thin wrapper around the bundled TRex STL Python client for simple port, traffic, stats, and ping workflows.

This library was built to solve practical lab tasks:

- bootstrap a TRex console from a CML host
- acquire or observe TRex ports
- configure L2 or L3 port state
- send simple L2 or L3 traffic
- read counters and summarize pass/fail results
- package sample scripts so other tools can reuse them

## Status

This is currently a repo-local library under [scripts/trexcmllib](/Users/pawansi/workspace/trex-core/scripts/trexcmllib). It now includes package metadata in [pyproject.toml](/Users/pawansi/workspace/trex-core/scripts/trexcmllib/pyproject.toml) and example console-script entrypoints.

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
  README.md
  examples/
    __init__.py
    common.py
    open_console.py
    run_l2_traffic.py
    run_l2_bidirectional.py
```

## Main API

### `TrexConsoleConfig`

Configuration for connecting to a TRex node through a CML terminal server.

Useful fields:

- `jump_host`
- `user`
- `lab_name`
- `node_name`
- `node_port`
- `password` or `password_env`
- `readonly`
- `force_acquire`

No real connection target is embedded in the library. Callers are expected to provide the host, user, lab, node, and credentials explicitly.

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

## Example Scripts

These examples can be run as modules when `scripts/` is on `PYTHONPATH`, or directly from the repo checkout.

### Open Console

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.open_console \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name>
```

### Unidirectional L2 Traffic

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_traffic \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --packets 10
```

### Bidirectional L2 Traffic

```bash
TREXCMLLIB_PASSWORD='<ssh-password>' python3 -m trexcmllib.examples.run_l2_bidirectional \
  --cml-host <cml-host> \
  --user <ssh-user> \
  --lab-name <lab-name> \
  --node-name <node-name> \
  --packets 10
```

### Installed Console Scripts

If the package is installed, the same examples are exposed as console scripts:

```bash
trexcmllib-open-console
trexcmllib-l2-traffic
trexcmllib-l2-bidirectional
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

## Recommended Next Steps Before Publishing

- add automated tests for output parsing and batch success detection
- add CI for `py_compile`, packaging, and example `--help` smoke tests
- decide whether the top-level repo scripts should remain wrappers or move entirely under the package
- document the supported TRex server images and required node-side tools more formally
