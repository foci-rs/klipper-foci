# TMC4671 register definitions and FOCI driver class.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Register reference: TMC4671-LA datasheet rev 2.08

import logging
from collections.abc import Callable

log = logging.getLogger(__name__)


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
    return "%d/65536" % val


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
    "PHI_E_SELECTION": 0x52,
    "MODE_RAMP_MODE_MOTION": 0x63,
    "PID_TORQUE_FLUX_TARGET": 0x64,
    "PID_TORQUE_FLUX_ACTUAL": 0x69,
    "PID_TORQUE_FLUX_LIMITS": 0x5E,
    "PIDOUT_UQ_UD_LIMITS": 0x5D,
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
    "ABN_DECODER_PHI_E_PHI_M": 0x2A,
    "PID_TORQUE_FLUX_OFFSET": 0x65,
    "PID_VELOCITY_OFFSET": 0x67,
    "PID_POSITION_TARGET": 0x68,
    "PID_POSITION_ACTUAL": 0x6B,
    "ADC_VM_LIMITS": 0x75,
    "STATUS_FLAGS": 0x7C,
    "PWM_SV_CHOP": 0x1A,
    # Sub-registers (synthetic addresses 0x80+, match firmware encoding)
    "INTERIM_PIDIN_TARGET_VELOCITY": 0x80,
    "INTERIM_PIDOUT_TARGET_VELOCITY": 0x81,
    "PID_POSITION_ERROR_SUM": 0x82,
    "PID_TORQUE_ERROR_SUM": 0x83,
    "PID_FLUX_ERROR_SUM": 0x84,
    "PID_VELOCITY_ERROR_SUM": 0x85,
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
    "flux_limit": 0xFFFF,
    "torque_limit": 0xFFFF << 16,
}

Fields["PIDOUT_UQ_UD_LIMITS"] = {
    "voltage_limit": 0xFFFF,
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
    "pidin_target_velocity",
    "pidout_target_velocity",
    "position_error_sum",
    "torque_error_sum",
    "flux_error_sum",
    "velocity_error_sum",
]

