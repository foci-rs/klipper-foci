"""Tests for klipper-foci per-driver config parsing."""

from __future__ import annotations

from dataclasses import fields

import pytest

from klipper_foci.config import FociDriverConfig, parse_driver_config

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
    "identified_tau_e_crosscheck_us",
    "identified_tau_residual_permille",
    "identified_inner_warning_flags",
    "identified_j_eff",
    "identified_b_eff",
    "autotune_profile",
    "autotune_mode",
    "autotune_status",
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
            "identified_tau_e_crosscheck_us": 731,
            "identified_tau_residual_permille": 8,
            "identified_inner_warning_flags": 2,
            "identified_j_eff": 9,
            "identified_b_eff": 10,
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
    assert parsed.identified_j_eff == 9
    assert parsed.identified_b_eff == 10
    assert parsed.autotune_profile == "balanced"
    assert parsed.autotune_mode == "nominal"
    assert parsed.autotune_status == "commissioned"


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


def test_foci_driver_stores_config_and_mirrors_all_config_fields():
    _printer, _chips, sections, config = make_foci_config(
        stepper_values={"microsteps": 16, "full_steps_per_rotation": 400},
        foci_values={"run_current": 0.9, "encoder_ppr": 1200},
    )

    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")

    assert isinstance(driver.config, FociDriverConfig)
    assert driver.config.run_current == 0.9
    assert driver.config.encoder_ppr == 1200
    assert driver.config.microsteps == 16
    assert driver.config.full_steps == 400
    for field in fields(driver.config):
        assert getattr(driver, field.name) == getattr(driver.config, field.name)
