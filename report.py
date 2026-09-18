"""Shared console/log reporting: a short operator summary on the console,
full developer detail to klippy.log only, gated behind [foci] debug."""

from __future__ import annotations

import logging


def report_summary(gcode, message: str) -> None:
    """Operator-facing line: console + Klipper's normal log echo. Always on."""
    gcode.respond_info(message)


def report_detail(logger: logging.Logger, debug_enabled: bool, message: str) -> None:
    """Developer-facing line: klippy.log only, opt-in. Never reaches console.

    Klipper's root logger defaults to INFO and is only raised to DEBUG by
    klippy's own -v/--verbose launch flag (a global setting this module does
    not control), so logger.debug() plus level filtering would be silently
    dropped under a normal deployment regardless of [foci] debug. Check the
    flag explicitly and log at INFO instead.
    """
    if debug_enabled:
        logger.info(message)


def humanize(name: str) -> str:
    """Turn an enum-symbol-style name into a plain phrase: "a_b" -> "a b"."""
    return name.replace("_", " ")
