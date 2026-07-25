"""Tests for DUMP_FOCI/DUMP_TMC register dump workflow."""

from __future__ import annotations

import pytest

from klipper_foci.registers import REGISTERS
from tests.mocks import (
    CommandError,
    MockGCmd,
    SAMPLE_ACTIVE_GAINS,
    make_config_driver,
    make_config_printer,
    make_driver,
)


DEFAULT_DUMP_VALUES = {
    REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
    REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
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


class TimeoutDumpProtocol:
    """Protocol fake that never reports dump completion."""

    def __init__(self):
        self.calls = []

    def dump_registers(self):
        self.calls.append("dump_registers")

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
    driver.config.pid_flux_i = 416
    driver.config.pid_torque_p = 256
    driver.config.pid_torque_i = 416
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
    driver.config.identified_lambda_us = 0
    driver.config.identified_tau_e_us = 1348
    driver.config.identified_theta_e_us = 160
    driver.config.identified_ringing_count = 7
    driver.config.identified_bandwidth_hz = 0
    driver.config.identified_inner_warning_flags = 36

    driver.config.identified_l_source = 1
    driver.config.identified_l_warning_flags = 0
    driver.config.identified_l_frequency_millihz = 1_000_000
    driver.config.identified_l_reactance_count_ratio_milli = 8600
    driver.config.identified_l_d_reactance_count_ratio_milli = 9200
    driver.config.identified_l_q_reactance_count_ratio_milli = 8000
    driver.config.identified_l_saliency_status = 1
    driver.config.identified_l_saliency_permille = 140
    driver.config.identified_l_iq_mean_milli_count = -84000
    driver.config.identified_l_drift_permille = 40
    driver.config.identified_l_r_shift_minus_permille = 4
    driver.config.identified_l_r_shift_plus_permille = 4
    driver.config.identified_l_x_mag_vs_quad_permille = 20

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
    driver.config.identified_current_candidate_flux_i = 416
    driver.config.identified_current_candidate_torque_p = 650
    driver.config.identified_current_candidate_torque_i = 336
    driver.config.identified_current_candidate_attempt = 1
    driver.config.identified_current_validation_axes = 3
    driver.config.identified_current_flux_validation_sample_count = 4
    driver.config.identified_current_torque_validation_sample_count = 2
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0
    driver.config.identified_current_flux_response_min_permille = 710
    driver.config.identified_current_torque_response_min_permille = 590
    driver.config.identified_current_flux_encoder_delta_counts = 0
    driver.config.identified_current_torque_encoder_delta_counts = 4

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
    driver.config.identified_r_peak_abs_current_count = 1200
    driver.config.identified_r_max_abs_steady_mean_current_count = 900
    driver.config.identified_r_current_ceiling_count = 1600


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


def test_dump_reports_live_adc_vm_raw():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.adc_vm_offset_raw = 33662
    driver.mcu.constants.update(
        {
            "FOCI_VM_DIVIDER_HIGH_OHMS": 71500,
            "FOCI_VM_DIVIDER_LOW_OHMS": 1500,
            "FOCI_VM_ADC_REFERENCE_MILLIVOLTS": 2500,
            "FOCI_VM_ADC_CENTER_COUNTS": 32767,
        }
    )

    assert "ADC_VM_RAW" in REGISTERS
    output, calls = _run_dump(driver, values={REGISTERS["ADC_VM_RAW"]: 43389})

    assert calls == ["dump_registers"]
    assert "========== Voltage / Brake ==========" in output
    assert "ADC_VM_RAW" in output
    assert "adc_vm_raw=43389(~36.12V)" in output


def test_dump_keeps_adc_vm_raw_when_model_constants_are_absent():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.adc_vm_offset_raw = 33662

    output, calls = _run_dump(driver, values={REGISTERS["ADC_VM_RAW"]: 43389})

    assert calls == ["dump_registers"]
    assert "adc_vm_raw=43389" in output
    assert "~36" not in output


def test_dump_requires_runtime_adc_vm_offset_for_voltage_decode():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.mcu.constants.update(
        {
            "FOCI_VM_DIVIDER_HIGH_OHMS": 71500,
            "FOCI_VM_DIVIDER_LOW_OHMS": 1500,
            "FOCI_VM_ADC_REFERENCE_MILLIVOLTS": 2500,
            "FOCI_VM_ADC_CENTER_COUNTS": 32767,
        }
    )

    output, calls = _run_dump(driver, values={REGISTERS["ADC_VM_RAW"]: 43389})

    assert calls == ["dump_registers"]
    assert "adc_vm_raw=43389" in output
    assert "~36" not in output


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
    assert "control-model count-space fields" in output


def test_tuning_flag_appends_autotune_readiness_report():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.is_calibrated = True
    driver.state.runtime_status = "commissioned"
    driver.config.identified_bandwidth_hz = 1600
    driver.config.identified_inner_warning_flags = 0
    driver.config.identified_l_source = 1
    driver.config.identified_l_reactance_count_ratio_milli = 8600
    driver.config.identified_l_saliency_status = 1
    driver.config.identified_r_count_slope_milli = 1042

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Autotune readiness --" in output
    assert "FOCI foci manual_stepper stepper_x autotune readiness:" in output
    assert "result: ready" in output
    assert "stage2_policy: normal" in output
    assert "blockers: none" in output
    assert "warnings: none" in output
    trusted_inputs_line = next(
        line for line in output.splitlines() if "trusted_inputs:" in line
    )
    assert "current_loop_gains" in trusted_inputs_line
    assert "current_bandwidth" in trusted_inputs_line
    assert "unavailable_inputs: none" in output


def test_tuning_readiness_blocks_live_current_gain_mismatch():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_bandwidth_hz = 1600
    values = {
        REGISTERS["PID_FLUX_P_FLUX_I"]: (257 << 16) | 416,
    }

    output, _calls = _run_dump(driver, {"TUNING": "1"}, values)

    assert "-- Autotune readiness --" in output
    assert "result: blocked" in output
    assert "stage2_policy: unavailable" in output
    assert "warnings: inner confidence:" in output
    assert "unavailable_inputs: none" in output
    assert "live current-loop gain flux_p mismatch live=257 host=256" in output


def test_tuning_readiness_reports_unavailable_inputs_line():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.is_calibrated = True
    driver.state.runtime_status = "commissioned"
    driver.config.identified_l_source = 0
    driver.config.identified_l_reactance_count_ratio_milli = None

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "result: ready_with_warnings" in output
    assert "blockers: none" in output
    assert "warnings: inner confidence:" in output
    assert "unavailable_inputs: average_inductance" in output


def test_read_live_current_gains_returns_missing_fields_as_none():
    driver = make_driver()
    _seed_tuning_state(driver)
    protocol = DumpOnlyProtocol(
        driver,
        {
            REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
        },
    )
    driver.protocol = protocol

    live_gains = driver.dump.read_live_current_gains()

    assert protocol.calls == ["dump_registers"]
    assert live_gains == {
        "flux_p": 256,
        "flux_i": 416,
        "torque_p": None,
        "torque_i": None,
    }


def test_read_live_current_gains_reports_dump_timeout():
    driver = make_driver()
    _seed_tuning_state(driver)
    protocol = TimeoutDumpProtocol()
    driver.protocol = protocol

    with pytest.raises(CommandError, match="live current-loop gain readback timed out"):
        driver.dump.read_live_current_gains()

    assert protocol.calls == ["dump_registers"]


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
    assert "config.identified_r_peak_abs_current_count" in output
    assert "config.identified_r_max_abs_steady_mean_current_count" in output
    assert "config.identified_r_current_ceiling_count" in output
    assert "host performs no" in output


def test_tuning_flag_separates_persisted_and_last_inductance_evidence():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.diagnostics.active.handle_inductance_run(
        {
            "oid": driver.oid,
            "source": 1,
            "status": 0,
            "warning_flags": 2,
            "ud_count": 768,
            "realized_frequency_millihz": 1_000_000,
            "elapsed_us": 8000,
            "openloop_phi_delta_counts": 524_288,
            "sample_count": 104,
            "encoder_delta_counts": 0,
            "status_flags_or": 0,
        }
    )
    driver.diagnostics.active.handle_inductance_frame(
        {
            "oid": driver.oid,
            "id_mean_milli_count": 20000,
            "iq_mean_milli_count": -85000,
            "id_rms_milli_count": 5000,
            "iq_rms_milli_count": 21000,
            "drift_permille": 55,
            "zero_id_mean_milli_count": 100,
            "zero_iq_mean_milli_count": -200,
        }
    )
    driver.diagnostics.active.handle_inductance_estimate(
        {
            "oid": driver.oid,
            "x_average_count_ratio_milli": 8700,
            "x_d_count_ratio_milli": 9300,
            "x_q_count_ratio_milli": 8100,
            "saliency_status": 1,
            "saliency_permille": 138,
            "x_mag_nominal_count_ratio_milli": 8870,
            "x_mag_shift_minus_permille": 5,
            "x_mag_shift_plus_permille": 5,
            "x_mag_vs_quad_permille": 21,
        }
    )

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Persisted inductance evidence --" in output
    assert "config.identified_l_reactance_count_ratio_milli" in output
    assert "8600" in output
    assert "config.identified_l_d_reactance_count_ratio_milli" in output
    assert "config.identified_l_q_reactance_count_ratio_milli" in output
    assert "persisted identified_l_* inductance fields" in output
    assert "-- Last inductance evidence (not persisted) --" in output
    assert "last.inductance_run.source" in output
    assert "last.inductance_run.warning_flags" in output
    assert "last.inductance_frame.iq_mean_milli_count" in output
    assert "-85000" in output
    assert "last.inductance_estimate.x_average_count_ratio_milli" in output
    assert "8700" in output


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


def test_tuning_flag_names_physical_current_gain_tier():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_current_gains_source = 1
    driver.config.identified_axis_split_source = 0
    driver.config.identified_current_gains_tier = 4
    driver.config.identified_current_validation_axes = 3
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "current_gains_source: measured" in output
    assert "axis_split_source: none" in output
    assert "current_gains_tier: physical_symmetric" in output
    assert "current_validation: flux=pass torque=pass" in output
    assert "retry_budget_exhausted: no" in output
    assert "failure_reason: none" in output


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
            "candidate_flux_i": 416,
            "candidate_torque_p": 711,
            "candidate_torque_i": 416,
            "candidate_attempt": 1,
            "current_validation_axes": 0,
            "flux_validation_sample_count": 4,
            "torque_validation_sample_count": 0,
            "retry_budget_exhausted": 1,
            "failure_reason": 9,
        }
    )
    driver.diagnostics.active.handle_current_loop_hold(
        {
            "oid": driver.oid,
            "hold_status": 1,
            "warning_flags": 0,
            "elapsed_us": 250000,
            "requested_sample_period_us": 1000,
            "sample_count": 250,
            "position_span_count": 1,
            "position_drift_count": 1,
            "torque_mean_count": 0,
            "torque_rms_count": 12,
            "torque_peak_to_peak_count": 34,
            "torque_crossing_count": 17,
            "flux_mean_count": 0,
            "flux_rms_count": 9,
            "flux_peak_to_peak_count": 21,
            "flux_crossing_count": 11,
            "status_flags_or": 0,
            "actionable_status_count": 0,
        }
    )
    driver.diagnostics.active.handle_closed_loop_entry(
        {
            "oid": driver.oid,
            "entry_status": 3,
            "position_1": -3,
            "position_2": 4,
            "drift_count": 7,
            "threshold_count": 2,
            "runaway": 0,
        }
    )

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Last current-loop run (not persisted) --" in output
    assert "last.current_gains_source          = failed" in output
    assert "last.candidate_gains_source        = measured" in output
    assert "last.candidate_gains_tier          = measured_symmetric" in output
    assert "last.candidate_flux_p              = 711" in output
    assert "last.candidate_flux_i              = 416" in output
    assert "last.candidate_torque_p            = 711" in output
    assert "last.candidate_torque_i            = 416" in output
    assert "last.candidate_attempt             = 1" in output
    assert "last.current_validation            = flux=fail torque=not_run" in output
    assert "last.failure_reason                = retry_exhausted" in output
    assert "-- Last closed-loop entry (not persisted) --" in output
    assert "last.entry_status                = fail_drift" in output
    assert "last.entry_position              = pos1=-3 pos2=4" in output
    assert "last.entry_drift                 = drift=7 threshold=2" in output
    assert "last.entry_runaway               = no" in output
    assert "-- Last sustained-hold gate (not persisted) --" in output
    assert "last.hold_status                 = pass" in output
    assert (
        "last.hold_samples                = 250 @ 1000 us, elapsed_us=250000" in output
    )
    assert "last.hold_position               = span=1 drift=1" in output
    assert (
        "last.hold_torque                 = mean=0 rms=12 span=34 crossings=17"
        in output
    )
    assert (
        "last.hold_flux                   = mean=0 rms=9 span=21 crossings=11" in output
    )
    assert (
        "last.hold_status_flags           = or=0 actionable_count=0 warnings=0"
        in output
    )


