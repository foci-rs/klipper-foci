# FOCI - Field Oriented Control Interface
# Klipper extras module for TMC4671 FOC servo controllers.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later

from .driver import FociDriver
from .registry import FociGlobalConfig


def load_config(config):
    return FociGlobalConfig(config)


def load_config_prefix(config):
    return FociDriver(config)
