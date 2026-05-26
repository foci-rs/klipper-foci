# TMC4671 register definitions and FOCI driver class.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Register reference: TMC4671-LA datasheet rev 2.08

import logging
import math
from collections.abc import Callable

log = logging.getLogger(__name__)

OPENFFBOARD_CPU_CYCLES_PER_US = 168


######################################################################
# Field formatting helpers
######################################################################

MOTOR_TYPES: dict[int, str] = {0: "none", 1: "dc", 2: "stepper", 3: "bldc"}
PHI_E_SOURCES: dict[int, str] = {
    1: "ext",
    2: "openloop",
    3: "abn",
    5: "hall",
    6: "aenc",
    7: "aenc",
}
ANGLE_SOURCES: dict[int, str] = {
    0: "phi_e_selection",
    1: "phi_e_ext",
    2: "phi_e_openloop",
    3: "phi_e_abn",
    5: "phi_e_hal",
    6: "phi_e_aenc",
    7: "phi_a_aenc",
    9: "phi_m_abn",
    10: "phi_m_abn_2",
    11: "phi_m_aenc",
    12: "phi_m_hal",
}
VELOCITY_METER_SOURCES: dict[int, str] = {0: "default", 1: "advanced"}
MOTION_MODES: dict[int, str] = {
    0: "stopped",
    1: "torque",
    2: "velocity",
    3: "position",
    4: "pramp",
    5: "vramp",
    6: "hold",
    8: "uq_ud_ext",
}


def _fmt_motor_type(val: int) -> str:
    return "%d(%s)" % (val, MOTOR_TYPES.get(val, "?"))


def _fmt_phi_e(val: int) -> str:
    return PHI_E_SOURCES.get(val, str(val))


def _fmt_angle_source(val: int) -> str:
    return "%d(%s)" % (val, ANGLE_SOURCES.get(val, "?"))


def _fmt_velocity_meter(val: int) -> str:
    return "%d(%s)" % (val, VELOCITY_METER_SOURCES.get(val, "?"))


def _fmt_motion_mode(val: int) -> str:
    return MOTION_MODES.get(val, str(val))


def _fmt_pid_type(val: int) -> str:
    return "advanced" if val else ""


def _fmt_q4_12(val: int) -> str:
    return "%.3f" % (val * 2**-12)


def _fmt_q8_8(val: int) -> str:
    return "%.3f" % (val * 2**-8)


def _fmt_advanced_pi_current_i(val: int) -> str:
    if val == 0:
        return "0"
    return "%d(q8.8=%.3f,zero=%d/65536)" % (val, val * 2**-8, val)


def _fmt_direction(val: int) -> str:
    return "reversed" if val else ""


def _fmt_on_off(val: int) -> str:
    return "on" if val else ""


######################################################################
# Register addresses
#
# Regular registers use 7-bit addresses (0x00-0x7F).
# Sub-registers use synthetic addresses 0x80+ matching the firmware's
# DUMP_SUB_REGISTERS encoding.
######################################################################

REGISTERS: dict[str, int] = {
    "MOTOR_TYPE_N_POLE_PAIRS": 0x1B,
    "VELOCITY_SELECTION": 0x50,
    "POSITION_SELECTION": 0x51,
    "PHI_E_SELECTION": 0x52,
    "MODE_RAMP_MODE_MOTION": 0x63,
    "PID_TORQUE_FLUX_TARGET": 0x64,
    "PID_TORQUE_FLUX_ACTUAL": 0x69,
    "PID_TORQUE_FLUX_LIMITS": 0x5E,
    "PIDOUT_UQ_UD_LIMITS": 0x5D,
    "ADC_I_SELECT": 0x0A,
    "ADC_I0_SCALE_OFFSET": 0x09,
    "ADC_I1_SCALE_OFFSET": 0x08,
    "PID_FLUX_P_FLUX_I": 0x54,
    "PID_TORQUE_P_TORQUE_I": 0x56,
    "PID_VELOCITY_P_VELOCITY_I": 0x58,
    "PID_POSITION_P_POSITION_I": 0x5A,
    "PID_VELOCITY_LIMIT": 0x60,
    "ABN_DECODER_MODE": 0x25,
    "ABN_DECODER_PPR": 0x26,
    "ABN_DECODER_COUNT": 0x27,
    "ABN_DECODER_PHI_E_PHI_M_OFFSET": 0x29,
    "ABN_DECODER_PHI_E_PHI_M": 0x2A,
    "PID_TORQUE_FLUX_OFFSET": 0x65,
    "PID_VELOCITY_OFFSET": 0x67,
    "PID_POSITION_TARGET": 0x68,
    "PID_VELOCITY_ACTUAL": 0x6A,
    "PID_POSITION_ACTUAL": 0x6B,
    "ADC_VM_LIMITS": 0x75,
    "STATUS_FLAGS": 0x7C,
    "PWM_BBM_H_BBM_L": 0x19,
    "PWM_SV_CHOP": 0x1A,
    # Sub-registers (synthetic addresses 0x80+, match firmware encoding)
    "INTERIM_PIDIN_TARGET_VELOCITY": 0x80,
    "INTERIM_PIDOUT_TARGET_VELOCITY": 0x81,
    "PID_POSITION_ERROR_SUM": 0x82,
    "PID_TORQUE_ERROR_SUM": 0x83,
    "PID_FLUX_ERROR_SUM": 0x84,
    "PID_VELOCITY_ERROR_SUM": 0x85,
    "CONFIG_ADVANCED_PI_REPRESENT": 0x86,
}


######################################################################
# Field bitmasks: register_name -> {field_name: mask}
######################################################################

Fields: dict[str, dict[str, int]] = {}

Fields["MOTOR_TYPE_N_POLE_PAIRS"] = {
    "n_pole_pairs": 0xFFFF,
    "motor_type": 0xFF << 16,
}

Fields["PHI_E_SELECTION"] = {
    "phi_e": 0xFF,
}

Fields["VELOCITY_SELECTION"] = {
    "velocity_selection": 0xFF,
    "velocity_meter_selection": 0xFF << 8,
}

Fields["POSITION_SELECTION"] = {
    "position_selection": 0xFF,
}

Fields["MODE_RAMP_MODE_MOTION"] = {
    "mode": 0xFF,
    "mode_pid_type": 1 << 31,
}

Fields["PID_TORQUE_FLUX_TARGET"] = {
    "flux_target": 0xFFFF,
    "torque_target": 0xFFFF << 16,
}

Fields["PID_TORQUE_FLUX_ACTUAL"] = {
    "flux_actual": 0xFFFF,
    "torque_actual": 0xFFFF << 16,
}

Fields["PID_TORQUE_FLUX_LIMITS"] = {
    "current_limit": 0xFFFF,
}

Fields["PIDOUT_UQ_UD_LIMITS"] = {
    "voltage_limit": 0xFFFF,
}

Fields["ADC_I_SELECT"] = {
    "adc_i0_select": 0xFF,
    "adc_i1_select": 0xFF << 8,
    "adc_i_ux_select": 0x03 << 24,
    "adc_i_v_select": 0x03 << 26,
    "adc_i_wy_select": 0x03 << 28,
}

Fields["ADC_I0_SCALE_OFFSET"] = {
    "adc_i0_offset": 0xFFFF,
    "adc_i0_scale": 0xFFFF << 16,
}

Fields["ADC_I1_SCALE_OFFSET"] = {
    "adc_i1_offset": 0xFFFF,
    "adc_i1_scale": 0xFFFF << 16,
}

Fields["PID_FLUX_P_FLUX_I"] = {
    "flux_i": 0xFFFF,
    "flux_p": 0xFFFF << 16,
}

Fields["PID_TORQUE_P_TORQUE_I"] = {
    "torque_i": 0xFFFF,
    "torque_p": 0xFFFF << 16,
}

Fields["PID_VELOCITY_P_VELOCITY_I"] = {
    "velocity_i": 0xFFFF,
    "velocity_p": 0xFFFF << 16,
}

Fields["PID_POSITION_P_POSITION_I"] = {
    "position_i": 0xFFFF,
    "position_p": 0xFFFF << 16,
}

Fields["ABN_DECODER_MODE"] = {
    "abn_apol": 1,
    "abn_bpol": 1 << 1,
    "abn_npol": 1 << 2,
    "abn_use_abn_as_n": 1 << 3,
    "abn_cln": 1 << 8,
    "abn_direction": 1 << 12,
}

Fields["ABN_DECODER_PPR"] = {
    "ppr": 0xFFFFFF,
}

Fields["ABN_DECODER_COUNT"] = {
    "count": 0xFFFFFF,
}

Fields["ABN_DECODER_PHI_E_PHI_M_OFFSET"] = {
    "abn_phi_m_offset": 0xFFFF,
    "abn_phi_e_offset": 0xFFFF << 16,
}

Fields["ABN_DECODER_PHI_E_PHI_M"] = {
    "abn_phi_m": 0xFFFF,
    "abn_phi_e": 0xFFFF << 16,
}

Fields["ADC_VM_LIMITS"] = {
    "adc_vm_limit_low": 0xFFFF,
    "adc_vm_limit_high": 0xFFFF << 16,
}

Fields["STATUS_FLAGS"] = {
    "pid_x_target_limit": 1 << 0,
    "pid_x_errsum_limit": 1 << 2,
    "pid_x_output_limit": 1 << 3,
    "pid_v_target_limit": 1 << 4,
    "pid_v_errsum_limit": 1 << 6,
    "pid_v_output_limit": 1 << 7,
    "pid_id_target_limit": 1 << 8,
    "pid_id_errsum_limit": 1 << 10,
    "pid_id_output_limit": 1 << 11,
    "pid_iq_target_limit": 1 << 12,
    "pid_iq_errsum_limit": 1 << 14,
    "pid_iq_output_limit": 1 << 15,
    "ipark_cirlim_limit_u_d": 1 << 16,
    "ipark_cirlim_limit_u_q": 1 << 17,
    "ipark_cirlim_limit_u_r": 1 << 18,
    "ref_sw_r": 1 << 20,
    "ref_sw_h": 1 << 21,
    "ref_sw_l": 1 << 22,
    "pwm_min": 1 << 24,
    "pwm_max": 1 << 25,
    "adc_i_clipped": 1 << 26,
    "aenc_clipped": 1 << 27,
    "enc_n": 1 << 28,
    "enc_2_n": 1 << 29,
    "aenc_n": 1 << 30,
}

Fields["PWM_SV_CHOP"] = {
    "pwm_chop": 0xFF,
    "pwm_sv": 1 << 8,
}

Fields["PWM_BBM_H_BBM_L"] = {
    "bbm_l": 0xFF,
    "bbm_h": 0xFF << 8,
}

Fields["PID_VELOCITY_LIMIT"] = {
    "velocity_limit": 0xFFFFFFFF,
}

Fields["PID_TORQUE_FLUX_OFFSET"] = {
    "flux_offset": 0xFFFF,
    "torque_offset": 0xFFFF << 16,
}

Fields["PID_VELOCITY_OFFSET"] = {
    "velocity_offset": 0xFFFFFFFF,
}

Fields["PID_VELOCITY_ACTUAL"] = {
    "velocity_actual": 0xFFFFFFFF,
}

# Sub-register fields (synthetic addresses 0x80+). These are raw s32
# values displayed as a single field.
Fields["INTERIM_PIDIN_TARGET_VELOCITY"] = {
    "pidin_target_velocity": 0xFFFFFFFF,
}

Fields["INTERIM_PIDOUT_TARGET_VELOCITY"] = {
    "pidout_target_velocity": 0xFFFFFFFF,
}

Fields["PID_POSITION_ERROR_SUM"] = {
    "position_error_sum": 0xFFFFFFFF,
}

Fields["PID_TORQUE_ERROR_SUM"] = {
    "torque_error_sum": 0xFFFFFFFF,
}

Fields["PID_FLUX_ERROR_SUM"] = {
    "flux_error_sum": 0xFFFFFFFF,
}

Fields["PID_VELOCITY_ERROR_SUM"] = {
    "velocity_error_sum": 0xFFFFFFFF,
}

Fields["CONFIG_ADVANCED_PI_REPRESENT"] = {
    "current_i_q4_12": 1 << 0,
    "current_p_q4_12": 1 << 1,
    "velocity_i_q4_12": 1 << 2,
    "velocity_p_q4_12": 1 << 3,
    "position_i_q4_12": 1 << 4,
    "position_p_q4_12": 1 << 5,
}

TRACE_FAST_HEADERS = [
    "tick",
    "phase",
    "flags",
    "pos_tgt",
    "pos_act",
    "trq_act",
    "flx_act",
    "pidout_vel",
    "status",
    "abn",
]

TRACE_FULL_HEADERS = TRACE_FAST_HEADERS + [
    "trq_tgt",
    "flx_tgt",
    "vel_ofs",
    "esum_pos",
    "esum_vel",
    "esum_trq",
]

TRACE_VELOCITY_HEADERS = TRACE_FAST_HEADERS + [
    "pos_err",
    "pidout_trq",
    "pidout_flx",
    "pidin_vel",
    "vel_actual",
    "vel_ofs",
]

TRACE_HOLD_HEADERS = TRACE_FAST_HEADERS + [
    "pidout_trq",
    "pidout_flx",
    "foc_uq",
    "foc_ud",
    "foc_uq_lim",
    "foc_ud_lim",
    "esum_trq",
    "esum_flx",
]

TRACE_FINAL_SETTLE_WINDOW = 30


def _range_metric(samples: list[list[int]], idx: int) -> dict[str, int]:
    values = [row[idx] for row in samples]
    return {
        "min": min(values),
        "max": max(values),
        "final": values[-1],
        "nonzero": sum(1 for value in values if value != 0),
    }


def _range_float_metric(values: list[float]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "final": 0.0}
    return {
        "min": min(values),
        "max": max(values),
        "final": values[-1],
    }


def _phase_error_metric(values: list[int]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "min": 0, "max": 0, "mean": 0.0, "max_abs": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "mean": sum(values) / len(values),
        "max_abs": max(values, key=lambda value: abs(value)),
    }


def _settle_metric(samples: list[list[int]], idx: int) -> dict[str, float | int]:
    values = [row[idx] for row in samples]
    square_sum = sum(value * value for value in values)
    return {
        "rms": math.sqrt(square_sum / len(values)),
        "max_abs": max(abs(value) for value in values),
        "final": values[-1],
        "nonzero": sum(1 for value in values if value != 0),
    }


def _position_error_metric(
    errors: list[int], samples: list[list[int]], tick_idx: int
) -> dict[str, int]:
    max_abs_error = max(errors, key=lambda value: abs(value))
    max_abs_error_idx = errors.index(max_abs_error)
    return {
        "min": min(errors),
        "max": max(errors),
        "final": errors[-1],
        "max_abs": max_abs_error,
        "max_abs_tick": samples[max_abs_error_idx][tick_idx],
    }


def _format_metric_value(value: float | int) -> str:
    if isinstance(value, float):
        return ("%.3f" % value).rstrip("0").rstrip(".")
    return str(value)


def _format_phase_error_metric(name: str, metric: dict[str, float | int]) -> str:
    return "%s(n=%d min=%d max=%d mean=%s max_abs=%d)" % (
        name,
        metric["count"],
        metric["min"],
        metric["max"],
        _format_metric_value(metric["mean"]),
        metric["max_abs"],
    )


def _format_settle_metric(name: str, metric: dict[str, float | int]) -> str:
    return "%s(rms=%s max_abs=%d final=%d)" % (
        name,
        _format_metric_value(metric["rms"]),
        metric["max_abs"],
        metric["final"],
    )


def _trace_summary_metrics(
    samples: list[list[int]],
    headers: list[str],
    expected_tick_step: int,
) -> dict:
    """Compute compact trace metrics from parsed trace rows."""
    columns = {name: idx for idx, name in enumerate(headers)}
    tick_idx = columns["tick"]
    pos_tgt_idx = columns["pos_tgt"]
    pos_act_idx = columns["pos_act"]
    pos_err_idx = columns.get("pos_err")

    errors = [row[pos_tgt_idx] - row[pos_act_idx] for row in samples]
    hardware_errors = (
        [row[pos_err_idx] for row in samples] if pos_err_idx is not None else []
    )

    duplicate_ticks = 0
    missed_samples = 0
    out_of_order_ticks = 0
    derived_target_velocities = []
    derived_actual_velocities = []
    derived_velocity_errors = []
    phase_error_values = {"accel": [], "cruise": [], "decel": []}
    hardware_phase_error_values = {"accel": [], "cruise": [], "decel": []}
    prev_target_velocity = None
    prev = samples[0]
    for row in samples[1:]:
        delta_tick = row[tick_idx] - prev[tick_idx]
        if delta_tick == 0:
            duplicate_ticks += 1
        elif delta_tick < 0:
            out_of_order_ticks += 1
        else:
            if delta_tick > expected_tick_step:
                missed_samples += (delta_tick - 1) // expected_tick_step
            delta_target = row[pos_tgt_idx] - prev[pos_tgt_idx]
            delta_actual = row[pos_act_idx] - prev[pos_act_idx]
            target_velocity = delta_target / delta_tick
            actual_velocity = delta_actual / delta_tick
            derived_target_velocities.append(target_velocity)
            derived_actual_velocities.append(actual_velocity)
            derived_velocity_errors.append(actual_velocity - target_velocity)

            if target_velocity != 0 and prev_target_velocity is not None:
                target_accel = target_velocity - prev_target_velocity
                position_error = row[pos_tgt_idx] - row[pos_act_idx]
                hardware_position_error = (
                    row[pos_err_idx] if pos_err_idx is not None else None
                )
                if target_velocity * target_accel > 0:
                    phase_error_values["accel"].append(position_error)
                    if hardware_position_error is not None:
                        hardware_phase_error_values["accel"].append(
                            hardware_position_error
                        )
                elif target_velocity * target_accel < 0:
                    phase_error_values["decel"].append(position_error)
                    if hardware_position_error is not None:
                        hardware_phase_error_values["decel"].append(
                            hardware_position_error
                        )
                else:
                    phase_error_values["cruise"].append(position_error)
                    if hardware_position_error is not None:
                        hardware_phase_error_values["cruise"].append(
                            hardware_position_error
                        )
            prev_target_velocity = target_velocity
        prev = row

    metrics = {
        "sample_count": len(samples),
        "tick_start": samples[0][tick_idx],
        "tick_end": samples[-1][tick_idx],
        "expected_tick_step": expected_tick_step,
        "duplicate_ticks": duplicate_ticks,
        "missed_samples": missed_samples,
        "out_of_order_ticks": out_of_order_ticks,
        "position_error": _position_error_metric(errors, samples, tick_idx),
    }

    if hardware_errors:
        metrics["hardware_position_error"] = _position_error_metric(
            hardware_errors, samples, tick_idx
        )

    metrics["derived_target_velocity"] = _range_float_metric(derived_target_velocities)
    metrics["derived_actual_velocity"] = _range_float_metric(derived_actual_velocities)
    metrics["derived_velocity"] = metrics["derived_actual_velocity"]
    metrics["derived_velocity_error"] = _range_float_metric(derived_velocity_errors)
    metrics["position_error_by_motion_phase"] = {
        "accel": _phase_error_metric(phase_error_values["accel"]),
        "cruise": _phase_error_metric(phase_error_values["cruise"]),
        "decel": _phase_error_metric(phase_error_values["decel"]),
    }
    if hardware_errors:
        metrics["hardware_position_error_by_motion_phase"] = {
            "accel": _phase_error_metric(hardware_phase_error_values["accel"]),
            "cruise": _phase_error_metric(hardware_phase_error_values["cruise"]),
            "decel": _phase_error_metric(hardware_phase_error_values["decel"]),
        }

    for field in (
        "trq_act",
        "flx_act",
        "pidin_vel",
        "pidout_vel",
        "vel_actual",
        "vel_ofs",
        "pidout_trq",
        "pidout_flx",
        "foc_uq",
        "foc_ud",
        "foc_uq_lim",
        "foc_ud_lim",
        "esum_trq",
        "esum_flx",
    ):
        if field in columns:
            metrics[field] = _range_metric(samples, columns[field])

    settle_samples = samples[-TRACE_FINAL_SETTLE_WINDOW:]
    final_settle = {
        "window_size": TRACE_FINAL_SETTLE_WINDOW,
        "sample_count": len(settle_samples),
    }
    for field in (
        "pos_err",
        "pidout_vel",
        "pidout_trq",
        "vel_actual",
        "trq_act",
        "flx_act",
        "foc_uq_lim",
        "foc_ud_lim",
        "esum_trq",
        "esum_flx",
    ):
        if field in columns:
            final_settle[field] = _settle_metric(settle_samples, columns[field])
    if len(final_settle) > 2:
        metrics["final_settle"] = final_settle

    if "status" in columns:
        status_values = [row[columns["status"]] for row in samples]
        metrics["status"] = {
            "unique": sorted(set(status_values)),
            "pid_v_output_limit_samples": sum(
                1 for value in status_values if value & (1 << 7)
            ),
        }

    return metrics


