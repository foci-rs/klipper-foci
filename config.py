"""Per-driver config parsing for klipper-foci."""

from __future__ import annotations

import logging

from dataclasses import dataclass, fields

from .constants import (
    DEFAULT_OPERATIONAL_VOLTAGE_LIMIT,
    MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
    MIN_RAW_VOLTAGE_LIMIT,
)
from .state import RuntimeStatus

STEP_PINS: dict[str, int] = {"STEP0": 0, "STEP1": 1}


@dataclass
class FociDriverConfig:
    """Parsed config for one ``[foci <stepper>]`` section."""

    name: str
    stepper_name: str
    run_current: float
    encoder_ppr: int
    voltage_limit: int
    encoder_reversed: bool
    microsteps: int
    full_steps: int
    step_pin_name: str
    mcu: object
    channel: int
    pid_flux_p: int | None
    pid_flux_i: int | None
    pid_torque_p: int | None
    pid_torque_i: int | None
    velocity_filter_hz: int
    torque_filter_hz: int
    position_filter_hz: int
    flux_filter_hz: int
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
    identified_r_int: int | None
    identified_l_int: int | None
    identified_r_count_milli: int | None
    identified_l_count_micro: int | None
    identified_lambda_us: int | None
    identified_theta_e_us: int | None
    identified_ringing_count: int | None
    identified_bandwidth_hz: int | None
    identified_tau_e_us: int | None
    identified_tau_e_crosscheck_us: int | None
    identified_tau_residual_permille: int | None
    identified_inner_warning_flags: int | None
    identified_j_eff: int | None
    identified_b_eff: int | None
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
    identified_r_profile_version: int | None
    identified_r_axis0_signed_count_slope_milli: int | None
    identified_r_axis1_signed_count_slope_milli: int | None
    identified_r_axis0_signed_asymmetry_permille: int | None
    identified_r_axis1_signed_asymmetry_permille: int | None
    identified_r_axis0_drift_permille: int | None
    identified_r_axis1_drift_permille: int | None
    identified_r_status_flags_or: int | None
    identified_r_warning_flags: int | None
    autotune_profile: str | None
    autotune_mode: str | None
    autotune_status: str | None


@dataclass
class FociControlSettings:
    """Mutable live control settings seeded from parsed driver config."""

    run_current: float
    voltage_limit: int
    pid_flux_p: int | None
    pid_flux_i: int | None
    pid_torque_p: int | None
    pid_torque_i: int | None
    velocity_filter_hz: int
    torque_filter_hz: int
    position_filter_hz: int
    flux_filter_hz: int
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
    def from_config(cls, config: FociDriverConfig) -> "FociControlSettings":
        """Seed mutable live settings from parsed config values."""
        return cls(**{field.name: getattr(config, field.name) for field in fields(cls)})


CONTROL_SETTING_FIELDS = tuple(field.name for field in fields(FociControlSettings))


@dataclass
class RuntimeValidationResult:
    """Accepted persisted runtime state derived from driver config."""

    runtime_status: RuntimeStatus
    active_gains: dict[str, int] | None


def _validate_complete_group(config, section_name, label, values) -> None:
    present = [value for value in values if value is not None]
    if present and len(present) != len(values):
        if label == "inner_pid":
            raise config.error(
                "PID gains must be set as a complete group"
                " (pid_flux_p, pid_flux_i, pid_torque_p, pid_torque_i)."
                " Found %d of 4 in [%s]" % (len(present), section_name)
            )
        raise config.error(
            "pid_position_p/i and pid_velocity_p/i must be set together"
            " (pid_position_p, pid_position_i, pid_velocity_p, pid_velocity_i)."
            " Found %d of 4 in [%s]" % (len(present), section_name)
        )


def _filter_hz(config, section_name, option):
    value = config.getint(option, 0, minval=0, maxval=1000)
    if value != 0 and value < 10:
        raise config.error(
            "%s must be 0 (disabled) or 10..1000 in [%s]" % (option, section_name)
        )
    return value


