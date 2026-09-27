"""Klipper plugin shim for a pip-installed klipper-foci.

Copy this file to <klipper>/klippy/plugins/foci.py. Klipper's extras
loader finds it there and calls load_config/load_config_prefix, which
this module re-exports from the installed klipper_foci package -- all
actual logic stays in the pip-installed wheel, not in this file.
"""

from klipper_foci.klipper import load_config, load_config_prefix

__all__ = ["load_config", "load_config_prefix"]
