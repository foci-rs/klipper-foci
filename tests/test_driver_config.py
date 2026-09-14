"""Tests for klipper-foci per-driver config parsing."""

from __future__ import annotations

from dataclasses import fields

import pytest
from klipper_foci.config import (
    CONTROL_SETTING_FIELDS,
    FociControlSettings,
    FociDriverConfig,
    RuntimeValidationResult,
    gain_to_permille,
    parse_driver_config,
    stall_threshold_units,
    validate_runtime_config,
)

from tests.mocks import (
    CommandError,
    MockConfig,
    MockMCU,
    complete_commission_result,
    make_config_driver,
    make_config_printer,
    make_driver,
)

CONFIG_FIELD_NAMES = {
    "name",
    "stepper_name",
    "run_current",
    "encoder_ppr",
    "voltage_limit",
    "encoder_reversed",
    "homing_current",
    "stall_distance",
    "stall_persistence",
    "rotation_distance",
    "microsteps",
    "full_steps",
    "planner_steps_per_rev",
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
    "velocity_feedforward_gain",
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
    "identified_r_count_milli",
    "identified_lambda_us",
    "identified_theta_e_us",
    "identified_ringing_count",
    "identified_bandwidth_hz",
    "identified_tau_e_us",
    "identified_inner_warning_flags",
    "identified_l_source",
    "identified_l_reactance_count_ratio_milli",
    "identified_l_saliency_status",
    "identified_current_gains_source",
    "identified_current_gains_tier",
    "identified_current_retry_budget_exhausted",
    "identified_current_failure_reason",
    "identified_r_count_slope_milli",
    "autotune_profile",
    "autotune_mode",
    "autotune_status",
    "autotune_probed_velocity_mrev_s",
    "autotune_d_eq_q",
    "autotune_confidence_q",
    "autotune_band_lower_percent",
    "autotune_band_upper_percent",
    "autotune_band_position_q",
}


DRIVER_CONFIG_FACADE_FIELDS = {
    "name",
    "stepper_name",
    "mcu",
    "channel",
}


DISALLOWED_DRIVER_CONFIG_FACADE_FIELDS = CONFIG_FIELD_NAMES - DRIVER_CONFIG_FACADE_FIELDS


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
    "velocity_feedforward_gain",
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
    "identified_current_gains_tier": 255,
    "identified_current_retry_budget_exhausted": 255,
    "identified_current_failure_reason": 255,
}


INDUCTANCE_FIELD_MAX_VALUES = {
    "identified_l_source": 255,
    "identified_l_reactance_count_ratio_milli": None,
    "identified_l_saliency_status": 255,
}


ACTIVE_PID_GAIN_FIELDS = (
    "pid_flux_p",
    "pid_flux_i",
    "pid_torque_p",
    "pid_torque_i",
    "pid_position_p",
    "pid_position_i",
    "pid_velocity_p",
    "pid_velocity_i",
)


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
            "rotation_distance": 32.0,
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
    assert parsed.rotation_distance == 32.0
    assert parsed.microsteps == 32
    assert parsed.full_steps == 400
    assert parsed.planner_steps_per_rev == 12800
    assert parsed.step_pin_name == "STEP1"
    assert parsed.mcu is chips["foci"]
    assert parsed.channel == 1
    assert printer.lookup_object("pins") is not None


def test_parse_driver_config_bounds_run_current_at_five_amps():
    _printer, _chips, _sections, config = make_foci_config(foci_values={"run_current": 5.0})

    assert parse_driver_config(config).run_current == 5.0

    _printer, _chips, _sections, config = make_foci_config(foci_values={"run_current": 5.001})
    with pytest.raises(CommandError, match="run_current above maximum"):
        parse_driver_config(config)


def test_parse_driver_config_accepts_largest_encoder_ppr_that_fits_quadrature():
    _printer, _chips, _sections, config = make_foci_config(foci_values={"encoder_ppr": 0x3FFF_FFFF})

    parsed = parse_driver_config(config)

    assert parsed.encoder_ppr == 0x3FFF_FFFF


