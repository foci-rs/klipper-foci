"""Tests for klipper-foci per-driver config parsing."""

from __future__ import annotations

from dataclasses import fields

import pytest

from klipper_foci.config import (
    CONTROL_SETTING_FIELDS,
    FociControlSettings,
    FociDriverConfig,
    RuntimeValidationResult,
    parse_driver_config,
    validate_runtime_config,
)

from tests.mocks import (
    CommandError,
    MockConfig,
    MockMCU,
    make_config_driver,
    make_config_printer,
)


CONFIG_FIELD_NAMES = {
    "name",
    "stepper_name",
    "run_current",
    "encoder_ppr",
    "voltage_limit",
    "encoder_reversed",
    "microsteps",
    "full_steps",
    "step_pin_name",
    "mcu",
    "channel",
    "pid_flux_p",
    "pid_flux_i",
    "pid_torque_p",
    "pid_torque_i",
    "velocity_filter_hz",
    "torque_filter_hz",
    "position_filter_hz",
    "flux_filter_hz",
    "pid_position_p",
    "pid_position_i",
    "pid_velocity_p",
    "pid_velocity_i",
    "velocity_feedforward",
    "velocity_feedforward_multiplier",
    "velocity_transient_feedforward",
    "velocity_transient_lead_time_us",
    "velocity_transient_gain",
    "velocity_transient_max_offset",
    "velocity_transient_rate_hz",
    "accel_feedforward",
    "accel_feedforward_accel_gain",
    "accel_feedforward_decel_gain",
    "decoupling_feedforward",
    "decoupling_r_int",
    "decoupling_l_int",
    "decoupling_pole_pairs",
    "decoupling_position_units_per_rev",
    "decoupling_f_pwm_hz",
    "decoupling_max_offset",
    "position_lead",
    "position_lead_gain",
    "position_lead_max_counts",
    "phase_advance",
    "phase_advance_gain_ppm",
    "phase_advance_max_counts",
    "phase_advance_deadband",
    "pid_velocity_limit",
    "commissioned_velocity_p",
    "commissioned_velocity_i",
    "commissioned_position_p",
    "commissioned_position_i",
    "commissioned_velocity_limit",
    "identified_r_int",
    "identified_l_int",
    "identified_r_count_milli",
    "identified_l_count_micro",
    "identified_lambda_us",
    "identified_theta_e_us",
    "identified_ringing_count",
    "identified_bandwidth_hz",
    "identified_tau_e_us",
    "identified_inner_warning_flags",
    "identified_l_source",
    "identified_l_warning_flags",
    "identified_l_frequency_millihz",
    "identified_l_reactance_count_ratio_milli",
    "identified_l_d_reactance_count_ratio_milli",
    "identified_l_q_reactance_count_ratio_milli",
    "identified_l_saliency_status",
    "identified_l_saliency_permille",
    "identified_l_iq_mean_milli_count",
    "identified_l_drift_permille",
    "identified_l_r_shift_minus_permille",
    "identified_l_r_shift_plus_permille",
    "identified_l_x_mag_vs_quad_permille",
    "identified_j_eff",
    "identified_b_eff",
    "identified_current_gains_source",
    "identified_current_candidate_gains_source",
    "identified_axis_split_source",
    "identified_current_candidate_axis_split_source",
    "identified_current_gains_tier",
    "identified_current_candidate_gains_tier",
    "identified_current_measured_axis_split_permille",
    "identified_current_candidate_measured_axis_split_permille",
    "identified_current_applied_axis_split_permille",
    "identified_current_candidate_applied_axis_split_permille",
    "identified_current_axis_split_clamped",
    "identified_current_candidate_axis_split_clamped",
    "identified_current_candidate_flux_p",
    "identified_current_candidate_flux_i",
    "identified_current_candidate_torque_p",
    "identified_current_candidate_torque_i",
    "identified_current_candidate_attempt",
    "identified_current_validation_axes",
    "identified_current_flux_validation_sample_count",
    "identified_current_torque_validation_sample_count",
    "identified_current_retry_budget_exhausted",
    "identified_current_failure_reason",
    "identified_current_flux_response_min_permille",
    "identified_current_torque_response_min_permille",
    "identified_current_flux_encoder_delta_counts",
    "identified_current_torque_encoder_delta_counts",
    "identified_r_count_slope_milli",
    "identified_r_gain_path_count_slope_milli",
    "identified_r_axis0_count_slope_milli",
    "identified_r_axis1_count_slope_milli",
    "identified_r_axis0_intercept_count",
    "identified_r_axis1_intercept_count",
    "identified_r_axis0_rmse_permille",
    "identified_r_axis1_rmse_permille",
    "identified_r_selected_mask_axis0",
    "identified_r_selected_mask_axis1",
    "identified_r_profile_version",
    "identified_r_axis0_signed_count_slope_milli",
    "identified_r_axis1_signed_count_slope_milli",
    "identified_r_axis0_signed_asymmetry_permille",
    "identified_r_axis1_signed_asymmetry_permille",
    "identified_r_axis0_drift_permille",
    "identified_r_axis1_drift_permille",
    "identified_r_status_flags_or",
    "identified_r_warning_flags",
    "autotune_profile",
    "autotune_mode",
    "autotune_status",
}


