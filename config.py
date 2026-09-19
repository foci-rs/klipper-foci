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
CURRENT_FILTER_MAX_HZ = 10000
MAX_ENCODER_PPR = 0x3FFF_FFFF
# Firmware quantizes both currents to TMC4671 register units before comparing
# them; a real board's per-LSB step is on the order of 1-2 mA
# (current_scale_ma_per_lsb), so a host-side check with less margin than this
# can pass in amps while landing on the identical register value as
# run_current, tripping the firmware's own quantized >= check on the first
# homing move.
HOMING_CURRENT_MARGIN_AMPS = 0.05
DEFAULT_STALL_DISTANCE_MM = 0.5
DEFAULT_STALL_PERSISTENCE_TICKS = 3
MAX_STALL_PERSISTENCE_TICKS = 255
POSITION_UNITS_PER_REV = 65536


def gain_to_permille(gain: float) -> int:
    """Convert a float gain to the wire's permille integer encoding."""
    return round(gain * 1000)


@dataclass
class FociDriverConfig:
    """Parsed config for one ``[foci <stepper>]`` section."""

    name: str
    stepper_name: str
    run_current: float
    encoder_ppr: int
    voltage_limit: int
    encoder_reversed: bool
    homing_current: float
    stall_distance: float
    stall_persistence: int
    rotation_distance: float
    homing_speed_mm_s: float
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
    velocity_feedforward_gain: float
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
    identified_lambda_us: int | None
    identified_theta_e_us: int | None
    identified_theta_source: int | None
    identified_ringing_count: int | None
    identified_bandwidth_hz: int | None
    identified_tau_e_us: int | None
    identified_inner_warning_flags: int | None
    identified_l_source: int | None
    identified_l_reactance_count_ratio_milli: int | None
    identified_l_saliency_status: int | None
    identified_current_gains_source: int | None
    identified_current_gains_tier: int | None
    identified_current_retry_budget_exhausted: int | None
    identified_current_failure_reason: int | None
    identified_r_count_slope_milli: int | None
    autotune_profile: str | None
    autotune_mode: str | None
    autotune_status: str | None
    autotune_probed_velocity_mrev_s: int | None
    autotune_d_eq_q: int | None
    autotune_confidence_q: int | None
    autotune_band_lower_percent: int | None
    autotune_band_upper_percent: int | None
    autotune_band_position_q: int | None
    autotune_position_bound_units: int | None
    autotune_position_homing_peak_units: int | None
    autotune_position_motion_cruise_units: int | None


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
    velocity_feedforward_gain: float
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

    homing_current = config.getfloat("homing_current", 0.0, above=0.0, maxval=MAX_RUN_CURRENT_AMPS)
    if homing_current > 0.0 and homing_current > run_current - HOMING_CURRENT_MARGIN_AMPS:
        raise config.error(
            f"homing_current {homing_current:.3f} in [{name}] must be at least "
            f"{HOMING_CURRENT_MARGIN_AMPS:.3f} below run_current {run_current:.3f} "
            "(omit homing_current to disable the homing clamp)"
        )
    stall_distance = config.getfloat("stall_distance", DEFAULT_STALL_DISTANCE_MM, above=0.0)
    stall_persistence = config.getint(
        "stall_persistence",
        DEFAULT_STALL_PERSISTENCE_TICKS,
        minval=1,
        maxval=MAX_STALL_PERSISTENCE_TICKS,
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
    velocity_feedforward_gain = config.getfloat(
        "velocity_feedforward_gain", 1.0, minval=0.0, maxval=8.0
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
    identified_lambda_us = config.getint("identified_lambda_us", None, minval=0)
    identified_theta_e_us = config.getint("identified_theta_e_us", None, minval=0)
    identified_theta_source = config.getint("identified_theta_source", None, minval=0, maxval=255)
    identified_ringing_count = config.getint("identified_ringing_count", None, minval=0, maxval=255)
    identified_bandwidth_hz = config.getint("identified_bandwidth_hz", None, minval=0)
    identified_tau_e_us = config.getint("identified_tau_e_us", None, minval=0)
    identified_inner_warning_flags = config.getint(
        "identified_inner_warning_flags", None, minval=0, maxval=255
    )
    identified_l_source = config.getint("identified_l_source", None, minval=0, maxval=255)
    identified_l_reactance_count_ratio_milli = config.getint(
        "identified_l_reactance_count_ratio_milli", None, minval=0
    )
    identified_l_saliency_status = config.getint(
        "identified_l_saliency_status", None, minval=0, maxval=255
    )
    identified_current_gains_source = config.getint(
        "identified_current_gains_source", None, minval=0, maxval=255
    )
    identified_current_gains_tier = config.getint(
        "identified_current_gains_tier", None, minval=0, maxval=255
    )
    identified_current_retry_budget_exhausted = config.getint(
        "identified_current_retry_budget_exhausted", None, minval=0, maxval=255
    )
    identified_current_failure_reason = config.getint(
        "identified_current_failure_reason", None, minval=0, maxval=255
    )

    identified_r_count_slope_milli = config.getint("identified_r_count_slope_milli", None)

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
    autotune_position_bound_units = config.getint("autotune_position_bound_units", None, minval=0)
    autotune_position_homing_peak_units = config.getint(
        "autotune_position_homing_peak_units", None, minval=0
    )
    autotune_position_motion_cruise_units = config.getint(
        "autotune_position_motion_cruise_units", None, minval=0
    )

    if not config.has_section(stepper_name):
        raise config.error(f"[{name}] cannot find stepper section for '{stepper_name}'")
    stepper_config = config.getsection(stepper_name)
    microsteps = stepper_config.getint("microsteps")
    full_steps = stepper_config.getint("full_steps_per_rotation", 200)
    rotation_distance = stepper_config.getfloat("rotation_distance", above=0.0)
    homing_speed_mm_s = stepper_config.getfloat("homing_speed", 5.0)
    if stall_distance > rotation_distance / 4.0:
        raise config.error(
            f"stall_distance {stall_distance:.3f} in [{name}] must be at most a quarter of "
            f"rotation_distance ({rotation_distance / 4.0:.3f})"
        )
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
        homing_current=homing_current,
        stall_distance=stall_distance,
        stall_persistence=stall_persistence,
        rotation_distance=rotation_distance,
        homing_speed_mm_s=homing_speed_mm_s,
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
        velocity_feedforward_gain=velocity_feedforward_gain,
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
        identified_lambda_us=identified_lambda_us,
        identified_theta_e_us=identified_theta_e_us,
        identified_theta_source=identified_theta_source,
        identified_ringing_count=identified_ringing_count,
        identified_bandwidth_hz=identified_bandwidth_hz,
        identified_tau_e_us=identified_tau_e_us,
        identified_inner_warning_flags=identified_inner_warning_flags,
        identified_l_source=identified_l_source,
        identified_l_reactance_count_ratio_milli=(identified_l_reactance_count_ratio_milli),
        identified_l_saliency_status=identified_l_saliency_status,
        identified_current_gains_source=identified_current_gains_source,
        identified_current_gains_tier=identified_current_gains_tier,
        identified_current_retry_budget_exhausted=(identified_current_retry_budget_exhausted),
        identified_current_failure_reason=identified_current_failure_reason,
        identified_r_count_slope_milli=identified_r_count_slope_milli,
        autotune_profile=autotune_profile,
        autotune_mode=autotune_mode,
        autotune_status=autotune_status,
        autotune_probed_velocity_mrev_s=autotune_probed_velocity_mrev_s,
        autotune_d_eq_q=autotune_d_eq_q,
        autotune_confidence_q=autotune_confidence_q,
        autotune_band_lower_percent=autotune_band_lower_percent,
        autotune_band_upper_percent=autotune_band_upper_percent,
        autotune_band_position_q=autotune_band_position_q,
        autotune_position_bound_units=autotune_position_bound_units,
        autotune_position_homing_peak_units=autotune_position_homing_peak_units,
        autotune_position_motion_cruise_units=autotune_position_motion_cruise_units,
    )


def stall_threshold_units(config: FociDriverConfig) -> int:
    """Convert stall_distance (mm) to TMC position units (65536 per revolution)."""
    return max(1, round(config.stall_distance / config.rotation_distance * POSITION_UNITS_PER_REV))


def validate_runtime_config(config: FociDriverConfig) -> RuntimeValidationResult:
    """Validate persisted config and build active gains/runtime status."""
    status = config.autotune_status
    if status is None:
        return RuntimeValidationResult("uncommissioned", None)

    valid_statuses = ("commissioned", "tuned", "tuned_conservative")
    if status not in valid_statuses:
        logging.warning(
            "FOCI %s: unknown autotune_status='%s' (expected one of: %s). "
            "Motor cannot be enabled until FOCI_SETUP is run.",
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
            "Motor cannot be enabled until FOCI_SETUP is run.",
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


# Operating velocity must clear the probed velocity by this percentage before
# FOCI warns of a stale tune. A pure equality check would fire on ordinary
# rounding/unit-conversion noise between nominally-equal probed and operating
# velocities; 10% is large enough to absorb that noise while still catching a
# genuine increase in configured operating range.
AUTOTUNE_STALENESS_MARGIN_PERCENT = 10


def velocity_mm_s_to_mrev_s(velocity_mm_s: float, rotation_distance_mm: float) -> float:
    """Convert a printer-space linear velocity (mm/s) to motor mrev/s.

    ``rev/s = mm_s / rotation_distance``, ``mrev_s = rev/s * 1000``.
    """
    return (velocity_mm_s / rotation_distance_mm) * 1000.0


def check_autotune_staleness(config: FociDriverConfig, operating_velocity_mm_s: float) -> None:
    """Warn when the configured operating velocity outruns the probed tune.

    ``autotune_probed_velocity_mrev_s`` records the highest velocity
    FOCI_AUTOTUNE actually probed while producing the deployed gain. If the
    operating velocity now exceeds that by more than
    ``AUTOTUNE_STALENESS_MARGIN_PERCENT``, the gain was never validated up
    there. This is advisory only: it never raises and never blocks startup.
    Silent when the driver has no recorded probe velocity (untuned, or a
    tune saved before this provenance field existed).
    """
    probed_mrev_s = config.autotune_probed_velocity_mrev_s
    if probed_mrev_s is None:
        return
    operating_mrev_s = velocity_mm_s_to_mrev_s(operating_velocity_mm_s, config.rotation_distance)
    threshold_mrev_s = probed_mrev_s * (100 + AUTOTUNE_STALENESS_MARGIN_PERCENT) / 100.0
    if operating_mrev_s > threshold_mrev_s:
        logging.warning(
            "FOCI %s: tuned below operating range (probed up to %dmrev_s, operating at "
            "%.0fmrev_s); re-run FOCI_AUTOTUNE to retune for the current velocity",
            config.name,
            probed_mrev_s,
            operating_mrev_s,
        )
