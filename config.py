"""Per-driver config parsing for klipper-foci."""

from __future__ import annotations

import logging
from dataclasses import dataclass, fields

from .constants import (
    DEFAULT_OPERATIONAL_VOLTAGE_LIMIT,
    MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
    MAX_RUN_CURRENT_AMPS,
    MIN_RAW_VOLTAGE_LIMIT,
    PID_GAIN_MAX_RAW,
)
from .state import RuntimeStatus

STEP_PINS: dict[str, int] = {"STEP0": 0, "STEP1": 1}
FILTER_MIN_HZ = 10
MOTION_FILTER_MAX_HZ = 1000
CURRENT_FILTER_MAX_HZ = 6000
MAX_ENCODER_PPR = 0x3FFF_FFFF


@dataclass
class FociDriverConfig:
    """Parsed config for one ``[foci <stepper>]`` section."""

    name: str
    stepper_name: str
    run_current: float
    encoder_ppr: int
    voltage_limit: int
    encoder_reversed: bool
    rotation_distance: float
    microsteps: int
    full_steps: int
    planner_steps_per_rev: int
    step_pin_name: str
    mcu: object
    channel: int
    pid_flux_p: int | None
    pid_flux_i: int | None
    pid_torque_p: int | None
    pid_torque_i: int | None
    velocity_filter_hz: int | None
    torque_filter_hz: int | None
    position_filter_hz: int | None
    flux_filter_hz: int | None
    pid_position_p: int | None
    pid_position_i: int | None
    pid_velocity_p: int | None
    pid_velocity_i: int | None
    velocity_feedforward: bool
    velocity_feedforward_multiplier: int
    velocity_transient_feedforward: bool
    velocity_transient_lead_time_us: int
    velocity_transient_gain: int
    velocity_transient_max_offset: int
    velocity_transient_rate_hz: int
    accel_feedforward: bool
    accel_feedforward_accel_gain: int
    accel_feedforward_decel_gain: int
    decoupling_feedforward: bool
    decoupling_r_int: int
    decoupling_l_int: int
    decoupling_pole_pairs: int
    decoupling_position_units_per_rev: int
    decoupling_f_pwm_hz: int
    decoupling_max_offset: int
    position_lead: bool
    position_lead_gain: int
    position_lead_max_counts: int
    phase_advance: bool
    phase_advance_gain_ppm: int
    phase_advance_max_counts: int
    phase_advance_deadband: int
    pid_velocity_limit: int | None
    commissioned_velocity_p: int | None
    commissioned_velocity_i: int | None
    commissioned_position_p: int | None
    commissioned_position_i: int | None
    commissioned_velocity_limit: int | None
    identified_r_count_milli: int | None
    identified_l_count_micro: int | None
    identified_lambda_us: int | None
    identified_theta_e_us: int | None
    identified_ringing_count: int | None
    identified_bandwidth_hz: int | None
    identified_tau_e_us: int | None
    identified_inner_warning_flags: int | None
    identified_l_source: int | None
    identified_l_warning_flags: int | None
    identified_l_frequency_millihz: int | None
    identified_l_reactance_count_ratio_milli: int | None
    identified_l_d_reactance_count_ratio_milli: int | None
    identified_l_q_reactance_count_ratio_milli: int | None
    identified_l_saliency_status: int | None
    identified_l_saliency_permille: int | None
    identified_l_iq_mean_milli_count: int | None
    identified_l_drift_permille: int | None
    identified_l_r_shift_minus_permille: int | None
    identified_l_r_shift_plus_permille: int | None
    identified_l_x_mag_vs_quad_permille: int | None
    identified_j_eff: int | None
    identified_b_eff: int | None
    identified_current_gains_source: int | None
    identified_current_candidate_gains_source: int | None
    identified_axis_split_source: int | None
    identified_current_candidate_axis_split_source: int | None
    identified_current_gains_tier: int | None
    identified_current_candidate_gains_tier: int | None
    identified_current_measured_axis_split_permille: int | None
    identified_current_candidate_measured_axis_split_permille: int | None
    identified_current_applied_axis_split_permille: int | None
    identified_current_candidate_applied_axis_split_permille: int | None
    identified_current_axis_split_clamped: int | None
    identified_current_candidate_axis_split_clamped: int | None
    identified_current_candidate_flux_p: int | None
    identified_current_candidate_flux_i: int | None
    identified_current_candidate_torque_p: int | None
    identified_current_candidate_torque_i: int | None
    identified_current_candidate_attempt: int | None
    identified_current_validation_axes: int | None
    identified_current_flux_validation_sample_count: int | None
    identified_current_torque_validation_sample_count: int | None
    identified_current_retry_budget_exhausted: int | None
    identified_current_failure_reason: int | None
    identified_current_flux_response_min_permille: int | None
    identified_current_torque_response_min_permille: int | None
    identified_current_flux_encoder_delta_counts: int | None
    identified_current_torque_encoder_delta_counts: int | None
    identified_r_count_slope_milli: int | None
    identified_r_gain_path_count_slope_milli: int | None
    identified_r_axis0_count_slope_milli: int | None
    identified_r_axis1_count_slope_milli: int | None
    identified_r_axis0_intercept_count: int | None
    identified_r_axis1_intercept_count: int | None
    identified_r_axis0_rmse_permille: int | None
    identified_r_axis1_rmse_permille: int | None
    identified_r_selected_mask_axis0: int | None
    identified_r_selected_mask_axis1: int | None
    identified_r_axis0_signed_count_slope_milli: int | None
    identified_r_axis1_signed_count_slope_milli: int | None
    identified_r_axis0_signed_asymmetry_permille: int | None
    identified_r_axis1_signed_asymmetry_permille: int | None
    identified_r_axis0_drift_permille: int | None
    identified_r_axis1_drift_permille: int | None
    identified_r_status_flags_or: int | None
    identified_r_warning_flags: int | None
    identified_r_peak_abs_current_count: int | None
    identified_r_max_abs_steady_mean_current_count: int | None
    identified_r_current_ceiling_count: int | None
    autotune_profile: str | None
    autotune_mode: str | None
    autotune_status: str | None
    autotune_probed_velocity_mrev_s: int | None
    autotune_d_eq_q: int | None
    autotune_confidence_q: int | None
    autotune_band_lower_percent: int | None
    autotune_band_upper_percent: int | None
    autotune_band_position_q: int | None


