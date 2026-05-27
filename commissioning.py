"""Commissioning workflow for FOCI host commands."""

from __future__ import annotations


class CommissioningWorkflow:
    """Run Stage 1 commissioning and own commissioning state transitions."""

    def __init__(self, driver) -> None:
        self.driver = driver

    def handle_chip_reset_detected(self) -> None:
        """Clear calibration after firmware reports chip reset without inhibiting."""
        self.driver.state.is_calibrated = False
        self.driver.state.inhibited = False
        self.driver.homing.set_auto_calibrate_on_enable_allowed(True)

    def maybe_clear_calibration_for_chip_reset(self, status: int) -> None:
        """Apply chip-reset recovery for CommissionError status 18."""
        if status == 18:
            self.handle_chip_reset_detected()