def _format_trace_summary(
    name: str,
    samples: list[list[int]],
    headers: list[str],
    preset_name: str,
    sample_period_us: int,
    dropped: int,
    expected_tick_step: int,
) -> list[str]:
    """Format compact trace metrics for G-code responses."""
    metrics = _trace_summary_metrics(samples, headers, expected_tick_step)
    effective_sample_period_us = sample_period_us * expected_tick_step
    lines = [
        "FOCI %s trace summary: %d samples, %s preset, %dus tick, %dus samples"
        % (
            name,
            metrics["sample_count"],
            preset_name,
            sample_period_us,
            effective_sample_period_us,
        )
    ]
    lines.append(
        "ticks: start=%d end=%d expected_step=%d duplicate=%d missed=%d"
        " out_of_order=%d dropped=%d"
        % (
            metrics["tick_start"],
            metrics["tick_end"],
            metrics["expected_tick_step"],
            metrics["duplicate_ticks"],
            metrics["missed_samples"],
            metrics["out_of_order_ticks"],
            dropped,
        )
    )

    position_error = metrics["position_error"]
    lines.append(
        "position_error_counts: min=%d max=%d final=%d max_abs=%d at_tick=%d"
        % (
            position_error["min"],
            position_error["max"],
            position_error["final"],
            position_error["max_abs"],
            position_error["max_abs_tick"],
        )
    )

    phase_errors = metrics["position_error_by_motion_phase"]
    lines.append(
        "position_error_by_phase: %s %s %s"
        % (
            _format_phase_error_metric("accel", phase_errors["accel"]),
            _format_phase_error_metric("cruise", phase_errors["cruise"]),
            _format_phase_error_metric("decel", phase_errors["decel"]),
        )
    )

    if "hardware_position_error" in metrics:
        hardware_position_error = metrics["hardware_position_error"]
        lines.append(
            "hardware_position_error_counts: min=%d max=%d final=%d max_abs=%d"
            " at_tick=%d"
            % (
                hardware_position_error["min"],
                hardware_position_error["max"],
                hardware_position_error["final"],
                hardware_position_error["max_abs"],
                hardware_position_error["max_abs_tick"],
            )
        )

    if "hardware_position_error_by_motion_phase" in metrics:
        phase_errors = metrics["hardware_position_error_by_motion_phase"]
        lines.append(
            "hardware_position_error_by_phase: %s %s %s"
            % (
                _format_phase_error_metric("accel", phase_errors["accel"]),
                _format_phase_error_metric("cruise", phase_errors["cruise"]),
                _format_phase_error_metric("decel", phase_errors["decel"]),
            )
        )

    derived_target_velocity = metrics["derived_target_velocity"]
    lines.append(
        "derived_target_velocity_counts_per_tick: min=%s max=%s final=%s"
        % (
            _format_metric_value(derived_target_velocity["min"]),
            _format_metric_value(derived_target_velocity["max"]),
            _format_metric_value(derived_target_velocity["final"]),
        )
    )

    derived_velocity = metrics["derived_velocity"]
    lines.append(
        "derived_actual_velocity_counts_per_tick: min=%s max=%s final=%s"
        % (
            _format_metric_value(derived_velocity["min"]),
            _format_metric_value(derived_velocity["max"]),
            _format_metric_value(derived_velocity["final"]),
        )
    )

    derived_velocity_error = metrics["derived_velocity_error"]
    lines.append(
        "derived_velocity_error_counts_per_tick: min=%s max=%s final=%s"
        % (
            _format_metric_value(derived_velocity_error["min"]),
            _format_metric_value(derived_velocity_error["max"]),
            _format_metric_value(derived_velocity_error["final"]),
        )
    )

    for field in (
        "trq_act",
        "flx_act",
        "pidin_vel",
        "pidout_vel",
        "vel_actual",
        "vel_ofs",
        "pidout_trq",
        "pidout_flx",
        "foc_uq",
        "foc_ud",
        "foc_uq_lim",
        "foc_ud_lim",
        "esum_trq",
        "esum_flx",
    ):
        if field in metrics:
            metric = metrics[field]
            lines.append(
                "%s: min=%d max=%d final=%d nonzero=%d"
                % (
                    field,
                    metric["min"],
                    metric["max"],
                    metric["final"],
                    metric["nonzero"],
                )
            )

    if "final_settle" in metrics:
        final_settle = metrics["final_settle"]
        settle_fields = []
        for field in (
            "pos_err",
            "pidout_vel",
            "pidout_trq",
            "vel_actual",
            "trq_act",
            "flx_act",
            "foc_uq_lim",
            "foc_ud_lim",
            "esum_trq",
            "esum_flx",
        ):
            if field in final_settle:
                settle_fields.append(_format_settle_metric(field, final_settle[field]))
        if settle_fields:
            lines.append(
                "final_settle_last_%d: n=%d %s"
                % (
                    final_settle["window_size"],
                    final_settle["sample_count"],
                    " ".join(settle_fields),
                )
            )

    if "status" in metrics:
        status = metrics["status"]
        unique = ",".join("0x%08x" % value for value in status["unique"])
        lines.append(
            "status: unique=%s pid_v_output_limit_samples=%d"
            % (unique, status["pid_v_output_limit_samples"])
        )

    return lines


######################################################################
# Signed fields and formatters
######################################################################

SIGNED_FIELDS: list[str] = [
    "adc_i0_scale",
    "adc_i1_scale",
    "flux_target",
    "torque_target",
    "flux_actual",
    "torque_actual",
    "voltage_limit",
    "flux_offset",
    "torque_offset",
    "velocity_offset",
    "velocity_actual",
    "pidin_target_velocity",
    "pidout_target_velocity",
    "position_error_sum",
    "torque_error_sum",
    "flux_error_sum",
    "velocity_error_sum",
    "abn_phi_m_offset",
    "abn_phi_e_offset",
]

FIELD_FORMATTERS: dict[str, Callable[[int], str]] = {
    "motor_type": _fmt_motor_type,
    "phi_e": _fmt_phi_e,
    "velocity_selection": _fmt_angle_source,
    "velocity_meter_selection": _fmt_velocity_meter,
    "position_selection": _fmt_angle_source,
    "mode": _fmt_motion_mode,
    "mode_pid_type": _fmt_pid_type,
    "abn_direction": _fmt_direction,
    "pwm_sv": _fmt_on_off,
    "flux_p": _fmt_q8_8,  # Q8.8 per DS 4.7.6
    # Raw current-I is Q8.8 with CONFIG_ADVANCED_PI_REPRESENT at its default 0.
    # The advanced PI integrator makes the effective zero factor raw/65536.
    "flux_i": _fmt_advanced_pi_current_i,
    "torque_p": _fmt_q8_8,  # Q8.8 per DS 4.7.6
    "torque_i": _fmt_advanced_pi_current_i,
    "velocity_p": _fmt_q8_8,
    "velocity_i": _fmt_q8_8,  # Q8.8 in advanced PID mode (ADVANCED_PI_REPRESENT default)
    "position_p": _fmt_q8_8,
    "position_i": _fmt_q8_8,  # Q8.8 in advanced PID mode (ADVANCED_PI_REPRESENT default)
}


######################################################################
# Dump register groups (ordered for DUMP_FOCI output)
######################################################################

DUMP_GROUPS: list[tuple[str, list[str]]] = [
    (
        "FOCI %s",
        [
            "MOTOR_TYPE_N_POLE_PAIRS",
            "VELOCITY_SELECTION",
            "POSITION_SELECTION",
            "PHI_E_SELECTION",
            "MODE_RAMP_MODE_MOTION",
        ],
    ),
    (
        "Current",
        [
            "PID_TORQUE_FLUX_TARGET",
            "PID_TORQUE_FLUX_ACTUAL",
            "PID_TORQUE_FLUX_LIMITS",
            "PIDOUT_UQ_UD_LIMITS",
            "ADC_I_SELECT",
            "ADC_I0_SCALE_OFFSET",
            "ADC_I1_SCALE_OFFSET",
        ],
    ),
    (
        "PID Gains",
        [
            "PID_FLUX_P_FLUX_I",
            "PID_TORQUE_P_TORQUE_I",
            "PID_VELOCITY_P_VELOCITY_I",
            "PID_POSITION_P_POSITION_I",
            "PID_VELOCITY_LIMIT",
            "CONFIG_ADVANCED_PI_REPRESENT",
        ],
    ),
    (
        "Position",
        [
            "PID_POSITION_TARGET",
            "PID_POSITION_ACTUAL",
        ],
    ),
    (
        "PID Cascade",
        [
            "INTERIM_PIDIN_TARGET_VELOCITY",
            "INTERIM_PIDOUT_TARGET_VELOCITY",
            "PID_VELOCITY_ACTUAL",
            "PID_TORQUE_FLUX_OFFSET",
            "PID_VELOCITY_OFFSET",
            "PID_POSITION_ERROR_SUM",
            "PID_TORQUE_ERROR_SUM",
            "PID_FLUX_ERROR_SUM",
            "PID_VELOCITY_ERROR_SUM",
        ],
    ),
    (
        "Encoder",
        [
            "ABN_DECODER_MODE",
            "ABN_DECODER_PPR",
            "ABN_DECODER_COUNT",
            "ABN_DECODER_PHI_E_PHI_M_OFFSET",
            "ABN_DECODER_PHI_E_PHI_M",
        ],
    ),
    (
        "Voltage / Brake",
        [
            "ADC_VM_LIMITS",
        ],
    ),
    (
        "Status",
        [
            "STATUS_FLAGS",
            "PWM_BBM_H_BBM_L",
            "PWM_SV_CHOP",
        ],
    ),
]


######################################################################
# FieldHelper - read-only register field extraction and formatting
######################################################################


def _ffs(mask: int) -> int:
    """Find first set bit position (0-indexed)."""
    return (mask & -mask).bit_length() - 1


class FieldHelper:
    """Extract and format TMC4671 register fields for display."""

    def __init__(
        self,
        all_fields: dict[str, dict[str, int]],
        signed_fields: list[str],
        field_formatters: dict[str, Callable[[int], str]],
    ) -> None:
        self.all_fields = all_fields
        self.signed_fields = set(signed_fields)
        self.field_formatters = field_formatters

    def get_field(self, field_name: str, reg_name: str, reg_value: int) -> int:
        """Extract a named field from a 32-bit register value.

        Args:
            field_name: Name of the field to extract.
            reg_name: Name of the register containing the field.
            reg_value: Full 32-bit register value.

        Returns:
            The extracted field value, sign-extended if the field is
            listed in signed_fields.
        """
        mask = self.all_fields[reg_name][field_name]
        shift = _ffs(mask)
        field_value = (reg_value & mask) >> shift
        if field_name in self.signed_fields:
            bits = (mask >> shift).bit_length()
            if field_value >= (1 << (bits - 1)):
                field_value -= 1 << bits
        return field_value

    def pretty_format(self, reg_name: str, reg_value: int) -> str:
        """Format a register as 'NAME: hex field=val field=val'.

        Zero-valued fields are omitted. Fields are sorted by bitmask
        position (lowest bit first).

        Args:
            reg_name: Register name used as display label.
            reg_value: Full 32-bit register value.

        Returns:
            A human-readable string showing the register name, raw hex
            value, and any non-zero fields with their formatted values.
        """
        reg_fields = self.all_fields.get(reg_name, {})
        sorted_fields = sorted([(mask, name) for name, mask in reg_fields.items()])
        parts: list[str] = []
        for mask, field_name in sorted_fields:
            field_value = self.get_field(field_name, reg_name, reg_value)
            fmt = self.field_formatters.get(field_name, str)
            sval = fmt(field_value)
            if sval and sval != "0":
                parts.append(" %s=%s" % (field_name, sval))
        return "%-30s %08x%s" % (reg_name + ":", reg_value, "".join(parts))


######################################################################
# FociDriver - per-axis driver instance
######################################################################

STEP_PINS: dict[str, int] = {"STEP0": 0, "STEP1": 1}
MIN_OPERATIONAL_VOLTAGE_LIMIT = 1024
MAX_DIAGNOSTIC_VOLTAGE_LIMIT = 32767