@dataclass
class FociControlSettings:
    """Mutable live control settings seeded from parsed driver config."""

    run_current: float
    voltage_limit: int
    pid_flux_p: int | None
    pid_flux_i: int | None
    pid_torque_p: int | None
    pid_torque_i: int | None
    velocity_filter_hz: int | None
    torque_filter_hz: int | None
    position_filter_hz: int | None
    flux_filter_hz: int | None
    pid_position_p: int | None
    pid_position_i: int | None
    pid_velocity_p: int | None
    pid_velocity_i: int | None
    velocity_feedforward: bool
    velocity_feedforward_multiplier: int
    velocity_transient_feedforward: bool
    velocity_transient_lead_time_us: int
    velocity_transient_gain: int
    velocity_transient_max_offset: int
    velocity_transient_rate_hz: int
    accel_feedforward: bool
    accel_feedforward_accel_gain: int
    accel_feedforward_decel_gain: int
    decoupling_feedforward: bool
    decoupling_r_int: int
    decoupling_l_int: int
    decoupling_pole_pairs: int
    decoupling_position_units_per_rev: int
    decoupling_f_pwm_hz: int
    decoupling_max_offset: int
    position_lead: bool
    position_lead_gain: int
    position_lead_max_counts: int
    phase_advance: bool
    phase_advance_gain_ppm: int
    phase_advance_max_counts: int
    phase_advance_deadband: int
    pid_velocity_limit: int | None

    @classmethod
    def from_config(cls, config: FociDriverConfig) -> FociControlSettings:
        """Seed mutable live settings from parsed config values."""
        return cls(**{field.name: getattr(config, field.name) for field in fields(cls)})


CONTROL_SETTING_FIELDS = tuple(field.name for field in fields(FociControlSettings))


@dataclass
class RuntimeValidationResult:
    """Accepted persisted runtime state derived from driver config."""

    runtime_status: RuntimeStatus
    active_gains: dict[str, int | None] | None


def _validate_complete_group(config, section_name, label, values) -> None:
    present = [value for value in values if value is not None]
    if present and len(present) != len(values):
        if label == "inner_pid":
            raise config.error(
                f"PID gains must be set as a complete group (pid_flux_p, pid_flux_i, "
                f"pid_torque_p, pid_torque_i). Found {len(present)} of 4 in [{section_name}]"
            )
        raise config.error(
            f"pid_position_p/i and pid_velocity_p/i must be set together (pid_position_p, "
            f"pid_position_i, pid_velocity_p, pid_velocity_i). Found {len(present)} of 4 in ["
            f"{section_name}]"
        )


