"""Reusable helpers for bootstrapping CML TRex consoles and driving TRex STL.

Dependency summary:
- Console workflows use only the Python standard library locally.
- Console workflows also require local ``ssh`` access to a CML terminal server.
- The remote TRex node is expected to provide ``tmux``, ``python3``, a TRex
  installation under ``/trex`` or an equivalent path layout, and the
  ``trex_console`` Python module that ships with TRex.
- ``TrexCmlLib`` depends on the TRex STL client bits from a ``trex-core``
  checkout. If the package is installed outside that checkout, set
  ``TREX_CORE_SCRIPTS_DIR`` to the ``trex-core/scripts`` directory.
- On macOS, direct STL imports may still fail because the bundled TRex client
  dependencies include Linux-oriented payloads such as ``pyzmq-ctypes``.
  In that case prefer console-batch automation through ``TrexConsoleLauncher``.
- ASTF/stateful helpers in ``TrexAstfConsoleRunner`` also use the console-batch
  path and require the remote TRex server to be started in ASTF mode.
- ``TrexTraffic`` provides a single high-level API over the console launcher for
  the bundled L2, L3, ping, and ASTF workflows used by the example scripts.
"""

from .astf import TrexAstfConsoleRunner, TrexAstfProfileRunResult, parse_astf_numeric_stats
from .console import SessionError, TrexConsoleBatchResult, TrexConsoleConfig, TrexConsoleLauncher
from .stl import TrexCmlLib, configure_trex_python_path
from .traffic import PingProbe, TrexTraffic, TrexTrafficResult, loss_count, loss_percent, parse_probe

__all__ = [
    "PingProbe",
    "SessionError",
    "TrexAstfConsoleRunner",
    "TrexAstfProfileRunResult",
    "TrexConsoleBatchResult",
    "TrexCmlLib",
    "TrexConsoleConfig",
    "TrexConsoleLauncher",
    "TrexTraffic",
    "TrexTrafficResult",
    "configure_trex_python_path",
    "loss_count",
    "parse_astf_numeric_stats",
    "parse_probe",
    "loss_percent",
]