def test_tuning_flag_names_bounded_closed_loop_entry_drift():
    driver = make_driver()
    driver.diagnostics.active.handle_closed_loop_entry(
        {
            "oid": driver.oid,
            "entry_status": 4,
            "position_1": 0,
            "position_2": 17,
            "drift_count": 17,
            "threshold_count": 2,
            "runaway": 0,
        }
    )

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Last closed-loop entry (not persisted) --" in output
    assert "last.entry_status                = warn_drift" in output
    assert "last.entry_drift                 = drift=17 threshold=2" in output


def test_tuning_flag_appends_last_encoder_alignment_evidence():
    driver = make_driver()
    driver.diagnostics.active.handle_encoder_alignment(
        {
            "oid": driver.oid,
            "encoder_count": 163,
            "electrical_residual_counts": 3,
            "stability_counts": 1,
            "movement_counts": 37,
            "min_movement_counts": 2,
            "counts_per_electrical_rev": 80,
        }
    )

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "-- Last encoder alignment (not persisted) --" in output
    assert "last.encoder_alignment_count       = 163" in output
    assert "last.encoder_alignment_residual    = 3/80 counts" in output
    assert "last.encoder_alignment_stability   = 1 counts" in output


def test_tuning_flag_labels_last_current_validation_gate_samples():
    driver = make_driver()
    for sample in (
        # axis, sample_index, delay_ms, positive, negative, cross, voltage,
        # encoder_abs, encoder_positive, encoder_negative
        (0, 0, 2, 910, 900, 140, 420, 0, 0, 0),
        (0, 3, 100, 1010, 1005, 44, 410, 0, 0, 0),
        (1, 0, 0, 620, 610, 52, 500, 0, 0, 0),
        (1, 2, 2, 780, 760, 180, 530, 6, 6, -4),
    ):
        (
            axis,
            sample_index,
            delay_ms,
            positive,
            negative,
            cross,
            voltage,
            encoder,
            positive_encoder,
            negative_encoder,
        ) = sample
        driver.diagnostics.active.handle_current_validation_axis(
            {
                "oid": driver.oid,
                "axis": axis,
                "sample_index": sample_index,
                "status": 0,
                "attempt": 0,
                "target": 250,
                "sample_delay_ms": delay_ms,
                "positive_response_permille": positive,
                "negative_response_permille": negative,
                "cross_axis_permille": cross,
                "cross_axis_peak_permille": cross + 1,
                "voltage_output_permille": voltage,
                "encoder_delta_counts": encoder,
                "positive_encoder_delta_counts": positive_encoder,
                "negative_encoder_delta_counts": negative_encoder,
                "status_flags_or": 0,
            }
        )
    driver.diagnostics.active.handle_current_loop_run(
        {
            "oid": driver.oid,
            "status": 0,
            "gains_source": 1,
            "candidate_gains_source": 1,
            "axis_split_source": 0,
            "candidate_axis_split_source": 0,
            "gains_tier": 1,
            "candidate_gains_tier": 1,
            "measured_axis_split_permille": 1000,
            "candidate_measured_axis_split_permille": 1000,
            "applied_axis_split_permille": 1000,
            "candidate_applied_axis_split_permille": 1000,
            "axis_split_clamped": 0,
            "candidate_axis_split_clamped": 0,
            "candidate_flux_p": 711,
            "candidate_flux_i": 2448,
            "candidate_torque_p": 711,
            "candidate_torque_i": 2448,
            "candidate_attempt": 0,
            "current_validation_axes": 3,
            "flux_validation_sample_count": 4,
            "torque_validation_sample_count": 3,
            "retry_budget_exhausted": 0,
            "failure_reason": 0,
        }
    )

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "last.current_validation_sample[flux:0] = role=telemetry" in output
    assert "last.current_validation_sample[flux:3] = role=gate" in output
    assert "cross=44 cross_peak=45" in output
    assert "last.current_validation_sample[torque:0] = role=gate" in output
    assert "last.current_validation_sample[torque:2] = role=telemetry" in output
    assert "signed_encoder_delta=6/-4" in output


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
        REGISTERS["PID_FLUX_P_FLUX_I"]: (257 << 16) | 416,
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
