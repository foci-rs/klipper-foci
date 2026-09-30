"""Tests for DUMP_FOCI/DUMP_TMC register dump workflow."""

from __future__ import annotations

import re

from klipper_foci.registers import REGISTERS
from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    MockGCmd,
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


DEFAULT_STALL_RESULT = {
    "latched": 1,
    "peak_error_units": 1234,
    "trigger_tick": 7,
    "clamp_active": 0,
}


class DumpOnlyProtocol:
    """Protocol fake that permits only the existing dump request."""

    def __init__(self, driver, dump_values, stall_result=None):
        self.driver = driver
        self.dump_values = dump_values
        self.stall_result = stall_result or DEFAULT_STALL_RESULT
        self.calls = []

    def dump_registers(self):
        self.calls.append("dump_registers")
        for addr, value in self.dump_values.items():
            self.driver.dump.handle_dump_value({"addr": addr, "value": value})
        self.driver.dump.handle_dump_done({})

    def query_stall(self):
        return self.stall_result

    def __getattr__(self, name):
        raise AssertionError(f"unexpected protocol call: {name}")


def _install_dump_response(driver, values=None, stall_result=None):
    dump_values = DEFAULT_DUMP_VALUES.copy()
    if values is not None:
        dump_values.update(values)
    protocol = DumpOnlyProtocol(driver, dump_values, stall_result)
    driver.protocol = protocol
    return protocol


def _seed_tuning_state(driver):
    driver.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
    driver.state.runtime_status = "tuned"

    driver.config.autotune_status = "tuned"
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
    driver.config.identified_lambda_us = 0
    driver.config.identified_tau_e_us = 1348
    driver.config.identified_theta_e_us = 160
    driver.config.identified_theta_source = 1
    driver.config.identified_bandwidth_hz = 0
    driver.config.identified_inner_warning_flags = 36

    driver.config.identified_l_source = 1
    driver.config.identified_l_reactance_count_ratio_milli = 8600
    driver.config.identified_l_saliency_status = 1

    driver.config.identified_current_gains_source = 1
    driver.config.identified_current_gains_tier = 2
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0

    driver.config.identified_r_count_slope_milli = 1042


def kv(text, key):
    """Value of the first `key: value` line in text, with alignment padding stripped."""
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            return line[len(key) + 1 :].strip()
    raise AssertionError(f"no {key!r} line in output")


def section(output, title):
    return output.split(f"---------- {title} ----------")[1].split("----------")[0]


def table_row(output, gain):
    return next(line for line in output.splitlines() if re.match(rf"{gain}\s", line))


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
    return next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == command_name)


def test_dump_foci_works_with_no_diagnostics_package_installed(monkeypatch):
    monkeypatch.setattr("klipper_foci.registry.entry_points", lambda *, group: [])
    driver = _configured_driver()
    _seed_tuning_state(driver)
    protocol = _install_dump_response(driver)
    handler = _registered_handler(driver, "DUMP_FOCI")
    gcmd = MockGCmd({})

    handler(gcmd)

    assert protocol.calls == ["dump_registers"]
    assert gcmd.last_info is not None


def test_default_dump_omits_tuning_section_and_sends_one_dump_request():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, calls = _run_dump(driver)

    assert calls == ["dump_registers"]
    assert "---------- PID Gains ----------" in output
    assert "========== Tuning Analysis ==========" not in output


def test_dump_shows_homing_state_under_firmware_state_as_key_values():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(driver)

    firmware = output.split("Firmware state (not chip registers)")[1]
    assert (
        "homing: clamp_active=0 last_stall(latched=1 peak_error_units=1234 trigger_tick=7)"
        in firmware
    )


def test_dump_reports_position_error_as_target_minus_actual():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(
        driver,
        values={
            REGISTERS["PID_POSITION_TARGET"]: 0xFFFFE000,
            REGISTERS["PID_POSITION_ACTUAL"]: 0xFFFFE010,
        },
    )

    assert "position_actual=-8176 (error=-16)" in output


