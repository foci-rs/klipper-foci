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
    stall_ceiling_units,
    stall_margin_units,
    validate_runtime_config,
)
from .constants import FOCI_MAX_RUN_CURRENT_MA_CONSTANT
from .controls import (
    ControlsWorkflow,
)
from .diagnostics import DiagnosticsWorkflow
from .diagnostics.stepper_scale import POSITION_UNITS_PER_REV, tmc_grid
from .dump import RegisterDumpWorkflow
from .homing import HomingWorkflow
from .protocol import FociProtocol
from .registry import GCODE_COMMANDS, discover_optional_specs, register_gcode_commands
from .selftest import SelftestWorkflow
from .state import FociRuntimeState
from .virtual_endstop import FociVirtualEndstop


class FociDriver:
    """Klipper extras driver for a single TMC4671 FOC channel."""

    def __init__(self, config) -> None:
        self.printer = config.get_printer()
        self.global_config = self.printer.load_object(config, "foci")

        self.config = parse_driver_config(config)
        self.settings = FociControlSettings.from_config(self.config)
        self.name = self.config.name
        self.stepper_name = self.config.stepper_name
        self.mcu = self.config.mcu
        self.channel = self.config.channel

        self.oid: int | None = None
        self.stepper_oid: int | None = None
        self.max_run_current_ma: int | None = None

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

        gcode = self.printer.lookup_object("gcode")
        register_gcode_commands(
            self, gcode, command_specs=GCODE_COMMANDS + discover_optional_specs(self)
        )

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
        self.max_run_current_ma = self._read_run_current_cap()
        run_ma = int(self.settings.run_current * 1000.0)
        if run_ma > self.max_run_current_ma:
            raise self.printer.config_error(
                f"[{self.name}] run_current {self.settings.run_current:.3f} A exceeds the "
                f"{self.max_run_current_ma / 1000.0:.3f} A cap of MCU {self.mcu.get_name()}"
            )

    def _read_run_current_cap(self) -> int:
        """Return the board's run current cap in milliamps from the MCU dictionary."""
        mcu_name = self.mcu.get_name()
        constants = self.mcu.get_constants()
        if FOCI_MAX_RUN_CURRENT_MA_CONSTANT not in constants:
            raise self.printer.config_error(
                f"[{self.name}] MCU {mcu_name} does not report "
                f"{FOCI_MAX_RUN_CURRENT_MA_CONSTANT}; update the firmware"
            )
        raw = constants[FOCI_MAX_RUN_CURRENT_MA_CONSTANT]
        try:
            cap_ma = int(raw)
        except (TypeError, ValueError):
            cap_ma = 0
        if cap_ma <= 0:
            raise self.printer.config_error(
                f"[{self.name}] MCU {mcu_name} reports an invalid "
                f"{FOCI_MAX_RUN_CURRENT_MA_CONSTANT}: {raw!r}"
            )
        return cap_ma

    def _handle_connect(self) -> None:
        """Send truthful planner and encoder configuration to firmware."""
        settings = self.settings
        parsed = self.config
        run_ma: int = int(settings.run_current * 1000.0)

        validation = validate_runtime_config(self.config)
        self.state.runtime_status = validation.runtime_status
        self.state.active_gains = validation.active_gains
        active_gains = validation.active_gains

        pid_gains, position_gains, velocity_limit, filter_hz = self._resolve_startup_gains(
            settings, active_gains
        )
        self.protocol.configure_startup(
            current_ma=run_ma,
            voltage_limit=settings.voltage_limit,
            channel=self.channel,
            encoder_ppr=parsed.encoder_ppr,
            planner_steps_per_rev=parsed.planner_steps_per_rev,
            encoder_reversed=parsed.encoder_reversed,
            pid_gains=pid_gains,
            filter_hz=filter_hz,
            position_gains=position_gains,
            velocity_feedforward=(
                settings.velocity_feedforward,
                gain_to_permille(settings.velocity_feedforward_gain),
            ),
            velocity_limit=velocity_limit,
            homing=(
                round(parsed.homing_current * 1000.0),
                stall_ceiling_units(parsed),
                stall_margin_units(parsed),
                parsed.stall_persistence,
            ),
        )
        self._report_motion_scale_mapping()
        self._warn_if_tuned_below_operating_range()
        self.homing.apply_initial_state()

    @staticmethod
    def _resolve_startup_gains(
        settings: FociControlSettings,
        active_gains: dict[str, int | None] | None,
    ) -> tuple[
        tuple[int, int, int, int] | None,
        tuple[int, int, int, int] | None,
        int | None,
        dict[str, int | None],
    ]:
        """Resolve the single connect-time send, preferring saved gains over config."""
        flux_p = active_gains["flux_p"] if active_gains is not None else settings.pid_flux_p
        pid_gains = None
        if flux_p is not None:
            pid_gains = (
                flux_p,
                active_gains["flux_i"] if active_gains is not None else settings.pid_flux_i,
                active_gains["torque_p"] if active_gains is not None else settings.pid_torque_p,
                active_gains["torque_i"] if active_gains is not None else settings.pid_torque_i,
            )

        position_gains = None
        if active_gains is not None and active_gains.get("velocity_p") is not None:
            position_gains = (
                active_gains["position_p"],
                active_gains["position_i"],
                active_gains["velocity_p"],
                active_gains["velocity_i"],
            )
        elif settings.pid_position_p is not None:
            position_gains = (
                settings.pid_position_p,
                settings.pid_position_i,
                settings.pid_velocity_p,
                settings.pid_velocity_i,
            )

        if active_gains is not None and active_gains.get("velocity_limit"):
            velocity_limit = active_gains["velocity_limit"]
        else:
            velocity_limit = settings.pid_velocity_limit

        filter_hz: dict[str, int | None] = {}
        for name in ("velocity", "torque", "position", "flux"):
            value = active_gains.get(f"{name}_filter_hz") if active_gains is not None else None
            filter_hz[name] = value if value is not None else getattr(settings, f"{name}_filter_hz")

        return pid_gains, position_gains, velocity_limit, filter_hz

    def _warn_if_tuned_below_operating_range(self) -> None:
        """Compare the configured operating velocity against the probed tune.

        Advisory only: this runs inside a ``klippy:connect`` handler, where Klipper's connect
        dispatcher treats any raised exception as a fatal "Internal error during connect" and aborts
        startup.
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
        grid = tmc_grid(planner_steps)
        step_width = POSITION_UNITS_PER_REV // grid
        error_bound = str(step_width // 2) if step_width % 2 == 0 else "0.5"
        gcode = self.printer.lookup_object("gcode")
        gcode.respond_info(
            f"[foci {self.stepper_name}] motion scale:\nplanner={int(parsed.full_steps)}*"
            f"{int(parsed.microsteps)}={int(planner_steps)} steps/rev encoder="
            f"{int(parsed.encoder_ppr)} ppr={int(parsed.encoder_ppr * 4)} quadrature "
            f"counts/rev\ntmc_grid={int(grid)} pulses/rev step_width={int(step_width)} "
            f"position_units/pulse pulse_ratio={int(grid)}/{int(planner_steps)}"
            f"\naccumulated_scale_error=0 instantaneous_error_bound={error_bound} "
            f"position_units\nconfigured rotation_distance={parsed.rotation_distance:g}"
        )
        gcode.respond_info(
            f"[foci {self.stepper_name}] rollout warning: remove legacy hand compensation and "
            f"compare rotation_distance with the actual transmission before enabling motion"
        )
