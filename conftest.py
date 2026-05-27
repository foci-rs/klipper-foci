"""Pytest configuration for klipper-foci tests.

Loads a synthetic ``klipper_foci`` package so tests can import package modules
without installing this Klipper extras module.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
_PKG_NAME = "klipper_foci"

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if _PKG_NAME not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        _PKG_NAME,
        str(_ROOT / "__init__.py"),
        submodule_search_locations=[str(_ROOT)],
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = _PKG_NAME
    sys.modules[_PKG_NAME] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    sys.modules.setdefault("__init__", module)