DRIVER_CONFIG_FACADE_FIELDS = {
    "name",
    "stepper_name",
    "mcu",
    "channel",
}


DISALLOWED_DRIVER_CONFIG_FACADE_FIELDS = (
    CONFIG_FIELD_NAMES - DRIVER_CONFIG_FACADE_FIELDS
)


EXPECTED_CONTROL_SETTING_FIELDS = (
    "run_current",
    "voltage_limit",
    "pid_flux_p",
    "pid_flux_i",
    "pid_torque_p",
    "pid_torque_i",
    "velocity_filter_hz",
    "torque_filter_hz",
    "position_filter_hz",
    "flux_filter_hz",
    "pid_position_p",
    "pid_position_i",
    "pid_velocity_p",
    "pid_velocity_i",
    "velocity_feedforward",
    "velocity_feedforward_multiplier",
    "velocity_transient_feedforward",
    "velocity_transient_lead_time_us",
    "velocity_transient_gain",
    "velocity_transient_max_offset",
    "velocity_transient_rate_hz",
    "accel_feedforward",
    "accel_feedforward_accel_gain",
    "accel_feedforward_decel_gain",
    "decoupling_feedforward",
    "decoupling_r_int",
    "decoupling_l_int",
    "decoupling_pole_pairs",
    "decoupling_position_units_per_rev",
    "decoupling_f_pwm_hz",
    "decoupling_max_offset",
    "position_lead",
    "position_lead_gain",
    "position_lead_max_counts",
    "phase_advance",
    "phase_advance_gain_ppm",
    "phase_advance_max_counts",
    "phase_advance_deadband",
    "pid_velocity_limit",
)


CURRENT_LOOP_FIELD_MAX_VALUES = {
    "identified_current_gains_source": 255,
    "identified_current_candidate_gains_source": 255,
    "identified_axis_split_source": 255,
    "identified_current_candidate_axis_split_source": 255,
    "identified_current_gains_tier": 255,
    "identified_current_candidate_gains_tier": 255,
    "identified_current_measured_axis_split_permille": 65535,
    "identified_current_candidate_measured_axis_split_permille": 65535,
    "identified_current_applied_axis_split_permille": 65535,
    "identified_current_candidate_applied_axis_split_permille": 65535,
    "identified_current_axis_split_clamped": 255,
    "identified_current_candidate_axis_split_clamped": 255,
    "identified_current_candidate_flux_p": 65535,
    "identified_current_candidate_flux_i": 65535,
    "identified_current_candidate_torque_p": 65535,
    "identified_current_candidate_torque_i": 65535,
    "identified_current_candidate_attempt": 255,
    "identified_current_validation_axes": 255,
    "identified_current_flux_validation_sample_count": 255,
    "identified_current_torque_validation_sample_count": 255,
    "identified_current_retry_budget_exhausted": 255,
    "identified_current_failure_reason": 255,
    "identified_current_flux_response_min_permille": 65535,
    "identified_current_torque_response_min_permille": 65535,
    "identified_current_flux_encoder_delta_counts": 65535,
    "identified_current_torque_encoder_delta_counts": 65535,
}


INDUCTANCE_FIELD_MAX_VALUES = {
    "identified_l_source": 255,
    "identified_l_warning_flags": 0xFFFF,
    "identified_l_frequency_millihz": None,
    "identified_l_reactance_count_ratio_milli": None,
    "identified_l_d_reactance_count_ratio_milli": None,
    "identified_l_q_reactance_count_ratio_milli": None,
    "identified_l_saliency_status": 255,
    "identified_l_saliency_permille": 1000,
    "identified_l_drift_permille": 1000,
    "identified_l_r_shift_minus_permille": 1000,
    "identified_l_r_shift_plus_permille": 1000,
    "identified_l_x_mag_vs_quad_permille": 1000,
}