FIELD_FORMATTERS: dict[str, Callable[[int], str]] = {
    "motor_type": _fmt_motor_type,
    "phi_e": _fmt_phi_e,
    "mode": _fmt_motion_mode,
    "mode_pid_type": _fmt_pid_type,
    "abn_direction": _fmt_direction,
    "pwm_sv": _fmt_on_off,
    "flux_p": _fmt_q8_8,  # Q8.8 per DS 4.7.6
    "flux_i": _fmt_advanced_pi_current_i,  # Advanced PI zero scale.
    "torque_p": _fmt_q8_8,  # Q8.8 per DS 4.7.6
    "torque_i": _fmt_advanced_pi_current_i,  # Advanced PI zero scale.
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


class FociDriver:
    """Klipper extras driver for a single TMC4671 FOC channel."""

    cmd_DUMP_FOCI_help = "Dump TMC4671 register state for a FOCI stepper"
    cmd_FOCI_TRACE_help = "Fetch and display trace capture buffer"
    cmd_FOCI_SELFTEST_help = "Run TMC4671 self-test for a FOCI stepper"
    cmd_FOCI_COMMISSION_help = "Commission a FOCI stepper (Stage 1: diagnostics + current tune + closed-loop entry)"
    cmd_FOCI_AUTOTUNE_help = (
        "Tune installed FOCI stepper (Stage 2: requires commissioning + homing)"
    )

    def __init__(self, config) -> None:
        # Parse section name: [foci stepper_x]
        self.stepper_name: str = " ".join(config.get_name().split()[1:])
        self.name: str = config.get_name()

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
        self.identified_r_mohm: int | None = config.getint(
            "identified_r_mohm", None, minval=0
        )
        self.identified_l_uh: int | None = config.getint(
            "identified_l_uh", None, minval=0
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
        self.set_velocity_limit_cmd = None
        self.set_auto_calibrate_on_enable_cmd = None
        self.trace_info_cmd = None
        self.trace_fetch_cmd = None

        # Trace capture state
        self._trace_info: dict | None = None
        self._trace_info_received: bool = False

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
            "FOCI_TRACE",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_TRACE,
            desc=self.cmd_FOCI_TRACE_help,
        )

        # Lifecycle events
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "homing:home_rails_begin", self._handle_home_rails_begin
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
            "tmc_set_velocity_feedforward oid=%c enable=%c"
        )
        self.set_velocity_limit_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_limit oid=%c limit=%u"
        )
        self.set_auto_calibrate_on_enable_cmd = self.mcu.lookup_command(
            "tmc_set_auto_calibrate_on_enable oid=%c enable=%c"
        )
        self.trace_info_cmd = self.mcu.lookup_command("foci_trace_info oid=%c")
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
            return "%s: %s (r_mohm=%d, limit=%d)" % (
                phase_name,
                name,
                value0,
                value1,
            )
        if code == 22:
            return "%s: %s (l_int=%d, l_uh=%d)" % (
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
            self.set_velocity_feedforward_cmd.send([self.oid, 1])
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
            gains = self._active_gains
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
        """Ensure calibration before homing any rail that includes this stepper.

        Args:
            homing_state: Current homing state object.
            rails: List of PrinterRail objects being homed.
        """
        dominated_steppers = set()
        for rail in rails:
            for stepper in rail.get_steppers():
                dominated_steppers.add(stepper.get_name())
        if self.stepper_name in dominated_steppers:
            self._ensure_calibrated()

    def _handle_stepper_enable(self, print_time, is_enable) -> None:
        """Reset calibration state when the stepper is disabled.

        On disable: clears calibration state so the next enable triggers
        recalibration via the firmware's auto-calibrate-on-enable path.

        Args:
            print_time: Timestamp of the enable/disable event.
            is_enable: True if enabling, False if disabling.
        """
        if not is_enable:
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

            # Terminal state: motor enabled, holding
            enable_line.motor_enable(toolhead.get_last_move_time())
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

            # Persist to config
            self._persist_commission_results(result, profile_name)

            status_str = "accepted" if status == 0 else "accepted with warnings"
            gcmd.respond_info(
                "FOCI %s commissioned (%s): R=%dmOhm L=%duH"
                % (self.name, status_str, result["r_mohm"], result["l_uh"])
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
        configfile.set(self.name, "identified_r_mohm", "%d" % result["r_mohm"])
        configfile.set(self.name, "identified_l_uh", "%d" % result["l_uh"])
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
            headers = [
                "tick",
                "phase",
                "flags",
                "pos_tgt",
                "pos_act",
                "trq_act",
                "flx_act",
                "vel_act",
                "status",
                "abn",
                "trq_tgt",
                "flx_tgt",
                "vel_ofs",
                "esum_pos",
                "esum_vel",
                "esum_trq",
            ]
        else:  # Fast
            sample_size = 28
            fmt = "<HBBiiIiIi"
            headers = [
                "tick",
                "phase",
                "flags",
                "pos_tgt",
                "pos_act",
                "trq_act",
                "flx_act",
                "vel_act",
                "status",
                "abn",
            ]

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
                row.extend(list(fields[6:9]))  # vel_act, status, abn
                tf_tgt = fields[9]
                row.append(_i16((tf_tgt >> 16) & 0xFFFF))  # torque_target
                row.append(_i16(tf_tgt & 0xFFFF))  # flux_target
                row.extend(list(fields[10:]))  # vel_ofs, esum_pos/vel/trq
            else:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:]))  # vel_act, status, abn
            samples.append(row)

        # Apply phase filter
        if phase_filter is not None:
            phase_col = 1  # phase is second column
            samples = [s for s in samples if s[phase_col] == phase_filter]

        if not samples:
            gcmd.respond_info("FOCI %s: no samples match filter" % self.name)
            return

        # Format output
        preset_name = "full" if preset == 1 else "fast"
        header = "FOCI %s trace: %d samples" % (self.name, len(samples))
        if dropped > 0:
            header += " (%d dropped)" % dropped
        header += ", %s preset, %dus period" % (preset_name, sample_period)

        if format_name == "csv":
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
