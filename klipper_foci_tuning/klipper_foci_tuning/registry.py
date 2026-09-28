"""Entry point: attach TuningWorkflow and return its GcodeCommandSpecs."""

from __future__ import annotations

from klipper_foci.registry import GcodeCommandSpec

from .workflow import TuningWorkflow


def register(driver) -> tuple[GcodeCommandSpec, ...]:
    driver.tuning = TuningWorkflow(driver)
    return (
        GcodeCommandSpec(
            "FOCI_SET_ACCEL_FEEDFORWARD",
            "tuning",
            "set_accel_feedforward",
            "Set FOCI acceleration/deceleration feedforward runtime gains for bringup debugging",
        ),
        GcodeCommandSpec(
            "FOCI_SET_POSITION_LEAD",
            "tuning",
            "set_position_lead",
            "Set FOCI diagnostic position-target lead for bringup debugging",
        ),
        GcodeCommandSpec(
            "FOCI_SET_PHASE_ADVANCE",
            "tuning",
            "set_phase_advance",
            "Set FOCI diagnostic commutation phase advance for bringup debugging",
        ),
    )
