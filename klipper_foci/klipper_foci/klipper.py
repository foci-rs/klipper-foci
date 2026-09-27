"""Re-export point for Klipper's extras loader shim.

Klipper's extras loader only scans klippy/extras/ and klippy/plugins/ on
disk via pkgutil.iter_modules() -- it has no awareness of installed
site-packages or entry points. This module exists so a thin shim file
placed in klippy/plugins/ can import from the pip-installed package by a
stable path, without duplicating load_config/load_config_prefix's logic.
"""

from __future__ import annotations

from . import load_config, load_config_prefix

__all__ = ["load_config", "load_config_prefix"]