def test_parse_driver_config_rejects_encoder_ppr_above_quadrature_bound_with_context():
    _printer, _chips, _sections, config = make_foci_config(foci_values={"encoder_ppr": 0x4000_0000})

    with pytest.raises(CommandError) as excinfo:
        parse_driver_config(config)

    message = str(excinfo.value)
    assert "foci stepper_x" in message
    assert "encoder_ppr" in message
    assert "1073741824" in message
    assert "1..1073741823" in message


@pytest.mark.parametrize(
    ("stepper_values", "invalid_value"),
    [
        ({"microsteps": 0, "full_steps_per_rotation": 200}, 0),
        ({"microsteps": 256, "full_steps_per_rotation": 65537}, 16777472),
    ],
)
def test_parse_driver_config_rejects_invalid_planner_scale_with_context(
    stepper_values, invalid_value
):
    _printer, _chips, _sections, config = make_foci_config(stepper_values=stepper_values)

    with pytest.raises(CommandError) as excinfo:
        parse_driver_config(config)

    message = str(excinfo.value)
    assert "stepper_x" in message
    assert str(invalid_value) in message
    assert "1..16777216" in message


def test_parse_driver_config_preserves_persisted_and_tuning_fields():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={
            "pid_flux_p": 256,
            "pid_flux_i": 416,
            "pid_torque_p": 257,
            "pid_torque_i": 432,
            "velocity_filter_hz": 200,
            "torque_filter_hz": 100,
            "position_filter_hz": 300,
            "flux_filter_hz": 400,
            "pid_position_p": 640,
            "pid_position_i": 16,
            "pid_velocity_p": 1152,
            "pid_velocity_i": 32,
            "velocity_feedforward": True,
            "velocity_feedforward_gain": 7,
            "pid_velocity_limit": 500000,
            "commissioned_velocity_p": 1100,
            "commissioned_velocity_i": 48,
            "commissioned_position_p": 600,
            "commissioned_position_i": 64,
            "commissioned_velocity_limit": 300000,
            "identified_r_count_milli": 1700,
            "identified_lambda_us": 12,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 25,
            "identified_tau_e_us": 730,
            "identified_inner_warning_flags": 2,
            "identified_l_source": 1,
            "identified_l_reactance_count_ratio_milli": 8600,
            "identified_l_saliency_status": 1,
            "identified_current_gains_source": 1,
            "identified_current_gains_tier": 2,
            "identified_current_retry_budget_exhausted": 0,
            "identified_current_failure_reason": 0,
            "autotune_profile": "balanced",
            "autotune_mode": "nominal",
            "autotune_status": "commissioned",
        },
    )

    parsed = parse_driver_config(config)

    assert parsed.pid_flux_p == 256
    assert parsed.pid_torque_i == 432
    assert parsed.velocity_filter_hz == 200
    assert parsed.flux_filter_hz == 400
    assert parsed.pid_position_p == 640
    assert parsed.pid_velocity_i == 32
    assert parsed.velocity_feedforward is True
    assert parsed.velocity_feedforward_gain == 7
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
    assert parsed.commissioned_position_i == 64
    assert parsed.identified_r_count_milli == 1700
    assert parsed.identified_tau_e_us == 730
    assert parsed.identified_inner_warning_flags == 2
    assert parsed.identified_l_source == 1
    assert parsed.identified_l_reactance_count_ratio_milli == 8600
    assert parsed.identified_l_saliency_status == 1
    assert parsed.identified_current_gains_source == 1
    assert parsed.identified_current_gains_tier == 2
    assert parsed.identified_current_retry_budget_exhausted == 0
    assert parsed.identified_current_failure_reason == 0
    assert parsed.autotune_profile == "balanced"
    assert parsed.autotune_mode == "nominal"
    assert parsed.autotune_status == "commissioned"


