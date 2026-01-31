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
    "PID_POSITION_TARGET": 0x68,
    "PID_POSITION_ACTUAL": 0x6B,
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
        "Position",
        [
            "PID_POSITION_TARGET",
            "PID_POSITION_ACTUAL",
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
    cmd_FOCI_CALIBRATE_help = "Calibrate FOCI motor (ADC, encoder, closed-loop)"

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
        self.calibrate_cmd = None
        self.dump_cmd = None

        # Calibration state
        self.is_calibrated = False
        self._calibration_completion = None

        # Dump state
        self._dump_buffer: dict[int, int] = {}
        self._dump_complete = False

        # Selftest state
        self._selftest_results: list[dict] = []
        self._selftest_complete = False
        self._selftest_status = 0

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
        self.mcu.register_response(self._handle_dump_value, "foci_dump_value", self.oid)
        self.mcu.register_response(self._handle_dump_done, "foci_dump_done", self.oid)
        self.mcu.register_response(
            self._handle_calibrate_response, "foci_calibrate_response", self.oid
        )
        self.mcu.register_response(
            self._handle_selftest_result, "foci_selftest_result", self.oid
        )
        self.mcu.register_response(
            self._handle_selftest_done, "foci_selftest_done", self.oid
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

    def _handle_selftest_result(self, params: dict) -> None:
        """Handle a single selftest stage result from firmware."""
        self._selftest_results.append(
            {
                "stage": params["stage"],
                "status": params["status"],
                "value": params["value"],
            }
        )

    def _handle_selftest_done(self, params: dict) -> None:
        """Handle selftest completion signal from firmware."""
        self._selftest_complete = True
        self._selftest_status = params["status"]

    def cmd_DUMP_FOCI(self, gcmd) -> None:
        """Handler for DUMP_FOCI and DUMP_TMC GCode commands.

        Sends a single foci_dump_registers command to the firmware and
        waits for all register values to be streamed back via the
        FOCI:DUMP: output protocol, then prints them formatted to the
        GCode console.
        """
        import time

        self._dump_buffer.clear()
        self._dump_complete = False
        self.dump_cmd.send([self.oid])

        # Wait for dump to complete. The serial reader thread calls
        # _handle_dump_done which sets _dump_complete.
        deadline = time.monotonic() + 5.0
        while not self._dump_complete and time.monotonic() < deadline:
            time.sleep(0.05)

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

    def _ensure_calibrated(self) -> None:
        """Run calibration if not already calibrated. Blocks until complete.

        Sends foci_calibrate to the firmware and waits up to 5 seconds for
        the foci_calibrate_response. Raises command_error on timeout or
        non-zero status.
        """
        if self.is_calibrated:
            return
        reactor = self.printer.get_reactor()
        self._calibration_completion = reactor.completion()
        self.calibrate_cmd.send([self.oid])
        params = self._calibration_completion.wait(reactor.monotonic() + 5.0)
        self._calibration_completion = None
        if params is None:
            raise self.printer.command_error(
                "FOCI %s: calibration timed out (no response from firmware)" % self.name
            )
        status = params.get("status", 255)
        if status == 5:
            # ALREADY_ENABLED: firmware auto-calibrated on enable before
            # this foci_calibrate arrived. Motor is calibrated and running.
            self.is_calibrated = True
            logging.info("FOCI %s: already calibrated (firmware auto-cal)", self.name)
            return
        if status != 0:
            status_names = {
                1: "SPI_ERROR (TMC4671 not responding)",
                2: "ADC_FAULT (ADC offsets out of range: I0=%d I1=%d)"
                % (params.get("adc_i0", 0), params.get("adc_i1", 0)),
                3: "ENCODER_FAULT (encoder not connected or unstable)",
                4: "PID_FAULT (control loop not converging)",
                6: "INTERNAL_ERROR (firmware command queue full)",
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

    # Selftest stage names for human-readable reporting
    SELFTEST_STAGES = {
        1: "ADC calibration",
        2: "Motor coil A",
        3: "Motor coil B",
        4: "Phase wiring",
        5: "Encoder",
        6: "Encoder direction (physical)",
        7: "Resistance",
        8: "Inductance",
    }

    def cmd_FOCI_SELFTEST(self, gcmd) -> None:
        """Handler for FOCI_SELFTEST GCode command.

        Sends foci_selftest command and collects streaming results.
        Formats a human-readable report to the GCode console.
        """
        import time

        self._selftest_results.clear()
        self._selftest_complete = False
        self._selftest_status = 0

        self.selftest_cmd.send([self.oid])

        # Wait for completion (10s timeout)
        deadline = time.monotonic() + 10.0
        while not self._selftest_complete:
            if time.monotonic() > deadline:
                raise self.printer.command_error(
                    "FOCI self-test timeout for %s" % self.stepper_name
                )
            time.sleep(0.05)

        # Format report
        lines = ["FOCI Self-Test: %s" % self.stepper_name]
        status_names = {0: "PASS", 1: "FAIL", 2: "SKIP"}
        passed = 0
        total = len(self._selftest_results)
        for r in self._selftest_results:
            stage = r["stage"]
            status = r["status"]
            value = r["value"]
            name = self.SELFTEST_STAGES.get(stage, "Stage %d" % stage)
            status_str = status_names.get(status, "?")
            detail = self._format_selftest_value(stage, status, value)
            dots = "." * max(1, 35 - len(name))
            lines.append("  %s %s %s%s" % (name, dots, status_str, detail))
            if status == 0:
                passed += 1
            elif status == 1 and stage <= 5:
                lines.append("  [ABORTED] %s" % self._selftest_error_hint(stage))
                break

        overall = "PASS" if self._selftest_status == 0 else "FAIL"
        if self._selftest_status == 2:
            overall = "ABORTED (motor enabled or selftest already running)"
        lines.append("Result: %s (%d/%d stages)" % (overall, passed, total))
        gcmd.respond_info("\n".join(lines))

    def _format_selftest_value(self, stage: int, status: int, value: int) -> str:
        """Format a stage-specific value for display."""
        if status != 0:
            return " (value: %d)" % value if value else ""
        if stage == 1:
            i0 = (value >> 16) & 0xFFFF
            i1 = value & 0xFFFF
            return " (I0: %d, I1: %d)" % (i0, i1)
        if stage in (2, 3):
            return " (current: %d)" % value
        if stage == 5:
            return " (delta: %d)" % value
        if stage == 6:
            return " (increasing)" if value == 0 else " (decreasing)"
        if stage == 7:
            a = ((value >> 16) & 0xFFFF) / 1000.0
            b = (value & 0xFFFF) / 1000.0
            return " (coil A: %.1f ohm, coil B: %.1f ohm)" % (a, b)
        if stage == 8:
            a = ((value >> 16) & 0xFFFF) / 1000.0
            b = (value & 0xFFFF) / 1000.0
            return " (coil A: %.1f mH, coil B: %.1f mH)" % (a, b)
        return ""

    def _selftest_error_hint(self, stage: int) -> str:
        """Return a human-readable hint for a failed stage."""
        hints = {
            1: "ADC calibration failed - check current sense hardware",
            2: "Motor not detected on coil A - check wiring",
            3: "Motor not detected on coil B - check wiring",
            4: "Phase wiring error - coils may be swapped at connector",
            5: "Encoder not responding - check encoder cable",
        }
        return hints.get(stage, "Stage %d failed" % stage)

    def cmd_FOCI_CALIBRATE(self, gcmd) -> None:
        """Handler for FOCI_CALIBRATE GCode command.

        Forces recalibration regardless of current calibration state.
        Reports success or failure to the GCode console.
        """
        self.is_calibrated = False
        self._ensure_calibrated()
        gcmd.respond_info("FOCI %s: calibration OK" % self.name)
