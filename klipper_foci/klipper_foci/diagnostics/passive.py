"""Passive FOCI diagnostic commands and response handlers."""

from __future__ import annotations

import logging

from ..report import report_detail
from .formatting import format_stepper_event

log = logging.getLogger(__name__)


class PassiveDiagnostics:
    """Own read-only FOCI diagnostic commands and events."""

    def __init__(self, driver) -> None:
        self.driver = driver

    def handle_stepper_event(self, params: dict) -> None:
        """Handle bounded firmware stepper diagnostics: per-step noise, klippy.log
        only, gated behind [foci] debug -- see report.report_detail."""
        message = format_stepper_event(self.driver.stepper_name, params)
        report_detail(log, self.driver.global_config.debug, message)