def test_gain_default_and_maxval_and_retired_key():
    printer, _chips, sections, _config = make_foci_config(
        foci_values={"velocity_feedforward": "true"}
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()
    assert driver.settings.velocity_feedforward_gain == 1.0

    with pytest.raises(CommandError):
        p, _c, s, _cfg = make_foci_config(foci_values={"velocity_feedforward_gain": "40"})
        make_config_driver(p, s, "foci stepper_x")

    with pytest.raises(CommandError):
        p, _c, s, _cfg = make_foci_config(foci_values={"velocity_feedforward_multiplier": "40"})
        config = MockConfig(p, s, "foci stepper_x")
        parse_driver_config(config)
        unused = config.unused_options()
        assert "velocity_feedforward_multiplier" in unused
        raise CommandError(f"Option(s) {', '.join(unused)} in [foci stepper_x] are not valid")


def test_gain_to_permille_conversion():
    assert gain_to_permille(1.0) == 1000 and gain_to_permille(2.5) == 2500


def test_config_path_sends_gain_as_permille():
    printer, _chips, sections, _config = make_foci_config(
        foci_values={"velocity_feedforward": "true", "velocity_feedforward_gain": "1.0"}
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()
    driver._handle_connect()
    assert driver.protocol.commands.set_velocity_feedforward.last_args == [driver.oid, 1, 1000]


def test_parse_driver_config_bounds_current_loop_evidence_fields():
    for field_name, max_value in CURRENT_LOOP_FIELD_MAX_VALUES.items():
        with pytest.raises(CommandError, match="below minimum"):
            parsed_config_with({field_name: -1})
        with pytest.raises(CommandError, match="above maximum"):
            parsed_config_with({field_name: max_value + 1})


@pytest.mark.parametrize("field_name", ACTIVE_PID_GAIN_FIELDS)
def test_parse_driver_config_bounds_active_pid_gains(field_name):
    inner = dict.fromkeys(ACTIVE_PID_GAIN_FIELDS[:4], 0)
    outer = dict.fromkeys(ACTIVE_PID_GAIN_FIELDS[4:], 0)
    values = {**inner, **outer, field_name: 32767}

    parsed = parsed_config_with(values)

    assert getattr(parsed, field_name) == 32767

    values[field_name] = 32768
    with pytest.raises(CommandError, match=f"{field_name} above maximum"):
        parsed_config_with(values)


def test_parse_driver_config_bounds_inductance_evidence_fields():
    for field_name, max_value in INDUCTANCE_FIELD_MAX_VALUES.items():
        with pytest.raises(CommandError, match="below minimum"):
            parsed_config_with({field_name: -1})
        if max_value is not None:
            with pytest.raises(CommandError, match="above maximum"):
                parsed_config_with({field_name: max_value + 1})


def test_parse_driver_config_rejects_low_filter_hz():
    _printer, _chips, _sections, config = make_foci_config(foci_values={"velocity_filter_hz": 5})

    with pytest.raises(CommandError, match="velocity_filter_hz must be 0"):
        parse_driver_config(config)


def test_parse_driver_config_allows_current_filters_up_to_six_khz():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={"torque_filter_hz": 6000, "flux_filter_hz": 6000}
    )

    parsed = parse_driver_config(config)

    assert parsed.torque_filter_hz == 6000
    assert parsed.flux_filter_hz == 6000


def test_parse_driver_config_leaves_omitted_filters_unset_for_firmware_auto():
    _printer, _chips, _sections, config = make_foci_config()

    parsed = parse_driver_config(config)

    assert parsed.velocity_filter_hz is None
    assert parsed.torque_filter_hz is None
    assert parsed.position_filter_hz is None
    assert parsed.flux_filter_hz is None


def test_parse_driver_config_preserves_explicit_zero_filter_disable():
    _printer, _chips, _sections, config = make_foci_config(
        foci_values={
            "velocity_filter_hz": 0,
            "torque_filter_hz": 0,
            "position_filter_hz": 0,
            "flux_filter_hz": 0,
        }
    )

    parsed = parse_driver_config(config)

    assert parsed.velocity_filter_hz == 0
    assert parsed.torque_filter_hz == 0
    assert parsed.position_filter_hz == 0
    assert parsed.flux_filter_hz == 0


def test_parse_driver_config_keeps_motion_filters_capped_at_one_khz():
    for option in ("velocity_filter_hz", "position_filter_hz"):
        _printer, _chips, _sections, config = make_foci_config(foci_values={option: 1001})

        with pytest.raises(CommandError, match=f"{option} above maximum"):
            parse_driver_config(config)


def test_parse_driver_config_rejects_incomplete_inner_pid_group():
    _printer, _chips, _sections, config = make_foci_config(foci_values={"pid_flux_p": 256})

    with pytest.raises(CommandError, match="must be set as a complete group"):
        parse_driver_config(config)


def test_parse_driver_config_rejects_incomplete_position_velocity_pid_group():
    _printer, _chips, _sections, config = make_foci_config(foci_values={"pid_position_p": 600})

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
    assert driver.config.rotation_distance == 40.0
    assert driver.config.microsteps == 16
    assert driver.config.full_steps == 400
    assert driver.config.planner_steps_per_rev == 6400
    for field_name in DRIVER_CONFIG_FACADE_FIELDS:
        assert getattr(driver, field_name) == getattr(driver.config, field_name)
    for field_name in DISALLOWED_DRIVER_CONFIG_FACADE_FIELDS:
        assert not hasattr(driver, field_name), (
            f"{field_name} should live on driver.config or driver.settings, not the driver facade"
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
                "pid_flux_i": 416,
                "pid_torque_p": 257,
                "pid_torque_i": 432,
                "identified_lambda_us": 12,
                "identified_theta_e_us": 160,
                "identified_ringing_count": 7,
                "identified_bandwidth_hz": 1600,
                "commissioned_velocity_p": 1100,
                "commissioned_velocity_i": 48,
                "commissioned_position_p": 600,
                "commissioned_position_i": 64,
                "commissioned_velocity_limit": 300000,
                "position_filter_hz": 200,
            }
        )
    )

    assert result.runtime_status == "commissioned"
    assert result.active_gains == {
        "flux_p": 256,
        "flux_i": 416,
        "torque_p": 257,
        "torque_i": 432,
        "velocity_p": 1100,
        "velocity_i": 48,
        "position_p": 600,
        "position_i": 64,
        "velocity_limit": 300000,
        "velocity_filter_hz": None,
        "torque_filter_hz": None,
        "position_filter_hz": 200,
        "flux_filter_hz": None,
    }


