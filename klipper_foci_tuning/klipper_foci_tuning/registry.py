"""Entry point: attach TuningWorkflow and return its GcodeCommandSpecs."""

from __future__ import annotations

from klipper_foci.registry import GcodeCommandSpec

from .workflow import TuningWorkflow


def register(driver) -> tuple[GcodeCommandSpec, ...]:
    driver.tuning = TuningWorkflow(driver)
    return (
        GcodeCommandSpec(
            "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
            "tuning",
            "set_velocity_transient_feedforward",
            "Set FOCI diagnostic velocity transient feedforward for bringup debugging",
        ),
        GcodeCommandSpec(
            "FOCI_SET_ACCEL_FEEDFORWARD",
            "tuning",
            "set_accel_feedforward",
            "Set FOCI acceleration/deceleration feedforward runtime gains for bringup debugging",
        ),
        GcodeCommandSpec(
            "FOCI_SET_DECOUPLING_FEEDFORWARD",
            "tuning",
            "set_decoupling_feedforward",
            "Set FOCI diagnostic q/d decoupling proxy feedforward for bringup debugging",
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
        GcodeCommandSpec(
            "FOCI_SET_VOLTAGE_LIMIT",
            "tuning",
            "set_voltage_limit",
            "Set FOCI PIDOUT_UQ_UD_LIMITS for bringup authority diagnostics",
        ),
    )