class FociDriver:
    """Klipper extras driver for a single TMC4671 FOC channel."""

    cmd_DUMP_FOCI_help = "Dump TMC4671 register state for a FOCI stepper"
    cmd_FOCI_TRACE_START_help = "Start FOCI per-tick trace capture"
    cmd_FOCI_TRACE_STOP_help = "Stop FOCI per-tick trace capture"
    cmd_FOCI_TRACE_help = "Fetch and display trace capture buffer"
    cmd_FOCI_STEP_POSITION_help = (
        "Query raw FOCI MCU step position without syncing Klipper"
    )
    cmd_FOCI_STEPPER_STATS_help = (
        "Query FOCI MCU step queue/execution counters without motion"
    )
    cmd_FOCI_DISPATCH_STATS_help = (
        "Query FOCI MCU step-dispatch cycle counters without motion"
    )
    cmd_FOCI_SELFTEST_help = "Run TMC4671 self-test for a FOCI stepper"
    cmd_FOCI_COMMISSION_help = "Commission a FOCI stepper (Stage 1: diagnostics + current tune + closed-loop entry)"
    cmd_FOCI_AUTOTUNE_help = (
        "Tune installed FOCI stepper (Stage 2: requires commissioning + homing)"
    )
    cmd_FOCI_SET_GAINS_help = "Set FOCI outer gains for bringup debugging"
    cmd_FOCI_SET_INNER_GAINS_help = "Set FOCI inner current gains for bringup debugging"
    cmd_FOCI_SET_CURRENT_help = "Set FOCI run current for bringup debugging"
    cmd_FOCI_SET_VELOCITY_FEEDFORWARD_help = (
        "Set FOCI velocity feedforward runtime multiplier for bringup debugging"
    )
    cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD_help = (
        "Set FOCI diagnostic velocity transient feedforward for bringup debugging"
    )
    cmd_FOCI_SET_ACCEL_FEEDFORWARD_help = "Set FOCI acceleration/deceleration feedforward runtime gains for bringup debugging"
    cmd_FOCI_SET_DECOUPLING_FEEDFORWARD_help = (
        "Set FOCI diagnostic q/d decoupling proxy feedforward for bringup debugging"
    )
    cmd_FOCI_SET_POSITION_LEAD_help = (
        "Set FOCI diagnostic position-target lead for bringup debugging"
    )
    cmd_FOCI_SET_PHASE_ADVANCE_help = (
        "Set FOCI diagnostic commutation phase advance for bringup debugging"
    )
    cmd_FOCI_SET_VOLTAGE_LIMIT_help = (
        "Set FOCI PIDOUT_UQ_UD_LIMITS for bringup authority diagnostics"
    )
    cmd_FOCI_CURRENT_STEP_TEST_help = "Run a bounded FOCI current-loop step diagnostic"
    cmd_FOCI_CURRENT_VECTOR_STEP_TEST_help = (
        "Run a bounded FOCI current-vector step diagnostic"
    )
    cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST_help = (
        "Run a bounded FOCI torque pulse and sample it early"
    )
    cmd_FOCI_POSITION_TORQUE_OFFSET_TEST_help = (
        "Run a bounded FOCI position-mode torque-offset sample"
    )
    cmd_FOCI_VOLTAGE_STEP_TEST_help = (
        "Run a bounded FOCI open-loop voltage-vector diagnostic"
    )

    def __init__(self, config) -> None:
        # Parse section name: [foci stepper_x]
        self.stepper_name: str = " ".join(config.get_name().split()[1:])
        self.name: str = config.get_name()
        self._current_torque_sample_details: dict[tuple[int, int, int, int], dict] = {}
        self._current_torque_sample_labels: dict[tuple[int, int, int, int], str] = {}

        self.printer = config.get_printer()

        # Required motor config
        self.run_current: float = config.getfloat("run_current", above=0.0)
        self.encoder_ppr: int = config.getint("encoder_ppr", minval=1)
        # Encoder count direction relative to motor rotation.
        # "default" = encoder counts up when motor drives forward.
        # "reversed" = encoder counts down when motor drives forward
        #              (swap A/B wiring or mount orientation).
        dir_choice: str = config.getchoice(
            "encoder_direction",
            {"default": False, "reversed": True},
            default="default",
        )
        self.encoder_reversed: bool = dir_choice

        # Optional PID gains (from FOCI_AUTOTUNE + SAVE_CONFIG or manual).
        # All four must be set together or not at all.
        self.pid_flux_p: int | None = config.getint(
            "pid_flux_p", None, minval=0, maxval=65535
        )
        self.pid_flux_i: int | None = config.getint(
            "pid_flux_i", None, minval=0, maxval=65535
        )
        self.pid_torque_p: int | None = config.getint(
            "pid_torque_p", None, minval=0, maxval=65535
        )
        self.pid_torque_i: int | None = config.getint(
            "pid_torque_i", None, minval=0, maxval=65535
        )
        pid_gains = [
            self.pid_flux_p,
            self.pid_flux_i,
            self.pid_torque_p,
            self.pid_torque_i,
        ]
        pid_set = [v for v in pid_gains if v is not None]
        if pid_set and len(pid_set) != 4:
            raise config.error(
                "PID gains must be set as a complete group"
                " (pid_flux_p, pid_flux_i, pid_torque_p, pid_torque_i)."
                " Found %d of 4 in [%s]" % (len(pid_set), self.name)
            )

        # Optional biquad low-pass filters (0 = disabled, 10..1000 Hz)
        self.velocity_filter_hz: int = config.getint(
            "velocity_filter_hz", 0, minval=0, maxval=1000
        )
        if self.velocity_filter_hz != 0 and self.velocity_filter_hz < 10:
            raise config.error(
                "velocity_filter_hz must be 0 (disabled) or 10..1000 in [%s]"
                % self.name
            )
        self.torque_filter_hz: int = config.getint(
            "torque_filter_hz", 0, minval=0, maxval=1000
        )
        if self.torque_filter_hz != 0 and self.torque_filter_hz < 10:
            raise config.error(
                "torque_filter_hz must be 0 (disabled) or 10..1000 in [%s]" % self.name
            )
        self.position_filter_hz: int = config.getint(
            "position_filter_hz", 0, minval=0, maxval=1000
        )
        if self.position_filter_hz != 0 and self.position_filter_hz < 10:
            raise config.error(
                "position_filter_hz must be 0 (disabled) or 10..1000 in [%s]"
                % self.name
            )
        self.flux_filter_hz: int = config.getint(
            "flux_filter_hz", 0, minval=0, maxval=1000
        )
        if self.flux_filter_hz != 0 and self.flux_filter_hz < 10:
            raise config.error(
                "flux_filter_hz must be 0 (disabled) or 10..1000 in [%s]" % self.name
            )

        # Optional position/velocity PID gains (Q8.8 raw register values)
        self.pid_position_p: int | None = config.getint(
            "pid_position_p", None, minval=0, maxval=32767
        )
        self.pid_position_i: int | None = config.getint(
            "pid_position_i", None, minval=0, maxval=32767
        )
        self.pid_velocity_p: int | None = config.getint(
            "pid_velocity_p", None, minval=0, maxval=32767
        )
        self.pid_velocity_i: int | None = config.getint(
            "pid_velocity_i", None, minval=0, maxval=32767
        )
        pos_gains = [
            self.pid_position_p,
            self.pid_position_i,
            self.pid_velocity_p,
            self.pid_velocity_i,
        ]
        pos_set = [v for v in pos_gains if v is not None]
        if pos_set and len(pos_set) != 4:
            raise config.error(
                "pid_position_p/i and pid_velocity_p/i must be set together"
                " (pid_position_p, pid_position_i, pid_velocity_p, pid_velocity_i)."
                " Found %d of 4 in [%s]" % (len(pos_set), self.name)
            )

        # Velocity feedforward (boolean, default disabled)
        self.velocity_feedforward: bool = config.getboolean(
            "velocity_feedforward", False
        )
        self.velocity_feedforward_multiplier: int = config.getint(
            "velocity_feedforward_multiplier", 1, minval=0, maxval=65535
        )
        self.velocity_transient_feedforward: bool = False
        self.velocity_transient_lead_time_us: int = 0
        self.velocity_transient_gain: int = 0
        self.velocity_transient_max_offset: int = 0
        self.velocity_transient_rate_hz: int = 1000
        self.accel_feedforward: bool = False
        self.accel_feedforward_accel_gain: int = 1000
        self.accel_feedforward_decel_gain: int = 1000
        self.decoupling_feedforward: bool = False
        self.decoupling_r_int: int = 3000
        self.decoupling_l_int: int = 4095
        self.decoupling_pole_pairs: int = 50
        self.decoupling_position_units_per_rev: int = 65536
        self.decoupling_f_pwm_hz: int = 25000
        self.decoupling_max_offset: int = 500
        self.position_lead: bool = False
        self.position_lead_gain: int = 0
        self.position_lead_max_counts: int = 0
        self.phase_advance: bool = False
        self.phase_advance_gain_ppm: int = 0
        self.phase_advance_max_counts: int = 0
        self.phase_advance_deadband: int = 16

        # PID velocity limit (caps position PID output, anti-windup).
        # 0 or unset = unconstrained (0x7FFFFFFF). Units: TMC4671 internal
        # velocity. Appropriate value depends on motor/encoder config.
        self.pid_velocity_limit: int | None = config.getint(
            "pid_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
        )

        # Commissioned fallback gains (from Stage 1, separate from tuned gains)
        self.commissioned_velocity_p: int | None = config.getint(
            "commissioned_velocity_p", None, minval=0, maxval=32767
        )
        self.commissioned_velocity_i: int | None = config.getint(
            "commissioned_velocity_i", None, minval=0, maxval=32767
        )
        self.commissioned_position_p: int | None = config.getint(
            "commissioned_position_p", None, minval=0, maxval=32767
        )
        self.commissioned_position_i: int | None = config.getint(
            "commissioned_position_i", None, minval=0, maxval=32767
        )
        self.commissioned_velocity_limit: int | None = config.getint(
            "commissioned_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
        )

        # Inner-tuning parameters (persisted by Stage 1 for Stage 2 restart)
        self.identified_r_int: int | None = config.getint(
            "identified_r_int", None, minval=0
        )
        self.identified_l_int: int | None = config.getint(
            "identified_l_int", None, minval=0
        )
        self.identified_r_count_milli: int | None = config.getint(
            "identified_r_count_milli", None, minval=0
        )
        self.identified_l_count_micro: int | None = config.getint(
            "identified_l_count_micro", None, minval=0
        )
        self.identified_lambda_us: int | None = config.getint(
            "identified_lambda_us", None, minval=0
        )
        self.identified_theta_e_us: int | None = config.getint(
            "identified_theta_e_us", None, minval=0
        )
        self.identified_ringing_count: int | None = config.getint(
            "identified_ringing_count", None, minval=0, maxval=255
        )
        self.identified_bandwidth_hz: int | None = config.getint(
            "identified_bandwidth_hz", None, minval=0
        )

        # Phase 1 inner-confidence fields (added 2026-04-30). Optional in
        # the persisted config: old configs that never ran the new firmware
        # leave these unset and `_resolve_inner_confidence` substitutes
        # documented defaults (bit 6 = host-default confidence).
        self.identified_tau_e_us: int | None = config.getint(
            "identified_tau_e_us", None, minval=0
        )
        self.identified_tau_e_crosscheck_us: int | None = config.getint(
            "identified_tau_e_crosscheck_us", None, minval=0
        )
        self.identified_tau_residual_permille: int | None = config.getint(
            "identified_tau_residual_permille", None, minval=0, maxval=1000
        )
        self.identified_inner_warning_flags: int | None = config.getint(
            "identified_inner_warning_flags", None, minval=0, maxval=255
        )

        # Stage 2 model parameters persisted for traceability.
        self.identified_j_eff: int | None = config.getint(
            "identified_j_eff", None, minval=0
        )
        self.identified_b_eff: int | None = config.getint(
            "identified_b_eff", None, minval=0
        )

        # Persisted profile/mode labels from SAVE_CONFIG.
        self.autotune_profile: str | None = config.get("autotune_profile", None)
        self.autotune_mode: str | None = config.get("autotune_mode", None)

        # Autotune status (commissioned / tuned / tuned_conservative)
        self.autotune_status: str | None = config.get("autotune_status", None)

        # Find stepper config section. The stepper may be defined as
        # [manual_stepper stepper_x], [stepper stepper_x], or [stepper_x]
        # depending on kinematics. The foci section always uses the short
        # name: [foci stepper_x].
        if not config.has_section(self.stepper_name):
            raise config.error(
                "[%s] cannot find stepper section for '%s'"
                % (self.name, self.stepper_name)
            )
        stepper_config = config.getsection(self.stepper_name)

        self.microsteps: int = stepper_config.getint("microsteps")
        self.full_steps: int = stepper_config.getint("full_steps_per_rotation", 200)

        # Resolve MCU and channel from step_pin
        step_pin: str = stepper_config.get("step_pin")
        ppins = self.printer.lookup_object("pins")
        pin_params = ppins.parse_pin(step_pin, can_invert=True)
        pin_name: str = pin_params["pin"]
        if pin_name not in STEP_PINS:
            raise config.error(
                "[%s] step_pin '%s' is not a FOCI STEP pin (expected one"
                " of: %s)" % (self.name, pin_name, ", ".join(sorted(STEP_PINS)))
            )
        self.mcu = pin_params["chip"]
        self.channel: int = STEP_PINS[pin_name]

        # Runtime FOCI commands use the Klipper stepper OID. It is resolved
        # after MCU identification, when Klipper has loaded all steppers.
        self.oid: int | None = None
        self.stepper_oid: int | None = None

        # Command handles — resolved in _handle_mcu_identify after
        # the MCU data dictionary is loaded.
        self.set_current_cmd = None
        self.set_encoder_cmd = None
        self.set_encoder_dir_cmd = None
        self.selftest_cmd = None
        self.read_reg_cmd = None
        self.calibrate_cmd = None
        self.dump_cmd = None
        self.set_pid_gains_cmd = None
        self.commission_cmd = None
        self.tune_cmd = None
        self.set_velocity_filter_cmd = None
        self.set_position_gains_cmd = None
        self.set_velocity_feedforward_cmd = None
        self.set_velocity_transient_feedforward_cmd = None
        self.set_accel_feedforward_cmd = None
        self.set_decoupling_feedforward_cmd = None
        self.set_position_lead_cmd = None
        self.set_phase_advance_cmd = None
        self.set_velocity_limit_cmd = None
        self.set_voltage_limit_cmd = None
        self.set_auto_calibrate_on_enable_cmd = None
        self.trace_info_cmd = None
        self.trace_fetch_cmd = None
        self.trace_start_cmd = None
        self.trace_stop_cmd = None
        self.stepper_get_position_cmd = None
        self.stepper_stats_cmd = None
        self.stepper_exec_stats_cmd = None
        self.stepper_timing_stats_cmd = None
        self.stepper_stop_stats_cmd = None
        self.stepper_perf_stats_cmd = None

        # Trace capture state
        self._trace_info: dict | None = None
        self._trace_info_received: bool = False
        self._homing_move_start_times: dict[int, float] = {}

        # Calibration state
        self.is_calibrated = False
        self._calibration_completion = None

        # Dump state
        self._dump_buffer: dict[int, int] = {}
        self._dump_complete = False

        # Selftest streaming state (populated by foci_selftest_result / foci_selftest_done).
        self._selftest_results: list[dict] = []
        self._selftest_complete: bool = False
        self._selftest_status: int = 0

        # Two-stage commissioning volatile state (per-session, not persisted)
        # See spec: docs/specs/2026-04-11-two-stage-foci-commissioning-design.md
        self._inhibited: bool = False
        self._commissioned_result: dict | None = None  # CommissionResult cache
        self._active_gains: dict | None = None  # SavedGains for re-enable
        self._runtime_status: str | None = (
            None  # 'commissioned'|'tuned'|'tuned_conservative'
        )
        self._foci_lock: bool = False  # Operation lock (non-blocking try-acquire)

        # Commissioning phase tracking (used by commission/tune progress callbacks)
        self._last_phase_id: int | None = None
        self._commission_result: dict | None = None  # inner or outer result
        self._commission_done: bool = False
        self._commission_error_code: int = 0
        self._commission_details: list[dict] = []

        # Track whether enable methods have been monkey-patched
        self._enable_patched = False

        # Field formatting helper
        self.fields = FieldHelper(Fields, SIGNED_FIELDS, FIELD_FORMATTERS)

        # Register GCode commands
        gcode = self.printer.lookup_object("gcode")
        gcode.register_mux_command(
            "DUMP_FOCI",
            "STEPPER",
            self.stepper_name,
            self.cmd_DUMP_FOCI,
            desc=self.cmd_DUMP_FOCI_help,
        )
        gcode.register_mux_command(
            "DUMP_TMC",
            "STEPPER",
            self.stepper_name,
            self.cmd_DUMP_FOCI,
            desc=self.cmd_DUMP_FOCI_help,
        )
        gcode.register_mux_command(
            "FOCI_SELFTEST",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SELFTEST,
            desc=self.cmd_FOCI_SELFTEST_help,
        )
        gcode.register_mux_command(
            "FOCI_COMMISSION",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_COMMISSION,
            desc=self.cmd_FOCI_COMMISSION_help,
        )
        gcode.register_mux_command(
            "FOCI_AUTOTUNE",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_AUTOTUNE,
            desc=self.cmd_FOCI_AUTOTUNE_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_GAINS",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_GAINS,
            desc=self.cmd_FOCI_SET_GAINS_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_INNER_GAINS",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_INNER_GAINS,
            desc=self.cmd_FOCI_SET_INNER_GAINS_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_CURRENT",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_CURRENT,
            desc=self.cmd_FOCI_SET_CURRENT_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_VELOCITY_FEEDFORWARD",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_VELOCITY_FEEDFORWARD,
            desc=self.cmd_FOCI_SET_VELOCITY_FEEDFORWARD_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD,
            desc=self.cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_ACCEL_FEEDFORWARD",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_ACCEL_FEEDFORWARD,
            desc=self.cmd_FOCI_SET_ACCEL_FEEDFORWARD_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_DECOUPLING_FEEDFORWARD",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_DECOUPLING_FEEDFORWARD,
            desc=self.cmd_FOCI_SET_DECOUPLING_FEEDFORWARD_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_POSITION_LEAD",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_POSITION_LEAD,
            desc=self.cmd_FOCI_SET_POSITION_LEAD_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_PHASE_ADVANCE",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_PHASE_ADVANCE,
            desc=self.cmd_FOCI_SET_PHASE_ADVANCE_help,
        )
        gcode.register_mux_command(
            "FOCI_SET_VOLTAGE_LIMIT",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_SET_VOLTAGE_LIMIT,
            desc=self.cmd_FOCI_SET_VOLTAGE_LIMIT_help,
        )
        gcode.register_mux_command(
            "FOCI_CURRENT_STEP_TEST",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_CURRENT_STEP_TEST,
            desc=self.cmd_FOCI_CURRENT_STEP_TEST_help,
        )
        gcode.register_mux_command(
            "FOCI_CURRENT_VECTOR_STEP_TEST",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_CURRENT_VECTOR_STEP_TEST,
            desc=self.cmd_FOCI_CURRENT_VECTOR_STEP_TEST_help,
        )
        gcode.register_mux_command(
            "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST,
            desc=self.cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST_help,
        )
        gcode.register_mux_command(
            "FOCI_POSITION_TORQUE_OFFSET_TEST",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_POSITION_TORQUE_OFFSET_TEST,
            desc=self.cmd_FOCI_POSITION_TORQUE_OFFSET_TEST_help,
        )
        gcode.register_mux_command(
            "FOCI_VOLTAGE_STEP_TEST",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_VOLTAGE_STEP_TEST,
            desc=self.cmd_FOCI_VOLTAGE_STEP_TEST_help,
        )
        gcode.register_mux_command(
            "FOCI_TRACE",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_TRACE,
            desc=self.cmd_FOCI_TRACE_help,
        )
        gcode.register_mux_command(
            "FOCI_TRACE_START",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_TRACE_START,
            desc=self.cmd_FOCI_TRACE_START_help,
        )
        gcode.register_mux_command(
            "FOCI_TRACE_STOP",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_TRACE_STOP,
            desc=self.cmd_FOCI_TRACE_STOP_help,
        )
        gcode.register_mux_command(
            "FOCI_STEP_POSITION",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_STEP_POSITION,
            desc=self.cmd_FOCI_STEP_POSITION_help,
        )
        gcode.register_mux_command(
            "FOCI_STEPPER_STATS",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_STEPPER_STATS,
            desc=self.cmd_FOCI_STEPPER_STATS_help,
        )
        gcode.register_mux_command(
            "FOCI_DISPATCH_STATS",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_DISPATCH_STATS,
            desc=self.cmd_FOCI_DISPATCH_STATS_help,
        )

        # Lifecycle events
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "homing:home_rails_begin", self._handle_home_rails_begin
        )
        self.printer.register_event_handler(
            "homing:homing_move_begin", self._handle_homing_move_begin
        )
        self.printer.register_event_handler(
            "homing:homing_move_end", self._handle_homing_move_end
        )

    def _find_linked_stepper(self):
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is not None:
            kin = toolhead.get_kinematics()
            rails = getattr(kin, "rails", None)
            if rails is None and hasattr(kin, "get_rails"):
                rails = kin.get_rails()
            if rails is not None:
                for rail in rails:
                    for stepper in rail.get_steppers():
                        if stepper.get_name() == self.stepper_name:
                            return stepper
            get_steppers = getattr(kin, "get_steppers", None)
            if get_steppers is not None:
                for stepper in get_steppers():
                    if stepper.get_name() == self.stepper_name:
                        return stepper
        for _name, manual_stepper in self.printer.lookup_objects("manual_stepper"):
            steppers = getattr(manual_stepper, "steppers", [])
            for stepper in steppers:
                if stepper.get_name() == self.stepper_name:
                    return stepper
        return None

    def _resolve_stepper_oid(self) -> int:
        force_move = self.printer.lookup_object("force_move", None)
        if force_move is not None and hasattr(force_move, "lookup_stepper"):
            stepper = force_move.lookup_stepper(self.stepper_name)
        else:
            stepper = self._find_linked_stepper()
        if stepper is None or not hasattr(stepper, "get_oid"):
            raise self.printer.config_error(
                "[%s] could not resolve MCU stepper OID for %s"
                % (self.name, self.stepper_name)
            )
        oid = stepper.get_oid()
        if oid is None:
            raise self.printer.config_error(
                "[%s] could not resolve MCU stepper OID for %s"
                % (self.name, self.stepper_name)
            )
        return oid

    def _handle_mcu_identify(self) -> None:
        """Look up MCU commands after data dictionary is loaded."""
        self.stepper_oid = self._resolve_stepper_oid()
        self.oid = self.stepper_oid
        cmd_queue = self.mcu.alloc_command_queue()
        self.stepper_get_position_cmd = self.mcu.lookup_query_command(
            "stepper_get_position oid=%c",
            "stepper_position oid=%c pos=%i",
            oid=self.oid,
        )
        self.stepper_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_stats oid=%c",
            "foci_stepper_stats_result oid=%c channel=%c position=%i"
            " queued_segments=%u queued_steps=%u"
            " loaded_segments=%u loaded_steps=%u"
            " discarded_segments=%u discarded_steps=%u"
            " timer_active=%c queue_len=%hu",
            oid=self.oid,
        )
        self.stepper_exec_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_exec_stats oid=%c",
            "foci_stepper_exec_stats_result oid=%c channel=%c"
            " executed_pos_steps=%u executed_neg_steps=%u"
            " queue_empty_count=%u missed_deadline_count=%u",
            oid=self.oid,
        )
        self.stepper_timing_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_timing_stats oid=%c",
            "foci_stepper_timing_stats_result oid=%c channel=%c"
            " activation_count=%u last_activation_clock=%u"
            " first_load_now=%u first_load_scheduled=%u first_load_compare=%u"
            " first_load_lead_ticks=%i first_load_compare_delay_ticks=%i"
            " first_step_clock=%u first_step_delay_ticks=%i",
            oid=self.oid,
        )
        self.stepper_stop_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_stop_stats oid=%c",
            "foci_stepper_stop_stats_result oid=%c channel=%c"
            " stop_count=%u stop_drained_segments=%u stop_drained_steps=%u"
            " reset_count=%u reset_drained_segments=%u reset_drained_steps=%u"
            " last_stop_reason=%c"
            " last_stop_remaining_events=%u last_stop_queue_len=%hu"
            " last_stop_drained_segments=%u last_stop_drained_steps=%u",
            oid=self.oid,
        )
        self.stepper_perf_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_perf_stats oid=%c clear=%c",
            "foci_stepper_perf_stats_result oid=%c channel=%c"
            " sample_count=%u crit_count=%u"
            " crit_max_cycles=%u crit_max_site=%c"
            " crit_over_10us=%u crit_over_50us=%u"
            " crit_over_100us=%u crit_over_1000us=%u"
            " queue_step_count=%u queue_step_max_cycles=%u"
            " tim5_activation_count=%u tim5_irq_max_cycles=%u"
            " tim5_dispatch_max_cycles=%u tim5_events_max_per_irq=%u"
            " tim5_event_count_total=%u tim5_defer_count=%u"
            " tim5_empty_count=%u tim5_events_last_activation=%u"
            " tim5_burst_cycles_per_event_max=%u"
            " tim5_entry_latency_max_ticks=%u"
            " tim5_pop_lateness_max_ticks=%u"
            " stepper_load_lateness_max_ticks=%u"
            " stepper_load_lateness_last_ticks=%i build_trace_enabled=%c",
            oid=self.oid,
        )
        self.set_current_cmd = self.mcu.lookup_command(
            "tmc_set_current oid=%c run_ma=%u"
        )
        self.set_encoder_cmd = self.mcu.lookup_command(
            "tmc_set_encoder oid=%c channel=%c ppr=%u"
        )
        self.set_encoder_dir_cmd = self.mcu.lookup_command(
            "tmc_set_encoder_dir oid=%c channel=%c invert=%c"
        )
        self.selftest_cmd = self.mcu.lookup_command("foci_selftest oid=%c")
        # tmc_read_register is only available in dev firmware builds
        # (#[cfg(feature = "dev")]). Gracefully degrade on release builds.
        try:
            self.read_reg_cmd = self.mcu.lookup_query_command(
                "tmc_read_register oid=%c addr=%c",
                "tmc_register_value oid=%c addr=%c value=%u",
                oid=self.oid,
            )
        except Exception:
            self.read_reg_cmd = None
        self.calibrate_cmd = self.mcu.lookup_command(
            "foci_calibrate oid=%c", cq=cmd_queue
        )
        self.dump_cmd = self.mcu.lookup_command("foci_dump_registers oid=%c")
        self.mcu._serial.register_response(
            self._handle_dump_value, "foci_dump_value", self.oid
        )
        self.mcu._serial.register_response(
            self._handle_dump_done, "foci_dump_done", self.oid
        )
        self.mcu._serial.register_response(
            self._handle_calibrate_response, "foci_calibrate_result", self.oid
        )
        self.set_pid_gains_cmd = self.mcu.lookup_command(
            "tmc_set_pid_gains oid=%c flux_p=%hu flux_i=%hu torque_p=%hu torque_i=%hu"
        )
        self.commission_cmd = self.mcu.lookup_command(
            "foci_commission oid=%c profile=%c"
        )
        self.tune_cmd = self.mcu.lookup_command(
            "foci_tune oid=%c profile=%c mode=%c"
            " inner_lambda=%u theta_e=%u current_ringing=%c current_bw=%u"
            " tau_e_us=%u tau_e_crosscheck_us=%u"
            " tau_residual_permille=%hu inner_warning_flags=%c"
        )
        self.mcu._serial.register_response(
            self._handle_commission_phase, "foci_commission_phase", self.oid
        )
        self.mcu._serial.register_response(
            self._handle_commission_result,
            "foci_commission_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_tune_result,
            "foci_tune_result",
            self.oid,
        )
        self.set_velocity_filter_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_filter oid=%c filter_hz=%hu"
        )
        self.set_torque_filter_cmd = self.mcu.lookup_command(
            "tmc_set_torque_filter oid=%c filter_hz=%hu"
        )
        self.set_position_filter_cmd = self.mcu.lookup_command(
            "tmc_set_position_filter oid=%c filter_hz=%hu"
        )
        self.set_flux_filter_cmd = self.mcu.lookup_command(
            "tmc_set_flux_filter oid=%c filter_hz=%hu"
        )
        self.set_position_gains_cmd = self.mcu.lookup_command(
            "tmc_set_position_gains oid=%c position_p=%hu position_i=%hu"
            " velocity_p=%hu velocity_i=%hu"
        )
        self.set_velocity_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_feedforward oid=%c enable=%c multiplier=%hu"
        )
        self.set_velocity_transient_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_transient_feedforward oid=%c enable=%c"
            " lead_time_us=%hu gain_permille=%hu max_offset=%hu rate_hz=%hu"
        )
        self.set_accel_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_accel_feedforward oid=%c enable=%c"
            " accel_gain_permille=%hu decel_gain_permille=%hu"
        )
        self.set_decoupling_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_decoupling_feedforward oid=%c enable=%c"
            " r_int=%u l_int=%u pole_pairs=%hu position_units_per_rev=%u"
            " f_pwm_hz=%u max_offset=%hu"
        )
        self.set_position_lead_cmd = self.mcu.lookup_command(
            "tmc_set_position_lead oid=%c enable=%c gain_permille=%hu max_counts=%hu"
        )
        self.set_phase_advance_cmd = self.mcu.lookup_command(
            "tmc_set_phase_advance oid=%c enable=%c"
            " gain_ppm=%i max_counts=%hu deadband=%hu"
        )
        self.set_velocity_limit_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_limit oid=%c limit=%u"
        )
        self.set_voltage_limit_cmd = self.mcu.lookup_command(
            "tmc_set_voltage_limit oid=%c voltage_limit=%u"
        )
        self.current_step_test_cmd = self.mcu.lookup_command(
            "tmc_current_step_test oid=%c target=%hi duration_ms=%hu voltage_limit=%hu"
        )
        self.current_vector_step_test_cmd = self.mcu.lookup_command(
            "tmc_current_vector_step_test oid=%c torque_target=%hi flux_target=%hi"
            " duration_ms=%hu voltage_limit=%hu"
        )
        self.current_torque_sample_test_cmd = self.mcu.lookup_command(
            "tmc_current_torque_sample_test oid=%c target=%hi flux_target=%hi"
            " sample_delay_ms=%hu voltage_limit=%hu"
        )
        self.position_torque_offset_sample_test_cmd = self.mcu.lookup_command(
            "tmc_position_torque_offset_sample_test oid=%c target=%hi"
            " sample_delay_ms=%hu voltage_limit=%hu"
        )
        self.voltage_step_test_cmd = self.mcu.lookup_command(
            "tmc_voltage_step_test oid=%c uq_ext=%hi ud_ext=%hi sample_delay_ms=%hu"
        )
        self.mcu._serial.register_response(
            self._handle_current_step_result,
            "foci_current_step_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_current_vector_step_result,
            "foci_current_vector_step_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_current_torque_sample_result,
            "foci_current_torque_sample_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_current_torque_sample_detail_result,
            "foci_current_torque_sample_detail_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_voltage_step_result,
            "foci_voltage_step_result",
            self.oid,
        )
        self.set_auto_calibrate_on_enable_cmd = self.mcu.lookup_command(
            "tmc_set_auto_calibrate_on_enable oid=%c enable=%c"
        )
        self.trace_info_cmd = self.mcu.lookup_command("foci_trace_info oid=%c")
        self.trace_start_cmd = self.mcu.lookup_command(
            "foci_trace_start oid=%c preset=%c"
        )
        self.trace_stop_cmd = self.mcu.lookup_command("foci_trace_stop oid=%c")
        self.trace_fetch_cmd = self.mcu.lookup_query_command(
            "foci_trace_fetch oid=%c offset=%hu generation=%c",
            "foci_trace_data oid=%c offset=%hu status=%c data=%*s",
            oid=self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_trace_info_result,
            "foci_trace_info_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_selftest_result,
            "foci_selftest_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_selftest_done,
            "foci_selftest_done",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_commission_detail,
            "foci_commission_detail",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_stepper_event,
            "foci_stepper_event",
        )
        self.mcu._serial.register_response(
            self._handle_stepper_perf_event,
            "foci_stepper_perf_event",
        )

    def _read_register(self, reg_name: str) -> int:
        """Read a single TMC4671 register via the firmware.

        Args:
            reg_name: Name of the register to read (must be in REGISTERS).

        Returns:
            The 32-bit register value returned by the firmware.

        Raises:
            command_error: If raw register access is not available in this
                firmware build.
        """
        if self.read_reg_cmd is None:
            raise self.printer.command_error(
                "Raw register access requires dev firmware build"
            )
        addr = REGISTERS[reg_name]
        params = self.read_reg_cmd.send([self.oid, addr])
        return params["value"]

    @staticmethod
    def _stepper_dir_inverted(stepper) -> bool:
        get_dir_inverted = getattr(stepper, "get_dir_inverted", None)
        if get_dir_inverted is None:
            return False
        dir_info = get_dir_inverted()
        if isinstance(dir_info, (list, tuple)):
            return bool(dir_info[0])
        return bool(dir_info)

    def _handle_dump_value(self, params: dict) -> None:
        """Handle a single register value from the firmware dump."""
        self._dump_buffer[params["addr"]] = params["value"]

    def _handle_dump_done(self, params: dict) -> None:
        """Handle dump completion signal from firmware."""
        self._dump_complete = True

    # -----------------------------------------------------------------
    # Commissioning phase/error/profile/mode maps
    # -----------------------------------------------------------------

    PHASE_NAMES: dict[int, str] = {
        1: "ADC calibration",
        2: "Coil check",
        3: "Phase wiring",
        4: "Encoder check",
        5: "Electrical ID",
        6: "Current tune",
        7: "Current validation",
        8: "Inner done",
        9: "Mechanical ID",
        10: "Velocity tune",
        11: "Velocity validation",
        12: "Position tune",
        13: "Filter selection",
        14: "Commit",
        15: "Outer done",
        16: "Encoder alignment",
        17: "Closed-loop entry",
    }

    STEPPER_EVENT_REASON_NAMES: dict[int, str] = {
        1: "queue_empty",
        2: "missed_deadline_load",
        3: "missed_deadline_step",
        4: "trsync_stop",
        5: "p1_stop",
        6: "reset_step_clock",
        7: "tmc_disable_signal",
    }

    COMMISSION_ERROR_NAMES: dict[int, str] = {
        1: "motor already enabled",
        2: "no current detected",
        3: "SPI communication error",
        4: "ADC calibration fault",
        5: "coil connectivity fault",
        6: "phase wiring fault",
        7: "encoder fault",
        8: "electrical identification failed",
        9: "current validation failed",
        10: "mechanical identification failed",
        11: "velocity validation failed",
        12: "position tune failed",
        13: "encoder not aligned",
        14: "shutdown requested",
        15: "commissioning already running",
        16: "command queue full",
        17: "safety envelope violation",
    }

    # Error codes that indicate a hard-disable fault: firmware has
    # disabled the motor and cleared its state. The host must sync
    # its enable line and clear is_calibrated.
    # 3 = SPI error, 9 = current validation failed (post-restore
    # stability check in Stage 2), 14 = shutdown, 17 = safety envelope.
    HARD_FAULT_CODES: frozenset[int] = frozenset({3, 9, 14, 17})

    # Bit-to-name mapping for the firmware-side `inner_warning_flags`
    # bitfield (matches docs/specs/2026-04-30-inner-commissioning-stability.md
    # §4). Bit 7 is reserved for future Phase 2 use.
    INNER_WARNING_FLAG_NAMES: list[tuple[int, str]] = [
        (1 << 0, "coil R mismatch"),
        (1 << 1, "coil tau mismatch"),
        (1 << 2, "tau residual"),
        (1 << 3, "theta/tau ratio"),
        (1 << 4, "current validation retry"),
        (1 << 5, "current gains fell back to defaults"),
        (1 << 6, "host-default confidence (no fresh measurement)"),
    ]

    PROFILE_MAP: dict[str, int] = {
        "conservative": 0,
        "balanced": 1,
        "stiff": 2,
    }

    MODE_MAP: dict[str, int] = {
        "unloaded": 0,
        "nominal": 1,
        "high_inertia": 2,
    }

    SELFTEST_STAGES: dict[int, str] = {
        1: "ADC calibration",
        2: "Motor coil A",
        3: "Motor coil B",
        4: "Phase wiring",
        5: "Encoder",
        6: "Encoder direction",
        7: "Resistance",
        8: "Inductance",
    }

    ELECTRICAL_ID_DETAIL_NAMES: dict[int, str] = {
        1: "excitation",
        2: "coil A resistance",
        3: "coil B resistance",
        4: "coil A inductance",
        5: "coil B inductance",
        6: "transient",
        20: "no usable per-coil samples",
        21: "only one coil produced non-zero tau",
        22: "model scale rounded to zero",
        23: "resistance below short threshold",
        24: "resistance above open threshold",
        25: "coil resistance mismatch",
        26: "coil tau mismatch",
        27: "tau crosscheck unmeasurable",
        28: "tau residual too high",
        29: "transport delay too large",
    }

    @classmethod
    def _format_commission_detail(cls, detail: dict) -> str:
        phase_name = cls.PHASE_NAMES.get(detail["phase"], "Phase %d" % detail["phase"])
        code = detail["code"]
        name = cls.ELECTRICAL_ID_DETAIL_NAMES.get(code, "diagnostic %d" % code)
        value0 = detail["value0"]
        value1 = detail["value1"]
        value2 = detail["value2"]
        if detail["phase"] == 2 and code in (1, 2):
            coil = "A" if code == 1 else "B"
            expected = value0 if value0 < 0x8000 else value0 - 0x10000
            other = value1 if value1 < 0x8000 else value1 - 0x10000
            status = "FAIL" if detail["status"] else "PASS"
            return (
                "%s: coil %s sample %s "
                "(expected=%d counts, other=%d counts, raw=0x%08x)"
                % (phase_name, coil, status, expected, other, value2)
            )
        if code == 1:
            return "%s: %s (voltage_count=%d, didt_cycles=%d, sample_period=%dus)" % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        if code in (2, 3):
            return "%s: %s (avg_current=%d counts, r=%d mOhm, samples=%d)" % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        if code in (4, 5):
            return "%s: %s (avg_delta=%d counts, tau=%dus, samples=%d)" % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        if code == 6:
            return "%s: %s (steady_state=%d counts, theta=%dus, crosscheck=%dus)" % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        if code in (25, 26):
            return "%s: %s (%d permille, limit=%d)" % (
                phase_name,
                name,
                value0,
                value1,
            )
        if code == 28:
            return "%s: %s (%d permille, tau=%dus, crosscheck=%dus)" % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        if code in (23, 24):
            return "%s: %s (r_count_milli=%d, limit=%d)" % (
                phase_name,
                name,
                value0,
                value1,
            )
        if code == 22:
            return "%s: %s (l_int=%d, l_count_micro=%d)" % (
                phase_name,
                name,
                value0,
                value1,
            )
        if code == 29:
            return "%s: %s (theta_us=%d, tau_us=%d)" % (
                phase_name,
                name,
                value0,
                value1,
            )
        if value0 or value1 or value2:
            return "%s: %s (value0=%d, value1=%d, value2=%d)" % (
                phase_name,
                name,
                value0,
                value1,
                value2,
            )
        return "%s: %s" % (phase_name, name)

    @staticmethod
    def _format_selftest_value(stage: int, status: int, value: int) -> str:
        """Return a stage-specific detail string (empty string for bare PASS).

        ``value`` is decoded per the firmware-side encoding in foci-core:

        - stage 1 (ADC calibration): low 16 bits = offset_i0, high 16 bits = offset_i1
        - stages 2, 3 (coil currents): i16 bit-reinterpreted as u16, then zero-extended
        - stage 4 (phase wiring): value is always 0
        - stage 5 (encoder delta): unsigned magnitude (sign in stage 6)
        - stage 6 (encoder direction): 0 = increasing, 1 = reversed
        - stage 7 (resistance): milliohms
        - stage 8 (inductance): microhenries

        Args:
            stage: Stage number (1–8) as reported by the firmware.
            status: 0 = pass, non-zero = fail.
            value: Stage-specific encoded value from the firmware.

        Returns:
            A parenthesised detail string, or an empty string when no
            per-stage detail is applicable (e.g. bare phase-wiring pass).
        """
        if status != 0:
            return " (FAIL, raw=%d)" % value
        if stage == 1:
            offset_i0 = value & 0xFFFF
            offset_i1 = (value >> 16) & 0xFFFF
            return " (offset_i0=%d, offset_i1=%d)" % (offset_i0, offset_i1)
        if stage in (2, 3):
            # Value is an i16 whose two's-complement bit pattern was stored
            # in the low 16 bits of a u32. Reinterpret bit 15 as sign.
            low16 = value & 0xFFFF
            signed = low16 if low16 < 0x8000 else low16 - 0x10000
            return " (current=%d)" % signed
        if stage == 4:
            return ""
        if stage == 5:
            return " (delta=%d)" % value
        if stage == 6:
            return " (reversed)" if value == 1 else " (increasing)"
        if stage == 7:
            return " (%.1f ohm)" % (value / 1000.0)
        if stage == 8:
            return " (%.1f mH)" % (value / 1000.0)
        return ""

    def _handle_commission_phase(self, params: dict) -> None:
        """Handle foci_commission_phase message from firmware.

        Caches the most recent phase ID for failure reporting and
        reports phase transitions to the Klipper console. A message with
        phase=0 and nonzero status signals a command admission failure before
        a terminal result message exists. The Stage 1 and Stage 2 poll loops
        both watch this error code so they can report the real failure instead
        of timing out.
        """
        phase_id = params.get("phase", 0)
        status = params.get("status", 0)
        if phase_id > 0 and status == 0:
            self._last_phase_id = phase_id
            phase_name = self.PHASE_NAMES.get(phase_id, "Phase %d" % phase_id)
            gcode = self.printer.lookup_object("gcode")
            gcode.respond_info("FOCI %s autotune: %s" % (self.stepper_name, phase_name))
        elif phase_id == 0 and status != 0:
            self._commission_error_code = status

    def _handle_commission_result(self, params: dict) -> None:
        """Handle foci_commission_result from firmware (Stage 1 completion)."""
        self._commission_result = params
        self._commission_done = True

    def _handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware (Stage 2 completion)."""
        self._commission_result = params
        self._commission_done = True

    def _handle_current_step_result(self, params: dict) -> None:
        """Handle foci_current_step_result from firmware."""
        msg = (
            "FOCI %s current step: status=%d target=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.name,
                params["status"],
                params["target"],
                params["torque_during"],
                params["torque_before"],
                params["torque_after"],
                params["flux_during"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.printer.lookup_object("gcode").respond_info(msg)

    def _handle_current_vector_step_result(self, params: dict) -> None:
        """Handle foci_current_vector_step_result from firmware."""
        msg = (
            "FOCI %s current vector step: status=%d"
            " torque_target=%d flux_target=%d"
            " actual_torque=%d actual_flux=%d"
            " before=%d after=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.name,
                params["status"],
                params["torque_target"],
                params["flux_target"],
                params["torque_during"],
                params["flux_during"],
                params["torque_before"],
                params["torque_after"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.printer.lookup_object("gcode").respond_info(msg)

    def _handle_current_torque_sample_result(self, params: dict) -> None:
        """Handle foci_current_torque_sample_result from firmware."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        detail = self._current_torque_sample_details.pop(detail_key, {})
        label = self._current_torque_sample_labels.pop(
            detail_key, "current torque sample"
        )
        msg = (
            "FOCI %s %s: status=%d"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " pidin_target_torque=%d pidin_target_flux=%d"
            " pidout_target_torque=%d pidout_target_flux=%d"
            " pid_torque_target_monitor=%d"
            " torque_error=%d flux_error=%d"
            " torque_error_sum=%d flux_error_sum=%d"
            " uq_prelimit=%d ud_prelimit=%d"
            " ff_velocity=%d ff_torque=%d"
            " status_flags=0x%08x"
            % (
                self.name,
                label,
                params["status"],
                params["target"],
                params.get("flux_target", 0),
                params["sample_delay_ms"],
                params["voltage_limit"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params.get("pidin_target_torque", 0),
                params.get("pidin_target_flux", 0),
                params.get("pidout_target_torque", 0),
                params.get("pidout_target_flux", 0),
                params.get("pid_torque_target_monitor", 0),
                detail.get("torque_error", 0),
                detail.get("flux_error", 0),
                detail.get("torque_error_sum", 0),
                detail.get("flux_error_sum", 0),
                detail.get("uq_prelimit", 0),
                detail.get("ud_prelimit", 0),
                detail.get("ff_velocity", 0),
                detail.get("ff_torque", 0),
                params.get("status_flags", 0),
            )
        )
        self.printer.lookup_object("gcode").respond_info(msg)

    def _handle_current_torque_sample_detail_result(self, params: dict) -> None:
        """Cache split current torque sample details until the base reply arrives."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        self._current_torque_sample_details[detail_key] = params

    def _handle_voltage_step_result(self, params: dict) -> None:
        """Handle foci_voltage_step_result from firmware."""
        msg = (
            "FOCI %s voltage step: status=%d"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " uux_sample=%d uwy_sample=%d"
            " pwm_ux_sample=%d pwm_wy_sample=%d"
            " pwm_sv_chop=0x%08x pwm_bbm=0x%08x pwm_maxcnt=%d"
            " phi_e_sample=%d phi_m_sample=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " status_flags=0x%08x"
            % (
                self.name,
                params["status"],
                params["uq_ext"],
                params["ud_ext"],
                params["sample_delay_ms"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["uux_sample"],
                params["uwy_sample"],
                params["pwm_ux_sample"],
                params["pwm_wy_sample"],
                params["pwm_sv_chop"],
                params["pwm_bbm"],
                params["pwm_maxcnt"],
                params["phi_e_sample"],
                params["phi_m_sample"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params["status_flags"],
            )
        )
        self.printer.lookup_object("gcode").respond_info(msg)

    def _format_stepper_event(self, params: dict) -> str:
        """Format one firmware stepper diagnostic event."""
        reason_code = params.get("reason", 0)
        reason_name = self.STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")
        return (
            "FOCI_STEPPER_EVENT %s reason=%s(%d) channel=%d pos=%d"
            " clock=%d timer_active=%d queue_len=%d dir=%d data0=%d data1=%d"
            % (
                self.stepper_name,
                reason_name,
                reason_code,
                params.get("channel", 255),
                params.get("position", 0),
                params.get("clock", 0),
                params.get("timer_active", 0),
                params.get("queue_len", 65535),
                params.get("direction", 0),
                params.get("data0", 0),
                params.get("data1", 0),
            )
        )

    def _handle_stepper_event(self, params: dict) -> None:
        """Handle bounded firmware stepper diagnostics."""
        message = self._format_stepper_event(params)
        log.info(message)
        gcode = self.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def _format_stepper_perf_event(self, params: dict) -> str:
        """Format one fatal firmware step-dispatch performance snapshot."""
        reason_code = params.get("reason", 0)
        reason_name = self.STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")

        def cycles_to_us(field: str) -> int | str:
            value = params.get(field)
            if value is None:
                return "?"
            return int(value) // OPENFFBOARD_CPU_CYCLES_PER_US

        return (
            "FOCI_STEPPER_PERF_EVENT %s reason=%s(%d) channel=%d clock=%d"
            " sample_count=%d crit_count=%d crit_max_cycles=%d crit_max_site=%d"
            " crit_max_us=%s crit_over_10us=%d crit_over_50us=%d"
            " crit_over_100us=%d crit_over_1000us=%d queue_step_count=%d"
            " queue_step_max_cycles=%d queue_step_max_us=%s"
            " tim5_activation_count=%d"
            " tim5_irq_max_cycles=%d tim5_irq_max_us=%s"
            " tim5_dispatch_max_cycles=%d tim5_dispatch_max_us=%s"
            " tim5_events_max_per_irq=%d"
            " tim5_event_count_total=%d tim5_defer_count=%d"
            " tim5_empty_count=%d tim5_events_last_activation=%d"
            " tim5_burst_cycles_per_event_max=%d"
            " tim5_entry_latency_max_ticks=%d tim5_pop_lateness_max_ticks=%d"
            " stepper_load_lateness_max_ticks=%d"
            " stepper_load_lateness_last_ticks=%d build_trace_enabled=%d"
            % (
                self.stepper_name,
                reason_name,
                reason_code,
                params.get("channel", 255),
                params.get("clock", 0),
                params.get("sample_count", 0),
                params.get("crit_count", 0),
                params.get("crit_max_cycles", 0),
                params.get("crit_max_site", 0),
                cycles_to_us("crit_max_cycles"),
                params.get("crit_over_10us", 0),
                params.get("crit_over_50us", 0),
                params.get("crit_over_100us", 0),
                params.get("crit_over_1000us", 0),
                params.get("queue_step_count", 0),
                params.get("queue_step_max_cycles", 0),
                cycles_to_us("queue_step_max_cycles"),
                params.get("tim5_activation_count", 0),
                params.get("tim5_irq_max_cycles", 0),
                cycles_to_us("tim5_irq_max_cycles"),
                params.get("tim5_dispatch_max_cycles", 0),
                cycles_to_us("tim5_dispatch_max_cycles"),
                params.get("tim5_events_max_per_irq", 0),
                params.get("tim5_event_count_total", 0),
                params.get("tim5_defer_count", 0),
                params.get("tim5_empty_count", 0),
                params.get("tim5_events_last_activation", 0),
                params.get("tim5_burst_cycles_per_event_max", 0),
                params.get("tim5_entry_latency_max_ticks", 0),
                params.get("tim5_pop_lateness_max_ticks", 0),
                params.get("stepper_load_lateness_max_ticks", 0),
                params.get("stepper_load_lateness_last_ticks", 0),
                params.get("build_trace_enabled", 0),
            )
        )

    def _handle_stepper_perf_event(self, params: dict) -> None:
        """Handle fatal firmware step-dispatch performance snapshots."""
        message = self._format_stepper_perf_event(params)
        log.info(message)
        gcode = self.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def _handle_selftest_result(self, params: dict) -> None:
        """Collect one stage result streamed during FOCI_SELFTEST."""
        result = {
            "stage": params["stage"],
            "status": params["status"],
            "value": params["value"],
        }
        for idx, existing in enumerate(self._selftest_results):
            if existing["stage"] == result["stage"]:
                self._selftest_results[idx] = result
                return
        self._selftest_results.append(result)

    def _handle_selftest_done(self, params: dict) -> None:
        """Terminal signal for FOCI_SELFTEST."""
        self._selftest_complete = True
        self._selftest_status = params["status"]

    def _handle_commission_detail(self, params: dict) -> None:
        """Collect structured commissioning diagnostic detail."""
        self._commission_details.append(
            {
                "phase": params["phase"],
                "code": params["code"],
                "status": params["status"],
                "value0": params["value0"],
                "value1": params["value1"],
                "value2": params["value2"],
            }
        )

    def cmd_DUMP_FOCI(self, gcmd) -> None:
        """Handler for DUMP_FOCI and DUMP_TMC GCode commands.

        Sends a single foci_dump_registers command to the firmware and
        waits for all register values to be streamed back via the
        FOCI:DUMP: output protocol, then prints them formatted to the
        GCode console.
        """
        reactor = self.printer.get_reactor()
        self._dump_buffer.clear()
        self._dump_complete = False
        self.dump_cmd.send([self.oid])

        # Wait for dump to complete. The serial reader thread calls
        # _handle_dump_done which sets _dump_complete.
        deadline = reactor.monotonic() + 5.0
        while not self._dump_complete and reactor.monotonic() < deadline:
            reactor.pause(reactor.monotonic() + 0.05)

        if not self._dump_complete:
            gcmd.respond_info("FOCI register dump timed out")
            return

        lines: list[str] = []
        for group_name, regs in DUMP_GROUPS:
            if "%s" in group_name:
                header = group_name % self.stepper_name
            else:
                header = group_name
            lines.append("========== %s ==========" % header)
            for reg_name in regs:
                addr = REGISTERS[reg_name]
                if addr in self._dump_buffer:
                    val = self._dump_buffer[addr]
                    lines.append(self.fields.pretty_format(reg_name, val))
                else:
                    lines.append("  %-30s = (not in dump)" % reg_name)
        gcmd.respond_info("\n".join(lines))

    def cmd_FOCI_STEP_POSITION(self, gcmd) -> None:
        """Query raw MCU step position without updating Klipper state."""
        if self.stepper_get_position_cmd is None or self.oid is None:
            raise gcmd.error("FOCI_STEP_POSITION is not available before MCU identify")

        stepper = self._find_linked_stepper()
        if stepper is None:
            raise gcmd.error(
                "FOCI_STEP_POSITION could not find linked stepper %s"
                % self.stepper_name
            )

        params = self.stepper_get_position_cmd.send([self.oid])
        if params is None or "pos" not in params:
            raise gcmd.error("FOCI_STEP_POSITION query returned no position")

        raw_position = int(params["pos"])
        invert_dir = self._stepper_dir_inverted(stepper)
        host_position = -raw_position if invert_dir else raw_position

        get_mcu_position = getattr(stepper, "get_mcu_position", None)
        klipper_position = None
        delta = None
        if get_mcu_position is not None:
            klipper_position = int(get_mcu_position())
            delta = host_position - klipper_position

        parts = [
            "FOCI_STEP_POSITION %s:" % self.stepper_name,
            "raw=%d" % raw_position,
            "host=%d" % host_position,
            "klipper=%s" % (klipper_position if klipper_position is not None else "?"),
            "delta=%s" % (delta if delta is not None else "?"),
            "invert_dir=%d" % (1 if invert_dir else 0),
        ]

        get_step_dist = getattr(stepper, "get_step_dist", None)
        if get_step_dist is not None:
            step_dist = float(get_step_dist())
            parts.append("step_dist=%.6f" % step_dist)
            if delta is not None:
                parts.append("delta_mm=%.3f" % (delta * step_dist))

        gcmd.respond_info(" ".join(parts))

    def cmd_FOCI_STEPPER_STATS(self, gcmd) -> None:
        """Query MCU step queue and execution counters."""
        query_cmds = (
            ("stats", self.stepper_stats_cmd),
            ("exec_stats", self.stepper_exec_stats_cmd),
            ("timing_stats", self.stepper_timing_stats_cmd),
            ("stop_stats", self.stepper_stop_stats_cmd),
        )
        if self.oid is None or any(cmd is None for _, cmd in query_cmds):
            raise gcmd.error("FOCI_STEPPER_STATS is not available before MCU identify")

        params = {}
        for name, cmd in query_cmds:
            response = cmd.send([self.oid])
            if response is None:
                raise gcmd.error("FOCI_STEPPER_STATS %s query returned no data" % name)
            params.update(response)

        fields = [
            "channel",
            "position",
            "queued_segments",
            "queued_steps",
            "loaded_segments",
            "loaded_steps",
            "executed_pos_steps",
            "executed_neg_steps",
            "activation_count",
            "last_activation_clock",
            "first_load_now",
            "first_load_scheduled",
            "first_load_compare",
            "first_load_lead_ticks",
            "first_load_compare_delay_ticks",
            "first_step_clock",
            "first_step_delay_ticks",
            "discarded_segments",
            "discarded_steps",
            "queue_empty_count",
            "missed_deadline_count",
            "stop_count",
            "stop_drained_segments",
            "stop_drained_steps",
            "reset_count",
            "reset_drained_segments",
            "reset_drained_steps",
            "last_stop_reason",
            "last_stop_remaining_events",
            "last_stop_queue_len",
            "last_stop_drained_segments",
            "last_stop_drained_steps",
            "timer_active",
            "queue_len",
        ]
        parts = ["FOCI_STEPPER_STATS %s:" % self.stepper_name]
        for field in fields:
            parts.append("%s=%s" % (field, params.get(field, "?")))
        gcmd.respond_info(" ".join(parts))

    def cmd_FOCI_DISPATCH_STATS(self, gcmd) -> None:
        """Query MCU step-dispatch cycle counters."""
        if self.oid is None or self.stepper_perf_stats_cmd is None:
            raise gcmd.error("FOCI_DISPATCH_STATS is not available before MCU identify")

        clear = gcmd.get_int("RESET", 0, minval=0, maxval=1)
        response = self.stepper_perf_stats_cmd.send([self.oid, clear])
        if response is None:
            raise gcmd.error("FOCI_DISPATCH_STATS query returned no data")

        def cycles_to_us(field: str) -> int | str:
            value = response.get(field)
            if value is None:
                return "?"
            return int(value) // OPENFFBOARD_CPU_CYCLES_PER_US

        fields = [
            "channel",
            "sample_count",
            "crit_count",
            "crit_max_cycles",
            "crit_max_site",
            "crit_over_10us",
            "crit_over_50us",
            "crit_over_100us",
            "crit_over_1000us",
            "queue_step_count",
            "queue_step_max_cycles",
            "tim5_activation_count",
            "tim5_irq_max_cycles",
            "tim5_dispatch_max_cycles",
            "tim5_events_max_per_irq",
            "tim5_event_count_total",
            "tim5_defer_count",
            "tim5_empty_count",
            "tim5_events_last_activation",
            "tim5_burst_cycles_per_event_max",
            "tim5_entry_latency_max_ticks",
            "tim5_pop_lateness_max_ticks",
            "stepper_load_lateness_max_ticks",
            "stepper_load_lateness_last_ticks",
            "build_trace_enabled",
        ]
        parts = ["FOCI_DISPATCH_STATS %s:" % self.stepper_name]
        for field in fields:
            parts.append("%s=%s" % (field, response.get(field, "?")))
        parts.append("crit_max_us=%s" % cycles_to_us("crit_max_cycles"))
        parts.append("queue_step_max_us=%s" % cycles_to_us("queue_step_max_cycles"))
        parts.append("tim5_irq_max_us=%s" % cycles_to_us("tim5_irq_max_cycles"))
        parts.append(
            "tim5_dispatch_max_us=%s" % cycles_to_us("tim5_dispatch_max_cycles")
        )
        gcmd.respond_info(" ".join(parts))

    def _validate_and_load_config(self) -> None:
        """Validate persisted config and populate _active_gains/_runtime_status.

        Called from _handle_connect. Checks that all mandatory fields for the
        claimed autotune_status are present. If any are missing, logs a warning
        and leaves _active_gains and _runtime_status as None (motor cannot be
        enabled until FOCI_COMMISSION is run).
        """
        status = self.autotune_status
        if status is None:
            # No prior commissioning -- virgin hardware
            return

        valid_statuses = ("commissioned", "tuned", "tuned_conservative")
        if status not in valid_statuses:
            logging.warning(
                "FOCI %s: unknown autotune_status='%s' (expected one of: %s). "
                "Motor cannot be enabled until FOCI_COMMISSION is run.",
                self.name,
                status,
                ", ".join(valid_statuses),
            )
            return

        # Mandatory for all statuses: current-loop gains + inner-tuning params
        required_base = [
            ("pid_flux_p", self.pid_flux_p),
            ("pid_flux_i", self.pid_flux_i),
            ("pid_torque_p", self.pid_torque_p),
            ("pid_torque_i", self.pid_torque_i),
            ("identified_lambda_us", self.identified_lambda_us),
            ("identified_theta_e_us", self.identified_theta_e_us),
            ("identified_ringing_count", self.identified_ringing_count),
            ("identified_bandwidth_hz", self.identified_bandwidth_hz),
        ]
        missing = [name for name, val in required_base if val is None]

        # Status-specific outer gain requirements
        if status == "commissioned":
            commissioned_fields = [
                ("commissioned_velocity_p", self.commissioned_velocity_p),
                ("commissioned_velocity_i", self.commissioned_velocity_i),
                ("commissioned_position_p", self.commissioned_position_p),
                ("commissioned_position_i", self.commissioned_position_i),
                ("commissioned_velocity_limit", self.commissioned_velocity_limit),
            ]
            missing.extend(name for name, val in commissioned_fields if val is None)
        elif status in ("tuned", "tuned_conservative"):
            tuned_fields = [
                ("pid_velocity_p", self.pid_velocity_p),
                ("pid_velocity_i", self.pid_velocity_i),
                ("pid_velocity_limit", self.pid_velocity_limit),
                ("pid_position_p", self.pid_position_p),
                ("pid_position_i", self.pid_position_i),
            ]
            missing.extend(name for name, val in tuned_fields if val is None)

        if missing:
            logging.warning(
                "FOCI %s: autotune_status='%s' but missing required fields: %s. "
                "Motor cannot be enabled until FOCI_COMMISSION is run.",
                self.name,
                status,
                ", ".join(missing),
            )
            return

        # All required fields present -- build _active_gains
        if status == "commissioned":
            self._active_gains = {
                "flux_p": self.pid_flux_p,
                "flux_i": self.pid_flux_i,
                "torque_p": self.pid_torque_p,
                "torque_i": self.pid_torque_i,
                "velocity_p": self.commissioned_velocity_p,
                "velocity_i": self.commissioned_velocity_i,
                "position_p": self.commissioned_position_p,
                "position_i": self.commissioned_position_i,
                "velocity_limit": self.commissioned_velocity_limit,
                "velocity_filter_hz": self.velocity_filter_hz,
                "torque_filter_hz": self.torque_filter_hz,
                "position_filter_hz": self.position_filter_hz,
                "flux_filter_hz": self.flux_filter_hz,
            }
        else:  # tuned or tuned_conservative
            self._active_gains = {
                "flux_p": self.pid_flux_p,
                "flux_i": self.pid_flux_i,
                "torque_p": self.pid_torque_p,
                "torque_i": self.pid_torque_i,
                "velocity_p": self.pid_velocity_p,
                "velocity_i": self.pid_velocity_i,
                "position_p": self.pid_position_p,
                "position_i": self.pid_position_i,
                "velocity_limit": self.pid_velocity_limit,
                "velocity_filter_hz": self.velocity_filter_hz,
                "torque_filter_hz": self.torque_filter_hz,
                "position_filter_hz": self.position_filter_hz,
                "flux_filter_hz": self.flux_filter_hz,
            }
        self._runtime_status = status
        logging.info(
            "FOCI %s: loaded config, status=%s, active gains ready",
            self.name,
            status,
        )

    def _handle_connect(self) -> None:
        """Send configuration to firmware and check microstep alignment.

        Converts run_current to milliamps and sends it with the encoder
        PPR to the firmware. Warns if the configured microstep resolution
        does not match the encoder's natural resolution.
        """
        run_ma: int = int(self.run_current * 1000.0)
        self.set_current_cmd.send([self.oid, run_ma])
        self.set_encoder_cmd.send([self.oid, self.channel, self.encoder_ppr])
        self.set_encoder_dir_cmd.send(
            [self.oid, self.channel, int(self.encoder_reversed)]
        )
        # Send saved PID gains if present (all-or-none validated at config time).
        # Otherwise firmware uses conservative defaults.
        if self.pid_flux_p is not None:
            self.set_pid_gains_cmd.send(
                [
                    self.oid,
                    self.pid_flux_p,
                    self.pid_flux_i,
                    self.pid_torque_p,
                    self.pid_torque_i,
                ]
            )
        if self.velocity_filter_hz > 0:
            self.set_velocity_filter_cmd.send([self.oid, self.velocity_filter_hz])
        if self.torque_filter_hz > 0:
            self.set_torque_filter_cmd.send([self.oid, self.torque_filter_hz])
        if self.position_filter_hz > 0:
            self.set_position_filter_cmd.send([self.oid, self.position_filter_hz])
        if self.flux_filter_hz > 0:
            self.set_flux_filter_cmd.send([self.oid, self.flux_filter_hz])
        if self.pid_position_p is not None:
            self.set_position_gains_cmd.send(
                [
                    self.oid,
                    self.pid_position_p,
                    self.pid_position_i,
                    self.pid_velocity_p,
                    self.pid_velocity_i,
                ]
            )
        if self.velocity_feedforward:
            self.set_velocity_feedforward_cmd.send(
                [self.oid, 1, self.velocity_feedforward_multiplier]
            )
        if self.pid_velocity_limit is not None:
            self.set_velocity_limit_cmd.send([self.oid, self.pid_velocity_limit])
        encoder_steps: int = self.encoder_ppr * 4
        configured_steps: int = self.microsteps * self.full_steps
        if configured_steps != encoder_steps:
            optimal: int = encoder_steps // self.full_steps
            gcode = self.printer.lookup_object("gcode")
            gcode.respond_info(
                "[foci %s] Note: microsteps=%d gives %d steps/rev,"
                " encoder resolves %d. Consider microsteps=%d"
                % (
                    self.stepper_name,
                    self.microsteps,
                    configured_steps,
                    encoder_steps,
                    optimal,
                )
            )
        self._validate_and_load_config()
        if self._active_gains is not None and not self._inhibited:
            self._apply_active_gains_to_firmware()
        self._set_auto_calibrate_on_enable_allowed(
            self._active_gains is not None and not self._inhibited
        )
        if not self._enable_patched:
            self._enable_patched = True
            stepper_enable = self.printer.lookup_object("stepper_enable")
            enable_line = stepper_enable.lookup_enable(self.stepper_name)
            enable_line.register_state_callback(self._handle_stepper_enable)
            force_move = self.printer.lookup_object("force_move", None)
            if force_move is not None:
                orig_force_enable = force_move._force_enable
                foci_driver = self

                def _wrapped_force_enable(stepper, _orig=orig_force_enable):
                    name = stepper.get_name()
                    if name == foci_driver.stepper_name:
                        foci_driver._ensure_calibrated()
                    return _orig(stepper)

                force_move._force_enable = _wrapped_force_enable
            for name, ms in self.printer.lookup_objects("manual_stepper"):
                steppers = getattr(ms, "steppers", [])
                if steppers and steppers[0].get_name() == self.stepper_name:
                    orig_do_enable = ms.do_enable
                    foci_ms = self

                    def _wrapped_do_enable(enable, _orig=orig_do_enable, _foci=foci_ms):
                        if enable:
                            _foci._ensure_calibrated()
                        _orig(enable)

                    ms.do_enable = _wrapped_do_enable

    def _handle_calibrate_response(self, params) -> None:
        """Handle foci_calibrate_response message from firmware.

        Args:
            params: Message parameters dict from the MCU response.
        """
        if self._calibration_completion is not None:
            self._calibration_completion.complete(params)

    def _try_acquire_foci_lock(self) -> bool:
        """Non-blocking try-acquire of the FOCI operation lock.

        Returns True if lock acquired, False if another operation holds it.
        The lock prevents concurrent FOCI operations on this stepper.
        Klipper is single-threaded (reactor pattern), so a boolean flag
        is sufficient -- no mutex needed.
        """
        if self._foci_lock:
            return False
        self._foci_lock = True
        return True

    def _release_foci_lock(self) -> None:
        """Release the FOCI operation lock. Must be called on every exit path."""
        self._foci_lock = False

    def _set_auto_calibrate_on_enable_allowed(self, allowed: bool) -> None:
        """Tell firmware whether raw enable may start auto-calibration."""
        if self.set_auto_calibrate_on_enable_cmd is not None:
            self.set_auto_calibrate_on_enable_cmd.send([self.oid, int(allowed)])

    def _apply_active_gains_to_firmware(self) -> None:
        """Preload saved FOCI gains into firmware state before enabling."""
        gains = self._active_gains
        if gains is None:
            return
        self.set_pid_gains_cmd.send(
            [
                self.oid,
                gains["flux_p"],
                gains["flux_i"],
                gains["torque_p"],
                gains["torque_i"],
            ]
        )
        if gains.get("velocity_p") is not None:
            self.set_position_gains_cmd.send(
                [
                    self.oid,
                    gains["position_p"],
                    gains["position_i"],
                    gains["velocity_p"],
                    gains["velocity_i"],
                ]
            )
        if gains.get("velocity_limit"):
            self.set_velocity_limit_cmd.send([self.oid, gains["velocity_limit"]])
        for filter_name in ("velocity", "torque", "position", "flux"):
            hz = gains.get("%s_filter_hz" % filter_name, 0)
            if hz > 0:
                cmd = getattr(self, "set_%s_filter_cmd" % filter_name)
                cmd.send([self.oid, hz])

    # Kinematics coupling map: in coupled kinematics a single motor
    # affects multiple Cartesian axes. Maps rail index -> affected axes.
    # Cartesian (default): rail N -> axis N only.
    COUPLED_AXES = {
        "CoreXYKinematics": {0: (0, 1), 1: (0, 1), 2: (2,)},
        "CoreXZKinematics": {0: (0, 2), 1: (1,), 2: (0, 2)},
        "HybridCoreXYKinematics": {0: (0, 1), 1: (0, 1), 2: (2,)},
        "HybridCoreXZKinematics": {0: (0, 2), 1: (1,), 2: (0, 2)},
    }

    def _invalidate_homing(self) -> None:
        """Mark all kinematic axes affected by this stepper as unhomed.

        Called at command-accepted time for foci_commission, foci_tune,
        foci_selftest, and foci_calibrate. Uses kinematics.clear_homing_state()
        to actually clear homed status. Kinematics-aware: CoreXY marks both
        X and Y for either motor, CoreXZ marks X and Z, Cartesian marks only
        the directly driven axis.
        """
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is None:
            return
        kin = toolhead.get_kinematics()
        if not hasattr(kin, "clear_homing_state"):
            return
        rails = getattr(kin, "rails", None)
        if rails is None:
            return
        # Find which rails contain this stepper
        matched_rails = set()
        for i, rail in enumerate(rails):
            for stepper in rail.get_steppers():
                if stepper.get_name() == self.stepper_name:
                    matched_rails.add(i)
        if not matched_rails:
            return
        # Map matched rails to affected axes using coupling table
        coupling = self.COUPLED_AXES.get(type(kin).__name__)
        axes_to_clear = set()
        for rail_index in matched_rails:
            if coupling and rail_index in coupling:
                axes_to_clear.update(coupling[rail_index])
            elif rail_index < 3:
                # Cartesian default: rail index = axis index
                axes_to_clear.add(rail_index)
        if axes_to_clear:
            # Build argument compatible with both Klipper and Kalico:
            # Klipper checks `axis_name in clear_axes` (string membership),
            # Kalico checks `i in axes` (integer membership). A set with
            # both representations satisfies both `in` checks.
            clear_arg = set()
            for i in axes_to_clear:
                clear_arg.add(i)
                clear_arg.add("xyz"[i])
            kin.clear_homing_state(clear_arg)
            axis_names = "".join("xyz"[i] for i in sorted(axes_to_clear))
            logging.info(
                "FOCI %s: marked axes %s unhomed (encoder re-zeroed)",
                self.name,
                axis_names,
            )

    def _ensure_calibrated(self) -> None:
        """Run calibration if not already calibrated. Blocks until complete.

        The Calibrate sequence performs ADC calibration, encoder alignment,
        and closed-loop entry using gains from _active_gains. It skips
        diagnostic phases (coil check, wiring, encoder direction) that
        were validated by Stage 1 commissioning.

        Preconditions (hard gates):
        - _active_gains is not None (requires prior FOCI_COMMISSION)
        - _inhibited is False (no failed commission in this session)

        Side effects:
        - Marks kinematic axes unhomed (encoder re-zeroing)
        - Preloads gains from _active_gains into firmware atomics
        """
        if self._inhibited:
            raise self.printer.command_error(
                "FOCI %s: operation inhibited after failed FOCI_COMMISSION. "
                "Retry FOCI_COMMISSION or restart Klipper." % self.name
            )
        if self.is_calibrated:
            return
        if self._active_gains is None:
            raise self.printer.command_error(
                "FOCI %s: no commissioned gains available. "
                "Run FOCI_COMMISSION first." % self.name
            )
        if not self._try_acquire_foci_lock():
            raise self.printer.command_error(
                "FOCI %s: another FOCI operation is in progress" % self.name
            )
        try:
            # Preload gains from _active_gains into firmware atomics
            self._apply_active_gains_to_firmware()

            # Send calibrate and wait for response
            reactor = self.printer.get_reactor()
            self._calibration_completion = reactor.completion()
            t_start = reactor.monotonic()
            self._set_auto_calibrate_on_enable_allowed(True)
            self.calibrate_cmd.send([self.oid])
            params = self._calibration_completion.wait(t_start + 5.0)
            t_elapsed = reactor.monotonic() - t_start
            self._calibration_completion = None

            logging.info(
                "FOCI %s: calibrate response after %.3fs: %s",
                self.name,
                t_elapsed,
                params,
            )

            if params is None:
                raise self.printer.command_error(
                    "FOCI %s: calibration timed out (no response from firmware)"
                    % self.name
                )
            status = params.get("status", 255)
            if status == 5:
                # ALREADY_ENABLED: firmware auto-calibrated on enable before
                # this foci_calibrate arrived. Motor is calibrated and running.
                self.is_calibrated = True
                logging.info(
                    "FOCI %s: already calibrated (firmware auto-cal)", self.name
                )
                return
            if status != 0:
                # Raw CommissionError status codes (1-17) from firmware.
                status_names = {
                    1: "MOTOR_ENABLED",
                    2: "NO_CURRENT (current limit not configured)",
                    3: "SPI_ERROR (TMC4671 not responding)",
                    4: "ADC_FAULT (ADC offsets out of range: I0=%d I1=%d)"
                    % (params.get("adc_i0", 0), params.get("adc_i1", 0)),
                    5: "COIL_FAULT (coil not connected)",
                    6: "PHASE_FAULT (phase wiring error)",
                    7: "ENCODER_FAULT (encoder not connected or unstable)",
                    8: "ELECTRICAL_ID_FAILED",
                    9: "CURRENT_VALIDATION_FAILED",
                    13: "ENCODER_NOT_ALIGNED",
                    16: "QUEUE_FULL (firmware command queue full)",
                }
                msg = status_names.get(status, "UNKNOWN(%d)" % status)
                raise self.printer.command_error(
                    "FOCI %s calibration failed: %s" % (self.name, msg)
                )
            self.is_calibrated = True
            logging.info(
                "FOCI %s calibrated: ADC I0=%d I1=%d encoder=%d",
                self.name,
                params.get("adc_i0", 0),
                params.get("adc_i1", 0),
                params.get("encoder_count", 0),
            )
        finally:
            self._release_foci_lock()

    def _handle_home_rails_begin(self, homing_state, rails) -> None:
        """Ensure calibration before homing any axis driven by this stepper.

        Args:
            homing_state: Current homing state object.
            rails: List of PrinterRail objects being homed.
        """
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is not None:
            kin = toolhead.get_kinematics()
            all_rails = getattr(kin, "rails", None)
            if all_rails is not None:
                homed_axes = set()
                for homed_rail in rails:
                    for rail_index, rail in enumerate(all_rails):
                        if rail is homed_rail:
                            if rail_index < 3:
                                homed_axes.add(rail_index)
                            break

                matched_rails = set()
                for rail_index, rail in enumerate(all_rails):
                    for stepper in rail.get_steppers():
                        if stepper.get_name() == self.stepper_name:
                            matched_rails.add(rail_index)

                coupling = self.COUPLED_AXES.get(type(kin).__name__)
                driver_axes = set()
                for rail_index in matched_rails:
                    if coupling and rail_index in coupling:
                        driver_axes.update(coupling[rail_index])
                    elif rail_index < 3:
                        driver_axes.add(rail_index)

                if homed_axes and driver_axes and homed_axes & driver_axes:
                    self._ensure_calibrated()
                    return

        dominated_steppers = set()
        for rail in rails:
            for stepper in rail.get_steppers():
                dominated_steppers.add(stepper.get_name())
        if self.stepper_name in dominated_steppers:
            self._ensure_calibrated()

    def _handle_homing_move_end(self, homing_move) -> None:
        """Report FOCI stepper positions captured by Kalico homing."""
        gcode = self.printer.lookup_object("gcode", None)
        if gcode is None:
            return
        start_time = self._homing_move_start_times.pop(id(homing_move), None)
        for sp in getattr(homing_move, "stepper_positions", []):
            if getattr(sp, "stepper_name", None) != self.stepper_name:
                continue
            start_pos = int(sp.start_pos)
            trig_pos = int(sp.trig_pos)
            halt_pos = int(sp.halt_pos)
            move_steps = halt_pos - start_pos
            over_steps = halt_pos - trig_pos
            step_dist = float(sp.stepper.get_step_dist())
            gcode.respond_info(
                "FOCI_HOME_POSITION %s endstop=%s start=%d trig=%d halt=%d"
                " move_steps=%d over_steps=%d move_mm=%.3f over_mm=%.3f"
                % (
                    self.stepper_name,
                    sp.endstop_name,
                    start_pos,
                    trig_pos,
                    halt_pos,
                    move_steps,
                    over_steps,
                    move_steps * step_dist,
                    over_steps * step_dist,
                )
            )
            self._report_homing_step_history(gcode, homing_move, sp, start_time)
            return

    def _handle_homing_move_begin(self, homing_move) -> None:
        """Record the homing move print-time window for step history diagnostics."""
        toolhead = getattr(homing_move, "toolhead", None)
        if toolhead is None:
            return
        get_last_move_time = getattr(toolhead, "get_last_move_time", None)
        if get_last_move_time is None:
            return
        self._homing_move_start_times[id(homing_move)] = float(get_last_move_time())

    def _report_homing_step_history(self, gcode, homing_move, sp, start_time) -> None:
        """Report Kalico stepcompress history for one homing stepper."""
        if start_time is None:
            return
        toolhead = getattr(homing_move, "toolhead", None)
        if toolhead is None:
            return
        get_last_move_time = getattr(toolhead, "get_last_move_time", None)
        get_mcu = getattr(sp.stepper, "get_mcu", None)
        dump_steps = getattr(sp.stepper, "dump_steps", None)
        if get_last_move_time is None or get_mcu is None or dump_steps is None:
            return
        mcu = get_mcu()
        print_time_to_clock = getattr(mcu, "print_time_to_clock", None)
        if print_time_to_clock is None:
            return

        end_time = float(get_last_move_time())
        start_clock = int(print_time_to_clock(start_time))
        end_clock = int(print_time_to_clock(end_time))
        history = self._extract_step_history(sp.stepper, start_clock, end_clock)
        if not history:
            return

        move_history = [step for step in history if int(step.step_count) != 0]
        marker_history = [step for step in history if int(step.step_count) == 0]
        if not move_history:
            return

        signed_steps = sum(int(step.step_count) for step in move_history)
        abs_steps = sum(abs(int(step.step_count)) for step in move_history)
        pos_steps = sum(
            int(step.step_count) for step in move_history if int(step.step_count) > 0
        )
        neg_steps = sum(
            -int(step.step_count) for step in move_history if int(step.step_count) < 0
        )
        dir_changes = self._count_history_dir_changes(move_history)
        gap_steps = self._sum_history_position_gaps(move_history)
        first = move_history[0]
        last = move_history[-1]
        planned_start = int(first.start_position)
        planned_end = int(last.start_position) + int(last.step_count)
        step_dist = float(sp.stepper.get_step_dist())
        gcode.respond_info(
            "FOCI_HOME_STEP_HISTORY %s start_clock=%d end_clock=%d"
            " segments=%d move_segments=%d marker_segments=%d signed_steps=%d"
            " abs_steps=%d pos_steps=%d neg_steps=%d dir_changes=%d"
            " gap_steps=%d planned_start=%d planned_end=%d first_clock=%d"
            " last_clock=%d signed_mm=%.3f abs_mm=%.3f"
            % (
                self.stepper_name,
                start_clock,
                end_clock,
                len(history),
                len(move_history),
                len(marker_history),
                signed_steps,
                abs_steps,
                pos_steps,
                neg_steps,
                dir_changes,
                gap_steps,
                planned_start,
                planned_end,
                int(first.first_clock),
                int(last.last_clock),
                signed_steps * step_dist,
                abs_steps * step_dist,
            )
        )
        gcode.respond_info(
            "FOCI_HOME_STEP_SEGMENTS %s first=%s last=%s markers=%s"
            % (
                self.stepper_name,
                self._format_history_segment_edges(move_history[:4]),
                self._format_history_segment_edges(move_history[-4:]),
                self._format_history_markers(marker_history[:4]),
            )
        )

    def _extract_step_history(self, stepper, start_clock, end_clock):
        """Return chronological stepcompress history overlapping a clock window."""
        batch_size = 128
        batches = []
        window_end = end_clock
        for _ in range(8):
            data, count = stepper.dump_steps(batch_size, start_clock, window_end)
            if not count:
                break
            batches.append((data, count))
            if count < batch_size:
                break
            window_end = int(data[count - 1].first_clock)

        history = []
        for data, count in reversed(batches):
            for idx in range(count - 1, -1, -1):
                history.append(data[idx])
        return history

    def _count_history_dir_changes(self, history) -> int:
        """Count sign changes between consecutive non-zero history segments."""
        changes = 0
        last_sign = 0
        for step in history:
            count = int(step.step_count)
            sign = 1 if count > 0 else -1
            if last_sign and sign != last_sign:
                changes += 1
            last_sign = sign
        return changes

    def _sum_history_position_gaps(self, history) -> int:
        """Return total absolute discontinuity between history segments."""
        gap_steps = 0
        last_end = None
        for step in history:
            start = int(step.start_position)
            if last_end is not None:
                gap_steps += abs(start - last_end)
            last_end = start + int(step.step_count)
        return gap_steps

    def _format_history_segment_edges(self, history) -> str:
        """Format compact signed segment edges for homing diagnostics."""
        if not history:
            return "none"
        return ",".join(
            "%d:%d:%+d@%d/%+d"
            % (
                int(step.first_clock),
                int(step.start_position),
                int(step.step_count),
                int(step.interval),
                int(step.add),
            )
            for step in history
        )

    def _format_history_markers(self, history) -> str:
        """Format zero-count reset/query markers for homing diagnostics."""
        if not history:
            return "none"
        return ",".join(
            "%d:%d" % (int(step.first_clock), int(step.start_position))
            for step in history
        )

    def _handle_stepper_enable(self, print_time, is_enable) -> None:
        """Synchronize FOCI calibration state with Klipper stepper enable.

        On enable: calibrates synchronously so Klipper only marks the stepper
        enabled after firmware reports the motor is armed and holding.

        On disable: clears calibration state so the next enable recalibrates.

        Args:
            print_time: Timestamp of the enable/disable event.
            is_enable: True if enabling, False if disabling.
        """
        if is_enable:
            self._ensure_calibrated()
        else:
            self.is_calibrated = False

    def cmd_FOCI_SELFTEST(self, gcmd) -> None:
        """Run TMC4671 self-test and emit a per-stage report.

        Sends foci_selftest; firmware streams foci_selftest_result for
        each completed stage and a terminal foci_selftest_done. This
        handler collects the stream and formats the GCode console report.

        Selftest includes encoder alignment, so homing is invalidated at
        command-accepted time.
        """
        if not self._try_acquire_foci_lock():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.name
            )
        try:
            self._invalidate_homing()

            reactor = self.printer.get_reactor()
            self._selftest_results = []
            self._selftest_complete = False
            self._selftest_status = 0
            self._commission_details = []

            self.selftest_cmd.send([self.oid])

            # Wait for the terminal foci_selftest_done message (15 s timeout).
            deadline = reactor.monotonic() + 15.0
            while not self._selftest_complete:
                if reactor.monotonic() > deadline:
                    raise self.printer.command_error(
                        "FOCI %s: selftest timed out" % self.stepper_name
                    )
                reactor.pause(reactor.monotonic() + 0.05)
        finally:
            self._release_foci_lock()

        status_names = {0: "PASS", 1: "FAIL", 2: "SKIP"}
        lines = ["Self-Test: %s" % self.stepper_name]
        passed = 0
        total = len(self._selftest_results)
        for result in self._selftest_results:
            stage_id = result["stage"]
            stage_status = result["status"]
            stage_value = result["value"]
            name = self.SELFTEST_STAGES.get(stage_id, "Stage %d" % stage_id)
            status_str = status_names.get(stage_status, "?")
            detail = self._format_selftest_value(stage_id, stage_status, stage_value)
            dots = "." * max(1, 35 - len(name))
            lines.append("  %s %s %s%s" % (name, dots, status_str, detail))
            if stage_status == 0:
                passed += 1

        if self._commission_details:
            lines.append("Diagnostics:")
            for detail in self._commission_details:
                lines.append("  %s" % self._format_commission_detail(detail))

        if self._selftest_status == 0:
            overall = "PASS"
        else:
            err = self.COMMISSION_ERROR_NAMES.get(
                self._selftest_status, "unknown error %d" % self._selftest_status
            )
            overall = "FAIL (%s)" % err
        lines.append("Result: %s (%d/%d stages)" % (overall, passed, total))
        gcmd.respond_info("\n".join(lines))

        if self._selftest_status != 0:
            err = self.COMMISSION_ERROR_NAMES.get(
                self._selftest_status, "unknown error %d" % self._selftest_status
            )
            raise self.printer.command_error(
                "FOCI %s: selftest failed: %s" % (self.stepper_name, err)
            )

    def cmd_FOCI_COMMISSION(self, gcmd) -> None:
        """Stage 1: commission motor for safe printer motion.

        Runs full diagnostic chain, electrical ID, current tune, current
        validation, and closed-loop entry with conservative fallback gains.
        Does not require homing. Leaves motor enabled and holding.
        """
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        if profile_name not in self.PROFILE_MAP:
            raise gcmd.error(
                "Unknown profile '%s'. Options: %s"
                % (profile_name, ", ".join(self.PROFILE_MAP.keys()))
            )
        profile_code = self.PROFILE_MAP[profile_name]

        # Hard gates -- before any side effects
        if not self._try_acquire_foci_lock():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.name
            )
        try:
            # Setup sequence (lock held)
            toolhead = self.printer.lookup_object("toolhead")
            toolhead.wait_moves()

            # Disable motor if enabled
            stepper_enable = self.printer.lookup_object("stepper_enable")
            enable_line = stepper_enable.lookup_enable(self.stepper_name)
            if enable_line.is_motor_enabled():
                enable_line.motor_disable(toolhead.get_last_move_time())

            self.is_calibrated = False
            self._invalidate_homing()

            # Send commission command and wait
            self._commission_done = False
            self._commission_result = None
            self._commission_error_code = 0
            self._last_phase_id = None
            self._commission_details = []

            self.commission_cmd.send([self.oid, profile_code])

            # Wait for result (up to 30 seconds -- full commissioning takes time)
            reactor = self.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + 30.0
            while not self._commission_done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    self._on_commission_failure()
                    raise gcmd.error("FOCI %s: FOCI_COMMISSION timed out" % self.name)
                if self._commission_error_code != 0:
                    self._on_commission_failure()
                    error_name = self.COMMISSION_ERROR_NAMES.get(
                        self._commission_error_code,
                        "UNKNOWN(%d)" % self._commission_error_code,
                    )
                    phase_name = self.PHASE_NAMES.get(
                        self._last_phase_id or 0, "unknown"
                    )
                    if self._commission_details:
                        detail_lines = [
                            "FOCI %s commissioning diagnostics:" % self.stepper_name
                        ]
                        detail_lines.extend(
                            "  %s" % self._format_commission_detail(detail)
                            for detail in self._commission_details
                        )
                        gcmd.respond_info("\n".join(detail_lines))
                    raise gcmd.error(
                        "FOCI %s: FOCI_COMMISSION failed at %s: %s"
                        % (self.name, phase_name, error_name)
                    )

            # Success -- update state
            result = self._commission_result
            status = result.get("status", 255)
            if status > 1:
                self._on_commission_failure()
                raise gcmd.error(
                    "FOCI %s: FOCI_COMMISSION failed (unexpected status %d)"
                    % (self.name, status)
                )

            # Terminal state: motor enabled, holding. Mark the host state before
            # syncing Klipper's enable tracker so the enable callback sees the
            # already-armed motor instead of starting a second calibration.
            self.is_calibrated = True
            self._inhibited = False
            self._set_auto_calibrate_on_enable_allowed(True)
            self._commissioned_result = result
            self._active_gains = {
                "flux_p": result["flux_p"],
                "flux_i": result["flux_i"],
                "torque_p": result["torque_p"],
                "torque_i": result["torque_i"],
                "velocity_p": result["fallback_velocity_p"],
                "velocity_i": result["fallback_velocity_i"],
                "position_p": result["fallback_position_p"],
                "position_i": result["fallback_position_i"],
                "velocity_limit": result["fallback_velocity_limit"],
                "velocity_filter_hz": 0,
                "torque_filter_hz": 0,
                "position_filter_hz": 0,
                "flux_filter_hz": 0,
            }
            self._runtime_status = "commissioned"
            enable_line.motor_enable(toolhead.get_last_move_time())

            # Persist to config
            self._persist_commission_results(result, profile_name)

            status_str = "accepted" if status == 0 else "accepted with warnings"
            gcmd.respond_info(
                "FOCI %s commissioned (%s): "
                "r_count_milli=%d l_count_micro=%d R_int=%d L_int=%d"
                % (
                    self.name,
                    status_str,
                    result["r_mohm"],
                    result["l_uh"],
                    result.get("r_int", 0),
                    result.get("l_int", 0),
                )
            )
            flags = result.get("inner_warning_flags", 0)
            if flags:
                gcmd.respond_info(
                    "FOCI %s inner confidence: %s"
                    % (self.name, self._format_inner_warning_flags(flags))
                )
        finally:
            self._release_foci_lock()

    def _on_commission_failure(self) -> None:
        """Handle Stage 1 failure state transitions."""
        self.is_calibrated = False
        self._commissioned_result = None
        self._active_gains = None
        self._runtime_status = None
        self._inhibited = True
        self._set_auto_calibrate_on_enable_allowed(False)

    def _persist_commission_results(self, result: dict, profile_name: str) -> None:
        """Persist Stage 1 results to printer.cfg (pending SAVE_CONFIG)."""
        configfile = self.printer.lookup_object("configfile")
        configfile.set(self.name, "pid_flux_p", "%d" % result["flux_p"])
        configfile.set(self.name, "pid_flux_i", "%d" % result["flux_i"])
        configfile.set(self.name, "pid_torque_p", "%d" % result["torque_p"])
        configfile.set(self.name, "pid_torque_i", "%d" % result["torque_i"])
        configfile.set(
            self.name,
            "commissioned_velocity_p",
            "%d" % result["fallback_velocity_p"],
        )
        configfile.set(
            self.name,
            "commissioned_velocity_i",
            "%d" % result["fallback_velocity_i"],
        )
        configfile.set(
            self.name,
            "commissioned_position_p",
            "%d" % result["fallback_position_p"],
        )
        configfile.set(
            self.name,
            "commissioned_position_i",
            "%d" % result["fallback_position_i"],
        )
        configfile.set(
            self.name,
            "commissioned_velocity_limit",
            "%d" % result["fallback_velocity_limit"],
        )
        configfile.set(
            self.name,
            "identified_r_count_milli",
            "%d" % result["r_mohm"],
        )
        configfile.set(
            self.name,
            "identified_l_count_micro",
            "%d" % result["l_uh"],
        )
        configfile.set(
            self.name,
            "identified_r_int",
            "%d" % result.get("r_int", 0),
        )
        configfile.set(
            self.name,
            "identified_l_int",
            "%d" % result.get("l_int", 0),
        )
        configfile.set(self.name, "identified_lambda_us", "%d" % result["lambda_us"])
        configfile.set(
            self.name,
            "identified_theta_e_us",
            "%d" % result["theta_e_us"],
        )
        configfile.set(
            self.name,
            "identified_ringing_count",
            "%d" % result["ringing_count"],
        )
        configfile.set(
            self.name,
            "identified_bandwidth_hz",
            "%d" % result["bandwidth_hz"],
        )
        configfile.set(
            self.name,
            "identified_tau_e_us",
            "%d" % result.get("tau_e_us", 0),
        )
        configfile.set(
            self.name,
            "identified_tau_e_crosscheck_us",
            "%d" % result.get("tau_e_crosscheck_us", 0),
        )
        configfile.set(
            self.name,
            "identified_tau_residual_permille",
            "%d" % result.get("tau_residual_permille", 1000),
        )
        configfile.set(
            self.name,
            "identified_inner_warning_flags",
            "%d" % result.get("inner_warning_flags", 0),
        )
        configfile.set(self.name, "autotune_profile", profile_name)
        configfile.set(self.name, "autotune_status", "commissioned")

    def _resolve_inner_confidence(self) -> tuple[int, int, int, int]:
        """Resolve the four Phase 1 inner-confidence fields for Stage 2.

        Returns ``(tau_e_us, tau_e_crosscheck_us, tau_residual_permille,
        inner_warning_flags)``. Fresh Stage 1 results from
        ``_commissioned_result`` win over persisted values; persisted
        values fall back to documented defaults when absent (used only
        for old configs that pre-date this field set).
        """
        if self._commissioned_result is not None:
            r = self._commissioned_result
            return (
                r.get("tau_e_us", 0),
                r.get("tau_e_crosscheck_us", 0),
                r.get("tau_residual_permille", 1000),
                r.get("inner_warning_flags", 0),
            )

        tau_e_us = self.identified_tau_e_us
        if tau_e_us is None:
            # Spec wording: "when `identified_lambda_us` is available,
            # otherwise 1000". Treat only `None` as missing — a genuine
            # zero (implausible but legal) maps to the 1000us floor.
            if self.identified_lambda_us is None:
                tau_e_us = 1000
            else:
                tau_e_us = max(self.identified_lambda_us, 1000)

        tau_e_crosscheck_us = self.identified_tau_e_crosscheck_us
        if tau_e_crosscheck_us is None:
            tau_e_crosscheck_us = 0

        tau_residual_permille = self.identified_tau_residual_permille
        if tau_residual_permille is None:
            tau_residual_permille = 1000

        inner_warning_flags = self.identified_inner_warning_flags
        if inner_warning_flags is None:
            # Bit 6: host-defaulted confidence data (no fresh measurement).
            inner_warning_flags = 0x40

        return (
            tau_e_us,
            tau_e_crosscheck_us,
            tau_residual_permille,
            inner_warning_flags,
        )

    def _format_inner_warning_flags(self, flags: int) -> str:
        """Decode an `inner_warning_flags` bitfield into a human-readable
        comma-separated list of warning names."""
        names = [name for bit, name in self.INNER_WARNING_FLAG_NAMES if flags & bit]
        return ", ".join(names) if names else "none"

    def cmd_FOCI_AUTOTUNE(self, gcmd) -> None:
        """Stage 2: installed tuning after commissioning and homing.

        Runs mechanical ID, velocity/position tuning, filter selection,
        and commit. Requires motor calibrated, enabled, in closed-loop
        position mode, and printer fully homed.
        """
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        mode_name = gcmd.get("MODE", "nominal").lower()
        if profile_name not in self.PROFILE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown profile '%s' (expected: %s)"
                % (self.name, profile_name, ", ".join(sorted(self.PROFILE_MAP)))
            )
        if mode_name not in self.MODE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown mode '%s' (expected: %s)"
                % (self.name, mode_name, ", ".join(sorted(self.MODE_MAP)))
            )

        # Hard gates -- before any side effects
        if not self._try_acquire_foci_lock():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.name
            )

        try:
            if self._inhibited:
                raise gcmd.error(
                    "FOCI %s: inhibited after failed FOCI_COMMISSION" % self.name
                )
            if self._runtime_status is None:
                raise gcmd.error(
                    "FOCI %s: not commissioned. Run FOCI_COMMISSION first." % self.name
                )
            if not self.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: not calibrated. Enable motor, re-home, then retry."
                    % self.name
                )

            # Check homing — skip for NoneKinematics (manual_stepper has
            # no kinematic axes and never reports homed_axes).
            toolhead = self.printer.lookup_object("toolhead")
            kinematics = toolhead.get_kinematics()
            if hasattr(kinematics, "rails"):
                kin_status = toolhead.get_status(toolhead.get_last_move_time())
                homed = set(kin_status.get("homed_axes", ""))
                expected = set("xyz")  # full homing required
                if not expected.issubset(homed):
                    missing = expected - homed
                    raise gcmd.error(
                        "FOCI %s: printer not fully homed (missing: %s). "
                        "Home first." % (self.name, "".join(sorted(missing)))
                    )

            # Setup sequence (lock held)
            toolhead.wait_moves()

            # Post-wait revalidation
            if not self.is_calibrated:
                raise gcmd.error("FOCI %s: calibration lost during wait" % self.name)
            if hasattr(kinematics, "rails"):
                kin_status = toolhead.get_status(toolhead.get_last_move_time())
                if not expected.issubset(set(kin_status.get("homed_axes", ""))):
                    raise gcmd.error("FOCI %s: homing lost during wait" % self.name)

            self._invalidate_homing()

            # Get inner-tuning params from cache or config
            if self._commissioned_result is not None:
                inner_lambda = self._commissioned_result["lambda_us"]
                theta_e = self._commissioned_result["theta_e_us"]
                ringing = self._commissioned_result["ringing_count"]
                bandwidth = self._commissioned_result["bandwidth_hz"]
            else:
                inner_lambda = self.identified_lambda_us
                theta_e = self.identified_theta_e_us
                ringing = self.identified_ringing_count
                bandwidth = self.identified_bandwidth_hz

            (
                tau_e_us,
                tau_e_crosscheck_us,
                tau_residual_permille,
                inner_warning_flags,
            ) = self._resolve_inner_confidence()

            # Send tune command
            self._commission_done = False
            self._commission_result = None
            self._commission_error_code = 0

            self.tune_cmd.send(
                [
                    self.oid,
                    self.PROFILE_MAP[profile_name],
                    self.MODE_MAP[mode_name],
                    inner_lambda,
                    theta_e,
                    ringing,
                    bandwidth,
                    tau_e_us,
                    tau_e_crosscheck_us,
                    tau_residual_permille,
                    inner_warning_flags,
                ]
            )

            # Wait for result (up to 30 seconds).
            # foci_tune_result is emitted for all outcomes: success, soft failure,
            # and safety fault (OuterFailed always sends foci_tune_result).
            reactor = self.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + 30.0
            while not self._commission_done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    raise gcmd.error("FOCI %s: FOCI_AUTOTUNE timed out" % self.name)
                if self._commission_error_code != 0:
                    error_name = self.COMMISSION_ERROR_NAMES.get(
                        self._commission_error_code,
                        "UNKNOWN(%d)" % self._commission_error_code,
                    )
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE failed: %s" % (self.name, error_name)
                    )

            result = self._commission_result
            status = result.get("status", 255)
            if status > 1:
                error_name = self.COMMISSION_ERROR_NAMES.get(
                    status, "UNKNOWN(%d)" % status
                )
                if status in self.HARD_FAULT_CODES:
                    # Hard fault: firmware disabled motor, cleared state.
                    # Sync host-side state and block raw-enable auto-calibration
                    # until a fresh Stage 1 commission succeeds.
                    self._on_commission_failure()
                    stepper_enable = self.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE safety fault: %s "
                        "(motor disabled by firmware)" % (self.name, error_name)
                    )
                # Soft failure -- firmware restored entry gains
                gcmd.respond_info(
                    "FOCI %s: FOCI_AUTOTUNE failed: %s "
                    "(motor holding with entry gains)" % (self.name, error_name)
                )
                return  # _runtime_status unchanged, gains preserved

            # Determine tuned vs tuned_conservative
            warning_code = result.get("warning_code", 0)
            if status == 1 or warning_code != 0:
                tune_status = "tuned_conservative"
            else:
                tune_status = "tuned"

            # Update _active_gains with tuned outer gains + existing current-loop
            self._active_gains = {
                "flux_p": self._active_gains["flux_p"],
                "flux_i": self._active_gains["flux_i"],
                "torque_p": self._active_gains["torque_p"],
                "torque_i": self._active_gains["torque_i"],
                "velocity_p": result["velocity_p"],
                "velocity_i": result["velocity_i"],
                "position_p": result["position_p"],
                "position_i": result["position_i"],
                "velocity_limit": result["velocity_limit"],
                "velocity_filter_hz": result["velocity_filter_hz"],
                "torque_filter_hz": result["torque_filter_hz"],
                "position_filter_hz": result["position_filter_hz"],
                "flux_filter_hz": result["flux_filter_hz"],
            }
            self._runtime_status = tune_status

            # Persist tuned gains
            self._persist_tune_results(result, mode_name, tune_status)

            gcmd.respond_info(
                "FOCI %s tuned (%s): vel_p=%d pos_p=%d"
                % (
                    self.name,
                    tune_status,
                    result["velocity_p"],
                    result["position_p"],
                )
            )
            # Reuse the inner_warning_flags resolved earlier in this command —
            # they were sent to the firmware along with the tune request and
            # have not changed since.
            if inner_warning_flags:
                gcmd.respond_info(
                    "FOCI %s inner confidence: %s"
                    % (
                        self.name,
                        self._format_inner_warning_flags(inner_warning_flags),
                    )
                )
        finally:
            self._release_foci_lock()

    def cmd_FOCI_SET_GAINS(self, gcmd) -> None:
        """Set outer-loop gains for live bringup debugging.

        Parameters are floating-point gain values. For example, `VELOCITY_P=2.0`
        writes raw Q8.8 value 512 and `POSITION_P=1.0` writes raw value 256.
        Values are applied immediately and kept in memory for the current Klipper
        session, but are not persisted to printer.cfg.
        """
        velocity_p = self._get_outer_gain(gcmd, "VELOCITY_P")
        velocity_i = self._get_outer_gain(gcmd, "VELOCITY_I")
        position_p = self._get_outer_gain(gcmd, "POSITION_P")
        position_i = self._get_outer_gain(gcmd, "POSITION_I")

        self.set_position_gains_cmd.send(
            [self.oid, position_p, position_i, velocity_p, velocity_i]
        )

        self.pid_velocity_p = velocity_p
        self.pid_velocity_i = velocity_i
        self.pid_position_p = position_p
        self.pid_position_i = position_i
        if self._active_gains is not None:
            self._active_gains["velocity_p"] = velocity_p
            self._active_gains["velocity_i"] = velocity_i
            self._active_gains["position_p"] = position_p
            self._active_gains["position_i"] = position_i

        gcmd.respond_info(
            "FOCI %s debug gains set: vel_p=%d/256 vel_i=%d/256"
            " pos_p=%d/256 pos_i=%d/256"
            % (self.name, velocity_p, velocity_i, position_p, position_i)
        )

    def cmd_FOCI_SET_INNER_GAINS(self, gcmd) -> None:
        """Set inner current-loop gains for live bringup debugging.

        Parameters are raw TMC4671 register values. P gains are Q8.8
        numerators. Current I gains are also Q8.8 while
        CONFIG_ADVANCED_PI_REPRESENT remains at its default 0; in advanced PI
        mode their effective zero factor is raw/65536 per PWM sample. Values
        are applied immediately and kept in memory for the current Klipper
        session, but are not persisted to printer.cfg.
        """
        flux_p = gcmd.get_int("FLUX_P", minval=0, maxval=65535)
        flux_i = gcmd.get_int("FLUX_I", minval=0, maxval=65535)
        torque_p = gcmd.get_int("TORQUE_P", minval=0, maxval=65535)
        torque_i = gcmd.get_int("TORQUE_I", minval=0, maxval=65535)

        self.set_pid_gains_cmd.send([self.oid, flux_p, flux_i, torque_p, torque_i])

        if self._active_gains is not None:
            self._active_gains["flux_p"] = flux_p
            self._active_gains["flux_i"] = flux_i
            self._active_gains["torque_p"] = torque_p
            self._active_gains["torque_i"] = torque_i

        gcmd.respond_info(
            "FOCI %s inner gains set: flux_p=%d/256"
            " flux_i=%d(q8.8=%.3f zero=%d/65536)"
            " torque_p=%d/256 torque_i=%d(q8.8=%.3f zero=%d/65536)"
            % (
                self.name,
                flux_p,
                flux_i,
                flux_i * 2**-8,
                flux_i,
                torque_p,
                torque_i,
                torque_i * 2**-8,
                torque_i,
            )
        )

    def cmd_FOCI_SET_CURRENT(self, gcmd) -> None:
        """Set run current for live bringup debugging.

        RUN_CURRENT is in amps RMS, matching the printer.cfg convention. The
        value is applied immediately and kept in memory for the current Klipper
        session, but is not persisted to printer.cfg.
        """
        run_current = gcmd.get_float("RUN_CURRENT", minval=0.0, maxval=5.0)
        if run_current <= 0.0:
            raise gcmd.error("FOCI %s: RUN_CURRENT must be above 0" % self.name)

        run_ma = int(run_current * 1000.0 + 0.5)
        self.set_current_cmd.send([self.oid, run_ma])
        self.run_current = run_current

        gcmd.respond_info(
            "FOCI %s run current set: run_current=%.3fA run_ma=%d"
            % (self.name, run_current, run_ma)
        )

    def cmd_FOCI_SET_VELOCITY_FEEDFORWARD(self, gcmd) -> None:
        """Set velocity feedforward multiplier for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        multiplier = gcmd.get_int(
            "MULTIPLIER",
            self.velocity_feedforward_multiplier,
            minval=0,
            maxval=65535,
        )

        self.set_velocity_feedforward_cmd.send([self.oid, enable, multiplier])
        self.velocity_feedforward = enable != 0
        self.velocity_feedforward_multiplier = multiplier

        gcmd.respond_info(
            "FOCI %s velocity feedforward set: enable=%d multiplier=%d"
            % (self.name, enable, multiplier)
        )

    def cmd_FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD(self, gcmd) -> None:
        """Set live-only command-acceleration velocity feedforward."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        lead_time_us = gcmd.get_int(
            "LEAD_TIME_US",
            self.velocity_transient_lead_time_us,
            minval=0,
            maxval=65535,
        )
        gain = gcmd.get_int(
            "GAIN",
            self.velocity_transient_gain,
            minval=0,
            maxval=65535,
        )
        max_offset = gcmd.get_int(
            "MAX_OFFSET",
            self.velocity_transient_max_offset,
            minval=0,
            maxval=32767,
        )
        rate_hz = gcmd.get_int(
            "RATE_HZ",
            self.velocity_transient_rate_hz,
            minval=1000,
            maxval=10000,
        )

        self.set_velocity_transient_feedforward_cmd.send(
            [self.oid, enable, lead_time_us, gain, max_offset, rate_hz]
        )
        self.velocity_transient_feedforward = enable != 0
        self.velocity_transient_lead_time_us = lead_time_us
        self.velocity_transient_gain = gain
        self.velocity_transient_max_offset = max_offset
        self.velocity_transient_rate_hz = rate_hz

        gcmd.respond_info(
            "FOCI %s velocity transient feedforward set: enable=%d"
            " lead_time_us=%d gain=%d max_offset=%d rate_hz=%d"
            % (self.name, enable, lead_time_us, gain, max_offset, rate_hz)
        )

    def cmd_FOCI_SET_ACCEL_FEEDFORWARD(self, gcmd) -> None:
        """Set acceleration feedforward gains for live bringup debugging.

        ACCEL_GAIN and DECEL_GAIN are in permille. GAIN is a convenience alias
        that sets both when neither split gain is supplied.
        """
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        split_gain_supplied = (
            gcmd.get("ACCEL_GAIN", None) is not None
            or gcmd.get("DECEL_GAIN", None) is not None
        )
        alias_gain = (
            gcmd.get_int("GAIN", minval=0, maxval=65535)
            if gcmd.get("GAIN", None) is not None
            else None
        )
        if alias_gain is not None and not split_gain_supplied:
            default_accel_gain = alias_gain
            default_decel_gain = alias_gain
        else:
            default_accel_gain = self.accel_feedforward_accel_gain
            default_decel_gain = self.accel_feedforward_decel_gain
        accel_gain = gcmd.get_int(
            "ACCEL_GAIN",
            default_accel_gain,
            minval=0,
            maxval=65535,
        )
        decel_gain = gcmd.get_int(
            "DECEL_GAIN",
            default_decel_gain,
            minval=0,
            maxval=65535,
        )

        self.set_accel_feedforward_cmd.send([self.oid, enable, accel_gain, decel_gain])
        self.accel_feedforward = enable != 0
        self.accel_feedforward_accel_gain = accel_gain
        self.accel_feedforward_decel_gain = decel_gain

        gcmd.respond_info(
            "FOCI %s acceleration feedforward set: enable=%d"
            " accel_gain=%d decel_gain=%d" % (self.name, enable, accel_gain, decel_gain)
        )

    def cmd_FOCI_SET_DECOUPLING_FEEDFORWARD(self, gcmd) -> None:
        """Set bounded q/d decoupling proxy feedforward for live debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        r_int = gcmd.get_int(
            "R_INT",
            self.decoupling_r_int,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        l_int = gcmd.get_int(
            "L_INT",
            self.decoupling_l_int,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        pole_pairs = gcmd.get_int(
            "POLE_PAIRS",
            self.decoupling_pole_pairs,
            minval=1,
            maxval=65535,
        )
        position_units_per_rev = gcmd.get_int(
            "POSITION_UNITS_PER_REV",
            self.decoupling_position_units_per_rev,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        f_pwm_hz = gcmd.get_int(
            "F_PWM_HZ",
            self.decoupling_f_pwm_hz,
            minval=1,
            maxval=0xFFFFFFFF,
        )
        max_offset = gcmd.get_int(
            "MAX_OFFSET",
            self.decoupling_max_offset,
            minval=0,
            maxval=32767,
        )

        self.set_decoupling_feedforward_cmd.send(
            [
                self.oid,
                enable,
                r_int,
                l_int,
                pole_pairs,
                position_units_per_rev,
                f_pwm_hz,
                max_offset,
            ]
        )
        self.decoupling_feedforward = enable != 0
        self.decoupling_r_int = r_int
        self.decoupling_l_int = l_int
        self.decoupling_pole_pairs = pole_pairs
        self.decoupling_position_units_per_rev = position_units_per_rev
        self.decoupling_f_pwm_hz = f_pwm_hz
        self.decoupling_max_offset = max_offset

        gcmd.respond_info(
            "FOCI %s decoupling feedforward set: enable=%d"
            " r_int=%d l_int=%d pole_pairs=%d position_units_per_rev=%d"
            " f_pwm_hz=%d max_offset=%d"
            % (
                self.name,
                enable,
                r_int,
                l_int,
                pole_pairs,
                position_units_per_rev,
                f_pwm_hz,
                max_offset,
            )
        )

    def cmd_FOCI_SET_POSITION_LEAD(self, gcmd) -> None:
        """Set bounded position-target lead for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        gain = gcmd.get_int(
            "GAIN",
            self.position_lead_gain,
            minval=0,
            maxval=65535,
        )
        max_counts = gcmd.get_int(
            "MAX_COUNTS",
            self.position_lead_max_counts,
            minval=0,
            maxval=200,
        )

        self.set_position_lead_cmd.send([self.oid, enable, gain, max_counts])
        self.position_lead = enable != 0
        self.position_lead_gain = gain
        self.position_lead_max_counts = max_counts

        gcmd.respond_info(
            "FOCI %s position lead set: enable=%d gain=%d max_counts=%d"
            % (self.name, enable, gain, max_counts)
        )

    def cmd_FOCI_SET_PHASE_ADVANCE(self, gcmd) -> None:
        """Set bounded commutation phase advance for live bringup debugging."""
        enable = gcmd.get_int("ENABLE", 1, minval=0, maxval=1)
        gain_ppm = gcmd.get_int(
            "GAIN_PPM",
            self.phase_advance_gain_ppm,
            minval=-2_000_000,
            maxval=2_000_000,
        )
        max_counts = gcmd.get_int(
            "MAX_COUNTS",
            self.phase_advance_max_counts,
            minval=0,
            maxval=512,
        )
        deadband = gcmd.get_int(
            "DEADBAND",
            self.phase_advance_deadband,
            minval=0,
            maxval=65535,
        )

        self.set_phase_advance_cmd.send(
            [self.oid, enable, gain_ppm, max_counts, deadband]
        )
        self.phase_advance = enable != 0
        self.phase_advance_gain_ppm = gain_ppm
        self.phase_advance_max_counts = max_counts
        self.phase_advance_deadband = deadband

        gcmd.respond_info(
            "FOCI %s phase advance set: enable=%d gain_ppm=%d"
            " max_counts=%d deadband=%d"
            % (self.name, enable, gain_ppm, max_counts, deadband)
        )

    def cmd_FOCI_SET_VOLTAGE_LIMIT(self, gcmd) -> None:
        """Set PIDOUT_UQ_UD_LIMITS for live authority diagnostics.

        VOLTAGE_LIMIT is a raw TMC4671 PIDOUT count. This command is live-only:
        it changes the current Klipper session and does not persist config.
        """
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
        )

        self.set_voltage_limit_cmd.send([self.oid, voltage_limit])

        gcmd.respond_info(
            "FOCI %s voltage limit set: pidout_uq_ud_limit=%d"
            % (self.name, voltage_limit)
        )

    def cmd_FOCI_CURRENT_STEP_TEST(self, gcmd) -> None:
        """Run a bounded current-loop step diagnostic.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, and outside a homing move.
        """
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.current_step_test_cmd.send([self.oid, target, duration_ms, voltage_limit])

        gcmd.respond_info(
            "FOCI %s current-step requested: target=%d"
            " duration_ms=%d voltage_limit=%d"
            % (self.name, target, duration_ms, voltage_limit)
        )

    def cmd_FOCI_CURRENT_VECTOR_STEP_TEST(self, gcmd) -> None:
        """Run a bounded current-vector step diagnostic.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, and outside a homing move.
        """
        torque_target = gcmd.get_int("TORQUE_TARGET", 0, minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.current_vector_step_test_cmd.send(
            [self.oid, torque_target, flux_target, duration_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s current-vector-step requested:"
            " torque_target=%d flux_target=%d duration_ms=%d voltage_limit=%d"
            % (self.name, torque_target, flux_target, duration_ms, voltage_limit)
        )

    def cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST(self, gcmd) -> None:
        """Run a bounded torque pulse and sample it before the 20 ms dwell floor.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, and outside a homing move.
        """
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 5, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self._current_torque_sample_details.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )
        self._current_torque_sample_labels.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )

        self.current_torque_sample_test_cmd.send(
            [self.oid, target, flux_target, sample_delay_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s current-torque-sample requested:"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.name, target, flux_target, sample_delay_ms, voltage_limit)
        )

    def cmd_FOCI_POSITION_TORQUE_OFFSET_TEST(self, gcmd) -> None:
        """Run a bounded torque-offset sample while staying in position mode.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, outside a homing move, and in production position mode.
        """
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        detail_key = (target, 0, sample_delay_ms, voltage_limit)
        self._current_torque_sample_details.pop(detail_key, None)
        self._current_torque_sample_labels[detail_key] = "position torque offset sample"

        self.position_torque_offset_sample_test_cmd.send(
            [self.oid, target, sample_delay_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s position-torque-offset requested:"
            " target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.name, target, sample_delay_ms, voltage_limit)
        )

    def cmd_FOCI_VOLTAGE_STEP_TEST(self, gcmd) -> None:
        """Run a bounded open-loop voltage-vector pulse and sample it.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, outside a homing move, and in production position mode.
        """
        uq_ext = gcmd.get_int("UQ", minval=-1024, maxval=1024)
        ud_ext = gcmd.get_int("UD", 0, minval=-1024, maxval=1024)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)

        self.voltage_step_test_cmd.send([self.oid, uq_ext, ud_ext, sample_delay_ms])

        gcmd.respond_info(
            "FOCI %s voltage-step requested:"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d"
            % (self.name, uq_ext, ud_ext, sample_delay_ms)
        )

    def _get_outer_gain(self, gcmd, key: str) -> int:
        """Read a floating-point gain parameter and convert it to raw Q8.8."""
        value = gcmd.get_float(key, minval=0.0, maxval=32767.0 / 256.0)
        return min(32767, int(value * 256.0 + 0.5))

    def _persist_tune_results(self, result: dict, mode_name: str, status: str) -> None:
        """Persist Stage 2 results to printer.cfg (pending SAVE_CONFIG)."""
        configfile = self.printer.lookup_object("configfile")
        configfile.set(self.name, "pid_velocity_p", "%d" % result["velocity_p"])
        configfile.set(self.name, "pid_velocity_i", "%d" % result["velocity_i"])
        configfile.set(self.name, "pid_velocity_limit", "%d" % result["velocity_limit"])
        configfile.set(self.name, "pid_position_p", "%d" % result["position_p"])
        configfile.set(self.name, "pid_position_i", "%d" % result["position_i"])
        configfile.set(
            self.name,
            "velocity_filter_hz",
            "%d" % result["velocity_filter_hz"],
        )
        configfile.set(
            self.name,
            "position_filter_hz",
            "%d" % result["position_filter_hz"],
        )
        configfile.set(self.name, "flux_filter_hz", "%d" % result["flux_filter_hz"])
        configfile.set(self.name, "torque_filter_hz", "%d" % result["torque_filter_hz"])
        configfile.set(self.name, "identified_j_eff", "%d" % result["j_eff"])
        configfile.set(self.name, "identified_b_eff", "%d" % result["b_eff"])
        configfile.set(self.name, "autotune_mode", mode_name)
        configfile.set(self.name, "autotune_status", status)

    def _handle_trace_info_result(self, params: dict) -> None:
        """Handle foci_trace_info_result response from firmware."""
        self._trace_info = params
        self._trace_info_received = True

    def cmd_FOCI_TRACE_START(self, gcmd) -> None:
        """Start per-tick trace capture for the selected stepper."""
        preset_name = gcmd.get("PRESET", "full").lower()
        presets = {"fast": 0, "full": 1, "velocity": 2, "hold": 3}
        if preset_name not in presets:
            raise gcmd.error(
                "FOCI %s: unknown trace preset '%s' "
                "(expected fast, full, velocity, or hold)" % (self.name, preset_name)
            )
        self.trace_start_cmd.send([self.oid, presets[preset_name]])
        gcmd.respond_info(
            "FOCI %s trace capture started (%s preset)" % (self.name, preset_name)
        )

    def cmd_FOCI_TRACE_STOP(self, gcmd) -> None:
        """Stop per-tick trace capture for the selected stepper."""
        self.trace_stop_cmd.send([self.oid])
        gcmd.respond_info("FOCI %s trace capture stopped" % self.name)

    def cmd_FOCI_TRACE(self, gcmd) -> None:
        """Fetch and display the trace capture buffer."""
        import struct

        format_name = gcmd.get("FORMAT", "table").lower()
        phase_filter = gcmd.get_int("PHASE", None)

        # Query trace buffer metadata
        self._trace_info = None
        self._trace_info_received = False
        self.trace_info_cmd.send([self.oid])

        reactor = self.printer.get_reactor()
        deadline = reactor.monotonic() + 5.0
        while not self._trace_info_received:
            if reactor.monotonic() > deadline:
                raise gcmd.error("FOCI %s: trace info timed out" % self.name)
            reactor.pause(reactor.monotonic() + 0.05)

        info = self._trace_info
        state = info.get("state", 0)
        count = info.get("count", 0)
        generation = info.get("generation", 0)

        if state != 2 or count == 0:
            gcmd.respond_info("FOCI %s: no trace data available" % self.name)
            return

        preset = info.get("preset", 0)
        dropped = info.get("dropped", 0)
        sample_period = info.get("sample_period_us", 1000)

        if preset == 1:  # Full
            sample_size = 48
            fmt = "<HBBiiIiIiIiiii"
            headers = TRACE_FULL_HEADERS
        elif preset == 2:  # Velocity
            sample_size = 52
            fmt = "<HBBiiIiIiiiiiii"
            headers = TRACE_VELOCITY_HEADERS
        elif preset == 3:  # Hold
            sample_size = 52
            fmt = "<HBBiiIiIiiiIIii"
            headers = TRACE_HOLD_HEADERS
        else:  # Fast
            sample_size = 28
            fmt = "<HBBiiIiIi"
            headers = TRACE_FAST_HEADERS

        def _i16(val: int) -> int:
            """Convert unsigned 16-bit half to signed i16."""
            return val - 0x10000 if val >= 0x8000 else val

        # Fetch samples
        samples = []
        for i in range(count):
            params = self.trace_fetch_cmd.send([self.oid, i, generation])
            status = params.get("status", 2)
            if status != 0:
                status_names = {1: "capture still active", 2: "invalid"}
                gcmd.respond_info(
                    "FOCI %s: trace fetch aborted at offset %d: %s"
                    % (self.name, i, status_names.get(status, "unknown"))
                )
                return
            data = params.get("data", b"")
            if len(data) != sample_size:
                gcmd.respond_info(
                    "FOCI %s: unexpected sample size %d (expected %d)"
                    % (self.name, len(data), sample_size)
                )
                return
            fields = struct.unpack(fmt, data)

            # Split torque/flux packed fields (halves are signed i16)
            if preset == 1:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:9]))  # pidout_vel, status, abn
                tf_tgt = fields[9]
                row.append(_i16((tf_tgt >> 16) & 0xFFFF))  # torque_target
                row.append(_i16(tf_tgt & 0xFFFF))  # flux_target
                row.extend(list(fields[10:]))  # vel_ofs, esum_pos/vel/trq
            elif preset == 2:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:9]))  # pidout_vel, status, abn
                row.extend(
                    list(fields[9:])
                )  # pos_err, pidout_trq/flx, pidin_vel, vel_actual, vel_ofs
            elif preset == 3:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:9]))  # pidout_vel, status, abn
                row.extend(list(fields[9:11]))  # pidout_trq, pidout_flx
                foc_uq_ud = fields[11]
                row.append(_i16((foc_uq_ud >> 16) & 0xFFFF))  # foc_uq
                row.append(_i16(foc_uq_ud & 0xFFFF))  # foc_ud
                foc_uq_ud_limited = fields[12]
                row.append(_i16((foc_uq_ud_limited >> 16) & 0xFFFF))  # foc_uq_lim
                row.append(_i16(foc_uq_ud_limited & 0xFFFF))  # foc_ud_lim
                row.extend(list(fields[13:]))  # esum_trq, esum_flx
            else:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:]))  # pidout_vel, status, abn
            samples.append(row)

        # Apply phase filter
        if phase_filter is not None:
            phase_col = 1  # phase is second column
            samples = [s for s in samples if s[phase_col] == phase_filter]

        if not samples:
            gcmd.respond_info("FOCI %s: no samples match filter" % self.name)
            return

        # Format output
        preset_names = {1: "full", 2: "velocity", 3: "hold"}
        preset_name = preset_names.get(preset, "fast")
        expected_tick_step = {1: 2, 2: 2, 3: 10}.get(preset, 1)
        header = "FOCI %s trace: %d samples" % (self.name, len(samples))
        if dropped > 0:
            header += " (%d dropped)" % dropped
        header += ", %s preset, %dus period" % (preset_name, sample_period)

        if format_name == "summary":
            lines = _format_trace_summary(
                self.name,
                samples,
                headers,
                preset_name,
                sample_period,
                dropped,
                expected_tick_step,
            )
        elif format_name == "csv":
            lines = [header, ",".join(headers)]
            for row in samples:
                lines.append(",".join(str(v) for v in row))
        else:
            lines = [header]
            col_widths = [max(len(h), 8) for h in headers]
            lines.append("  ".join(h.rjust(w) for h, w in zip(headers, col_widths)))
            for row in samples:
                lines.append(
                    "  ".join(str(v).rjust(w) for v, w in zip(row, col_widths))
                )

        gcmd.respond_info("\n".join(lines))
