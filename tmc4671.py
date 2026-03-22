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
    "flux_i": _fmt_q8_8,  # Q8.8 in advanced PID mode (ADVANCED_PI_REPRESENT default)
    "torque_p": _fmt_q8_8,  # Q8.8 per DS 4.7.6
    "torque_i": _fmt_q8_8,  # Q8.8 in advanced PID mode (ADVANCED_PI_REPRESENT default)
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
    cmd_FOCI_SELFTEST_help = "Run TMC4671 self-test for a FOCI stepper"
    cmd_FOCI_CALIBRATE_help = "Calibrate FOCI motor (ADC, encoder, closed-loop)"
    cmd_FOCI_AUTOTUNE_help = "Run full motor commissioning (inner + outer autotuning)"

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

        # Allocate an OID for this axis
        self.oid: int = self.mcu.create_oid()

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
        self.commission_inner_cmd = None
        self.commission_outer_cmd = None
        self.set_velocity_filter_cmd = None
        self.set_position_gains_cmd = None
        self.set_velocity_feedforward_cmd = None
        self.set_velocity_limit_cmd = None

        # Calibration state
        self.is_calibrated = False
        self._calibration_completion = None

        # Dump state
        self._dump_buffer: dict[int, int] = {}
        self._dump_complete = False

        # Selftest state (commissioning-engine based)
        self._selftest_done: bool = False
        self._selftest_in_flight: bool = False

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
            "FOCI_CALIBRATE",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_CALIBRATE,
            desc=self.cmd_FOCI_CALIBRATE_help,
        )
        gcode.register_mux_command(
            "FOCI_AUTOTUNE",
            "STEPPER",
            self.stepper_name,
            self.cmd_FOCI_AUTOTUNE,
            desc=self.cmd_FOCI_AUTOTUNE_help,
        )

        # Lifecycle events
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "homing:home_rails_begin", self._handle_home_rails_begin
        )

    def _handle_mcu_identify(self) -> None:
        """Look up MCU commands after data dictionary is loaded."""
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
            self._handle_calibrate_response, "foci_calibrate_response", self.oid
        )
        self.set_pid_gains_cmd = self.mcu.lookup_command(
            "tmc_set_pid_gains oid=%c flux_p=%hu flux_i=%hu torque_p=%hu torque_i=%hu"
        )
        self.commission_inner_cmd = self.mcu.lookup_command(
            "foci_commission_inner oid=%c profile=%c"
        )
        self.commission_outer_cmd = self.mcu.lookup_command(
            "foci_commission_outer oid=%c profile=%c mode=%c"
            " inner_lambda=%u theta_e=%u current_ringing=%c current_bw=%u"
        )
        self.mcu._serial.register_response(
            self._handle_commission_phase, "foci_commission_phase", self.oid
        )
        self.mcu._serial.register_response(
            self._handle_commission_inner_result,
            "foci_commission_inner_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_commission_outer_result,
            "foci_commission_outer_result",
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
        9: "Mechanical ID",
        10: "Velocity tune",
        11: "Velocity validation",
        12: "Position tune",
        13: "Filter selection",
        14: "Commit",
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
    }

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

    def _handle_commission_phase(self, params: dict) -> None:
        """Handle foci_commission_phase message from firmware.

        Caches the most recent phase ID for failure reporting and
        reports phase transitions to the Klipper console. A message with
        phase=0 and nonzero status signals a commissioning failure —
        sets the error code so the poll loop breaks immediately.
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
        elif phase_id == 0 and status == 0 and self._selftest_in_flight:
            self._selftest_done = True

    def _handle_commission_inner_result(self, params: dict) -> None:
        """Handle foci_commission_inner_result message from firmware."""
        self._commission_inner_result = params
        self._commission_inner_done = True

    def _handle_commission_outer_result(self, params: dict) -> None:
        """Handle foci_commission_outer_result message from firmware."""
        self._commission_outer_result = params
        self._commission_outer_done = True

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
        # Find which rails contain this stepper
        matched_rails = set()
        for i, rail in enumerate(kin.get_rails()):
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
        if self.is_calibrated:
            return
        if self._inhibited:
            raise self.printer.command_error(
                "FOCI %s: operation inhibited after failed FOCI_COMMISSION. "
                "Retry FOCI_COMMISSION or restart Klipper." % self.name
            )
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

            # Mark axes unhomed before sending calibrate (homing invalidation rule)
            self._invalidate_homing()

            # Send calibrate and wait for response
            reactor = self.printer.get_reactor()
            self._calibration_completion = reactor.completion()
            self.calibrate_cmd.send([self.oid])
            params = self._calibration_completion.wait(reactor.monotonic() + 5.0)
            self._calibration_completion = None

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
                status_names = {
                    1: "SPI_ERROR (TMC4671 not responding)",
                    2: "ADC_FAULT (ADC offsets out of range: I0=%d I1=%d)"
                    % (params.get("adc_i0", 0), params.get("adc_i1", 0)),
                    3: "ENCODER_FAULT (encoder not connected or unstable)",
                    4: "PID_FAULT (control loop not converging)",
                    6: "INTERNAL_ERROR (firmware command queue full)",
                    7: "CONFIG_FAULT (tmc_set_encoder not called before calibrate"
                    " -- check printer.cfg foci section has encoder_ppr)",
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
        """Handler for FOCI_SELFTEST GCode command.

        Sends foci_selftest command to create a commissioning-engine selftest
        in firmware. The firmware streams foci_commission_phase messages for
        progress and a terminal phase=0 status=0 on success.
        """
        reactor = self.printer.get_reactor()
        self._selftest_done = False
        self._selftest_in_flight = True
        self._last_phase_id = None
        self._commission_error_code = 0

        # Send selftest command (firmware creates new_selftest engine)
        self.selftest_cmd.send([self.oid])

        # Wait for completion (15s timeout -- selftest runs phases 0-4)
        deadline = reactor.monotonic() + 15.0
        while not self._selftest_done:
            if self._commission_error_code != 0:
                self._selftest_in_flight = False
                phase_name = (
                    self.PHASE_NAMES.get(self._last_phase_id, "unknown")
                    if self._last_phase_id
                    else "startup"
                )
                raise self.printer.command_error(
                    "FOCI %s: selftest failed at %s (code %d)"
                    % (self.stepper_name, phase_name, self._commission_error_code)
                )
            if reactor.monotonic() > deadline:
                self._selftest_in_flight = False
                raise self.printer.command_error(
                    "FOCI %s: selftest timed out" % self.stepper_name
                )
            reactor.pause(reactor.monotonic() + 0.05)

        self._selftest_in_flight = False
        gcmd.respond_info(
            "FOCI %s: selftest passed (phases 0-4 complete)" % self.stepper_name
        )

    def cmd_FOCI_CALIBRATE(self, gcmd) -> None:
        """Handler for FOCI_CALIBRATE GCode command.

        Forces recalibration regardless of current calibration state.
        Reports success or failure to the GCode console.
        """
        self.is_calibrated = False
        self._ensure_calibrated()
        gcmd.respond_info("FOCI %s: calibration OK" % self.name)

    def _build_commission_error(
        self, stepper_name: str, stage: str, status: int
    ) -> str:
        """Build a human-readable commissioning error message.

        Args:
            stepper_name: Name of the stepper that failed.
            stage: "inner" or "outer" commissioning stage.
            status: Firmware error status code.

        Returns:
            Formatted error string with phase name (if available)
            and error description.
        """
        error_name = self.COMMISSION_ERROR_NAMES.get(
            status, "unknown error %d" % status
        )
        if self._last_phase_id is not None:
            phase_name = self.PHASE_NAMES.get(
                self._last_phase_id, "Phase %d" % self._last_phase_id
            )
            return "FOCI %s: %s commissioning failed at %s: %s (code %d)" % (
                stepper_name,
                stage,
                phase_name,
                error_name,
                status,
            )
        return "FOCI %s: %s commissioning failed: %s (code %d)" % (
            stepper_name,
            stage,
            error_name,
            status,
        )

    def _run_inner_commission(self, profile_code: int, gcmd) -> dict:
        """Run inner (electrical) commissioning and return the result.

        Sends the foci_commission_inner command, monitors phase transitions,
        and waits for the inner result reply.

        Args:
            profile_code: Commissioning profile (0=conservative, 1=balanced,
                2=stiff).
            gcmd: GCode command context for error reporting.

        Returns:
            The inner result dict from firmware on success.

        Raises:
            command_error: On timeout or non-zero status.
        """
        reactor = self.printer.get_reactor()
        self._last_phase_id = None
        self._commission_inner_result = None
        self._commission_inner_done = False
        self._commission_error_code = 0

        self.commission_inner_cmd.send([self.oid, profile_code])

        deadline = reactor.monotonic() + 15.0
        while not self._commission_inner_done:
            if self._commission_error_code != 0:
                raise self.printer.command_error(
                    self._build_commission_error(
                        self.stepper_name, "inner", self._commission_error_code
                    )
                )
            if reactor.monotonic() > deadline:
                raise self.printer.command_error(
                    "FOCI %s: commissioning timed out waiting for"
                    " inner result" % self.stepper_name
                )
            reactor.pause(reactor.monotonic() + 0.05)

        result = self._commission_inner_result
        status = result.get("status", 255)
        # 0 = Accepted, 1 = AcceptedWithWarnings — both are success.
        if status > 1:
            raise self.printer.command_error(
                self._build_commission_error(self.stepper_name, "inner", status)
            )
        return result

    def _run_outer_commission(
        self,
        profile_code: int,
        mode_code: int,
        inner_result: dict,
        gcmd,
    ) -> dict:
        """Run outer (mechanical) commissioning and return the result.

        Sends the foci_commission_outer command with bandwidth parameters
        from the inner result, monitors phase transitions, and waits for
        the outer result reply.

        Args:
            profile_code: Commissioning profile code.
            mode_code: Operating mode code (0=unloaded, 1=nominal,
                2=high_inertia).
            inner_result: Dict from successful inner commissioning containing
                lambda_us, theta_e_us, ringing_count, bandwidth_hz.
            gcmd: GCode command context for error reporting.

        Returns:
            The outer result dict from firmware on success.

        Raises:
            command_error: On timeout or non-zero status.
        """
        reactor = self.printer.get_reactor()
        self._last_phase_id = None
        self._commission_outer_result = None
        self._commission_outer_done = False
        self._commission_error_code = 0

        self.commission_outer_cmd.send(
            [
                self.oid,
                profile_code,
                mode_code,
                inner_result["lambda_us"],
                inner_result["theta_e_us"],
                inner_result["ringing_count"],
                inner_result["bandwidth_hz"],
            ]
        )

        deadline = reactor.monotonic() + 20.0
        while not self._commission_outer_done:
            if self._commission_error_code != 0:
                raise self.printer.command_error(
                    self._build_commission_error(
                        self.stepper_name, "outer", self._commission_error_code
                    )
                )
            if reactor.monotonic() > deadline:
                raise self.printer.command_error(
                    "FOCI %s: commissioning timed out waiting for"
                    " outer result" % self.stepper_name
                )
            reactor.pause(reactor.monotonic() + 0.05)

        result = self._commission_outer_result
        status = result.get("status", 255)
        # 0 = Accepted, 1 = AcceptedWithWarnings — both are success.
        if status > 1:
            raise self.printer.command_error(
                self._build_commission_error(self.stepper_name, "outer", status)
            )
        return result

    def _persist_inner_results(
        self,
        result: dict,
        profile_name: str,
        mode_name: str,
        status_name: str,
    ) -> None:
        """Persist inner commissioning results for SAVE_CONFIG.

        Args:
            result: Inner result dict from firmware.
            profile_name: Human-readable profile name.
            mode_name: Human-readable mode name.
            status_name: Status string (accepted/inner_only).
        """
        configfile = self.printer.lookup_object("configfile")
        configfile.set(self.name, "pid_flux_p", "%d" % result["flux_p"])
        configfile.set(self.name, "pid_flux_i", "%d" % result["flux_i"])
        configfile.set(self.name, "pid_torque_p", "%d" % result["torque_p"])
        configfile.set(self.name, "pid_torque_i", "%d" % result["torque_i"])
        configfile.set(self.name, "identified_r_mohm", "%d" % result["r_mohm"])
        configfile.set(self.name, "identified_l_uh", "%d" % result["l_uh"])
        configfile.set(self.name, "autotune_profile", profile_name)
        configfile.set(self.name, "autotune_mode", mode_name)
        configfile.set(self.name, "autotune_status", status_name)

    def _persist_outer_results(self, result: dict) -> None:
        """Persist outer commissioning results for SAVE_CONFIG.

        Args:
            result: Outer result dict from firmware.
        """
        configfile = self.printer.lookup_object("configfile")
        configfile.set(self.name, "pid_velocity_p", "%d" % result["velocity_p"])
        configfile.set(self.name, "pid_velocity_i", "%d" % result["velocity_i"])
        configfile.set(
            self.name,
            "pid_velocity_limit",
            "%d" % result["velocity_limit"],
        )
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
        configfile.set(
            self.name,
            "torque_filter_hz",
            "%d" % result["torque_filter_hz"],
        )
        configfile.set(self.name, "identified_j_eff", "%d" % result["j_eff"])
        configfile.set(self.name, "identified_b_eff", "%d" % result["b_eff"])

    def _lookup_foci_driver(self, stepper_name: str):
        """Look up another FociDriver instance by stepper name.

        Args:
            stepper_name: The stepper name to search for (e.g. "stepper_y").

        Returns:
            The FociDriver instance, or None if not found.
        """
        for obj_name in self.printer.lookup_objects("foci"):
            driver = obj_name[1]
            if hasattr(driver, "stepper_name") and driver.stepper_name == stepper_name:
                return driver
        return None

    def _report_inner_results(self, gcmd, stepper_name: str, result: dict) -> None:
        """Report inner commissioning results to the GCode console.

        Args:
            gcmd: GCode command context.
            stepper_name: Name of the stepper.
            result: Inner result dict from firmware.
        """
        gcmd.respond_info(
            "FOCI %s inner commissioning complete:\n"
            "  Resistance: %.3f ohm\n"
            "  Inductance: %.3f mH\n"
            "  Flux P: %d (Q8.8 = %.3f)\n"
            "  Flux I: %d (Q8.8 = %.3f)\n"
            "  Torque P: %d (Q8.8 = %.3f)\n"
            "  Torque I: %d (Q8.8 = %.3f)\n"
            "  Bandwidth: %d Hz"
            % (
                stepper_name,
                result["r_mohm"] / 1000.0,
                result["l_uh"] / 1000.0,
                result["flux_p"],
                result["flux_p"] / 256.0,
                result["flux_i"],
                result["flux_i"] / 256.0,
                result["torque_p"],
                result["torque_p"] / 256.0,
                result["torque_i"],
                result["torque_i"] / 256.0,
                result["bandwidth_hz"],
            )
        )

    def _report_outer_results(self, gcmd, stepper_name: str, result: dict) -> None:
        """Report outer commissioning results to the GCode console.

        Args:
            gcmd: GCode command context.
            stepper_name: Name of the stepper.
            result: Outer result dict from firmware.
        """
        message = (
            "FOCI %s outer commissioning complete:\n"
            "  Velocity P: %d (Q8.8 = %.3f)\n"
            "  Velocity I: %d (Q8.8 = %.3f)\n"
            "  Velocity limit: %d\n"
            "  Position P: %d (Q8.8 = %.3f)\n"
            "  Position I: %d (Q8.8 = %.3f)\n"
            "  Velocity filter: %d Hz\n"
            "  Position filter: %d Hz\n"
            "  Flux filter: %d Hz\n"
            "  Torque filter: %d Hz\n"
            "  J_eff: %d, B_eff: %d"
            % (
                stepper_name,
                result["velocity_p"],
                result["velocity_p"] / 256.0,
                result["velocity_i"],
                result["velocity_i"] / 256.0,
                result["velocity_limit"],
                result["position_p"],
                result["position_p"] / 256.0,
                result["position_i"],
                result["position_i"] / 256.0,
                result["velocity_filter_hz"],
                result["position_filter_hz"],
                result["flux_filter_hz"],
                result["torque_filter_hz"],
                result["j_eff"],
                result["b_eff"],
            )
        )
        warning_code = result.get("warning_code", 0)
        if warning_code:
            warning_names = {
                1: "low-confidence mechanical ID, response-tuned gains used",
                2: "unsafe synthesized gains, response-tuned gains used",
            }
            message += "\n  Warning: %s" % warning_names.get(
                warning_code, "warning code %d" % warning_code
            )
        if "mech_torque_step" in result:
            message += (
                "\n  Mechanical ID: torque=%d, accel=%d/%d, peak=%d/%d, travel=%d/%d"
                % (
                    result["mech_torque_step"],
                    result["mech_fwd_accel"],
                    result["mech_rev_accel"],
                    result["mech_fwd_peak_velocity"],
                    result["mech_rev_peak_velocity"],
                    result["mech_fwd_travel"],
                    result["mech_rev_travel"],
                )
            )
        if "synth_velocity_p" in result:
            message += (
                "\n  Candidate before final guard: vel P/I=%d/%d, pos P/I=%d/%d"
                % (
                    result["synth_velocity_p"],
                    result["synth_velocity_i"],
                    result["synth_position_p"],
                    result["synth_position_i"],
                )
            )
        gcmd.respond_info(message)

    def _run_single_stepper_autotune(
        self,
        profile_code: int,
        mode_code: int,
        profile_name: str,
        mode_name: str,
        gcmd,
    ) -> None:
        """Run single-stepper commissioning (inner + outer).

        Args:
            profile_code: Commissioning profile code.
            mode_code: Operating mode code.
            profile_name: Human-readable profile name for persistence.
            mode_name: Human-readable mode name for persistence.
            gcmd: GCode command context.
        """
        # --- Inner commissioning ---
        inner_result = self._run_inner_commission(profile_code, gcmd)
        self._report_inner_results(gcmd, self.stepper_name, inner_result)

        # --- Outer commissioning ---
        try:
            outer_result = self._run_outer_commission(
                profile_code, mode_code, inner_result, gcmd
            )
        except Exception:
            # Outer failed — persist inner gains as inner_only
            self._persist_inner_results(
                inner_result, profile_name, mode_name, "inner_only"
            )
            gcmd.respond_info(
                "FOCI %s: outer commissioning failed."
                " Inner gains saved as inner_only.\n"
                "The SAVE_CONFIG command will update the printer"
                " config file and restart the printer." % self.stepper_name
            )
            raise

        # Both succeeded — persist everything.
        # Firmware status: 0 = Accepted, 1 = AcceptedWithWarnings.
        status_name = "accepted"
        inner_status = inner_result.get("status", 0)
        outer_status = outer_result.get("status", 0)
        if inner_status == 1 or outer_status == 1:
            status_name = "accepted_with_warnings"
        self._persist_inner_results(inner_result, profile_name, mode_name, status_name)
        self._persist_outer_results(outer_result)
        self._report_outer_results(gcmd, self.stepper_name, outer_result)
        gcmd.respond_info(
            "FOCI %s: commissioning complete.\n"
            "The SAVE_CONFIG command will update the printer"
            " config file and restart the printer." % self.stepper_name
        )

    def _run_dual_stepper_autotune(
        self,
        partner,
        profile_code: int,
        mode_code: int,
        profile_name: str,
        mode_name: str,
        gcmd,
    ) -> None:
        """Run dual-stepper commissioning with partner-hold orchestration.

        Phase 1: inner commission both steppers independently.
        Phase 2: outer commission each stepper while partner holds position.

        Args:
            partner: The partner FociDriver instance.
            profile_code: Commissioning profile code.
            mode_code: Operating mode code.
            profile_name: Human-readable profile name for persistence.
            mode_name: Human-readable mode name for persistence.
            gcmd: GCode command context.
        """
        # --- Phase 1: Inner commissioning (no partner needed) ---
        gcmd.respond_info(
            "FOCI dual-stepper autotune: inner commissioning %s" % self.stepper_name
        )
        inner_result_a = self._run_inner_commission(profile_code, gcmd)
        self._report_inner_results(gcmd, self.stepper_name, inner_result_a)
        self._persist_inner_results(
            inner_result_a, profile_name, mode_name, "inner_only"
        )

        gcmd.respond_info(
            "FOCI dual-stepper autotune: inner commissioning %s" % partner.stepper_name
        )
        inner_result_b = partner._run_inner_commission(profile_code, gcmd)
        self._report_inner_results(gcmd, partner.stepper_name, inner_result_b)
        partner._persist_inner_results(
            inner_result_b, profile_name, mode_name, "inner_only"
        )

        # --- Phase 2: Outer commissioning with partner hold ---

        # Outer commission stepper A while B holds
        gcmd.respond_info(
            "FOCI dual-stepper autotune: enabling %s for partner hold"
            % partner.stepper_name
        )
        partner._enable_stepper_hold()

        outer_failed_a = False
        try:
            gcmd.respond_info(
                "FOCI dual-stepper autotune: outer commissioning %s" % self.stepper_name
            )
            outer_result_a = self._run_outer_commission(
                profile_code, mode_code, inner_result_a, gcmd
            )
        except Exception:
            outer_failed_a = True
            outer_result_a = None
            gcmd.respond_info(
                "FOCI %s: outer commissioning failed."
                " Inner gains saved as inner_only." % self.stepper_name
            )

        # Disable partner B in hardware after A's outer phase
        partner._disable_stepper()

        if outer_failed_a:
            # A's outer failed. Per spec: disable partner, do not
            # attempt B's outer. Both inner gains already persisted.
            gcmd.respond_info(
                "FOCI dual-stepper autotune: outer commissioning"
                " failed for %s. Inner gains saved for both motors.\n"
                "The SAVE_CONFIG command will update the printer"
                " config file and restart the printer." % self.stepper_name
            )
            return

        # Persist A's full results.
        # Firmware status: 0 = Accepted, 1 = AcceptedWithWarnings.
        status_name_a = "accepted"
        if inner_result_a.get("status", 0) == 1:
            status_name_a = "accepted_with_warnings"
        if outer_result_a.get("status", 0) == 1:
            status_name_a = "accepted_with_warnings"
        self._persist_inner_results(
            inner_result_a, profile_name, mode_name, status_name_a
        )
        self._persist_outer_results(outer_result_a)
        self._report_outer_results(gcmd, self.stepper_name, outer_result_a)

        # Outer commission stepper B while A holds
        gcmd.respond_info(
            "FOCI dual-stepper autotune: enabling %s for partner hold"
            % self.stepper_name
        )
        self._enable_stepper_hold()

        outer_failed_b = False
        try:
            gcmd.respond_info(
                "FOCI dual-stepper autotune: outer commissioning %s"
                % partner.stepper_name
            )
            outer_result_b = partner._run_outer_commission(
                profile_code, mode_code, inner_result_b, gcmd
            )
        except Exception:
            outer_failed_b = True
            outer_result_b = None
            gcmd.respond_info(
                "FOCI %s: outer commissioning failed."
                " Inner gains saved as inner_only." % partner.stepper_name
            )

        # Disable self in hardware after B's outer phase
        self._disable_stepper()

        if not outer_failed_b:
            status_name_b = "accepted"
            if inner_result_b.get("status", 0) == 1:
                status_name_b = "accepted_with_warnings"
            if outer_result_b.get("status", 0) == 1:
                status_name_b = "accepted_with_warnings"
            partner._persist_inner_results(
                inner_result_b, profile_name, mode_name, status_name_b
            )
            partner._persist_outer_results(outer_result_b)
            self._report_outer_results(gcmd, partner.stepper_name, outer_result_b)

        # Summary
        if outer_failed_b:
            gcmd.respond_info(
                "FOCI dual-stepper autotune: %s fully commissioned,"
                " %s outer failed (inner gains saved).\n"
                "The SAVE_CONFIG command will update the printer"
                " config file and restart the printer."
                % (self.stepper_name, partner.stepper_name)
            )
        else:
            gcmd.respond_info(
                "FOCI dual-stepper autotune: commissioning complete"
                " for %s and %s.\n"
                "The SAVE_CONFIG command will update the printer"
                " config file and restart the printer."
                % (self.stepper_name, partner.stepper_name)
            )

    # CoreXY-family kinematics where stepper_x and stepper_y are paired.
    PAIRED_KINEMATICS: dict[str, tuple[str, str]] = {
        "corexy": ("stepper_x", "stepper_y"),
        "corexz": ("stepper_x", "stepper_z"),
    }

    def _detect_partner(self) -> "FociDriver | None":
        """Auto-detect the paired stepper for CoreXY-family kinematics.

        Returns the partner FociDriver if this stepper is part of a
        paired kinematics set and the partner is also FOCI-controlled.
        Returns None for cartesian or if the partner is not a FociDriver.
        """
        try:
            printer_config = self.printer.lookup_object("configfile")
            kin_name = printer_config.status_raw_config.get("printer", {}).get(
                "kinematics", ""
            )
        except Exception:
            return None
        pair = self.PAIRED_KINEMATICS.get(kin_name)
        if pair is None:
            return None
        if self.stepper_name not in pair:
            return None
        partner_name = pair[1] if self.stepper_name == pair[0] else pair[0]
        return self._lookup_foci_driver(partner_name)

    def _enable_stepper_hold(self) -> None:
        """Calibrate and enable this stepper in closed-loop position hold.

        Runs the firmware calibration sequence (ADC + encoder alignment),
        then enables the motor in hardware so the firmware enters its
        closed-loop position hold mode. Used to hold a partner motor
        during outer commissioning of the other axis.
        """
        self._ensure_calibrated()
        stepper_enable = self.printer.lookup_object("stepper_enable")
        enable_line = stepper_enable.lookup_enable(self.stepper_name)
        toolhead = self.printer.lookup_object("toolhead")
        print_time = toolhead.get_last_move_time()
        enable_line.motor_enable(print_time)
        toolhead.dwell(0.100)

    def _disable_stepper(self) -> None:
        """Disable this stepper's motor in hardware and clear calibration."""
        stepper_enable = self.printer.lookup_object("stepper_enable")
        enable_line = stepper_enable.lookup_enable(self.stepper_name)
        toolhead = self.printer.lookup_object("toolhead")
        print_time = toolhead.get_last_move_time()
        enable_line.motor_disable(print_time)
        toolhead.dwell(0.050)
        self.is_calibrated = False

    def _check_autotune_preconditions(self, gcmd) -> None:
        """Reject autotuning early if preconditions are not met.

        Checks that the motor is not currently enabled and that no
        moves are queued for this stepper. Raises command_error with
        a clear message on failure.
        """
        # Motor must not be enabled (firmware will also reject, but
        # catching it here gives a better error message).
        stepper_enable = self.printer.lookup_object("stepper_enable")
        enable_line = stepper_enable.lookup_enable(self.stepper_name)
        if enable_line.is_motor_enabled():
            raise gcmd.error(
                "FOCI %s: motor is currently enabled"
                " -- disable before autotuning" % self.stepper_name
            )
        # No queued moves for this stepper.
        toolhead = self.printer.lookup_object("toolhead")
        toolhead.wait_moves()

    def cmd_FOCI_AUTOTUNE(self, gcmd) -> None:
        """Run full motor commissioning (inner + outer autotuning).

        Auto-detects CoreXY partner for dual-stepper orchestration.
        Use PAIR=0 to skip partner detection and commission only this motor.
        On success, stages results for SAVE_CONFIG.
        """
        # Parse and validate parameters
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        if profile_name not in self.PROFILE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown profile '%s' (expected: %s)"
                % (
                    self.stepper_name,
                    profile_name,
                    ", ".join(sorted(self.PROFILE_MAP)),
                )
            )
        profile_code = self.PROFILE_MAP[profile_name]

        mode_name = gcmd.get("MODE", "nominal").lower()
        if mode_name not in self.MODE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown mode '%s' (expected: %s)"
                % (
                    self.stepper_name,
                    mode_name,
                    ", ".join(sorted(self.MODE_MAP)),
                )
            )
        mode_code = self.MODE_MAP[mode_name]

        # Pre-condition checks (spec: reject early with clear error)
        self._check_autotune_preconditions(gcmd)

        # Auto-detect paired stepper from kinematics (opt-out with PAIR=0)
        pair_enabled = gcmd.get_int("PAIR", 1, minval=0, maxval=1)
        partner = self._detect_partner() if pair_enabled else None

        if partner is not None:
            partner._check_autotune_preconditions(gcmd)
            gcmd.respond_info(
                "FOCI %s: detected paired stepper %s from kinematics,"
                " commissioning both (use PAIR=0 to skip)"
                % (self.stepper_name, partner.stepper_name)
            )
            self._run_dual_stepper_autotune(
                partner,
                profile_code,
                mode_code,
                profile_name,
                mode_name,
                gcmd,
            )
        else:
            # Single-stepper commissioning
            self._run_single_stepper_autotune(
                profile_code, mode_code, profile_name, mode_name, gcmd
            )