def test_dump_register_values_start_in_one_column():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(driver, values=dict.fromkeys(REGISTERS.values(), 0))

    columns = {
        re.search(r"[0-9a-f]{8}", line).start()
        for line in output.splitlines()
        if re.match(r"[A-Z][A-Z0-9_]*:", line)
    }
    assert len(columns) == 1
    assert sum(1 for line in output.splitlines() if re.match(r"[A-Z][A-Z0-9_]*:", line)) > 30


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
    assert "---------- Voltage / Brake ----------" in output
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


def test_dump_reports_velocity_ff_clamp_latch_and_count():
    driver = make_driver()
    _seed_tuning_state(driver)

    assert "VELOCITY_FF_CLAMP_LATCHED" in REGISTERS
    assert "VELOCITY_FF_CLAMP_COUNT" in REGISTERS

    output, calls = _run_dump(
        driver,
        values={
            REGISTERS["VELOCITY_FF_CLAMP_LATCHED"]: 1,
            REGISTERS["VELOCITY_FF_CLAMP_COUNT"]: 42,
        },
    )

    assert calls == ["dump_registers"]
    assert "---------- Firmware state (not chip registers) ----------" in output
    assert "velocity_ff_clamp: latched=1 count=42" in output
    assert "Velocity Feedforward Clamp" not in output
    assert "VELOCITY_FF_CLAMP_LATCHED" not in output


def test_tuning_flag_appends_banner_verdict_and_status():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, calls = _run_dump(driver, {"TUNING": "1"})

    assert calls == ["dump_registers"]
    assert "tuning analysis" in output
    verdict = kv(output, "verdict")
    assert "tuned (persisted) / tuned (runtime)" in verdict
    assert "live registers match host active gains" in verdict
    status = section(output, "Autotune status")
    assert kv(status, "autotune_status") == "tuned"
    assert kv(status, "runtime_status") == "tuned"
    assert kv(status, "active_gains_present") == "yes"
    assert kv(status, "autotune_profile") == "conservative"
    assert kv(status, "autotune_mode") == "outer"


def test_tuning_key_value_lines_always_separate_key_from_value():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    for title in (
        "Autotune status",
        "Readiness",
        "Identified model (count-space, not physical units)",
    ):
        for line in section(output, title).strip().splitlines():
            assert re.match(r"[a-z_]+:\s+\S", line), line


def test_tuning_analysis_sections_come_in_order():
    d = make_driver()
    d.state.active_gains = SAMPLE_ACTIVE_GAINS
    text = "\n".join(d.dump._format_tuning_analysis())
    titles = (
        "Autotune status",
        "Readiness",
        "Gains",
        "Identified model (count-space, not physical units)",
        "Velocity tune provenance",
        "Position tune provenance",
    )
    indexes = [text.index(f"---------- {title} ----------") for title in titles]
    assert indexes == sorted(indexes)


def test_tuning_gains_table_shows_live_config_and_active_once():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.pid_velocity_p = 700

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    gains = section(output, "Gains")
    assert re.fullmatch(r"flux_p\s+256 \(1\.000\)\s+256\s+256", table_row(gains, "flux_p"))
    assert re.fullmatch(r"flux_i\s+416 \(0\.1016\)\s+416\s+416", table_row(gains, "flux_i"))
    assert re.fullmatch(
        r"velocity_p\s+1152 \(4\.500\)\s+700\s+1152", table_row(gains, "velocity_p")
    )
    assert re.fullmatch(
        r"velocity_limit\s+500000\s+500000\s+500000", table_row(gains, "velocity_limit")
    )
    assert "commissioned" not in output
    assert "live.flux_p" not in output
    assert kv(gains, "filters_hz") == "velocity=0 torque=0 position=200 flux=0"


