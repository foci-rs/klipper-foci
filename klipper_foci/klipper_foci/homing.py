"""Homing, enable, and calibration workflow for FOCI."""

from __future__ import annotations

import logging
from typing import ClassVar

from .commissioning import COMMISSION_REASON_NAMES, format_commission_detail
from .config import POSITION_UNITS_PER_REV
from .constants import COMMISSION_CANCEL_GRACE_PERIOD_S
from .report import report_detail

log = logging.getLogger(__name__)

# Status codes for foci_calibrate_response (CalibrationError::status_code).
# This is a separate namespace from commissioning errors because calibration
# and commission paths report through different message types.
CALIBRATION_REASON_NAMES: dict[int, str] = {
    1: "SPI_ERROR (TMC4671 not responding)",
    2: "CHIP_RESET_DETECTED (TMC4671 lost state, re-commission required)",
    5: "ALREADY_ENABLED",
    6: "INTERNAL_ERROR",
    7: "CONFIG_FAULT (run-time configuration missing)",
    8: "ENCODER_FAULT (encoder did not report expected calibration movement)",
    9: "CLOSED_LOOP_ACTIVATION_UNSTABLE (position hold runaway or excess drift)",
    10: "CANCELLED (operator-requested cancel)",
    11: "ADC_FAULT (ADC calibration offsets out of range)",
    12: "COIL_FAULT (coil connectivity check failed)",
    13: "PHASE_FAULT (current on wrong ADC channel during phase wiring check)",
    14: "NO_CURRENT (no current detected in motor windings)",
    15: "CURRENT_VALIDATION_FAILED (retained gain storage corrupt)",
    16: "INVALID_SCHEDULE (internal deadline computation error)",
    17: "CURRENT_HOLD_FAILED (current-loop hold validation failed)",
    18: "FAULT_INTERLOCK (latched fault or STATUS pin asserted)",
    19: "SHUTDOWN (hardware shutdown requested during calibration)",
    20: "SAFE_STATE_INCOMPLETE (prior safe-state restore had write failures)",
}


