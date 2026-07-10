"""Stage 2 autotune workflow for FOCI host commands."""

from __future__ import annotations

from .commissioning import (
    COMMISSION_ERROR_NAMES,
    HARD_FAULT_CODES,
    PROFILE_MAP,
    format_inner_warning_flags,
)
from .autotune_budget import (
    AutotuneBudgetError,
    compute_autotune_motion_budget,
    format_safe_pose_move,
)
from .readiness import POLICY_UNAVAILABLE, resolve_autotune_readiness

MODE_MAP: dict[str, int] = {
    "unloaded": 0,
    "nominal": 1,
    "high_inertia": 2,
}

IDLE_PRINT_STATES = frozenset(("standby", "complete", "cancelled"))


class AutotuneWorkflow:
    """Run installed Stage 2 tuning after commissioning and homing."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.result: dict | None = None
        self.done = False

    def handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware."""
        self.result = params
        self.done = True

    def _ensure_printer_idle(self, gcmd, toolhead) -> None:
        print_stats = self.driver.printer.lookup_object("print_stats", None)
        if print_stats is None:
            raise gcmd.error(
                "FOCI %s: printer idle state unavailable" % self.driver.name
            )
        status = print_stats.get_status(toolhead.get_last_move_time())
        state = str(status.get("state", "")).lower()
        if state not in IDLE_PRINT_STATES:
            raise gcmd.error(
                "FOCI %s: printer is not idle (print_stats state=%s)"
                % (self.driver.name, state or "unknown")
            )

    def autotune(self, gcmd) -> None:
        """Stage 2: installed tuning after commissioning and homing."""
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        mode_name = gcmd.get("MODE", "nominal").lower()
        if profile_name not in PROFILE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown profile '%s' (expected: %s)"
                % (self.driver.name, profile_name, ", ".join(sorted(PROFILE_MAP)))
            )
        if mode_name not in MODE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown mode '%s' (expected: %s)"
                % (self.driver.name, mode_name, ", ".join(sorted(MODE_MAP)))
            )

        if not self.driver.state.try_acquire():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.driver.name
            )

        try:
            if self.driver.state.inhibited:
                raise gcmd.error(
                    "FOCI %s: inhibited after failed FOCI_COMMISSION" % self.driver.name
                )
            if self.driver.state.runtime_status == "uncommissioned":
                raise gcmd.error(
                    "FOCI %s: not commissioned. Run FOCI_COMMISSION first."
                    % self.driver.name
                )
            if not self.driver.state.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: not calibrated. Enable motor, re-home, then retry."
                    % self.driver.name
                )

            toolhead = self.driver.printer.lookup_object("toolhead")
            self._ensure_printer_idle(gcmd, toolhead)
            try:
                motion_budget = compute_autotune_motion_budget(self.driver, gcmd)
            except AutotuneBudgetError as err:
                raise gcmd.error("FOCI %s: %s" % (self.driver.name, err))

            toolhead.wait_moves()
            self._ensure_printer_idle(gcmd, toolhead)

            if not self.driver.state.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: calibration lost during wait" % self.driver.name
                )
            kin_status = toolhead.get_status(toolhead.get_last_move_time())
            if not {"x", "y"}.issubset(set(kin_status.get("homed_axes", ""))):
                raise gcmd.error("FOCI %s: homing lost during wait" % self.driver.name)

            live_current_gains = self.driver.dump.read_live_current_gains()
            readiness = resolve_autotune_readiness(
                self.driver,
                live_current_gains=live_current_gains,
            )
            if readiness.blocked:
                raise gcmd.error(
                    "FOCI %s: FOCI_AUTOTUNE blocked: %s"
                    % (self.driver.name, "; ".join(readiness.blockers))
                )
            if readiness.stage2_policy == POLICY_UNAVAILABLE:
                raise gcmd.error(
                    "FOCI %s: FOCI_AUTOTUNE stage 2 unavailable inputs: %s"
                    % (self.driver.name, ", ".join(readiness.unavailable_inputs))
                )

            if readiness.warnings:
                gcmd.respond_info(
                    "FOCI %s autotune readiness warnings: %s"
                    % (self.driver.name, "; ".join(readiness.warnings))
                )
            if readiness.unavailable_inputs:
                gcmd.respond_info(
                    "FOCI %s autotune unavailable inputs: %s"
                    % (self.driver.name, ", ".join(readiness.unavailable_inputs))
                )

            gcode = self.driver.printer.lookup_object("gcode")
            gcode.run_script_from_command(format_safe_pose_move(motion_budget))
            toolhead.wait_moves()
            if not self.driver.state.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: calibration lost during safe-pose move" % self.driver.name
                )
            kin_status = toolhead.get_status(toolhead.get_last_move_time())
            if not {"x", "y"}.issubset(set(kin_status.get("homed_axes", ""))):
                raise gcmd.error(
                    "FOCI %s: homing lost during safe-pose move" % self.driver.name
                )

            self.driver.homing.invalidate_homing()

            if self.driver.state.commissioned_result is not None:
                inner_lambda = self.driver.state.commissioned_result["lambda_us"]
                theta_e = self.driver.state.commissioned_result["theta_e_us"]
                ringing = self.driver.state.commissioned_result["ringing_count"]
                bandwidth = self.driver.state.commissioned_result["bandwidth_hz"]
            else:
                config = self.driver.config
                inner_lambda = config.identified_lambda_us
                theta_e = config.identified_theta_e_us
                ringing = config.identified_ringing_count
                bandwidth = config.identified_bandwidth_hz

            tau_e_us = readiness.tau_e_us
            inner_warning_flags = readiness.inner_warning_flags

            self.done = False
            self.result = None
            self.driver.commissioning.error_code = 0

            self.driver.protocol.run_tune(
                profile_code=PROFILE_MAP[profile_name],
                mode_code=MODE_MAP[mode_name],
                inner_lambda=inner_lambda,
                theta_e=theta_e,
                current_ringing=ringing,
                current_bw=bandwidth,
                tau_e_us=tau_e_us,
                inner_warning_flags=inner_warning_flags,
                max_travel_mrev=motion_budget.max_travel_mrev,
                max_velocity_mrev_s=motion_budget.max_velocity_mrev_s,
                max_duration_ms=motion_budget.max_duration_ms,
                direction_mask=motion_budget.direction_mask,
            )

            reactor = self.driver.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + 30.0
            while not self.done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE timed out" % self.driver.name
                    )
                if self.driver.commissioning.error_code != 0:
                    error_name = COMMISSION_ERROR_NAMES.get(
                        self.driver.commissioning.error_code,
                        "UNKNOWN(%d)" % self.driver.commissioning.error_code,
                    )
                    self.driver.commissioning.maybe_clear_calibration_for_chip_reset(
                        self.driver.commissioning.error_code
                    )
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE failed: %s"
                        % (self.driver.name, error_name)
                    )

            result = self.result
            status = result.get("status", 255)
            if status > 1:
                error_name = COMMISSION_ERROR_NAMES.get(status, "UNKNOWN(%d)" % status)
                if status == 18:
                    self.driver.commissioning.handle_chip_reset_detected()
                    stepper_enable = self.driver.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE chip reset: %s "
                        "(motor disabled by firmware)" % (self.driver.name, error_name)
                    )
                if status in HARD_FAULT_CODES:
                    self.driver.commissioning.on_commission_failure()
                    stepper_enable = self.driver.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE safety fault: %s "
                        "(motor disabled by firmware)" % (self.driver.name, error_name)
                    )
                gcmd.respond_info(
                    "FOCI %s: FOCI_AUTOTUNE failed: %s "
                    "(motor holding with entry gains)" % (self.driver.name, error_name)
                )
                return

            warning_code = result.get("warning_code", 0)
            if status == 1 or warning_code != 0:
                tune_status = "tuned_conservative"
            else:
                tune_status = "tuned"

            active_gains = self.driver.state.active_gains
            self.driver.state.active_gains = {
                "flux_p": active_gains["flux_p"],
                "flux_i": active_gains["flux_i"],
                "torque_p": active_gains["torque_p"],
                "torque_i": active_gains["torque_i"],
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
            self.driver.state.runtime_status = tune_status

            self.persist_tune_results(result, mode_name, tune_status)

            gcmd.respond_info(
                "FOCI %s tuned (%s): vel_p=%d pos_p=%d"
                % (
                    self.driver.name,
                    tune_status,
                    result["velocity_p"],
                    result["position_p"],
                )
            )
            if "stiffness_timebase_ms" in result:
                gcmd.respond_info(
                    "FOCI %s autotune evidence: budget=%dmrev "
                    "stiffness_timebase=%dms search_stop=%d flags=0x%02x"
                    % (
                        self.driver.name,
                        result.get("motion_budget_mrev", 0),
                        result.get("stiffness_timebase_ms", 0),
                        result.get("velocity_search_stop_reason", 0),
                        result.get("outer_evidence_flags", 0),
                    )
                )
            if inner_warning_flags:
                gcmd.respond_info(
                    "FOCI %s inner confidence: %s"
                    % (
                        self.driver.name,
                        format_inner_warning_flags(inner_warning_flags),
                    )
                )
        finally:
            self.driver.state.release()

    def persist_tune_results(self, result: dict, mode_name: str, status: str) -> None:
        """Persist Stage 2 results to printer.cfg (pending SAVE_CONFIG)."""
        configfile = self.driver.printer.lookup_object("configfile")
        configfile.set(self.driver.name, "pid_velocity_p", "%d" % result["velocity_p"])
        configfile.set(self.driver.name, "pid_velocity_i", "%d" % result["velocity_i"])
        configfile.set(
            self.driver.name,
            "pid_velocity_limit",
            "%d" % result["velocity_limit"],
        )
        configfile.set(self.driver.name, "pid_position_p", "%d" % result["position_p"])
        configfile.set(self.driver.name, "pid_position_i", "%d" % result["position_i"])
        configfile.set(
            self.driver.name,
            "velocity_filter_hz",
            "%d" % result["velocity_filter_hz"],
        )
        configfile.set(
            self.driver.name,
            "position_filter_hz",
            "%d" % result["position_filter_hz"],
        )
        configfile.set(
            self.driver.name,
            "flux_filter_hz",
            "%d" % result["flux_filter_hz"],
        )
        configfile.set(
            self.driver.name,
            "torque_filter_hz",
            "%d" % result["torque_filter_hz"],
        )
        configfile.set(self.driver.name, "identified_j_eff", "%d" % result["j_eff"])
        configfile.set(self.driver.name, "identified_b_eff", "%d" % result["b_eff"])
        configfile.set(self.driver.name, "autotune_mode", mode_name)
        configfile.set(self.driver.name, "autotune_status", status)
