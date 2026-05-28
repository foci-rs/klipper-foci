# TMC4671 register definitions and FOCI driver class.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Register reference: TMC4671-LA datasheet rev 2.08

from dataclasses import fields

from .autotune import AutotuneWorkflow
from .commissioning import (
    CommissioningWorkflow,
)
from .config import (
    CONTROL_SETTING_FIELDS,
    FociControlSettings,
    parse_driver_config,
    validate_runtime_config,
)
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
        self.settings = FociControlSettings.from_config(self.config)
        for field in fields(self.config):
            if field.name in CONTROL_SETTING_FIELDS:
                continue
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

    def _handle_connect(self) -> None:
        """Send configuration to firmware and check microstep alignment.

        Converts run_current to milliamps and sends it with the encoder
        PPR to the firmware. Warns if the configured microstep resolution
        does not match the encoder's natural resolution.
        """
        settings = self.settings
        run_ma: int = int(settings.run_current * 1000.0)
        pid_gains = None
        if settings.pid_flux_p is not None:
            pid_gains = (
                settings.pid_flux_p,
                settings.pid_flux_i,
                settings.pid_torque_p,
                settings.pid_torque_i,
            )
        position_gains = None
        if settings.pid_position_p is not None:
            position_gains = (
                settings.pid_position_p,
                settings.pid_position_i,
                settings.pid_velocity_p,
                settings.pid_velocity_i,
            )
        self.protocol.configure_startup(
            current_ma=run_ma,
            voltage_limit=settings.voltage_limit,
            channel=self.channel,
            encoder_ppr=self.encoder_ppr,
            encoder_reversed=self.encoder_reversed,
            pid_gains=pid_gains,
            filter_hz={
                "velocity": settings.velocity_filter_hz,
                "torque": settings.torque_filter_hz,
                "position": settings.position_filter_hz,
                "flux": settings.flux_filter_hz,
            },
            position_gains=position_gains,
            velocity_feedforward=(
                settings.velocity_feedforward,
                settings.velocity_feedforward_multiplier,
            ),
            velocity_limit=settings.pid_velocity_limit,
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
        validation = validate_runtime_config(self.config)
        self.state.runtime_status = validation.runtime_status
        self.state.active_gains = validation.active_gains
        self.homing.apply_initial_state()
