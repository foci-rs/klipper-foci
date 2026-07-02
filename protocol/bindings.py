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
        driver.diagnostics.active.handle_inductance_fit,
        "foci_inductance_fit",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_inductance_point,
        "foci_inductance_point",
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
        driver.diagnostics.active.handle_encoder_alignment,
        "foci_encoder_alignment",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_current_validation_axis,
        "foci_current_validation_axis",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_high_rate_capture_profile,
        "foci_high_rate_capture_profile",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_high_rate_capture_sample,
        "foci_high_rate_capture_sample",
        oid,
    )
    serial.register_response(
        driver.diagnostics.active.handle_high_rate_capture_run,
        "foci_high_rate_capture_run",
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