def make_foci_config(stepper_values=None, foci_values=None, chips=None):
    stepper_values = dict(stepper_values or {})
    stepper_values.setdefault("step_pin", "foci:STEP0")
    stepper_values.setdefault("dir_pin", "foci:DIR0")
    stepper_values.setdefault("oid", 10)
    printer, chips, sections = make_config_printer(
        {"stepper_x": stepper_values},
        chips=chips,
    )
    if foci_values:
        sections["foci stepper_x"].update(foci_values)
    return printer, chips, sections, MockConfig(printer, sections, "foci stepper_x")


def test_foci_driver_config_field_inventory_is_explicit():
    assert {field.name for field in fields(FociDriverConfig)} == CONFIG_FIELD_NAMES


def test_foci_control_settings_field_inventory_and_types_match_config():
    settings_fields = tuple(field.name for field in fields(FociControlSettings))
    assert settings_fields == EXPECTED_CONTROL_SETTING_FIELDS
    assert CONTROL_SETTING_FIELDS == EXPECTED_CONTROL_SETTING_FIELDS

    config_types = {field.name: field.type for field in fields(FociDriverConfig)}
    settings_types = {field.name: field.type for field in fields(FociControlSettings)}
    for field_name in EXPECTED_CONTROL_SETTING_FIELDS:
        assert settings_types[field_name] == config_types[field_name]


def test_parse_driver_config_captures_identity_motor_binding_and_defaults():
    printer, chips, _sections, config = make_foci_config(
        stepper_values={
            "microsteps": 32,
            "full_steps_per_rotation": 400,
            "step_pin": "foci:STEP1",
            "oid": 10,
        },
        foci_values={
            "run_current": 1.25,
            "encoder_ppr": 2048,
            "encoder_direction": "reversed",
        },
    )

    parsed = parse_driver_config(config)

    assert parsed.name == "foci stepper_x"
    assert parsed.stepper_name == "stepper_x"
    assert parsed.run_current == 1.25
    assert parsed.encoder_ppr == 2048
    assert parsed.voltage_limit == 16000
    assert parsed.encoder_reversed is True
    assert parsed.microsteps == 32
    assert parsed.full_steps == 400
    assert parsed.step_pin_name == "STEP1"
    assert parsed.mcu is chips["foci"]
    assert parsed.channel == 1
    assert printer.lookup_object("pins") is not None