def test_q4_12_i_values_remain_exact_through_host_lifecycle():
    configured_i = {
        "flux_i": 416,
        "torque_i": 2544,
        "velocity_i": 8192,
        "position_i": 2048,
    }
    parsed = parsed_config_with(
        {
            "autotune_status": "commissioned",
            "pid_flux_p": 256,
            "pid_flux_i": configured_i["flux_i"],
            "pid_torque_p": 257,
            "pid_torque_i": configured_i["torque_i"],
            "identified_lambda_us": 12,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 1600,
            "commissioned_velocity_p": 1100,
            "commissioned_velocity_i": configured_i["velocity_i"],
            "commissioned_position_p": 600,
            "commissioned_position_i": configured_i["position_i"],
            "commissioned_velocity_limit": 300000,
        }
    )
    validation = validate_runtime_config(parsed)
    active = validation.active_gains
    assert active is not None

    driver = make_driver()
    driver.protocol.preload_active_gains(active, voltage_limit=29000)
    assert driver.protocol.commands.set_pid_gains.last_args == [
        driver.oid,
        256,
        configured_i["flux_i"],
        257,
        configured_i["torque_i"],
    ]
    assert driver.protocol.commands.set_position_gains.last_args == [
        driver.oid,
        600,
        configured_i["position_i"],
        1100,
        configured_i["velocity_i"],
    ]
    driver.state.active_gains = dict(active)
    assert {name: driver.state.active_gains[name] for name in configured_i} == configured_i

    class ConfigSink:
        def __init__(self):
            self.values = {}

        def set(self, section, key, value):
            self.values[(section, key)] = value

    sink = ConfigSink()
    driver.printer._objects["configfile"] = sink
    reply = complete_commission_result()
    reply.update(
        flux_i=configured_i["flux_i"],
        torque_i=configured_i["torque_i"],
        fallback_velocity_i=configured_i["velocity_i"],
        fallback_position_i=configured_i["position_i"],
    )
    driver.commissioning.persist_commission_results(reply, "balanced")
    assert sink.values[(driver.name, "pid_flux_i")] == str(configured_i["flux_i"])
    assert sink.values[(driver.name, "pid_torque_i")] == str(configured_i["torque_i"])
    assert sink.values[(driver.name, "commissioned_velocity_i")] == str(configured_i["velocity_i"])
    assert sink.values[(driver.name, "commissioned_position_i")] == str(configured_i["position_i"])


