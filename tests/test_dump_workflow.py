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
