"""TMC4671 register metadata and field formatting helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping

VOLTAGE_LIMIT_FULL_SCALE = 32767
ADC_OFFSET_MIDSCALE = 32768
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
    return f"{int(val)}({MOTOR_TYPES.get(val, '?')})"


def _fmt_phi_e(val: int) -> str:
    if val in (0, 4):
        return f"{int(val)}(reserved)"
    return PHI_E_SOURCES.get(val, str(val))


def _fmt_angle_source(val: int) -> str:
    return f"{int(val)}({ANGLE_SOURCES.get(val, '?')})"


def _fmt_velocity_meter(val: int) -> str:
    return f"{int(val)}({VELOCITY_METER_SOURCES.get(val, '?')})"


def _fmt_motion_mode(val: int) -> str:
    return MOTION_MODES.get(val, str(val))


def _fmt_pid_type(val: int) -> str:
    return "advanced" if val else "classic"


def _fmt_q8_8(val: int) -> str:
    return f"{val * 2 ** (-8):.3f}"


def _fmt_p_gain(val: int) -> str:
    return f"{int(val)} ({_fmt_q8_8(val)})"


def _fmt_voltage_limit(val: int) -> str:
    limit = abs(int(val))
    return f"{limit} ({limit / VOLTAGE_LIMIT_FULL_SCALE * 100:.1f}%)"


def _fmt_adc_offset(val: int) -> str:
    return f"{int(val)} ({int(val) - ADC_OFFSET_MIDSCALE:+d} from mid)"


def format_p_gain(raw: int) -> str:
    """Format one raw Q8.8 proportional gain without changing its value."""
    return f"{raw * 2 ** (-8):.6f} Q8.8"


def format_i_gain(raw: int) -> str:
    """Format one raw Q4.12 integral gain without changing its value."""
    decimal = f"{raw * 2 ** (-12):.12f}".rstrip("0").rstrip(".")
    return f"{decimal} Q4.12"


def _fmt_i_gain(val: int) -> str:
    return f"{int(val)} ({format_i_gain(val).removesuffix(' Q4.12')})"


def adc_vm_raw_to_volts(
    raw: int,
    constants: Mapping[str, object],
    offset_raw: int | None,
) -> float | None:
    """Convert raw ADC_VM to volts using board constants and runtime offset."""
    if offset_raw is None:
        return None
    try:
        offset = int(offset_raw)
        high_ohms = int(constants["FOCI_VM_DIVIDER_HIGH_OHMS"])
        low_ohms = int(constants["FOCI_VM_DIVIDER_LOW_OHMS"])
        reference_mv = int(constants["FOCI_VM_ADC_REFERENCE_MILLIVOLTS"])
        center_counts = int(constants["FOCI_VM_ADC_CENTER_COUNTS"])
    except (KeyError, TypeError, ValueError):
        return None

    if low_ohms <= 0 or reference_mv <= 0 or center_counts <= 0:
        return None

    divider_ratio = low_ohms / (high_ohms + low_ohms)
    counts_per_volt = center_counts / (reference_mv / 1000.0) * divider_ratio
    if counts_per_volt <= 0:
        return None
    return (raw - offset) / counts_per_volt


def fmt_adc_vm_raw(
    raw: int,
    constants: Mapping[str, object],
    offset_raw: int | None,
) -> str:
    """Format ADC_VM raw plus approximate decoded voltage when available."""
    voltage = adc_vm_raw_to_volts(raw, constants, offset_raw)
    if voltage is None:
        return str(raw)
    return f"{int(raw)}(~{voltage:.2f}V)"


def _fmt_direction(val: int) -> str:
    return "reversed" if val else "normal"


def _fmt_on_off(val: int) -> str:
    return "on" if val else "off"


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
    "INTERIM_PIDIN_TARGET_VELOCITY": 0x80,
    "INTERIM_PIDOUT_TARGET_VELOCITY": 0x81,
    "PID_POSITION_ERROR_SUM": 0x82,
    "PID_TORQUE_ERROR_SUM": 0x83,
    "PID_FLUX_ERROR_SUM": 0x84,
    "PID_VELOCITY_ERROR_SUM": 0x85,
    "CONFIG_ADVANCED_PI_REPRESENT": 0x86,
    "ADC_VM_RAW": 0x87,
    "VELOCITY_FF_CLAMP_LATCHED": 0x88,
    "VELOCITY_FF_CLAMP_COUNT": 0x89,
    "CONFIG_BIQUAD_X_ENABLE": 0x8A,
}


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

Fields["ADC_VM_RAW"] = {
    "adc_vm_raw": 0xFFFF,
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

Fields["PID_POSITION_TARGET"] = {
    "position_target": 0xFFFFFFFF,
}

Fields["PID_POSITION_ACTUAL"] = {
    "position_actual": 0xFFFFFFFF,
}

Fields["PID_VELOCITY_ACTUAL"] = {
    "velocity_actual": 0xFFFFFFFF,
}

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

Fields["CONFIG_BIQUAD_X_ENABLE"] = {
    "biquad_x_enable": 0xFFFFFFFF,
}

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
    "position_target",
    "position_actual",
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
    "flux_p": _fmt_p_gain,  # Q8.8 per DS 4.7.6
    "flux_i": _fmt_i_gain,
    "torque_p": _fmt_p_gain,  # Q8.8 per DS 4.7.6
    "torque_i": _fmt_i_gain,
    "velocity_p": _fmt_p_gain,
    "velocity_i": _fmt_i_gain,
    "position_p": _fmt_p_gain,
    "position_i": _fmt_i_gain,
    "voltage_limit": _fmt_voltage_limit,
    "adc_i0_offset": _fmt_adc_offset,
    "adc_i1_offset": _fmt_adc_offset,
}

DUMP_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Motor / Selection",
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
        "Filters",
        [
            "CONFIG_BIQUAD_X_ENABLE",
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
            "ADC_VM_RAW",
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


DUMP_NAME_WIDTH = max(len(name) for name in REGISTERS) + 2
FLAG_LIST_REGISTERS: frozenset[str] = frozenset({"STATUS_FLAGS"})


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
        """Extract a named field from a 32-bit register value, sign-extended if it is listed in
        signed_fields.
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

        Every field is shown, highest bits first to match the register name. Registers listed in
        FLAG_LIST_REGISTERS print only the names of the set flags.
        """
        reg_fields = self.all_fields.get(reg_name, {})
        sorted_fields = sorted(((mask, name) for name, mask in reg_fields.items()), reverse=True)
        head = f"{reg_name + ':':{DUMP_NAME_WIDTH}}{reg_value:08x}"
        if reg_name in FLAG_LIST_REGISTERS:
            set_flags = [
                name for _mask, name in sorted_fields if self.get_field(name, reg_name, reg_value)
            ]
            return f"{head}  set: {' '.join(set_flags) if set_flags else 'none'}"
        parts: list[str] = []
        for _mask, field_name in sorted_fields:
            field_value = self.get_field(field_name, reg_name, reg_value)
            fmt = self.field_formatters.get(field_name, str)
            parts.append(f"{field_name}={fmt(field_value)}")
        return f"{head}  {' '.join(parts)}" if parts else head