def test_validate_runtime_config_preserves_explicit_zero_current_filter_disable():
    result = validate_runtime_config(
        parsed_config_with(
            {
                "autotune_status": "commissioned",
                "pid_flux_p": 256,
                "pid_flux_i": 416,
                "pid_torque_p": 257,
                "pid_torque_i": 432,
                "identified_lambda_us": 12,
                "identified_theta_e_us": 160,
                "identified_ringing_count": 7,
                "identified_bandwidth_hz": 1600,
                "commissioned_velocity_p": 1100,
                "commissioned_velocity_i": 48,
                "commissioned_position_p": 600,
                "commissioned_position_i": 64,
                "commissioned_velocity_limit": 300000,
                "torque_filter_hz": 0,
                "flux_filter_hz": 0,
            }
        )
    )

    assert result.runtime_status == "commissioned"
    assert result.active_gains["torque_filter_hz"] == 0
    assert result.active_gains["flux_filter_hz"] == 0


def test_validate_runtime_config_returns_tuned_active_gains():
    result = validate_runtime_config(
        parsed_config_with(
            {
                "autotune_status": "tuned_conservative",
                "pid_flux_p": 256,
                "pid_flux_i": 416,
                "pid_torque_p": 257,
                "pid_torque_i": 432,
                "identified_lambda_us": 12,
                "identified_theta_e_us": 160,
                "identified_ringing_count": 7,
                "identified_bandwidth_hz": 1600,
                "pid_velocity_p": 1100,
                "pid_velocity_i": 48,
                "pid_position_p": 600,
                "pid_position_i": 64,
                "pid_velocity_limit": 300000,
                "flux_filter_hz": 100,
            }
        )
    )

    assert result.runtime_status == "tuned_conservative"
    assert result.active_gains == {
        "flux_p": 256,
        "flux_i": 416,
        "torque_p": 257,
        "torque_i": 432,
        "velocity_p": 1100,
        "velocity_i": 48,
        "position_p": 600,
        "position_i": 64,
        "velocity_limit": 300000,
        "velocity_filter_hz": None,
        "torque_filter_hz": None,
        "position_filter_hz": None,
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
                "pid_flux_i": 416,
                "pid_torque_p": 257,
                "pid_torque_i": 432,
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
            "pid_flux_i": 416,
            "pid_torque_p": 257,
            "pid_torque_i": 432,
            "identified_lambda_us": 12,
            "identified_theta_e_us": 160,
            "identified_ringing_count": 7,
            "identified_bandwidth_hz": 25,
            "commissioned_velocity_p": 1100,
            "commissioned_velocity_i": 48,
            "commissioned_position_p": 600,
            "commissioned_position_i": 64,
            "commissioned_velocity_limit": 300000,
        }
    )
    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")
    # make_config_printer installs MockCartesianKinematics with this stepper OID.
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert driver.state.runtime_status == "commissioned"
    assert driver.state.active_gains["velocity_p"] == 1100


