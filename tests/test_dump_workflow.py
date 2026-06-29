"""Tests for DUMP_FOCI/DUMP_TMC register dump workflow."""

from __future__ import annotations

from klipper_foci.registers import REGISTERS
from tests.mocks import (
    MockGCmd,
    SAMPLE_ACTIVE_GAINS,
    make_config_driver,
    make_config_printer,
    make_driver,
)


DEFAULT_DUMP_VALUES = {
    REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 26,
    REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 26,
    REGISTERS["PID_VELOCITY_P_VELOCITY_I"]: (1152 << 16) | 0,
    REGISTERS["PID_POSITION_P_POSITION_I"]: (640 << 16) | 0,
    REGISTERS["PID_VELOCITY_LIMIT"]: 500000,
}


class DumpOnlyProtocol:
    """Protocol fake that permits only the existing dump request."""

    def __init__(self, driver, dump_values):
        self.driver = driver
        self.dump_values = dump_values
        self.calls = []

    def dump_registers(self):
        self.calls.append("dump_registers")
        for addr, value in self.dump_values.items():
            self.driver.dump.handle_dump_value({"addr": addr, "value": value})
        self.driver.dump.handle_dump_done({})

    def __getattr__(self, name):
        raise AssertionError("unexpected protocol call: %s" % name)


def _install_dump_response(driver, values=None):
    dump_values = DEFAULT_DUMP_VALUES.copy()
    if values is not None:
        dump_values.update(values)
    protocol = DumpOnlyProtocol(driver, dump_values)
    driver.protocol = protocol
    return protocol


def _seed_tuning_state(driver):
    driver.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
    driver.state.runtime_status = "tuned_conservative"

    driver.config.autotune_status = "tuned_conservative"
    driver.config.autotune_profile = "conservative"
    driver.config.autotune_mode = "outer"

    driver.config.pid_flux_p = 256
    driver.config.pid_flux_i = 26
    driver.config.pid_torque_p = 256
    driver.config.pid_torque_i = 26
    driver.config.pid_velocity_p = 1152
    driver.config.pid_velocity_i = 0
    driver.config.pid_position_p = 640
    driver.config.pid_position_i = 0
    driver.config.pid_velocity_limit = 500000

    driver.config.commissioned_velocity_p = 1152
    driver.config.commissioned_velocity_i = 0
    driver.config.commissioned_position_p = 640
    driver.config.commissioned_position_i = 0
    driver.config.commissioned_velocity_limit = 500000

    driver.config.identified_r_count_milli = 3002
    driver.config.identified_l_count_micro = 4046
    driver.config.identified_r_int = 3002
    driver.config.identified_l_int = 4046
    driver.config.identified_lambda_us = 0
    driver.config.identified_tau_e_us = 1348
    driver.config.identified_tau_e_crosscheck_us = 3739
    driver.config.identified_tau_residual_permille = 1000
    driver.config.identified_theta_e_us = 160
    driver.config.identified_ringing_count = 7
    driver.config.identified_bandwidth_hz = 0
    driver.config.identified_inner_warning_flags = 36

    driver.config.identified_current_gains_source = 1
    driver.config.identified_current_candidate_gains_source = 1
    driver.config.identified_axis_split_source = 1
    driver.config.identified_current_candidate_axis_split_source = 1
    driver.config.identified_current_gains_tier = 2
    driver.config.identified_current_candidate_gains_tier = 2
    driver.config.identified_current_measured_axis_split_permille = 1840
    driver.config.identified_current_candidate_measured_axis_split_permille = 1840
    driver.config.identified_current_applied_axis_split_permille = 1500
    driver.config.identified_current_candidate_applied_axis_split_permille = 1500
    driver.config.identified_current_axis_split_clamped = 1
    driver.config.identified_current_candidate_axis_split_clamped = 1
    driver.config.identified_current_candidate_flux_p = 711
    driver.config.identified_current_candidate_flux_i = 26
    driver.config.identified_current_candidate_torque_p = 650
    driver.config.identified_current_candidate_torque_i = 21
    driver.config.identified_current_candidate_attempt = 1
    driver.config.identified_current_validation_axes = 3
    driver.config.identified_current_flux_validation_sample_count = 3
    driver.config.identified_current_torque_validation_sample_count = 2
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0
    driver.config.identified_current_flux_response_min_permille = 710
    driver.config.identified_current_torque_response_min_permille = 590
    driver.config.identified_current_flux_encoder_delta_counts = 0
    driver.config.identified_current_torque_encoder_delta_counts = 4

    driver.config.identified_r_profile_version = 1
    driver.config.identified_r_count_slope_milli = 1042
    driver.config.identified_r_gain_path_count_slope_milli = 66752
    driver.config.identified_r_axis0_count_slope_milli = 1038
    driver.config.identified_r_axis1_count_slope_milli = 1046
    driver.config.identified_r_axis0_intercept_count = 24
    driver.config.identified_r_axis1_intercept_count = 27
    driver.config.identified_r_axis0_rmse_permille = 8
    driver.config.identified_r_axis1_rmse_permille = 9
    driver.config.identified_r_selected_mask_axis0 = 0b11111000
    driver.config.identified_r_selected_mask_axis1 = 0b11110000
    driver.config.identified_r_axis0_signed_count_slope_milli = 1041
    driver.config.identified_r_axis1_signed_count_slope_milli = 1047
    driver.config.identified_r_axis0_signed_asymmetry_permille = 12
    driver.config.identified_r_axis1_signed_asymmetry_permille = 15
    driver.config.identified_r_axis0_drift_permille = 5
    driver.config.identified_r_axis1_drift_permille = 6
    driver.config.identified_r_status_flags_or = 524288
    driver.config.identified_r_warning_flags = 0