def test_parse_driver_config_preserves_persisted_and_tuning_fields():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={
            "pid_flux_p": 256,
            "pid_flux_i": 26,
            "pid_torque_p": 257,
            "pid_torque_i": 27,
            "velocity_filter_hz": 200,
            "torque_filter_hz": 100,
            "position_filter_hz": 300,
            "flux_filter_hz": 400,
            "pid_position_p": 640,
            "pid_position_i": 1,
            "pid_velocity_p": 1152,
            "pid_velocity_i": 2,
            "velocity_feedforward": True,
            "velocity_feedforward_multiplier": 7,
            "pid_velocity_limit": 500000,
            "commissioned_velocity_p": 1100,
            "commissioned_velocity_i": 3,
            "commissioned_position_p": 600,
            "commissioned_position_i": 4,
            "commissioned_velocity_limit": 300000,
            "identified_r_int": 1706,
            "identified_l_int": 1245,
            "identified_r_count_milli": 1700,
            "identified_l_count_micro": 3300,
            "identified_lambda_us": 12,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 25,
            "identified_tau_e_us": 730,
            "identified_inner_warning_flags": 2,
            "identified_l_source": 1,
            "identified_l_warning_flags": 0,
            "identified_l_frequency_millihz": 1_000_000,
            "identified_l_reactance_count_ratio_milli": 8600,
            "identified_l_d_reactance_count_ratio_milli": 9200,
            "identified_l_q_reactance_count_ratio_milli": 8000,
            "identified_l_saliency_status": 1,
            "identified_l_saliency_permille": 140,
            "identified_l_iq_mean_milli_count": -84000,
            "identified_l_drift_permille": 40,
            "identified_l_r_shift_minus_permille": 4,
            "identified_l_r_shift_plus_permille": 4,
            "identified_l_x_mag_vs_quad_permille": 20,
            "identified_j_eff": 9,
            "identified_b_eff": 10,
            "identified_current_gains_source": 1,
            "identified_current_candidate_gains_source": 1,
            "identified_axis_split_source": 1,
            "identified_current_candidate_axis_split_source": 1,
            "identified_current_gains_tier": 2,
            "identified_current_candidate_gains_tier": 2,
            "identified_current_measured_axis_split_permille": 1840,
            "identified_current_candidate_measured_axis_split_permille": 1840,
            "identified_current_applied_axis_split_permille": 1500,
            "identified_current_candidate_applied_axis_split_permille": 1500,
            "identified_current_axis_split_clamped": 1,
            "identified_current_candidate_axis_split_clamped": 1,
            "identified_current_candidate_flux_p": 711,
            "identified_current_candidate_flux_i": 26,
            "identified_current_candidate_torque_p": 650,
            "identified_current_candidate_torque_i": 21,
            "identified_current_candidate_attempt": 1,
            "identified_current_validation_axes": 3,
            "identified_current_flux_validation_sample_count": 4,
            "identified_current_torque_validation_sample_count": 2,
            "identified_current_retry_budget_exhausted": 0,
            "identified_current_failure_reason": 0,
            "identified_current_flux_response_min_permille": 710,
            "identified_current_torque_response_min_permille": 590,
            "identified_current_flux_encoder_delta_counts": 0,
            "identified_current_torque_encoder_delta_counts": 4,
            "autotune_profile": "balanced",
            "autotune_mode": "nominal",
            "autotune_status": "commissioned",
        },
    )

    parsed = parse_driver_config(config)

    assert parsed.pid_flux_p == 256
    assert parsed.pid_torque_i == 27
    assert parsed.velocity_filter_hz == 200
    assert parsed.flux_filter_hz == 400
    assert parsed.pid_position_p == 640
    assert parsed.pid_velocity_i == 2
    assert parsed.velocity_feedforward is True
    assert parsed.velocity_feedforward_multiplier == 7
    assert parsed.velocity_transient_feedforward is False
    assert parsed.velocity_transient_lead_time_us == 0
    assert parsed.velocity_transient_gain == 0
    assert parsed.velocity_transient_max_offset == 0
    assert parsed.velocity_transient_rate_hz == 1000
    assert parsed.accel_feedforward is False
    assert parsed.accel_feedforward_accel_gain == 1000
    assert parsed.accel_feedforward_decel_gain == 1000
    assert parsed.decoupling_feedforward is False
    assert parsed.decoupling_r_int == 3000
    assert parsed.decoupling_l_int == 4095
    assert parsed.decoupling_pole_pairs == 50
    assert parsed.decoupling_position_units_per_rev == 65536
    assert parsed.decoupling_f_pwm_hz == 25000
    assert parsed.decoupling_max_offset == 500
    assert parsed.position_lead is False
    assert parsed.position_lead_gain == 0
    assert parsed.position_lead_max_counts == 0
    assert parsed.phase_advance is False
    assert parsed.phase_advance_gain_ppm == 0
    assert parsed.phase_advance_max_counts == 0
    assert parsed.phase_advance_deadband == 16
    assert parsed.pid_velocity_limit == 500000
    assert parsed.commissioned_velocity_p == 1100
    assert parsed.commissioned_position_i == 4
    assert parsed.identified_r_int == 1706
    assert parsed.identified_l_count_micro == 3300
    assert parsed.identified_tau_e_us == 730
    assert parsed.identified_inner_warning_flags == 2
    assert parsed.identified_l_source == 1
    assert parsed.identified_l_warning_flags == 0
    assert parsed.identified_l_frequency_millihz == 1_000_000
    assert parsed.identified_l_reactance_count_ratio_milli == 8600
    assert parsed.identified_l_d_reactance_count_ratio_milli == 9200
    assert parsed.identified_l_q_reactance_count_ratio_milli == 8000
    assert parsed.identified_l_saliency_status == 1
    assert parsed.identified_l_saliency_permille == 140
    assert parsed.identified_l_iq_mean_milli_count == -84000
    assert parsed.identified_l_drift_permille == 40
    assert parsed.identified_l_r_shift_minus_permille == 4
    assert parsed.identified_l_r_shift_plus_permille == 4
    assert parsed.identified_l_x_mag_vs_quad_permille == 20
    assert parsed.identified_j_eff == 9
    assert parsed.identified_b_eff == 10
    assert parsed.identified_current_gains_source == 1
    assert parsed.identified_current_candidate_gains_source == 1
    assert parsed.identified_axis_split_source == 1
    assert parsed.identified_current_candidate_axis_split_source == 1
    assert parsed.identified_current_gains_tier == 2
    assert parsed.identified_current_candidate_gains_tier == 2
    assert parsed.identified_current_measured_axis_split_permille == 1840
    assert parsed.identified_current_candidate_measured_axis_split_permille == 1840
    assert parsed.identified_current_applied_axis_split_permille == 1500
    assert parsed.identified_current_candidate_applied_axis_split_permille == 1500
    assert parsed.identified_current_axis_split_clamped == 1
    assert parsed.identified_current_candidate_axis_split_clamped == 1
    assert parsed.identified_current_candidate_flux_p == 711
    assert parsed.identified_current_candidate_flux_i == 26
    assert parsed.identified_current_candidate_torque_p == 650
    assert parsed.identified_current_candidate_torque_i == 21
    assert parsed.identified_current_candidate_attempt == 1
    assert parsed.identified_current_validation_axes == 3
    assert parsed.identified_current_flux_validation_sample_count == 4
    assert parsed.identified_current_torque_validation_sample_count == 2
    assert parsed.identified_current_retry_budget_exhausted == 0
    assert parsed.identified_current_failure_reason == 0
    assert parsed.identified_current_flux_response_min_permille == 710
    assert parsed.identified_current_torque_response_min_permille == 590
    assert parsed.identified_current_flux_encoder_delta_counts == 0
    assert parsed.identified_current_torque_encoder_delta_counts == 4
    assert parsed.autotune_profile == "balanced"
    assert parsed.autotune_mode == "nominal"
    assert parsed.autotune_status == "commissioned"