# Config for a stepper with saved commissioned gains that differ from the
# printer.cfg pid_position_p/i, pid_velocity_p/i, pid_velocity_limit values.
# Captured against the pre-change (two-pass) `_handle_connect` so the expected
# values below are the actual two-pass result, not a hand-derived guess: the
# saved commissioned_* gains run second and win over the printer.cfg values.
_CONNECT_SAVED_GAINS_DIFFER_FROM_CFG = {
    "autotune_status": "commissioned",
    "pid_flux_p": 256,
    "pid_flux_i": 416,
    "pid_torque_p": 257,
    "pid_torque_i": 432,
    "identified_lambda_us": 12,
    "identified_theta_e_us": 160,
    "identified_ringing_count": 7,
    "identified_bandwidth_hz": 1600,
    "commissioned_velocity_p": 1100,
    "commissioned_velocity_i": 48,
    "commissioned_position_p": 600,
    "commissioned_position_i": 64,
    "commissioned_velocity_limit": 300000,
    "pid_position_p": 111,
    "pid_position_i": 22,
    "pid_velocity_p": 33,
    "pid_velocity_i": 44,
    "pid_velocity_limit": 5000,
    "position_filter_hz": 200,
    "voltage_limit": 16000,
}


def test_handle_connect_sends_each_command_once_with_saved_gains():
    """Saved commissioned gains differ from printer.cfg: single send, active gains win."""
    _printer, _chips, sections, config = make_foci_config(
        foci_values=_CONNECT_SAVED_GAINS_DIFFER_FROM_CFG
    )
    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    cmds = driver.protocol.commands
    expected_last_args = {
        "set_current": [10, 800],
        "set_voltage_limit": [10, 16000],
        "query_adc_vm_offset": [10],
        "set_motion_scale": [10, 0, 1000, 4000],
        "set_encoder_dir": [10, 0, 0],
        "set_pid_gains": [10, 256, 416, 257, 432],
        "set_position_filter": [10, 200],
        "set_position_gains": [10, 600, 64, 1100, 48],
        "set_velocity_limit": [10, 300000],
    }
    for name, args in expected_last_args.items():
        command = getattr(cmds, name)
        assert command.call_count <= 1, f"{name} sent more than once"
        assert command.last_args == args

    for name in (
        "set_velocity_filter",
        "set_torque_filter",
        "set_flux_filter",
        "set_velocity_feedforward",
    ):
        assert getattr(cmds, name).call_count == 0