def _run_dump(driver, params=None, values=None):
    protocol = _install_dump_response(driver, values)
    gcmd = MockGCmd(params or {})

    driver.dump.dump_registers(gcmd)

    return gcmd.last_info, protocol.calls


def _configured_driver():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    return make_config_driver(printer, sections, "foci stepper_x")


def _registered_handler(driver, command_name):
    gcode = driver.printer.lookup_object("gcode")
    return next(
        args[3] for args, _kwargs in gcode._mux_commands if args[0] == command_name
    )


def test_default_dump_omits_tuning_section_and_sends_one_dump_request():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, calls = _run_dump(driver)

    assert calls == ["dump_registers"]
    assert "========== PID Gains ==========" in output
    assert "========== Tuning Analysis ==========" not in output


def test_tuning_flag_appends_context_and_count_space_note():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, calls = _run_dump(driver, {"TUNING": "1"})

    assert calls == ["dump_registers"]
    assert "========== Tuning Analysis ==========" in output
    assert "autotune_status" in output
    assert "tuned_conservative" in output
    assert "runtime_status" in output
    assert "active_gains_present" in output
    assert "live.flux_p" in output
    assert "active.flux_p" in output
    assert "config.identified_lambda_us" in output
    assert "config.identified_ringing_count" in output
    assert "count-space commissioning values" in output


def test_tuning_flag_appends_resistance_identification_evidence():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Resistance identification evidence --" in output
    assert "config.identified_r_count_slope_milli" in output
    assert "1042" in output
    assert "config.identified_r_gain_path_count_slope_milli" in output
    assert "66752" in output
    assert "config.identified_r_axis0_count_slope_milli" in output
    assert "config.identified_r_axis1_drift_permille" in output
    assert "config.identified_r_status_flags_or" in output
    assert "host performs no" in output


def test_tuning_flag_appends_current_loop_evidence():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Current-loop commissioning evidence --" in output
    assert "current_gains_source: measured" in output
    assert "axis_split_source: impedance" in output
    assert "current_gains_tier: measured_split" in output
    assert "current_validation: flux=pass torque=pass" in output
    assert "config.identified_current_gains_source" in output
    assert "config.identified_axis_split_source" in output
    assert "config.identified_current_measured_axis_split_permille" in output
    assert "1840" in output
    assert "config.identified_current_torque_response_min_permille" in output
    assert "590" in output
    assert "config.identified_current_torque_encoder_delta_counts" in output
    assert "firmware-reported current-loop" in output
    assert "identified_current_* and identified_axis_split_source" in output