def test_parse_driver_config_bounds_current_loop_evidence_fields():
    for field_name, max_value in CURRENT_LOOP_FIELD_MAX_VALUES.items():
        with pytest.raises(CommandError, match="below minimum"):
            parsed_config_with({field_name: -1})
        with pytest.raises(CommandError, match="above maximum"):
            parsed_config_with({field_name: max_value + 1})


def test_parse_driver_config_bounds_inductance_evidence_fields():
    for field_name, max_value in INDUCTANCE_FIELD_MAX_VALUES.items():
        with pytest.raises(CommandError, match="below minimum"):
            parsed_config_with({field_name: -1})
        if max_value is not None:
            with pytest.raises(CommandError, match="above maximum"):
                parsed_config_with({field_name: max_value + 1})


def test_parse_driver_config_rejects_low_filter_hz():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={"velocity_filter_hz": 5}
    )

    with pytest.raises(CommandError, match="velocity_filter_hz must be 0"):
        parse_driver_config(config)


def test_parse_driver_config_rejects_incomplete_inner_pid_group():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={"pid_flux_p": 256}
    )

    with pytest.raises(CommandError, match="must be set as a complete group"):
        parse_driver_config(config)


def test_parse_driver_config_rejects_incomplete_position_velocity_pid_group():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={"pid_position_p": 600}
    )

    with pytest.raises(CommandError, match="must be set together"):
        parse_driver_config(config)


def test_parse_driver_config_rejects_missing_linked_stepper_section():
    printer, _chips, sections, _config = make_foci_config()
    del sections["stepper_x"]

    with pytest.raises(CommandError, match="cannot find stepper section"):
        parse_driver_config(MockConfig(printer, sections, "foci stepper_x"))


def test_parse_driver_config_rejects_invalid_foci_step_pin():
    _printer, _chips, _sections, config = make_foci_config(
        stepper_values={"step_pin": "foci:STEP9"}
    )

    with pytest.raises(CommandError, match="not a FOCI STEP pin"):
        parse_driver_config(config)


def test_parse_driver_config_supports_dual_mcu_binding():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {"step_pin": "foci_x:STEP0", "oid": 10},
            "stepper_y": {"step_pin": "foci_y:STEP1", "oid": 12},
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )

    parsed_x = parse_driver_config(MockConfig(printer, sections, "foci stepper_x"))
    parsed_y = parse_driver_config(MockConfig(printer, sections, "foci stepper_y"))

    assert parsed_x.mcu is mcu_x
    assert parsed_x.channel == 0
    assert parsed_y.mcu is mcu_y
    assert parsed_y.channel == 1


