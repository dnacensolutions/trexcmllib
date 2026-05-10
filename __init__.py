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
"""

from .console import SessionError, TrexConsoleBatchResult, TrexConsoleConfig, TrexConsoleLauncher
from .stl import TrexCmlLib, configure_trex_python_path

__all__ = [
    "SessionError",
    "TrexConsoleBatchResult",
    "TrexCmlLib",
    "TrexConsoleConfig",
    "TrexConsoleLauncher",
    "configure_trex_python_path",
]