def test_tuning_flag_names_failed_current_loop_evidence():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_current_gains_source = 0
    driver.config.identified_axis_split_source = 0
    driver.config.identified_current_gains_tier = 0
    driver.config.identified_current_validation_axes = 0
    driver.config.identified_current_retry_budget_exhausted = 1
    driver.config.identified_current_failure_reason = 6

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "current_gains_source: failed" in output
    assert "axis_split_source: none" in output
    assert "current_gains_tier: none" in output
    assert "current_validation: flux=fail torque=fail" in output
    assert "retry_budget_exhausted: yes" in output
    assert "failure_reason: saturation" in output


def test_tuning_flag_appends_last_current_loop_run_evidence():
    driver = make_driver()
    driver.diagnostics.active.handle_current_loop_run(
        {
            "oid": driver.oid,
            "status": 9,
            "gains_source": 0,
            "candidate_gains_source": 1,
            "axis_split_source": 0,
            "candidate_axis_split_source": 0,
            "gains_tier": 0,
            "candidate_gains_tier": 1,
            "measured_axis_split_permille": 1000,
            "candidate_measured_axis_split_permille": 1000,
            "applied_axis_split_permille": 1000,
            "candidate_applied_axis_split_permille": 1000,
            "axis_split_clamped": 0,
            "candidate_axis_split_clamped": 0,
            "candidate_flux_p": 711,
            "candidate_flux_i": 26,
            "candidate_torque_p": 711,
            "candidate_torque_i": 26,
            "candidate_attempt": 1,
            "current_validation_axes": 0,
            "flux_validation_sample_count": 3,
            "torque_validation_sample_count": 0,
            "retry_budget_exhausted": 1,
            "failure_reason": 9,
        }
    )

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Last current-loop run (not persisted) --" in output
    assert "last.current_gains_source          = failed" in output
    assert "last.candidate_gains_source        = measured" in output
    assert "last.candidate_gains_tier          = measured_symmetric" in output
    assert "last.candidate_flux_p              = 711" in output
    assert "last.candidate_flux_i              = 26" in output
    assert "last.candidate_torque_p            = 711" in output
    assert "last.candidate_torque_i            = 26" in output
    assert "last.candidate_attempt             = 1" in output
    assert "last.current_validation            = flux=fail torque=not_run" in output
    assert "last.failure_reason                = retry_exhausted" in output


def test_tuning_flag_names_default_current_loop_evidence():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_current_gains_source = 2
    driver.config.identified_axis_split_source = 0
    driver.config.identified_current_gains_tier = 3
    driver.config.identified_current_validation_axes = 1
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "current_gains_source: default" in output
    assert "axis_split_source: none" in output
    assert "current_gains_tier: default" in output
    assert "current_validation: flux=pass torque=fail" in output
    assert "retry_budget_exhausted: no" in output
    assert "failure_reason: none" in output


def test_tuning_output_preserves_default_dump_prefix():
    driver = make_driver()
    _seed_tuning_state(driver)

    default_output, _calls = _run_dump(driver)
    tuning_output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert tuning_output.startswith(default_output + "\n")


def test_tuning_mismatch_warning_includes_live_and_host_values():
    driver = make_driver()
    _seed_tuning_state(driver)
    values = {
        REGISTERS["PID_FLUX_P_FLUX_I"]: (257 << 16) | 26,
    }

    output, _calls = _run_dump(driver, {"TUNING": "1"}, values)

    assert "WARNING: flux_p mismatch live=257 host=256" in output


def test_tuning_flags_persisted_and_validated_status_divergence():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.autotune_status = "commissioned"
    driver.state.runtime_status = "uncommissioned"
    driver.state.active_gains = None

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert (
        "WARNING: autotune_status/runtime_status divergence "
        "persisted=commissioned validated=uncommissioned"
    ) in output


def test_tuning_reports_absent_active_gains_without_field_spam():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.active_gains = None

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "active_gains unavailable; live/host comparison skipped" in output
    assert "WARNING: flux_p mismatch" not in output


def test_dump_tmc_alias_accepts_tuning_flag():
    driver = _configured_driver()
    _seed_tuning_state(driver)
    protocol = _install_dump_response(driver)
    handler = _registered_handler(driver, "DUMP_TMC")
    gcmd = MockGCmd({"TUNING": "1"})

    handler(gcmd)

    assert protocol.calls == ["dump_registers"]
    assert "========== Tuning Analysis ==========" in gcmd.last_info
