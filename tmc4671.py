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
# Register addresses (7-bit, no sub-registers for dump set)
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
    "ABN_DECODER_MODE": 0x25,
    "ABN_DECODER_PPR": 0x26,
    "ABN_DECODER_COUNT": 0x27,
    "ABN_DECODER_PHI_E_PHI_M": 0x2A,
    "STATUS_FLAGS": 0x7C,
    "PWM_SV_CHOP": 0x1A,
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

Fields["STATUS_FLAGS"] = {
    "pid_x_target_limit": 1 << 0,
    "pid_x_output_limit": 1 << 3,
    "pid_v_target_limit": 1 << 4,
    "pid_v_output_limit": 1 << 7,
    "pid_id_target_limit": 1 << 8,
    "pid_id_output_limit": 1 << 11,
    "pid_iq_target_limit": 1 << 12,
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
]

FIELD_FORMATTERS: dict[str, Callable[[int], str]] = {
    "motor_type": _fmt_motor_type,
    "phi_e": _fmt_phi_e,
    "mode": _fmt_motion_mode,
    "mode_pid_type": _fmt_pid_type,
    "abn_direction": _fmt_direction,
    "pwm_sv": _fmt_on_off,
    "flux_p": _fmt_q4_12,
    "flux_i": _fmt_q4_12,
    "torque_p": _fmt_q4_12,
    "torque_i": _fmt_q4_12,
    "velocity_p": _fmt_q8_8,
    "velocity_i": _fmt_q4_12,
    "position_p": _fmt_q8_8,
    "position_i": _fmt_q4_12,
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

    def __init__(self, config) -> None:
        # Parse section name: [foci stepper_x]
        parts = config.get_name().split(None, 1)
        self.stepper_name: str = parts[1] if len(parts) > 1 else parts[0]
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

        # Optional motor parameters
        self.motor_resistance: float | None = config.getfloat(
            "motor_resistance", None, above=0.0
        )
        self.motor_inductance: float | None = config.getfloat(
            "motor_inductance", None, above=0.0
        )

        # Read stepper config for microsteps and full_steps_per_rotation
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

        # Lifecycle events
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _handle_mcu_identify(self) -> None:
        """Look up MCU commands after data dictionary is loaded."""
        self.set_current_cmd = self.mcu.lookup_command(
            "tmc_set_current oid=%c run_ma=%u"
        )
        self.set_encoder_cmd = self.mcu.lookup_command(
            "tmc_set_encoder oid=%c channel=%c ppr=%u"
        )
        self.set_encoder_dir_cmd = self.mcu.lookup_command(
            "tmc_set_encoder_dir oid=%c channel=%c invert=%c"
        )
        self.selftest_cmd = self.mcu.lookup_command("tmc_selftest oid=%c")
        self.read_reg_cmd = self.mcu.lookup_query_command(
            "tmc_read_register oid=%c addr=%c",
            "tmc_register_value oid=%c addr=%c value=%u",
            oid=self.oid,
        )

    def _read_register(self, reg_name: str) -> int:
        """Read a single TMC4671 register via the firmware.

        Args:
            reg_name: Name of the register to read (must be in REGISTERS).

        Returns:
            The 32-bit register value returned by the firmware.
        """
        addr = REGISTERS[reg_name]
        params = self.read_reg_cmd.send([self.oid, addr])
        return params["value"]

    def cmd_DUMP_FOCI(self, gcmd) -> None:
        """Handler for DUMP_FOCI and DUMP_TMC GCode commands.

        Reads all registers in DUMP_GROUPS from the firmware and prints
        them formatted to the GCode console.
        """
        lines: list[str] = []
        for group_name, regs in DUMP_GROUPS:
            if "%s" in group_name:
                header = group_name % self.stepper_name
            else:
                header = group_name
            lines.append("========== %s ==========" % header)
            for reg_name in regs:
                val = self._read_register(reg_name)
                lines.append(self.fields.pretty_format(reg_name, val))
        gcmd.respond_info("\n".join(lines))

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

    def cmd_FOCI_SELFTEST(self, gcmd) -> None:
        """Handler for FOCI_SELFTEST GCode command.

        Sends the tmc_selftest command to the firmware and informs the
        user that results will appear in the console via defmt/RTT.
        """
        self.selftest_cmd.send([self.oid])
        gcmd.respond_info(
            "FOCI self-test started for %s."
            " Results will appear in the console." % self.stepper_name
        )