def test_tuning_gains_table_marks_absent_active_gains():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.active_gains = None

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert re.fullmatch(
        r"flux_p\s+256 \(1\.000\)\s+256\s+-", table_row(section(output, "Gains"), "flux_p")
    )
    assert "filters_hz" not in output
    assert "host active gains unavailable" in kv(output, "verdict")


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

    readiness = section(output, "Readiness")
    assert "FOCI foci" not in output
    assert kv(readiness, "result") == "ready"
    assert kv(readiness, "installed_tuning_policy") == "normal"
    assert kv(readiness, "blockers") == "none"
    assert kv(readiness, "warnings") == "none"
    assert "current_loop_gains" in kv(readiness, "trusted_inputs")
    assert "current_bandwidth" in kv(readiness, "trusted_inputs")
    assert kv(readiness, "unavailable_inputs") == "none"
    assert "ready" in kv(output, "verdict")


def test_tuning_readiness_blocks_live_current_gain_mismatch():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_bandwidth_hz = 1600
    values = {
        REGISTERS["PID_FLUX_P_FLUX_I"]: (257 << 16) | 416,
    }

    output, _calls = _run_dump(driver, {"TUNING": "1"}, values)

    readiness = section(output, "Readiness")
    assert kv(readiness, "result") == "blocked"
    assert kv(readiness, "installed_tuning_policy") == "unavailable"
    assert kv(readiness, "warnings").startswith("inner confidence:")
    assert kv(readiness, "unavailable_inputs") == "none"
    assert "live current-loop gain flux_p mismatch live=257 host=256" in output


def test_tuning_readiness_reports_unavailable_inputs_line():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.state.is_calibrated = True
    driver.state.runtime_status = "commissioned"
    driver.config.identified_l_source = 0
    driver.config.identified_l_reactance_count_ratio_milli = None

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    readiness = section(output, "Readiness")
    assert kv(readiness, "result") == "ready_with_warnings"
    assert kv(readiness, "blockers") == "none"
    assert kv(readiness, "warnings").startswith("inner confidence:")
    assert kv(readiness, "unavailable_inputs") == "average_inductance"


def test_tuning_flag_reports_identified_model_in_count_space():
    driver = make_driver()
    _seed_tuning_state(driver)

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    model = section(output, "Identified model (count-space, not physical units)")
    assert kv(model, "resistance") == "r_count_milli=3002 r_count_slope_milli=1042"
    assert kv(model, "electrical") == (
        "lambda_us=0 tau_e_us=1348 (1.35 ms) theta_e_us=160 theta_source=1"
    )
    assert kv(model, "bandwidth_hz") == "0"
    assert kv(model, "inner_warning_flags") == "36"
    assert kv(model, "inductance") == (
        "l_source=1 l_reactance_count_ratio_milli=8600 l_saliency_status=1"
    )


def test_tuning_flag_appends_velocity_tune_provenance():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.autotune_probed_velocity_mrev_s = 5366
    driver.config.autotune_d_eq_q = 1234
    driver.config.autotune_confidence_q = 5000
    driver.config.autotune_band_lower_percent = 70
    driver.config.autotune_band_upper_percent = 80
    driver.config.autotune_band_position_q = 3000

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    line = section(output, "Velocity tune provenance").strip()
    assert line == (
        "probed_velocity_mrev_s=5366 (5.366 rev/s) band=70..80% d_eq_q=1234 "
        "confidence_q=5000 band_position_q=3000"
    )


def test_tuning_flag_appends_position_tune_provenance():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.autotune_position_bound_units = 409
    driver.config.autotune_position_homing_peak_units = 300
    driver.config.autotune_position_motion_cruise_units = 210

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    line = section(output, "Position tune provenance").strip()
    assert line == "bound=409u (0.250mm) homing_peak=300u (0.183mm) motion_cruise=210u (0.128mm)"


def test_tuning_flag_reports_position_tune_not_run_when_unset():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.autotune_position_bound_units = None
    driver.config.autotune_position_homing_peak_units = None
    driver.config.autotune_position_motion_cruise_units = None

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert section(output, "Position tune provenance").strip().startswith("not run")


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

    assert "l_reactance_count_ratio_milli=8600" in output
    assert "---------- Last inductance evidence (not persisted) ----------" in output
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

    model = section(output, "Identified model (count-space, not physical units)")
    assert kv(model, "current_loop") == (
        "gains_source=measured(1) gains_tier=measured_split(2) "
        "retry_budget_exhausted=no failure_reason=none(0)"
    )