def test_handle_connect_matches_configure_startup_output_with_no_saved_gains():
    """Uncommissioned config: connect sequence is unchanged from configure_startup alone."""
    _printer, _chips, sections, config = make_foci_config(
        foci_values={
            "run_current": 0.8,
            "voltage_limit": 16000,
            "pid_position_p": 111,
            "pid_position_i": 22,
            "pid_velocity_p": 33,
            "pid_velocity_i": 44,
            "pid_velocity_limit": 5000,
            "position_filter_hz": 200,
        }
    )
    driver = make_config_driver(config.get_printer(), sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert driver.state.active_gains is None
    cmds = driver.protocol.commands
    assert cmds.set_current.last_args == [10, 800]
    assert cmds.set_voltage_limit.last_args == [10, 16000]
    assert cmds.set_voltage_limit.call_count == 1
    assert cmds.set_position_gains.last_args == [10, 111, 22, 33, 44]
    assert cmds.set_position_gains.call_count == 1
    assert cmds.set_velocity_limit.last_args == [10, 5000]
    assert cmds.set_velocity_limit.call_count == 1
    assert cmds.set_position_filter.last_args == [10, 200]
    assert cmds.set_position_filter.call_count == 1
    for name in (
        "set_velocity_filter",
        "set_torque_filter",
        "set_flux_filter",
        "set_velocity_feedforward",
    ):
        assert getattr(cmds, name).call_count == 0


def test_handle_connect_reads_payloads_from_settings_not_config():
    _printer, _chips, sections, config = make_foci_config(
        foci_values={
            "run_current": 0.8,
            "encoder_ppr": 1200,
            "voltage_limit": 16000,
            "velocity_feedforward": False,
            "velocity_feedforward_gain": 1,
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
    driver.settings.velocity_feedforward_gain = 9
    driver.settings.pid_velocity_limit = 123456

    driver.config.run_current = 0.1
    driver.config.voltage_limit = 0
    driver.config.pid_flux_p = None
    driver.config.pid_position_p = None
    driver.config.velocity_filter_hz = 0
    driver.config.velocity_feedforward = False
    driver.config.velocity_feedforward_gain = 1
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
        gain_to_permille(9),
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

    driver.encoder_ppr = 1
    driver.encoder_reversed = False
    driver.microsteps = 1
    driver.full_steps = 0

    driver._handle_connect()

    assert driver.protocol.commands.set_encoder_dir.last_args == [10, 0, 1]
    assert driver.protocol.commands.set_motion_scale.last_args == [10, 0, 1000, 4000]


@pytest.mark.parametrize("full_steps", [200, 400])
@pytest.mark.parametrize("microsteps", [1, 2, 4, 8, 16, 32, 64, 128, 256])
def test_handle_connect_supports_common_power_of_two_microsteps_without_warning(
    microsteps, full_steps
):
    printer, _chips, sections, _config = make_foci_config(
        stepper_values={
            "microsteps": microsteps,
            "full_steps_per_rotation": full_steps,
        }
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    planner_steps_per_rev = full_steps * microsteps
    assert driver.protocol.commands.set_motion_scale.last_args == [
        10,
        0,
        1000,
        planner_steps_per_rev,
    ]
    output = "\n".join(printer.lookup_object("gcode")._responses)
    assert "Consider microsteps" not in output
    assert "does not match" not in output


def test_handle_connect_reports_exact_ldo_mapping_and_rollout_warning():
    printer, _chips, sections, _config = make_foci_config(
        stepper_values={
            "microsteps": 16,
            "full_steps_per_rotation": 200,
            "rotation_distance": 40.0,
        }
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    output = "\n".join(printer.lookup_object("gcode")._responses)
    assert (
        "planner=200*16=3200 steps/rev encoder=1000 ppr=4000 quadrature counts/rev\n"
        "tmc_grid=4096 pulses/rev step_width=16 position_units/pulse "
        "pulse_ratio=4096/3200\n"
        "accumulated_scale_error=0 instantaneous_error_bound=8 position_units"
    ) in output
    assert "rotation_distance=40" in output
    assert "remove legacy hand compensation" in output
    assert "compare rotation_distance with the actual transmission before enabling motion" in output


def test_homing_defaults_and_threshold_units():
    printer, _chips, sections, _config = make_foci_config(
        stepper_values={"rotation_distance": 40.0}
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    cfg = driver.config
    assert cfg.homing_current == 0.7
    assert cfg.stall_distance == 0.5
    assert cfg.stall_persistence == 3
    assert stall_threshold_units(cfg) == 819


@pytest.mark.parametrize(
    "values",
    [
        {"homing_current": "2.3"},
        {"homing_current": "2.26"},
        {"homing_current": "-0.1"},
        {"stall_distance": "0"},
        {"stall_distance": "10.1"},
        {"stall_persistence": "0"},
        {"stall_persistence": "256"},
    ],
)
def test_homing_config_rejects_out_of_range(values):
    with pytest.raises(CommandError):
        printer, _chips, sections, _config = make_foci_config(
            stepper_values={"rotation_distance": 40.0},
            foci_values={"run_current": 2.3, **values},
        )
        make_config_driver(printer, sections, "foci stepper_x")


@pytest.mark.parametrize(
    "values,field_name,expected",
    [
        ({"stall_distance": "10.0"}, "stall_distance", 10.0),
        ({"stall_persistence": "1"}, "stall_persistence", 1),
        ({"stall_persistence": "255"}, "stall_persistence", 255),
        ({"homing_current": "2.0"}, "homing_current", 2.0),
    ],
)
def test_homing_config_accepts_boundary_values(values, field_name, expected):
    printer, _chips, sections, _config = make_foci_config(
        stepper_values={"rotation_distance": 40.0},
        foci_values={"run_current": 2.3, **values},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    assert getattr(driver.config, field_name) == expected


def test_homing_current_zero_opts_out():
    printer, _chips, sections, _config = make_foci_config(foci_values={"homing_current": "0"})
    driver = make_config_driver(printer, sections, "foci stepper_x")
    assert driver.config.homing_current == 0.0
