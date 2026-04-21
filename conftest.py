"""Pytest configuration for klipper-foci tests.

Makes ``import foci`` and ``from tests.mocks import ...`` resolve
without an installed package. Also pre-registers the ``klipper_foci``
package so that the relative import in ``__init__.py`` works when pytest
imports it during Package.setup().
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).parent

# --- Ensure bare imports resolve from this directory -----------------------

if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --- Pre-register a synthetic package so relative imports work -------------
#
# pytest's Package.setup() calls importtestmodule(klipper-foci/__init__.py).
# That file does ``from .foci import FociDriver``, which needs __package__
# set to "klipper_foci" (using underscores — Python package names cannot
# contain hyphens).  We load foci directly and register the package, so
# the relative import resolves correctly.

_PKG_NAME = "klipper_foci"

if _PKG_NAME not in sys.modules:
    # Create a package object.
    pkg = types.ModuleType(_PKG_NAME)
    pkg.__path__ = [str(_ROOT)]
    pkg.__package__ = _PKG_NAME
    pkg.__spec__ = importlib.util.spec_from_file_location(
        _PKG_NAME,
        str(_ROOT / "__init__.py"),
        submodule_search_locations=[str(_ROOT)],
    )
    sys.modules[_PKG_NAME] = pkg

    # Load foci as a submodule of the package.
    _tmc_name = _PKG_NAME + ".foci"
    if _tmc_name not in sys.modules:
        _tmc_spec = importlib.util.spec_from_file_location(
            _tmc_name, str(_ROOT / "foci.py")
        )
        _tmc_mod = importlib.util.module_from_spec(_tmc_spec)
        _tmc_mod.__package__ = _PKG_NAME
        sys.modules[_tmc_name] = _tmc_mod
        _tmc_spec.loader.exec_module(_tmc_mod)

    # Expose FociDriver on the package so ``from .foci import FociDriver``
    # inside __init__.py is satisfied by the already-loaded submodule.
    pkg.FociDriver = sys.modules[_tmc_name].FociDriver  # type: ignore[attr-defined]
    pkg.foci = sys.modules[_tmc_name]