def parse_driver_config(config) -> FociDriverConfig:
    """Parse one ``[foci <stepper>]`` config section."""
    name = config.get_name()
    stepper_name = " ".join(name.split()[1:])
    printer = config.get_printer()

    run_current = config.getfloat("run_current", above=0.0)
    encoder_ppr = config.getint("encoder_ppr", minval=1)
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

    pid_flux_p = config.getint("pid_flux_p", None, minval=0, maxval=65535)
    pid_flux_i = config.getint("pid_flux_i", None, minval=0, maxval=65535)
    pid_torque_p = config.getint("pid_torque_p", None, minval=0, maxval=65535)
    pid_torque_i = config.getint("pid_torque_i", None, minval=0, maxval=65535)
    _validate_complete_group(
        config,
        name,
        "inner_pid",
        [pid_flux_p, pid_flux_i, pid_torque_p, pid_torque_i],
    )

    velocity_filter_hz = _filter_hz(config, name, "velocity_filter_hz")
    torque_filter_hz = _filter_hz(config, name, "torque_filter_hz")
    position_filter_hz = _filter_hz(config, name, "position_filter_hz")
    flux_filter_hz = _filter_hz(config, name, "flux_filter_hz")

    pid_position_p = config.getint("pid_position_p", None, minval=0, maxval=32767)
    pid_position_i = config.getint("pid_position_i", None, minval=0, maxval=32767)
    pid_velocity_p = config.getint("pid_velocity_p", None, minval=0, maxval=32767)
    pid_velocity_i = config.getint("pid_velocity_i", None, minval=0, maxval=32767)
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
    pid_velocity_limit = config.getint(
        "pid_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
    )

    commissioned_velocity_p = config.getint(
        "commissioned_velocity_p", None, minval=0, maxval=32767
    )
    commissioned_velocity_i = config.getint(
        "commissioned_velocity_i", None, minval=0, maxval=32767
    )
    commissioned_position_p = config.getint(
        "commissioned_position_p", None, minval=0, maxval=32767
    )
    commissioned_position_i = config.getint(
        "commissioned_position_i", None, minval=0, maxval=32767
    )
    commissioned_velocity_limit = config.getint(
        "commissioned_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
    )

    identified_r_int = config.getint("identified_r_int", None, minval=0)
    identified_l_int = config.getint("identified_l_int", None, minval=0)
    identified_r_count_milli = config.getint("identified_r_count_milli", None, minval=0)
    identified_l_count_micro = config.getint("identified_l_count_micro", None, minval=0)
    identified_lambda_us = config.getint("identified_lambda_us", None, minval=0)
    identified_theta_e_us = config.getint("identified_theta_e_us", None, minval=0)
    identified_ringing_count = config.getint(
        "identified_ringing_count", None, minval=0, maxval=255
    )
    identified_bandwidth_hz = config.getint("identified_bandwidth_hz", None, minval=0)
    identified_tau_e_us = config.getint("identified_tau_e_us", None, minval=0)
    identified_tau_e_crosscheck_us = config.getint(
        "identified_tau_e_crosscheck_us", None, minval=0
    )
    identified_tau_residual_permille = config.getint(
        "identified_tau_residual_permille", None, minval=0, maxval=1000
    )
    identified_inner_warning_flags = config.getint(
        "identified_inner_warning_flags", None, minval=0, maxval=255
    )
    identified_j_eff = config.getint("identified_j_eff", None, minval=0)
    identified_b_eff = config.getint("identified_b_eff", None, minval=0)

    identified_r_count_slope_milli = config.getint(
        "identified_r_count_slope_milli", None
    )
    identified_r_gain_path_count_slope_milli = config.getint(
        "identified_r_gain_path_count_slope_milli", None
    )
    identified_r_axis0_count_slope_milli = config.getint(
        "identified_r_axis0_count_slope_milli", None
    )
    identified_r_axis1_count_slope_milli = config.getint(
        "identified_r_axis1_count_slope_milli", None
    )
    identified_r_axis0_intercept_count = config.getint(
        "identified_r_axis0_intercept_count", None
    )
    identified_r_axis1_intercept_count = config.getint(
        "identified_r_axis1_intercept_count", None
    )
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
    identified_r_profile_version = config.getint(
        "identified_r_profile_version", None, minval=0
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
    identified_r_status_flags_or = config.getint(
        "identified_r_status_flags_or", None, minval=0
    )
    identified_r_warning_flags = config.getint(
        "identified_r_warning_flags", None, minval=0
    )

    autotune_profile = config.get("autotune_profile", None)
    autotune_mode = config.get("autotune_mode", None)
    autotune_status = config.get("autotune_status", None)

    if not config.has_section(stepper_name):
        raise config.error(
            "[%s] cannot find stepper section for '%s'" % (name, stepper_name)
        )
    stepper_config = config.getsection(stepper_name)
    microsteps = stepper_config.getint("microsteps")
    full_steps = stepper_config.getint("full_steps_per_rotation", 200)
    step_pin = stepper_config.get("step_pin")
    ppins = printer.lookup_object("pins")
    pin_params = ppins.parse_pin(step_pin, can_invert=True)
    step_pin_name = pin_params["pin"]
    if step_pin_name not in STEP_PINS:
        raise config.error(
            "[%s] step_pin '%s' is not a FOCI STEP pin (expected one"
            " of: %s)" % (name, step_pin_name, ", ".join(sorted(STEP_PINS)))
        )

    return FociDriverConfig(
        name=name,
        stepper_name=stepper_name,
        run_current=run_current,
        encoder_ppr=encoder_ppr,
        voltage_limit=voltage_limit,
        encoder_reversed=encoder_reversed,
        microsteps=microsteps,
        full_steps=full_steps,
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
        identified_r_int=identified_r_int,
        identified_l_int=identified_l_int,
        identified_r_count_milli=identified_r_count_milli,
        identified_l_count_micro=identified_l_count_micro,
        identified_lambda_us=identified_lambda_us,
        identified_theta_e_us=identified_theta_e_us,
        identified_ringing_count=identified_ringing_count,
        identified_bandwidth_hz=identified_bandwidth_hz,
        identified_tau_e_us=identified_tau_e_us,
        identified_tau_e_crosscheck_us=identified_tau_e_crosscheck_us,
        identified_tau_residual_permille=identified_tau_residual_permille,
        identified_inner_warning_flags=identified_inner_warning_flags,
        identified_j_eff=identified_j_eff,
        identified_b_eff=identified_b_eff,
        identified_r_count_slope_milli=identified_r_count_slope_milli,
        identified_r_gain_path_count_slope_milli=(
            identified_r_gain_path_count_slope_milli
        ),
        identified_r_axis0_count_slope_milli=identified_r_axis0_count_slope_milli,
        identified_r_axis1_count_slope_milli=identified_r_axis1_count_slope_milli,
        identified_r_axis0_intercept_count=identified_r_axis0_intercept_count,
        identified_r_axis1_intercept_count=identified_r_axis1_intercept_count,
        identified_r_axis0_rmse_permille=identified_r_axis0_rmse_permille,
        identified_r_axis1_rmse_permille=identified_r_axis1_rmse_permille,
        identified_r_selected_mask_axis0=identified_r_selected_mask_axis0,
        identified_r_selected_mask_axis1=identified_r_selected_mask_axis1,
        identified_r_profile_version=identified_r_profile_version,
        identified_r_axis0_signed_count_slope_milli=(
            identified_r_axis0_signed_count_slope_milli
        ),
        identified_r_axis1_signed_count_slope_milli=(
            identified_r_axis1_signed_count_slope_milli
        ),
        identified_r_axis0_signed_asymmetry_permille=(
            identified_r_axis0_signed_asymmetry_permille
        ),
        identified_r_axis1_signed_asymmetry_permille=(
            identified_r_axis1_signed_asymmetry_permille
        ),
        identified_r_axis0_drift_permille=identified_r_axis0_drift_permille,
        identified_r_axis1_drift_permille=identified_r_axis1_drift_permille,
        identified_r_status_flags_or=identified_r_status_flags_or,
        identified_r_warning_flags=identified_r_warning_flags,
        autotune_profile=autotune_profile,
        autotune_mode=autotune_mode,
        autotune_status=autotune_status,
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