def test_foci_driver_stores_config_settings_and_explicit_facade():
    _printer, _chips, sections, config = make_foci_config(
        stepper_values={"microsteps": 16, "full_steps_per_rotation": 400},
        foci_values={"run_current": 0.9, "encoder_ppr": 1200},
    )

    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")

    assert isinstance(driver.config, FociDriverConfig)
    assert isinstance(driver.settings, FociControlSettings)
    assert driver.config.run_current == 0.9
    assert driver.settings.run_current == 0.9
    assert driver.config.encoder_ppr == 1200
    assert driver.config.microsteps == 16
    assert driver.config.full_steps == 400
    for field_name in DRIVER_CONFIG_FACADE_FIELDS:
        assert getattr(driver, field_name) == getattr(driver.config, field_name)
    for field_name in DISALLOWED_DRIVER_CONFIG_FACADE_FIELDS:
        assert not hasattr(driver, field_name), (
            f"{field_name} should live on driver.config or driver.settings, "
            "not the driver facade"
        )


def parsed_config_with(foci_values):
    _printer, _chips, _sections, config = make_foci_config(foci_values=foci_values)
    return parse_driver_config(config)


def assert_uncommissioned(result):
    assert isinstance(result, RuntimeValidationResult)
    assert result.runtime_status == "uncommissioned"
    assert result.active_gains is None


def test_validate_runtime_config_returns_uncommissioned_for_absent_status():
    result = validate_runtime_config(parsed_config_with({}))

    assert_uncommissioned(result)


def test_validate_runtime_config_returns_commissioned_active_gains():
    result = validate_runtime_config(
        parsed_config_with(
            {
                "autotune_status": "commissioned",
                "pid_flux_p": 256,
                "pid_flux_i": 26,
                "pid_torque_p": 257,
                "pid_torque_i": 27,
                "identified_lambda_us": 12,
                "identified_theta_e_us": 160,
                "identified_ringing_count": 7,
                "identified_bandwidth_hz": 25,
                "commissioned_velocity_p": 1100,
                "commissioned_velocity_i": 3,
                "commissioned_position_p": 600,
                "commissioned_position_i": 4,
                "commissioned_velocity_limit": 300000,
                "position_filter_hz": 200,
            }
        )
    )

    assert result.runtime_status == "commissioned"
    assert result.active_gains == {
        "flux_p": 256,
        "flux_i": 26,
        "torque_p": 257,
        "torque_i": 27,
        "velocity_p": 1100,
        "velocity_i": 3,
        "position_p": 600,
        "position_i": 4,
        "velocity_limit": 300000,
        "velocity_filter_hz": 0,
        "torque_filter_hz": 0,
        "position_filter_hz": 200,
        "flux_filter_hz": 0,
    }


def test_validate_runtime_config_returns_tuned_active_gains():
    result = validate_runtime_config(
        parsed_config_with(
            {
                "autotune_status": "tuned_conservative",
                "pid_flux_p": 256,
                "pid_flux_i": 26,
                "pid_torque_p": 257,
                "pid_torque_i": 27,
                "identified_lambda_us": 12,
                "identified_theta_e_us": 160,
                "identified_ringing_count": 7,
                "identified_bandwidth_hz": 25,
                "pid_velocity_p": 1100,
                "pid_velocity_i": 3,
                "pid_position_p": 600,
                "pid_position_i": 4,
                "pid_velocity_limit": 300000,
                "flux_filter_hz": 100,
            }
        )
    )

    assert result.runtime_status == "tuned_conservative"
    assert result.active_gains == {
        "flux_p": 256,
        "flux_i": 26,
        "torque_p": 257,
        "torque_i": 27,
        "velocity_p": 1100,
        "velocity_i": 3,
        "position_p": 600,
        "position_i": 4,
        "velocity_limit": 300000,
        "velocity_filter_hz": 0,
        "torque_filter_hz": 0,
        "position_filter_hz": 0,
        "flux_filter_hz": 100,
    }


def test_validate_runtime_config_warns_for_unknown_status(caplog):
    result = validate_runtime_config(parsed_config_with({"autotune_status": "unsafe"}))

    assert_uncommissioned(result)
    assert "unknown autotune_status='unsafe'" in caplog.text