def test_tuning_flag_names_failed_current_loop_evidence():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_current_gains_source = 0
    driver.config.identified_current_gains_tier = 0
    driver.config.identified_current_retry_budget_exhausted = 1
    driver.config.identified_current_failure_reason = 6

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "gains_source=failed(0)" in output
    assert "gains_tier=none(0)" in output
    assert "retry_budget_exhausted=yes" in output
    assert "failure_reason=saturation(6)" in output


def test_tuning_flag_names_physical_current_gain_tier():
    driver = make_driver()
    _seed_tuning_state(driver)
    driver.config.identified_current_gains_source = 1
    driver.config.identified_current_gains_tier = 4
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "gains_source=measured(1)" in output
    assert "gains_tier=physical_symmetric(4)" in output
    assert "retry_budget_exhausted=no" in output
    assert "failure_reason=none(0)" in output


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
    driver.diagnostics.active.handle_closed_loop_activation(
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

    assert "---------- Last current-loop run (not persisted) ----------" in output
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
    assert "---------- Last closed-loop entry (not persisted) ----------" in output
    assert "last.entry_status                = fail_drift" in output
    assert "last.entry_position              = pos1=-3 pos2=4" in output
    assert "last.entry_drift                 = drift=7 threshold=2" in output
    assert "last.entry_runaway               = no" in output
    assert "---------- Last sustained-hold gate (not persisted) ----------" in output
    assert "last.hold_status                 = pass" in output
    assert "last.hold_samples                = 250 @ 1000 us, elapsed_us=250000" in output
    assert "last.hold_position               = span=1 drift=1" in output
    assert "last.hold_torque                 = mean=0 rms=12 span=34 crossings=17" in output
    assert "last.hold_flux                   = mean=0 rms=9 span=21 crossings=11" in output
    assert "last.hold_status_flags           = or=0 actionable_count=0 warnings=0" in output


def test_tuning_flag_names_bounded_closed_loop_activation_drift():
    driver = make_driver()
    driver.diagnostics.active.handle_closed_loop_activation(
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

    assert "---------- Last closed-loop entry (not persisted) ----------" in output
    assert "last.entry_status                = warn_drift" in output
    assert "last.entry_drift                 = drift=17 threshold=2" in output


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
    driver.config.identified_current_gains_tier = 3
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0

    output, _calls = _run_dump(driver, {"TUNING": "1"})

    assert "gains_source=default(2)" in output
    assert "gains_tier=default(3)" in output
    assert "retry_budget_exhausted=no" in output
    assert "failure_reason=none(0)" in output


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

    assert "host active gains unavailable" in kv(output, "verdict")
    assert "WARNING: flux_p mismatch" not in output


def test_dump_tmc_alias_accepts_tuning_flag():
    driver = _configured_driver()
    _seed_tuning_state(driver)
    protocol = _install_dump_response(driver)
    handler = _registered_handler(driver, "DUMP_TMC")
    gcmd = MockGCmd({"TUNING": "1"})

    handler(gcmd)

    assert protocol.calls == ["dump_registers"]
    assert "tuning analysis" in gcmd.last_info


def test_dump_reports_position_filter_enable():
    driver = make_driver()
    _seed_tuning_state(driver)
    assert REGISTERS["CONFIG_BIQUAD_X_ENABLE"] == 0x8A

    disabled, _calls = _run_dump(driver, values={REGISTERS["CONFIG_BIQUAD_X_ENABLE"]: 0})
    line = next(row for row in disabled.splitlines() if "CONFIG_BIQUAD_X_ENABLE" in row)
    assert "00000000" in line
    assert "biquad_x_enable=0" in line
    assert section(disabled, "Filters").count("CONFIG_BIQUAD_X_ENABLE") == 1

    enabled, _calls = _run_dump(driver, values={REGISTERS["CONFIG_BIQUAD_X_ENABLE"]: 1})
    assert "biquad_x_enable=1" in enabled