class HomingWorkflow:
    """Coordinate calibration-on-enable and homing-related reporting."""

    COUPLED_AXES: ClassVar[dict[str, dict[int, tuple[int, ...]]]] = {
        "CoreXYKinematics": {0: (0, 1), 1: (0, 1), 2: (2,)},
        "CoreXZKinematics": {0: (0, 2), 1: (1,), 2: (0, 2)},
        "HybridCoreXYKinematics": {0: (0, 1), 1: (0, 1), 2: (2,)},
        "HybridCoreXZKinematics": {0: (0, 2), 1: (1,), 2: (0, 2)},
    }

    _TRIGGER_PATH_NAMES: ClassVar[dict[int, str]] = {
        0: "none",
        1: "ceiling",
        2: "margin",
    }

    def __init__(self, driver) -> None:
        self.driver = driver
        self._homing_move_start_times: dict[int, float] = {}
        self._enable_patched = False
        self._mirroring_firmware_arm = False

    def install_enable_hooks(self) -> None:
        """Install Klipper enable hooks that run FOCI calibration before enable."""
        if self._enable_patched:
            return
        self._enable_patched = True
        stepper_enable = self.driver.printer.lookup_object("stepper_enable")
        enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
        enable_line.register_state_callback(self.handle_stepper_enable)
        force_move = self.driver.printer.lookup_object("force_move", None)
        if force_move is not None:
            orig_force_enable = force_move._force_enable
            workflow = self

            def _wrapped_force_enable(stepper, _orig=orig_force_enable):
                name = stepper.get_name()
                if name == workflow.driver.stepper_name:
                    workflow.ensure_calibrated()
                return _orig(stepper)

            force_move._force_enable = _wrapped_force_enable
        for _name, ms in self.driver.printer.lookup_objects("manual_stepper"):
            steppers = getattr(ms, "steppers", [])
            if steppers and steppers[0].get_name() == self.driver.stepper_name:
                orig_do_enable = ms.do_enable
                workflow = self

                def _wrapped_do_enable(enable, _orig=orig_do_enable, _foci=workflow):
                    if enable:
                        _foci.ensure_calibrated()
                    _orig(enable)

                ms.do_enable = _wrapped_do_enable

    def handle_calibrate_response(self, params) -> None:
        """Handle foci_calibrate_response message from firmware."""
        if self.driver.state.calibration_completion is not None:
            self.driver.state.calibration_completion.complete(params)

    def _report_calibration_details(self) -> None:
        """Emit retained calibration diagnostics, if the firmware sent any."""
        details = self.driver.commissioning.details
        if not details:
            return
        gcode = self.driver.printer.lookup_object("gcode")
        lines = [f"FOCI {self.driver.stepper_name} calibration diagnostics:"]
        lines.extend(f"  {format_commission_detail(detail)}" for detail in details)
        gcode.respond_info("\n".join(lines))

    def apply_initial_state(self) -> None:
        """Apply connect-time homing state after driver config is loaded."""
        allow_auto_calibrate = (
            self.driver.state.active_gains is not None and not self.driver.state.inhibited
        )
        self.set_auto_calibrate_on_enable_allowed(allow_auto_calibrate)
        self.install_enable_hooks()

    def set_auto_calibrate_on_enable_allowed(self, allowed: bool) -> None:
        """Tell firmware whether raw enable may start auto-calibration."""
        self.driver.protocol.set_auto_calibrate_on_enable(allowed)

    def kinematic_motor_names_for_stepper(self) -> tuple[str, ...]:
        """Return steppers whose motor-space state is coupled to this driver."""
        toolhead = self.driver.printer.lookup_object("toolhead", None)
        if toolhead is None:
            return (self.driver.stepper_name,)
        kin = toolhead.get_kinematics()
        rails = getattr(kin, "rails", None)
        if rails is None and hasattr(kin, "get_rails"):
            rails = kin.get_rails()
        if rails is None:
            return (self.driver.stepper_name,)

        coupling = self.COUPLED_AXES.get(type(kin).__name__)
        rail_entries = []
        target_axes = set()
        for i, rail in enumerate(rails):
            names = tuple(stepper.get_name() for stepper in rail.get_steppers())
            axes = coupling.get(i, ()) if coupling else ((i,) if i < 3 else ())
            rail_entries.append((names, axes))
            if self.driver.stepper_name in names:
                target_axes.update(axes)
        if not target_axes:
            return (self.driver.stepper_name,)

        motor_names = []
        for names, axes in rail_entries:
            if target_axes.intersection(axes):
                motor_names.extend(names)
        return tuple(dict.fromkeys(motor_names))

    def format_calibration_status(self, status: int) -> str:
        """Format a non-zero foci_calibrate_result status for operators."""
        if status in CALIBRATION_REASON_NAMES:
            return CALIBRATION_REASON_NAMES[status]
        if status in COMMISSION_REASON_NAMES:
            return (
                f"legacy commissioning status {int(status)} in calibration reply: "
                f"{COMMISSION_REASON_NAMES[status]}"
            )
        return f"UNKNOWN_CALIBRATION_STATUS({int(status)})"

    def apply_active_gains_to_firmware(self) -> None:
        """Preload saved FOCI gains into firmware state before enabling."""
        gains = self.driver.state.active_gains
        if gains is None:
            return
        self.driver.protocol.preload_active_gains(
            gains,
            voltage_limit=self.driver.settings.voltage_limit,
        )

    def _driver_axes(self, kin, rails) -> set[int]:
        coupling = self.COUPLED_AXES.get(type(kin).__name__)
        axes = set()
        for rail_index, rail in enumerate(rails):
            if not any(
                stepper.get_name() == self.driver.stepper_name for stepper in rail.get_steppers()
            ):
                continue
            if coupling and rail_index in coupling:
                axes.update(coupling[rail_index])
            elif rail_index < 3:
                axes.add(rail_index)
        return axes

    def invalidate_homing(self) -> None:
        """Mark all kinematic axes affected by this stepper as unhomed."""
        toolhead = self.driver.printer.lookup_object("toolhead", None)
        if toolhead is None:
            return
        kin = toolhead.get_kinematics()
        if not hasattr(kin, "clear_homing_state"):
            return
        rails = getattr(kin, "rails", None)
        if rails is None:
            return
        axes_to_clear = self._driver_axes(kin, rails)
        if axes_to_clear:
            clear_arg = set()
            for i in axes_to_clear:
                clear_arg.add(i)
                clear_arg.add("xyz"[i])
            kin.clear_homing_state(clear_arg)
            axis_names = "".join("xyz"[i] for i in sorted(axes_to_clear))
            logging.info(
                "FOCI %s: marked axes %s unhomed (encoder re-zeroed)",
                self.driver.name,
                axis_names,
            )

    def sync_enable_line_armed(self) -> None:
        """Mirror a firmware-armed motor into Klipper's EnableLine.

        `run_calibration()` arms the motor directly through the FOCI
        commissioning backend, bypassing EnableLine, the same gap
        FOCI_SETUP's own success path guards against. Without this sync,
        EnableLine's is_enabled bookkeeping stays False, so a later
        motor_disable() call (e.g. mirroring a firmware-driven disarm into
        Klipper state) is a silent no-op and this stepper's is_calibrated
        never gets cleared.
        """
        stepper_enable = self.driver.printer.lookup_object("stepper_enable")
        enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
        toolhead = self.driver.printer.lookup_object("toolhead")
        self._mirroring_firmware_arm = True
        try:
            enable_line.motor_enable(toolhead.get_last_move_time())
        finally:
            self._mirroring_firmware_arm = False

    def ensure_calibrated(self, sync_enable_line: bool = True) -> None:
        """Run calibration if not already calibrated. Blocks until complete.

        Args:
            sync_enable_line: Mirror the firmware-armed motor into Klipper's
                EnableLine after calibrating. Pass False when already inside
                an EnableLine enable callback, which is about to take its own
                enable reference.
        """
        if self.driver.state.inhibited:
            detail = ""
            if self.driver.state.last_commission_failure:
                detail = f" last failure: {self.driver.state.last_commission_failure}."
            raise self.driver.printer.command_error(
                f"FOCI {self.driver.name}: operation inhibited after failed FOCI_SETUP. "
                f"Retry FOCI_SETUP or restart Klipper.{detail}"
            )
        if self.driver.state.is_calibrated:
            return
        if self.driver.state.active_gains is None:
            raise self.driver.printer.command_error(
                f"FOCI {self.driver.name}: no commissioned gains available. Run FOCI_SETUP first."
            )
        reactor = self.driver.printer.get_reactor()
        if getattr(reactor, "_prevent_pause_count", 0):
            # Klipper's motion flush handler enables steppers lazily (e.g. after
            # SET_KINEMATIC_POSITION marks an axis homed without enabling it) from
            # inside reactor.assert_no_pause(). Blocking here would raise a raw
            # ReactorError; report the real cause instead. Either way the flush
            # handler's bare `except:` shuts Klipper down.
            raise self.driver.printer.command_error(
                f"FOCI {self.driver.name}: cannot auto-calibrate -- the axis was marked "
                "homed without enabling the motor (e.g. via SET_KINEMATIC_POSITION), and a "
                "queued move is now trying to enable it lazily, which cannot block for "
                "calibration. Home the axis normally, or "
                f"SET_STEPPER_ENABLE STEPPER={self.driver.stepper_name} VALUE=1 before "
                "commanding motion."
            )
        if not self.driver.state.try_acquire("homing"):
            raise self.driver.printer.command_error(
                f"FOCI {self.driver.name}: another FOCI operation is in progress"
            )
        try:
            self.apply_active_gains_to_firmware()
            self.driver.commissioning.clear_details()

            self.driver.state.calibration_completion = reactor.completion()
            t_start = reactor.monotonic()
            self.set_auto_calibrate_on_enable_allowed(True)
            self.driver.protocol.run_calibration()
            params = self.driver.state.calibration_completion.wait(t_start + 5.0)
            if params is None:
                self.driver.protocol.run_commission_cancel()
                grace_deadline = reactor.monotonic() + COMMISSION_CANCEL_GRACE_PERIOD_S
                params = self.driver.state.calibration_completion.wait(grace_deadline)
            t_elapsed = reactor.monotonic() - t_start
            self.driver.state.calibration_completion = None

            logging.info(
                "FOCI %s: calibrate response after %.3fs: %s",
                self.driver.name,
                t_elapsed,
                params,
            )

            if params is None:
                raise self.driver.printer.command_error(
                    f"FOCI {self.driver.name}: calibration timed out (no response from firmware)"
                )
            status = params.get("status", 255)
            if status == 5:
                self.driver.state.is_calibrated = True
                if sync_enable_line:
                    self.sync_enable_line_armed()
                logging.info(
                    "FOCI %s: already calibrated (firmware auto-cal)",
                    self.driver.name,
                )
                self._report_calibration_details()
                return
            if status != 0:
                msg = self.format_calibration_status(status)
                if status == 2:
                    self.driver.commissioning.handle_chip_reset_detected()
                self._report_calibration_details()
                raise self.driver.printer.command_error(
                    f"FOCI {self.driver.name} calibration failed: {msg}"
                )
            self._report_calibration_details()
            self.driver.state.is_calibrated = True
            if sync_enable_line:
                self.sync_enable_line_armed()
            logging.info(
                "FOCI %s calibrated: ADC I0=%d I1=%d encoder=%d",
                self.driver.name,
                params.get("adc_i0", 0),
                params.get("adc_i1", 0),
                params.get("encoder_count", 0),
            )
        finally:
            self.driver.state.release()

    def handle_home_rails_begin(self, homing_state, rails) -> None:
        """Ensure calibration before homing any axis driven by this stepper."""
        toolhead = self.driver.printer.lookup_object("toolhead", None)
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

                driver_axes = self._driver_axes(kin, all_rails)
                if homed_axes and driver_axes and homed_axes & driver_axes:
                    self.ensure_calibrated()
                    return

        dominated_steppers = set()
        for rail in rails:
            for stepper in rail.get_steppers():
                dominated_steppers.add(stepper.get_name())
        if self.driver.stepper_name in dominated_steppers:
            self.ensure_calibrated()

    def _report(self, message: str) -> None:
        """Developer-facing homing diagnostic line: klippy.log only, gated behind
        [foci] debug -- see report.report_detail."""
        report_detail(log, self.driver.global_config.debug, message)

    def handle_homing_move_begin(self, homing_move) -> None:
        """Record the homing move print-time window for step history diagnostics."""
        toolhead = getattr(homing_move, "toolhead", None)
        if toolhead is None:
            return
        get_last_move_time = getattr(toolhead, "get_last_move_time", None)
        if get_last_move_time is None:
            return
        self._homing_move_start_times[id(homing_move)] = float(get_last_move_time())

    def handle_homing_move_end(self, homing_move) -> None:
        """Report FOCI stepper positions captured by Kalico homing."""
        start_time = self._homing_move_start_times.pop(id(homing_move), None)
        for sp in getattr(homing_move, "stepper_positions", []):
            if getattr(sp, "stepper_name", None) != self.driver.stepper_name:
                continue
            start_pos = int(sp.start_pos)
            trig_pos = int(sp.trig_pos)
            halt_pos = int(sp.halt_pos)
            move_steps = halt_pos - start_pos
            over_steps = halt_pos - trig_pos
            step_dist = float(sp.stepper.get_step_dist())
            self._report(
                f"FOCI_HOME_POSITION {self.driver.stepper_name} endstop={sp.endstop_name} "
                f"start={int(start_pos)} trig={int(trig_pos)} halt={int(halt_pos)} move_steps="
                f"{int(move_steps)} over_steps={int(over_steps)} move_mm="
                f"{move_steps * step_dist:.3f} over_mm={over_steps * step_dist:.3f}"
            )
            self._report_homing_step_history(homing_move, sp, start_time)
            self._report_stall_result()
            return

    def _report_stall_result(self) -> None:
        if self.driver.config.homing_current <= 0.0 or not self.driver.global_config.debug:
            return
        result = self.driver.protocol.query_stall()
        peak_mm = (
            result["peak_error_units"]
            / POSITION_UNITS_PER_REV
            * self.driver.config.rotation_distance
        )
        trigger_path = self._TRIGGER_PATH_NAMES.get(result["trigger_path"], "unknown")
        self._report(
            f"FOCI_HOME_STALL {self.driver.stepper_name} latched={result['latched']} "
            f"peak_error_units={result['peak_error_units']} peak_error_mm={peak_mm:.3f} "
            f"trigger_tick={result['trigger_tick']} clamp_active={result['clamp_active']} "
            f"trigger_path={trigger_path} "
            f"peak_margin_delta_units={result['peak_margin_delta_units']}"
        )

    def _report_homing_step_history(self, homing_move, sp, start_time) -> None:
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
        pos_steps = sum(int(step.step_count) for step in move_history if int(step.step_count) > 0)
        neg_steps = sum(-int(step.step_count) for step in move_history if int(step.step_count) < 0)
        dir_changes = self._count_history_dir_changes(move_history)
        gap_steps = self._sum_history_position_gaps(move_history)
        first = move_history[0]
        last = move_history[-1]
        planned_start = int(first.start_position)
        planned_end = int(last.start_position) + int(last.step_count)
        step_dist = float(sp.stepper.get_step_dist())
        self._report(
            f"FOCI_HOME_STEP_HISTORY {self.driver.stepper_name} start_clock={int(start_clock)} "
            f"end_clock={int(end_clock)} segments={len(history)} move_segments="
            f"{len(move_history)} marker_segments={len(marker_history)} signed_steps="
            f"{int(signed_steps)} abs_steps={int(abs_steps)} pos_steps={int(pos_steps)} "
            f"neg_steps={int(neg_steps)} dir_changes={int(dir_changes)} gap_steps="
            f"{int(gap_steps)} planned_start={int(planned_start)} planned_end="
            f"{int(planned_end)} first_clock={int(first.first_clock)} last_clock="
            f"{int(last.last_clock)} signed_mm={signed_steps * step_dist:.3f} abs_mm="
            f"{abs_steps * step_dist:.3f}"
        )
        self._report(
            f"FOCI_HOME_STEP_SEGMENTS {self.driver.stepper_name} first="
            f"{self._format_history_segment_edges(move_history[:4])} last="
            f"{self._format_history_segment_edges(move_history[-4:])} markers="
            f"{self._format_history_markers(marker_history[:4])}"
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
            (
                f"{int(step.first_clock)}:{int(step.start_position)}:{int(step.step_count):+}@"
                f"{int(step.interval)}/{int(step.add):+}"
            )
            for step in history
        )

    def _format_history_markers(self, history) -> str:
        """Format zero-count reset/query markers for homing diagnostics."""
        if not history:
            return "none"
        return ",".join(f"{int(step.first_clock)}:{int(step.start_position)}" for step in history)

    def handle_stepper_enable(self, print_time, is_enable) -> None:
        """Synchronize FOCI calibration state with Klipper stepper enable."""
        if is_enable:
            if not self._mirroring_firmware_arm:
                self.ensure_calibrated(sync_enable_line=False)
        else:
            self.driver.state.is_calibrated = False
