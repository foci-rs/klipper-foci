"""MCU response registration helpers for klipper-foci."""

from __future__ import annotations


def register_dump_responses(serial, driver, oid: int) -> None:
    serial.register_response(driver.dump.handle_dump_value, "foci_dump_value", oid)
    serial.register_response(driver.dump.handle_dump_done, "foci_dump_done", oid)


def register_homing_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.homing.handle_calibrate_response,
        "foci_calibrate_result",
        oid,
    )


def register_commissioning_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.commissioning.handle_commission_phase,
        "foci_commission_phase",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_result,
        "foci_commission_result",
        oid,
    )
    serial.register_response(
        driver.autotune.handle_tune_result,
        "foci_tune_result",
        oid,
    )
    serial.register_response(
        driver.commissioning.handle_commission_detail,
        "foci_commission_detail",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_run,
        "foci_inductance_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_frame,
        "foci_inductance_frame",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_estimate,
        "foci_inductance_estimate",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_filters,
        "foci_current_loop_filters",
        oid,
    )


def register_selftest_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.selftest.handle_selftest_result,
        "foci_selftest_result",
        oid,
    )
    serial.register_response(
        driver.selftest.handle_selftest_done,
        "foci_selftest_done",
        oid,
    )


def register_active_diagnostic_responses(serial, driver, oid: int) -> None:
    serial.register_response(
        driver.diagnostics.handle_current_step_result,
        "foci_current_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_vector_step_result,
        "foci_current_vector_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_result,
        "foci_current_torque_sample_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_current_torque_sample_detail_result,
        "foci_current_torque_sample_detail_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_voltage_step_result,
        "foci_voltage_step_result",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_profile,
        "foci_resistance_profile",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_run,
        "foci_resistance_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_resistance_axis,
        "foci_resistance_axis",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_run,
        "foci_current_loop_run",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_loop_hold,
        "foci_current_loop_hold",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_closed_loop_entry,
        "foci_closed_loop_entry",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_encoder_alignment,
        "foci_encoder_alignment",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_adc_residual,
        "foci_adc_residual",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_axis,
        "foci_current_validation_axis",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_settled_sample,
        "foci_current_validation_settled_sample",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_envelope,
        "foci_current_validation_envelope",
        oid,
    )
    serial.register_response(
        driver.diagnostics.handle_stepper_event,
        "foci_stepper_event",
    )
    serial.register_response(
        driver.diagnostics.handle_stepper_perf_event,
        "foci_stepper_perf_event",
    )
