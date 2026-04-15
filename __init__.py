# FOCI - Field Oriented Control Interface
# Klipper extras module for TMC4671 FOC servo controllers.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later

try:
    from .tmc4671 import FociDriver
except ImportError:
    from tmc4671 import FociDriver  # type: ignore[no-redef]  # flat import for pytest


def load_config_prefix(config):
    return FociDriver(config)
