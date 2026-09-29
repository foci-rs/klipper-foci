"""Pytest configuration for klipper-foci-diagnostics tests."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CORE_WORKSPACE = Path(__file__).parent.parent.parent / "klipper_foci"
_CORE_TESTS = _CORE_WORKSPACE / "tests"

if str(_CORE_TESTS) not in sys.path:
    sys.path.insert(0, str(_CORE_TESTS))

_core_conftest_spec = importlib.util.spec_from_file_location(
    "_klipper_foci_core_conftest", str(_CORE_WORKSPACE / "conftest.py")
)
_core_conftest = importlib.util.module_from_spec(_core_conftest_spec)
assert _core_conftest_spec.loader is not None
_core_conftest_spec.loader.exec_module(_core_conftest)
