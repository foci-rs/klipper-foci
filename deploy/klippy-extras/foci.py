# foci-shim: klipper-foci (do not edit; managed by install.sh)
"""Klipper extras shim for a pip-installed klipper-foci.

Copy this file to <klipper>/klippy/extras/foci.py. Mainline Klipper's
loader only ever scans klippy/extras/ (never klippy/plugins/ -- that
directory is Kalico-specific), so this file must land here rather than
in deploy/klippy-plugins/ on a mainline-Klipper host. It calls
load_config/load_config_prefix, which this module re-exports from the
installed klipper_foci package -- all actual logic stays in the
pip-installed wheel, not in this file.
"""

from klipper_foci.klipper import load_config, load_config_prefix

__all__ = ["load_config", "load_config_prefix"]
