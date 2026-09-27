"""Entry point: attach DiagnosticsActive/DiagnosticsPassive and return their specs."""

from __future__ import annotations

from klipper_foci.registry import GcodeCommandSpec

from .active import DiagnosticsActive
from .passive import DiagnosticsPassive


def register(driver) -> tuple[GcodeCommandSpec, ...]:
    driver.diagnostics_active = DiagnosticsActive(driver)
    driver.diagnostics_passive = DiagnosticsPassive(driver)
    return (
        GcodeCommandSpec(
            "FOCI_STEP_POSITION",
            "diagnostics_passive",
            "step_position",
            "Query raw FOCI MCU step position without syncing Klipper",
        ),
        GcodeCommandSpec(
            "FOCI_STEPPER_STATS",
            "diagnostics_passive",
            "stepper_stats",
            "Query FOCI MCU step queue/execution counters without motion",
        ),
        GcodeCommandSpec(
            "FOCI_STACK_WATERMARK",
            "diagnostics_passive",
            "stack_watermark",
            "Query unused FOCI MCU stack headroom since boot without motion",
        ),
        GcodeCommandSpec(
            "FOCI_CURRENT_STEP_TEST",
            "diagnostics_active",
            "current_step_test",
            "Run a bounded FOCI current-loop step diagnostic",
        ),
        GcodeCommandSpec(
            "FOCI_CURRENT_VECTOR_STEP_TEST",
            "diagnostics_active",
            "current_vector_step_test",
            "Run a bounded FOCI current-vector step diagnostic",
        ),
        GcodeCommandSpec(
            "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
            "diagnostics_active",
            "current_torque_sample_test",
            "Run a bounded FOCI torque pulse and sample it early",
        ),
        GcodeCommandSpec(
            "FOCI_POSITION_TORQUE_OFFSET_TEST",
            "diagnostics_active",
            "position_torque_offset_test",
            "Run a bounded FOCI position-mode torque-offset sample",
        ),
        GcodeCommandSpec(
            "FOCI_VOLTAGE_STEP_TEST",
            "diagnostics_active",
            "voltage_step_test",
            "Run a bounded FOCI open-loop voltage-vector diagnostic",
        ),
        GcodeCommandSpec(
            "FOCI_RESISTANCE_TEST",
            "diagnostics_active",
            "resistance_test",
            "Run the shared FOCI resistance-identification diagnostic",
        ),
    )
