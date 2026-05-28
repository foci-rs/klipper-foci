# TMC4671 register definitions and FOCI driver class.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Register reference: TMC4671-LA datasheet rev 2.08

import logging

from dataclasses import fields

from .autotune import AutotuneWorkflow
from .commissioning import (
    CommissioningWorkflow,
)
from .config import parse_driver_config
from .controls import (
    ControlsWorkflow,
)
from .diagnostics import DiagnosticsWorkflow
from .dump import RegisterDumpWorkflow
from .homing import HomingWorkflow
from .protocol import FociProtocol
from .registers import REGISTERS
from .registry import register_gcode_commands
from .selftest import SelftestWorkflow
from .state import FociRuntimeState
from .trace import LegacyTraceWorkflow

######################################################################
# FociDriver - per-axis driver instance
######################################################################


class FociDriver:
    """Klipper extras driver for a single TMC4671 FOC channel."""

    def __init__(self, config) -> None:
        self.printer = config.get_printer()
        self.global_config = self.printer.load_object(config, "foci")
        self.foci_mode: str = self.global_config.mode

        self.config = parse_driver_config(config)
        for field in fields(self.config):
            setattr(self, field.name, getattr(self.config, field.name))

        # Runtime FOCI commands use the Klipper stepper OID. It is resolved
        # after MCU identification, when Klipper has loaded all steppers.
        self.oid: int | None = None
        self.stepper_oid: int | None = None

        self.protocol = FociProtocol(self)
        self.state = FociRuntimeState()
        self.dump = RegisterDumpWorkflow(self)
        self.controls = ControlsWorkflow(self)
        self.homing = HomingWorkflow(self)
        self.commissioning = CommissioningWorkflow(self)
        self.selftest = SelftestWorkflow(self)
        self.autotune = AutotuneWorkflow(self)
        self.diagnostics = DiagnosticsWorkflow(self)
        self.trace = LegacyTraceWorkflow(self)

        # Two-stage commissioning volatile state (per-session, not persisted)
        # See spec: docs/specs/2026-04-11-two-stage-foci-commissioning-design.md
        # Commissioning phase tracking (used by commission/tune progress callbacks)
        # Register GCode commands
        gcode = self.printer.lookup_object("gcode")
        register_gcode_commands(self, gcode, self.foci_mode)

        # Lifecycle events
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "homing:home_rails_begin", self.homing.handle_home_rails_begin
        )
        self.printer.register_event_handler(
            "homing:homing_move_begin", self.homing.handle_homing_move_begin
        )
        self.printer.register_event_handler(
            "homing:homing_move_end", self.homing.handle_homing_move_end
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
        self.protocol.bind_mcu(self.mcu, self.oid)

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
        addr = REGISTERS[reg_name]
        return self.protocol.read_register(addr)

    def _validate_and_load_config(self) -> None:
        """Validate persisted config and populate active gains/runtime status.

        Called from _handle_connect. Checks that all mandatory fields for the
        claimed autotune_status are present. If any are missing, logs a warning
        and leaves active gains unset with runtime status uncommissioned.
        """
        status = self.autotune_status
        if status is None:
            # No prior commissioning -- virgin hardware
            self.state.runtime_status = "uncommissioned"
            self.state.active_gains = None
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
            self.state.runtime_status = "uncommissioned"
            self.state.active_gains = None
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
            self.state.runtime_status = "uncommissioned"
            self.state.active_gains = None
            return

        # All required fields present -- build active gains.
        if status == "commissioned":
            self.state.active_gains = {
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
            self.state.active_gains = {
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
        self.state.runtime_status = status
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
        pid_gains = None
        if self.pid_flux_p is not None:
            pid_gains = (
                self.pid_flux_p,
                self.pid_flux_i,
                self.pid_torque_p,
                self.pid_torque_i,
            )
        position_gains = None
        if self.pid_position_p is not None:
            position_gains = (
                self.pid_position_p,
                self.pid_position_i,
                self.pid_velocity_p,
                self.pid_velocity_i,
            )
        self.protocol.configure_startup(
            current_ma=run_ma,
            voltage_limit=self.voltage_limit,
            channel=self.channel,
            encoder_ppr=self.encoder_ppr,
            encoder_reversed=self.encoder_reversed,
            pid_gains=pid_gains,
            filter_hz={
                "velocity": self.velocity_filter_hz,
                "torque": self.torque_filter_hz,
                "position": self.position_filter_hz,
                "flux": self.flux_filter_hz,
            },
            position_gains=position_gains,
            velocity_feedforward=(
                self.velocity_feedforward,
                self.velocity_feedforward_multiplier,
            ),
            velocity_limit=self.pid_velocity_limit,
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
        self._validate_and_load_config()
        self.homing.apply_initial_state()
