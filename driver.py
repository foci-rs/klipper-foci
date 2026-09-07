# TMC4671 register definitions and FOCI driver class.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Register reference: TMC4671-LA datasheet rev 2.08

from .autotune import AutotuneWorkflow
from .commissioning import (
    CommissioningWorkflow,
)
from .config import (
    FociControlSettings,
    check_autotune_staleness,
    gain_to_permille,
    parse_driver_config,
    stall_threshold_units,
    validate_runtime_config,
)
from .controls import (
    ControlsWorkflow,
)
from .diagnostics import DiagnosticsWorkflow
from .dump import RegisterDumpWorkflow
from .homing import HomingWorkflow
from .protocol import FociProtocol
from .registry import (
    DEV_GCODE_COMMANDS,
    TRACE_GCODE_COMMANDS,
    mode_allows,
    register_gcode_commands,
)
from .selftest import SelftestWorkflow
from .state import FociRuntimeState
from .virtual_endstop import FociVirtualEndstop

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
        self.name = self.config.name
        self.stepper_name = self.config.stepper_name
        self.mcu = self.config.mcu
        self.channel = self.config.channel

        # Runtime FOCI commands use the Klipper stepper OID. It is resolved
        # after MCU identification, when Klipper has loaded all steppers.
        self.oid: int | None = None
        self.stepper_oid: int | None = None

        self.protocol = FociProtocol(self)
        self.state = FociRuntimeState()
        self.dump = RegisterDumpWorkflow(self)
        self.controls = ControlsWorkflow(self)
        self.homing = HomingWorkflow(self)
        self.virtual_endstop = FociVirtualEndstop(self)
        self.commissioning = CommissioningWorkflow(self)
        self.selftest = SelftestWorkflow(self)
        self.autotune = AutotuneWorkflow(self)
        self.diagnostics = DiagnosticsWorkflow(self)
        self._dev_gcode_registered = False
        self._trace_gcode_registered = False

        # Two-stage commissioning volatile state (per-session, not persisted)
        # See spec: docs/specs/2026-04-11-two-stage-foci-commissioning-design.md
        # Commissioning phase tracking (used by commission/tune progress callbacks)
        # Register GCode commands
        gcode = self.printer.lookup_object("gcode")
        register_gcode_commands(self, gcode, self.foci_mode)

        # Lifecycle events
        self.printer.register_event_handler("klippy:mcu_identify", self._handle_mcu_identify)
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
                f"[{self.name}] could not resolve MCU stepper OID for {self.stepper_name}"
            )
        oid = stepper.get_oid()
        if oid is None:
            raise self.printer.config_error(
                f"[{self.name}] could not resolve MCU stepper OID for {self.stepper_name}"
            )
        return oid

    def _handle_mcu_identify(self) -> None:
        """Look up MCU commands after data dictionary is loaded."""
        self.stepper_oid = self._resolve_stepper_oid()
        self.oid = self.stepper_oid
        self.protocol.bind_mcu(self.mcu, self.oid)
        self._register_trace_gcode_commands_if_available()
        self._register_dev_gcode_commands_if_available()

    def _register_trace_gcode_commands_if_available(self) -> None:
        """Register focused commands only when trace firmware publishes them."""
        foci_mode = getattr(self, "foci_mode", "default")
        if getattr(self, "_trace_gcode_registered", False) or not mode_allows(foci_mode, "expert"):
            return
        if self.protocol.commands.velocity_limit_latch_test is None:
            return
        gcode = self.printer.lookup_object("gcode")
        register_gcode_commands(
            self,
            gcode,
            foci_mode,
            command_specs=TRACE_GCODE_COMMANDS,
        )
        self._trace_gcode_registered = True

    def _register_dev_gcode_commands_if_available(self) -> None:
        """Register raw TMC developer commands only for dev firmware."""
        foci_mode = getattr(self, "foci_mode", "default")
        if getattr(self, "_dev_gcode_registered", False) or not mode_allows(foci_mode, "developer"):
            return
        commands = self.protocol.commands
        if commands.dev_tmc_read_register is None or commands.dev_tmc_write_register is None:
            return
        gcode = self.printer.lookup_object("gcode")
        register_gcode_commands(
            self,
            gcode,
            foci_mode,
            command_specs=DEV_GCODE_COMMANDS,
        )
        self._dev_gcode_registered = True

    def _handle_connect(self) -> None:
        """Send truthful planner and encoder configuration to firmware."""
        settings = self.settings
        parsed = self.config
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
            encoder_ppr=parsed.encoder_ppr,
            planner_steps_per_rev=parsed.planner_steps_per_rev,
            encoder_reversed=parsed.encoder_reversed,
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
                gain_to_permille(settings.velocity_feedforward_gain),
            ),
            velocity_limit=settings.pid_velocity_limit,
            homing=(
                round(parsed.homing_current * 1000.0),
                stall_threshold_units(parsed),
                parsed.stall_persistence,
            ),
        )
        self._report_motion_scale_mapping()
        validation = validate_runtime_config(self.config)
        self.state.runtime_status = validation.runtime_status
        self.state.active_gains = validation.active_gains
        self._warn_if_tuned_below_operating_range()
        self.homing.apply_initial_state()

    def _warn_if_tuned_below_operating_range(self) -> None:
        """Compare the configured operating velocity against the probed tune.

        Advisory only: this runs inside a ``klippy:connect`` handler, where
        Klipper's connect dispatcher treats any raised exception as a fatal
        "Internal error during connect" and aborts startup. A malformed or
        unavailable toolhead status must therefore degrade to "no warning",
        never to a startup failure.
        """
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is None:
            return
        try:
            status = toolhead.get_status(toolhead.get_last_move_time())
            operating_velocity_mm_s = float(status["max_velocity"])
        except (KeyError, TypeError, ValueError, AttributeError):
            return
        check_autotune_staleness(self.config, operating_velocity_mm_s)

    def _report_motion_scale_mapping(self) -> None:
        """Explain the deterministic startup mapping without overriding firmware."""
        parsed = self.config
        planner_steps = parsed.planner_steps_per_rev
        tmc_grid = 1 << (planner_steps - 1).bit_length() if planner_steps < 65_536 else 65_536
        step_width = 65_536 // tmc_grid
        error_bound = str(step_width // 2) if step_width % 2 == 0 else "0.5"
        gcode = self.printer.lookup_object("gcode")
        gcode.respond_info(
            f"[foci {self.stepper_name}] motion scale:\nplanner={int(parsed.full_steps)}*"
            f"{int(parsed.microsteps)}={int(planner_steps)} steps/rev encoder="
            f"{int(parsed.encoder_ppr)} ppr={int(parsed.encoder_ppr * 4)} quadrature "
            f"counts/rev\ntmc_grid={int(tmc_grid)} pulses/rev step_width={int(step_width)} "
            f"position_units/pulse pulse_ratio={int(tmc_grid)}/{int(planner_steps)}"
            f"\naccumulated_scale_error=0 instantaneous_error_bound={error_bound} "
            f"position_units\nconfigured rotation_distance={parsed.rotation_distance:g}"
        )
        gcode.respond_info(
            f"[foci {self.stepper_name}] rollout warning: remove legacy hand compensation and "
            f"compare rotation_distance with the actual transmission before enabling motion"
        )