def test_validate_runtime_config_warns_for_missing_required_fields(caplog):
    result = validate_runtime_config(
        parsed_config_with(
            {
                "autotune_status": "commissioned",
                "pid_flux_p": 256,
                "pid_flux_i": 26,
                "pid_torque_p": 257,
                "pid_torque_i": 27,
            }
        )
    )

    assert_uncommissioned(result)
    assert "missing required fields" in caplog.text
    assert "identified_lambda_us" in caplog.text
    assert "commissioned_velocity_p" in caplog.text


def test_handle_connect_installs_validation_result():
    _printer, _chips, sections, config = make_foci_config(
        foci_values={
            "autotune_status": "commissioned",
            "pid_flux_p": 256,
            "pid_flux_i": 26,
            "pid_torque_p": 257,
            "pid_torque_i": 27,
            "identified_lambda_us": 12,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 25,
            "commissioned_velocity_p": 1100,
            "commissioned_velocity_i": 3,
            "commissioned_position_p": 600,
            "commissioned_position_i": 4,
            "commissioned_velocity_limit": 300000,
        }
    )
    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")
    # make_config_printer installs MockCartesianKinematics with this stepper OID.
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert driver.state.runtime_status == "commissioned"
    assert driver.state.active_gains["velocity_p"] == 1100


def test_handle_connect_reads_payloads_from_settings_not_config():
    _printer, _chips, sections, config = make_foci_config(
        foci_values={
            "run_current": 0.8,
            "encoder_ppr": 1200,
            "voltage_limit": 16000,
            "velocity_feedforward": False,
            "velocity_feedforward_multiplier": 1,
        }
    )
    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver.settings.run_current = 1.5
    driver.settings.voltage_limit = 22000
    driver.settings.pid_flux_p = 101
    driver.settings.pid_flux_i = 102
    driver.settings.pid_torque_p = 103
    driver.settings.pid_torque_i = 104
    driver.settings.pid_position_p = 201
    driver.settings.pid_position_i = 202
    driver.settings.pid_velocity_p = 203
    driver.settings.pid_velocity_i = 204
    driver.settings.velocity_filter_hz = 40
    driver.settings.torque_filter_hz = 50
    driver.settings.position_filter_hz = 60
    driver.settings.flux_filter_hz = 70
    driver.settings.velocity_feedforward = True
    driver.settings.velocity_feedforward_multiplier = 9
    driver.settings.pid_velocity_limit = 123456

    driver.config.run_current = 0.1
    driver.config.voltage_limit = 0
    driver.config.pid_flux_p = None
    driver.config.pid_position_p = None
    driver.config.velocity_filter_hz = 0
    driver.config.velocity_feedforward = False
    driver.config.velocity_feedforward_multiplier = 1
    driver.config.pid_velocity_limit = None

    driver._handle_connect()

    assert driver.protocol.commands.set_current.last_args == [10, 1500]
    assert driver.protocol.commands.set_voltage_limit.last_args == [10, 22000]
    assert driver.protocol.commands.set_pid_gains.last_args == [
        10,
        101,
        102,
        103,
        104,
    ]
    assert driver.protocol.commands.set_position_gains.last_args == [
        10,
        201,
        202,
        203,
        204,
    ]
    assert driver.protocol.commands.set_velocity_filter.last_args == [10, 40]
    assert driver.protocol.commands.set_torque_filter.last_args == [10, 50]
    assert driver.protocol.commands.set_position_filter.last_args == [10, 60]
    assert driver.protocol.commands.set_flux_filter.last_args == [10, 70]
    assert driver.protocol.commands.set_velocity_feedforward.last_args == [
        10,
        1,
        9,
    ]
    assert driver.protocol.commands.set_velocity_limit.last_args == [10, 123456]


def test_handle_connect_reads_mechanical_payloads_from_config_not_facade():
    _printer, _chips, sections, config = make_foci_config(
        foci_values={
            "encoder_ppr": 1000,
            "encoder_direction": "reversed",
        }
    )
    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")
    driver._handle_mcu_identify()

    setattr(driver, "encoder_ppr", 1)
    setattr(driver, "encoder_reversed", False)
    setattr(driver, "microsteps", 1)
    setattr(driver, "full_steps", 0)

    driver._handle_connect()

    assert driver.protocol.commands.set_encoder.last_args == [10, 0, 1000]
    assert driver.protocol.commands.set_encoder_dir.last_args == [10, 0, 1]