def _filter_hz(config, section_name, option, max_hz):
    value = config.getint(option, None, minval=0, maxval=max_hz)
    if value is None:
        return None
    if value != 0 and value < FILTER_MIN_HZ:
        raise config.error(
            f"{option} must be 0 (disabled) or {int(FILTER_MIN_HZ)}..{int(max_hz)} in ["
            f"{section_name}]"
        )
    return value


def parse_driver_config(config) -> FociDriverConfig:
    """Parse one ``[foci <stepper>]`` config section."""
    name = config.get_name()
    stepper_name = " ".join(name.split()[1:])
    printer = config.get_printer()

    run_current = config.getfloat(
        "run_current",
        above=0.0,
        maxval=MAX_RUN_CURRENT_AMPS,
    )
    encoder_ppr = config.getint("encoder_ppr", minval=1)
    if encoder_ppr > MAX_ENCODER_PPR:
        raise config.error(
            f"encoder_ppr {int(encoder_ppr)} in [{name}] is outside 1..{int(MAX_ENCODER_PPR)}"
        )
    voltage_limit = config.getint(
        "voltage_limit",
        DEFAULT_OPERATIONAL_VOLTAGE_LIMIT,
        minval=MIN_RAW_VOLTAGE_LIMIT,
        maxval=MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
    )
    encoder_reversed = config.getchoice(
        "encoder_direction",
        {"default": False, "reversed": True},
        default="default",
    )

    pid_flux_p = config.getint("pid_flux_p", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    pid_flux_i = config.getint("pid_flux_i", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    pid_torque_p = config.getint("pid_torque_p", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    pid_torque_i = config.getint("pid_torque_i", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    _validate_complete_group(
        config,
        name,
        "inner_pid",
        [pid_flux_p, pid_flux_i, pid_torque_p, pid_torque_i],
    )

    velocity_filter_hz = _filter_hz(config, name, "velocity_filter_hz", MOTION_FILTER_MAX_HZ)
    torque_filter_hz = _filter_hz(config, name, "torque_filter_hz", CURRENT_FILTER_MAX_HZ)
    position_filter_hz = _filter_hz(config, name, "position_filter_hz", MOTION_FILTER_MAX_HZ)
    flux_filter_hz = _filter_hz(config, name, "flux_filter_hz", CURRENT_FILTER_MAX_HZ)

    pid_position_p = config.getint("pid_position_p", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    pid_position_i = config.getint("pid_position_i", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    pid_velocity_p = config.getint("pid_velocity_p", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    pid_velocity_i = config.getint("pid_velocity_i", None, minval=0, maxval=PID_GAIN_MAX_RAW)
    _validate_complete_group(
        config,
        name,
        "position_velocity_pid",
        [pid_position_p, pid_position_i, pid_velocity_p, pid_velocity_i],
    )

    velocity_feedforward = config.getboolean("velocity_feedforward", False)
    velocity_feedforward_multiplier = config.getint(
        "velocity_feedforward_multiplier", 1, minval=0, maxval=65535
    )
    pid_velocity_limit = config.getint("pid_velocity_limit", None, minval=1, maxval=0x7FFFFFFF)

    commissioned_velocity_p = config.getint(
        "commissioned_velocity_p", None, minval=0, maxval=PID_GAIN_MAX_RAW
    )
    commissioned_velocity_i = config.getint(
        "commissioned_velocity_i", None, minval=0, maxval=PID_GAIN_MAX_RAW
    )
    commissioned_position_p = config.getint(
        "commissioned_position_p", None, minval=0, maxval=PID_GAIN_MAX_RAW
    )
    commissioned_position_i = config.getint(
        "commissioned_position_i", None, minval=0, maxval=PID_GAIN_MAX_RAW
    )
    commissioned_velocity_limit = config.getint(
        "commissioned_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
    )

    identified_r_count_milli = config.getint("identified_r_count_milli", None, minval=0)
    identified_l_count_micro = config.getint("identified_l_count_micro", None, minval=0)
    identified_lambda_us = config.getint("identified_lambda_us", None, minval=0)
    identified_theta_e_us = config.getint("identified_theta_e_us", None, minval=0)
    identified_ringing_count = config.getint("identified_ringing_count", None, minval=0, maxval=255)
    identified_bandwidth_hz = config.getint("identified_bandwidth_hz", None, minval=0)
    identified_tau_e_us = config.getint("identified_tau_e_us", None, minval=0)
    identified_inner_warning_flags = config.getint(
        "identified_inner_warning_flags", None, minval=0, maxval=255
    )
    identified_l_source = config.getint("identified_l_source", None, minval=0, maxval=255)
    identified_l_warning_flags = config.getint(
        "identified_l_warning_flags", None, minval=0, maxval=0xFFFF
    )
    identified_l_frequency_millihz = config.getint("identified_l_frequency_millihz", None, minval=0)
    identified_l_reactance_count_ratio_milli = config.getint(
        "identified_l_reactance_count_ratio_milli", None, minval=0
    )
    identified_l_d_reactance_count_ratio_milli = config.getint(
        "identified_l_d_reactance_count_ratio_milli", None, minval=0
    )
    identified_l_q_reactance_count_ratio_milli = config.getint(
        "identified_l_q_reactance_count_ratio_milli", None, minval=0
    )
    identified_l_saliency_status = config.getint(
        "identified_l_saliency_status", None, minval=0, maxval=255
    )
    identified_l_saliency_permille = config.getint(
        "identified_l_saliency_permille", None, minval=0, maxval=1000
    )
    identified_l_iq_mean_milli_count = config.getint("identified_l_iq_mean_milli_count", None)
    identified_l_drift_permille = config.getint(
        "identified_l_drift_permille", None, minval=0, maxval=1000
    )
    identified_l_r_shift_minus_permille = config.getint(
        "identified_l_r_shift_minus_permille", None, minval=0, maxval=1000
    )
    identified_l_r_shift_plus_permille = config.getint(
        "identified_l_r_shift_plus_permille", None, minval=0, maxval=1000
    )
    identified_l_x_mag_vs_quad_permille = config.getint(
        "identified_l_x_mag_vs_quad_permille", None, minval=0, maxval=1000
    )
    identified_j_eff = config.getint("identified_j_eff", None, minval=0)
    identified_b_eff = config.getint("identified_b_eff", None, minval=0)
    identified_current_gains_source = config.getint(
        "identified_current_gains_source", None, minval=0, maxval=255
    )
    identified_current_candidate_gains_source = config.getint(
        "identified_current_candidate_gains_source", None, minval=0, maxval=255
    )
    identified_axis_split_source = config.getint(
        "identified_axis_split_source", None, minval=0, maxval=255
    )
    identified_current_candidate_axis_split_source = config.getint(
        "identified_current_candidate_axis_split_source", None, minval=0, maxval=255
    )
    identified_current_gains_tier = config.getint(
        "identified_current_gains_tier", None, minval=0, maxval=255
    )
    identified_current_candidate_gains_tier = config.getint(
        "identified_current_candidate_gains_tier", None, minval=0, maxval=255
    )
    identified_current_measured_axis_split_permille = config.getint(
        "identified_current_measured_axis_split_permille", None, minval=0, maxval=65535
    )
    identified_current_candidate_measured_axis_split_permille = config.getint(
        "identified_current_candidate_measured_axis_split_permille",
        None,
        minval=0,
        maxval=65535,
    )
    identified_current_applied_axis_split_permille = config.getint(
        "identified_current_applied_axis_split_permille", None, minval=0, maxval=65535
    )
    identified_current_candidate_applied_axis_split_permille = config.getint(
        "identified_current_candidate_applied_axis_split_permille",
        None,
        minval=0,
        maxval=65535,
    )
    identified_current_axis_split_clamped = config.getint(
        "identified_current_axis_split_clamped", None, minval=0, maxval=255
    )
    identified_current_candidate_axis_split_clamped = config.getint(
        "identified_current_candidate_axis_split_clamped", None, minval=0, maxval=255
    )
    identified_current_candidate_flux_p = config.getint(
        "identified_current_candidate_flux_p", None, minval=0, maxval=65535
    )
    identified_current_candidate_flux_i = config.getint(
        "identified_current_candidate_flux_i", None, minval=0, maxval=65535
    )
    identified_current_candidate_torque_p = config.getint(
        "identified_current_candidate_torque_p", None, minval=0, maxval=65535
    )
    identified_current_candidate_torque_i = config.getint(
        "identified_current_candidate_torque_i", None, minval=0, maxval=65535
    )
    identified_current_candidate_attempt = config.getint(
        "identified_current_candidate_attempt", None, minval=0, maxval=255
    )
    identified_current_validation_axes = config.getint(
        "identified_current_validation_axes", None, minval=0, maxval=255
    )
    identified_current_flux_validation_sample_count = config.getint(
        "identified_current_flux_validation_sample_count", None, minval=0, maxval=255
    )
    identified_current_torque_validation_sample_count = config.getint(
        "identified_current_torque_validation_sample_count", None, minval=0, maxval=255
    )
    identified_current_retry_budget_exhausted = config.getint(
        "identified_current_retry_budget_exhausted", None, minval=0, maxval=255
    )
    identified_current_failure_reason = config.getint(
        "identified_current_failure_reason", None, minval=0, maxval=255
    )
    identified_current_flux_response_min_permille = config.getint(
        "identified_current_flux_response_min_permille", None, minval=0, maxval=65535
    )
    identified_current_torque_response_min_permille = config.getint(
        "identified_current_torque_response_min_permille", None, minval=0, maxval=65535
    )
    identified_current_flux_encoder_delta_counts = config.getint(
        "identified_current_flux_encoder_delta_counts", None, minval=0, maxval=65535
    )
    identified_current_torque_encoder_delta_counts = config.getint(
        "identified_current_torque_encoder_delta_counts", None, minval=0, maxval=65535
    )

    identified_r_count_slope_milli = config.getint("identified_r_count_slope_milli", None)
    identified_r_gain_path_count_slope_milli = config.getint(
        "identified_r_gain_path_count_slope_milli", None
    )
    identified_r_axis0_count_slope_milli = config.getint(
        "identified_r_axis0_count_slope_milli", None
    )
    identified_r_axis1_count_slope_milli = config.getint(
        "identified_r_axis1_count_slope_milli", None
    )
    identified_r_axis0_intercept_count = config.getint("identified_r_axis0_intercept_count", None)
    identified_r_axis1_intercept_count = config.getint("identified_r_axis1_intercept_count", None)
    identified_r_axis0_rmse_permille = config.getint(
        "identified_r_axis0_rmse_permille", None, minval=0, maxval=1000
    )
    identified_r_axis1_rmse_permille = config.getint(
        "identified_r_axis1_rmse_permille", None, minval=0, maxval=1000
    )
    identified_r_selected_mask_axis0 = config.getint(
        "identified_r_selected_mask_axis0", None, minval=0, maxval=0xFFFF
    )
    identified_r_selected_mask_axis1 = config.getint(
        "identified_r_selected_mask_axis1", None, minval=0, maxval=0xFFFF
    )
    identified_r_axis0_signed_count_slope_milli = config.getint(
        "identified_r_axis0_signed_count_slope_milli", None
    )
    identified_r_axis1_signed_count_slope_milli = config.getint(
        "identified_r_axis1_signed_count_slope_milli", None
    )
    identified_r_axis0_signed_asymmetry_permille = config.getint(
        "identified_r_axis0_signed_asymmetry_permille", None, minval=0, maxval=1000
    )
    identified_r_axis1_signed_asymmetry_permille = config.getint(
        "identified_r_axis1_signed_asymmetry_permille", None, minval=0, maxval=1000
    )
    identified_r_axis0_drift_permille = config.getint(
        "identified_r_axis0_drift_permille", None, minval=0, maxval=1000
    )
    identified_r_axis1_drift_permille = config.getint(
        "identified_r_axis1_drift_permille", None, minval=0, maxval=1000
    )
    identified_r_status_flags_or = config.getint("identified_r_status_flags_or", None, minval=0)
    identified_r_warning_flags = config.getint("identified_r_warning_flags", None, minval=0)
    identified_r_peak_abs_current_count = config.getint(
        "identified_r_peak_abs_current_count", None, minval=0, maxval=0xFFFF
    )
    identified_r_max_abs_steady_mean_current_count = config.getint(
        "identified_r_max_abs_steady_mean_current_count",
        None,
        minval=0,
        maxval=0xFFFF,
    )
    identified_r_current_ceiling_count = config.getint(
        "identified_r_current_ceiling_count", None, minval=0, maxval=0xFFFF
    )

    autotune_profile = config.get("autotune_profile", None)
    autotune_mode = config.get("autotune_mode", None)
    autotune_status = config.get("autotune_status", None)
    autotune_probed_velocity_mrev_s = config.getint(
        "autotune_probed_velocity_mrev_s", None, minval=0
    )
    autotune_d_eq_q = config.getint("autotune_d_eq_q", None)
    autotune_confidence_q = config.getint("autotune_confidence_q", None, minval=0, maxval=0xFFFF)
    autotune_band_lower_percent = config.getint(
        "autotune_band_lower_percent", None, minval=0, maxval=100
    )
    autotune_band_upper_percent = config.getint(
        "autotune_band_upper_percent", None, minval=0, maxval=100
    )
    autotune_band_position_q = config.getint(
        "autotune_band_position_q", None, minval=0, maxval=0xFFFF
    )

    if not config.has_section(stepper_name):
        raise config.error(f"[{name}] cannot find stepper section for '{stepper_name}'")
    stepper_config = config.getsection(stepper_name)
    microsteps = stepper_config.getint("microsteps")
    full_steps = stepper_config.getint("full_steps_per_rotation", 200)
    rotation_distance = stepper_config.getfloat("rotation_distance", above=0.0)
    planner_steps_per_rev = microsteps * full_steps
    if not 1 <= planner_steps_per_rev <= 16_777_216:
        raise config.error(
            f"[{name}] stepper {stepper_name} planner_steps_per_rev="
            f"{int(planner_steps_per_rev)} (full_steps_per_rotation={int(full_steps)} * "
            f"microsteps={int(microsteps)}) must be in 1..16777216"
        )
    step_pin = stepper_config.get("step_pin")
    ppins = printer.lookup_object("pins")
    pin_params = ppins.parse_pin(step_pin, can_invert=True)
    step_pin_name = pin_params["pin"]
    if step_pin_name not in STEP_PINS:
        raise config.error(
            f"[{name}] step_pin '{step_pin_name}' is not a FOCI STEP pin (expected one of: "
            f"{', '.join(sorted(STEP_PINS))})"
        )

    return FociDriverConfig(
        name=name,
        stepper_name=stepper_name,
        run_current=run_current,
        encoder_ppr=encoder_ppr,
        voltage_limit=voltage_limit,
        encoder_reversed=encoder_reversed,
        rotation_distance=rotation_distance,
        microsteps=microsteps,
        full_steps=full_steps,
        planner_steps_per_rev=planner_steps_per_rev,
        step_pin_name=step_pin_name,
        mcu=pin_params["chip"],
        channel=STEP_PINS[step_pin_name],
        pid_flux_p=pid_flux_p,
        pid_flux_i=pid_flux_i,
        pid_torque_p=pid_torque_p,
        pid_torque_i=pid_torque_i,
        velocity_filter_hz=velocity_filter_hz,
        torque_filter_hz=torque_filter_hz,
        position_filter_hz=position_filter_hz,
        flux_filter_hz=flux_filter_hz,
        pid_position_p=pid_position_p,
        pid_position_i=pid_position_i,
        pid_velocity_p=pid_velocity_p,
        pid_velocity_i=pid_velocity_i,
        velocity_feedforward=velocity_feedforward,
        velocity_feedforward_multiplier=velocity_feedforward_multiplier,
        velocity_transient_feedforward=False,
        velocity_transient_lead_time_us=0,
        velocity_transient_gain=0,
        velocity_transient_max_offset=0,
        velocity_transient_rate_hz=1000,
        accel_feedforward=False,
        accel_feedforward_accel_gain=1000,
        accel_feedforward_decel_gain=1000,
        decoupling_feedforward=False,
        decoupling_r_int=3000,
        decoupling_l_int=4095,
        decoupling_pole_pairs=50,
        decoupling_position_units_per_rev=65536,
        decoupling_f_pwm_hz=25000,
        decoupling_max_offset=500,
        position_lead=False,
        position_lead_gain=0,
        position_lead_max_counts=0,
        phase_advance=False,
        phase_advance_gain_ppm=0,
        phase_advance_max_counts=0,
        phase_advance_deadband=16,
        pid_velocity_limit=pid_velocity_limit,
        commissioned_velocity_p=commissioned_velocity_p,
        commissioned_velocity_i=commissioned_velocity_i,
        commissioned_position_p=commissioned_position_p,
        commissioned_position_i=commissioned_position_i,
        commissioned_velocity_limit=commissioned_velocity_limit,
        identified_r_count_milli=identified_r_count_milli,
        identified_l_count_micro=identified_l_count_micro,
        identified_lambda_us=identified_lambda_us,
        identified_theta_e_us=identified_theta_e_us,
        identified_ringing_count=identified_ringing_count,
        identified_bandwidth_hz=identified_bandwidth_hz,
        identified_tau_e_us=identified_tau_e_us,
        identified_inner_warning_flags=identified_inner_warning_flags,
        identified_l_source=identified_l_source,
        identified_l_warning_flags=identified_l_warning_flags,
        identified_l_frequency_millihz=identified_l_frequency_millihz,
        identified_l_reactance_count_ratio_milli=(identified_l_reactance_count_ratio_milli),
        identified_l_d_reactance_count_ratio_milli=(identified_l_d_reactance_count_ratio_milli),
        identified_l_q_reactance_count_ratio_milli=(identified_l_q_reactance_count_ratio_milli),
        identified_l_saliency_status=identified_l_saliency_status,
        identified_l_saliency_permille=identified_l_saliency_permille,
        identified_l_iq_mean_milli_count=identified_l_iq_mean_milli_count,
        identified_l_drift_permille=identified_l_drift_permille,
        identified_l_r_shift_minus_permille=identified_l_r_shift_minus_permille,
        identified_l_r_shift_plus_permille=identified_l_r_shift_plus_permille,
        identified_l_x_mag_vs_quad_permille=identified_l_x_mag_vs_quad_permille,
        identified_j_eff=identified_j_eff,
        identified_b_eff=identified_b_eff,
        identified_current_gains_source=identified_current_gains_source,
        identified_current_candidate_gains_source=(identified_current_candidate_gains_source),
        identified_axis_split_source=identified_axis_split_source,
        identified_current_candidate_axis_split_source=(
            identified_current_candidate_axis_split_source
        ),
        identified_current_gains_tier=identified_current_gains_tier,
        identified_current_candidate_gains_tier=(identified_current_candidate_gains_tier),
        identified_current_measured_axis_split_permille=(
            identified_current_measured_axis_split_permille
        ),
        identified_current_candidate_measured_axis_split_permille=(
            identified_current_candidate_measured_axis_split_permille
        ),
        identified_current_applied_axis_split_permille=(
            identified_current_applied_axis_split_permille
        ),
        identified_current_candidate_applied_axis_split_permille=(
            identified_current_candidate_applied_axis_split_permille
        ),
        identified_current_axis_split_clamped=identified_current_axis_split_clamped,
        identified_current_candidate_axis_split_clamped=(
            identified_current_candidate_axis_split_clamped
        ),
        identified_current_candidate_flux_p=identified_current_candidate_flux_p,
        identified_current_candidate_flux_i=identified_current_candidate_flux_i,
        identified_current_candidate_torque_p=identified_current_candidate_torque_p,
        identified_current_candidate_torque_i=identified_current_candidate_torque_i,
        identified_current_candidate_attempt=identified_current_candidate_attempt,
        identified_current_validation_axes=identified_current_validation_axes,
        identified_current_flux_validation_sample_count=(
            identified_current_flux_validation_sample_count
        ),
        identified_current_torque_validation_sample_count=(
            identified_current_torque_validation_sample_count
        ),
        identified_current_retry_budget_exhausted=(identified_current_retry_budget_exhausted),
        identified_current_failure_reason=identified_current_failure_reason,
        identified_current_flux_response_min_permille=(
            identified_current_flux_response_min_permille
        ),
        identified_current_torque_response_min_permille=(
            identified_current_torque_response_min_permille
        ),
        identified_current_flux_encoder_delta_counts=(identified_current_flux_encoder_delta_counts),
        identified_current_torque_encoder_delta_counts=(
            identified_current_torque_encoder_delta_counts
        ),
        identified_r_count_slope_milli=identified_r_count_slope_milli,
        identified_r_gain_path_count_slope_milli=(identified_r_gain_path_count_slope_milli),
        identified_r_axis0_count_slope_milli=identified_r_axis0_count_slope_milli,
        identified_r_axis1_count_slope_milli=identified_r_axis1_count_slope_milli,
        identified_r_axis0_intercept_count=identified_r_axis0_intercept_count,
        identified_r_axis1_intercept_count=identified_r_axis1_intercept_count,
        identified_r_axis0_rmse_permille=identified_r_axis0_rmse_permille,
        identified_r_axis1_rmse_permille=identified_r_axis1_rmse_permille,
        identified_r_selected_mask_axis0=identified_r_selected_mask_axis0,
        identified_r_selected_mask_axis1=identified_r_selected_mask_axis1,
        identified_r_axis0_signed_count_slope_milli=(identified_r_axis0_signed_count_slope_milli),
        identified_r_axis1_signed_count_slope_milli=(identified_r_axis1_signed_count_slope_milli),
        identified_r_axis0_signed_asymmetry_permille=(identified_r_axis0_signed_asymmetry_permille),
        identified_r_axis1_signed_asymmetry_permille=(identified_r_axis1_signed_asymmetry_permille),
        identified_r_axis0_drift_permille=identified_r_axis0_drift_permille,
        identified_r_axis1_drift_permille=identified_r_axis1_drift_permille,
        identified_r_status_flags_or=identified_r_status_flags_or,
        identified_r_warning_flags=identified_r_warning_flags,
        identified_r_peak_abs_current_count=identified_r_peak_abs_current_count,
        identified_r_max_abs_steady_mean_current_count=(
            identified_r_max_abs_steady_mean_current_count
        ),
        identified_r_current_ceiling_count=identified_r_current_ceiling_count,
        autotune_profile=autotune_profile,
        autotune_mode=autotune_mode,
        autotune_status=autotune_status,
        autotune_probed_velocity_mrev_s=autotune_probed_velocity_mrev_s,
        autotune_d_eq_q=autotune_d_eq_q,
        autotune_confidence_q=autotune_confidence_q,
        autotune_band_lower_percent=autotune_band_lower_percent,
        autotune_band_upper_percent=autotune_band_upper_percent,
        autotune_band_position_q=autotune_band_position_q,
    )


def validate_runtime_config(config: FociDriverConfig) -> RuntimeValidationResult:
    """Validate persisted config and build active gains/runtime status."""
    status = config.autotune_status
    if status is None:
        return RuntimeValidationResult("uncommissioned", None)

    valid_statuses = ("commissioned", "tuned", "tuned_conservative")
    if status not in valid_statuses:
        logging.warning(
            "FOCI %s: unknown autotune_status='%s' (expected one of: %s). "
            "Motor cannot be enabled until FOCI_COMMISSION is run.",
            config.name,
            status,
            ", ".join(valid_statuses),
        )
        return RuntimeValidationResult("uncommissioned", None)

    required_base = [
        ("pid_flux_p", config.pid_flux_p),
        ("pid_flux_i", config.pid_flux_i),
        ("pid_torque_p", config.pid_torque_p),
        ("pid_torque_i", config.pid_torque_i),
        ("identified_lambda_us", config.identified_lambda_us),
        ("identified_theta_e_us", config.identified_theta_e_us),
        ("identified_ringing_count", config.identified_ringing_count),
        ("identified_bandwidth_hz", config.identified_bandwidth_hz),
    ]
    missing = [name for name, value in required_base if value is None]

    if status == "commissioned":
        commissioned_fields = [
            ("commissioned_velocity_p", config.commissioned_velocity_p),
            ("commissioned_velocity_i", config.commissioned_velocity_i),
            ("commissioned_position_p", config.commissioned_position_p),
            ("commissioned_position_i", config.commissioned_position_i),
            ("commissioned_velocity_limit", config.commissioned_velocity_limit),
        ]
        missing.extend(name for name, value in commissioned_fields if value is None)
    elif status in ("tuned", "tuned_conservative"):
        tuned_fields = [
            ("pid_velocity_p", config.pid_velocity_p),
            ("pid_velocity_i", config.pid_velocity_i),
            ("pid_velocity_limit", config.pid_velocity_limit),
            ("pid_position_p", config.pid_position_p),
            ("pid_position_i", config.pid_position_i),
        ]
        missing.extend(name for name, value in tuned_fields if value is None)

    if missing:
        logging.warning(
            "FOCI %s: autotune_status='%s' but missing required fields: %s. "
            "Motor cannot be enabled until FOCI_COMMISSION is run.",
            config.name,
            status,
            ", ".join(missing),
        )
        return RuntimeValidationResult("uncommissioned", None)

    if status == "commissioned":
        active_gains = {
            "flux_p": config.pid_flux_p,
            "flux_i": config.pid_flux_i,
            "torque_p": config.pid_torque_p,
            "torque_i": config.pid_torque_i,
            "velocity_p": config.commissioned_velocity_p,
            "velocity_i": config.commissioned_velocity_i,
            "position_p": config.commissioned_position_p,
            "position_i": config.commissioned_position_i,
            "velocity_limit": config.commissioned_velocity_limit,
            "velocity_filter_hz": config.velocity_filter_hz,
            "torque_filter_hz": config.torque_filter_hz,
            "position_filter_hz": config.position_filter_hz,
            "flux_filter_hz": config.flux_filter_hz,
        }
    else:
        active_gains = {
            "flux_p": config.pid_flux_p,
            "flux_i": config.pid_flux_i,
            "torque_p": config.pid_torque_p,
            "torque_i": config.pid_torque_i,
            "velocity_p": config.pid_velocity_p,
            "velocity_i": config.pid_velocity_i,
            "position_p": config.pid_position_p,
            "position_i": config.pid_position_i,
            "velocity_limit": config.pid_velocity_limit,
            "velocity_filter_hz": config.velocity_filter_hz,
            "torque_filter_hz": config.torque_filter_hz,
            "position_filter_hz": config.position_filter_hz,
            "flux_filter_hz": config.flux_filter_hz,
        }

    logging.info(
        "FOCI %s: loaded config, status=%s, active gains ready",
        config.name,
        status,
    )
    return RuntimeValidationResult(status, active_gains)
