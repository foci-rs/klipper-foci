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
from .velocity_sweep import VelocitySweepAssembler, VelocitySweepProtocolError

MODE_MAP: dict[str, int] = {
    "unloaded": 0,
    "nominal": 1,
    "high_inertia": 2,
}

IDLE_PRINT_STATES = frozenset(("standby", "complete", "cancelled"))
VELOCITY_SWEEP_PLAN_TIMEOUT_S = 5.0
VELOCITY_SWEEP_COMMS_MARGIN_S = 5.0

OUTER_SAFETY_FAULT_NAMES = {
    1: "invalid_budget",
    2: "unusable_budget",
    3: "duration",
    4: "velocity",
    5: "position",
    6: "post_switch_settle",
    7: "observation_gap",
    8: "quarter_turn",
    9: "current",
}


class AutotuneWorkflow:
    """Run installed Stage 2 tuning after commissioning and homing."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.result: dict | None = None
        self.outer_safety_fault: dict | None = None
        self.velocity_sweep = VelocitySweepAssembler()
        self.velocity_sweep_error: VelocitySweepProtocolError | None = None
        self._stage_b_candidate_request: dict | None = None
        self.done = False

    def handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware."""
        self.result = params
        self.done = True

    def handle_outer_safety_fault(self, params: dict) -> None:
        """Handle foci_outer_safety_fault from firmware."""
        self.outer_safety_fault = dict(params)

    def _handle_velocity_sweep(self, method_name: str, params: dict) -> None:
        if self.velocity_sweep_error is not None:
            return
        try:
            getattr(self.velocity_sweep, method_name)(params)
        except VelocitySweepProtocolError as err:
            self.velocity_sweep_error = err

    def _request_for_stage_b_dispatch(self, request_fields: dict) -> dict:
        """Reuse the exact retained encoding when the explicit request matches."""
        if (
            self._stage_b_candidate_request is not None
            and request_fields == self._stage_b_candidate_request
        ):
            return dict(self._stage_b_candidate_request)
        return request_fields

    def _retain_stage_b_request_from_terminal(self, request_fields: dict) -> None:
        """Mirror firmware candidate lifetime without interpreting its evidence."""
        outcome = self.velocity_sweep.outcome
        cause = int((self.velocity_sweep.terminal or {}).get("cause", 0))
        if outcome == "complete_candidate" or (
            outcome == "inconclusive" and cause == 5
        ):
            self._stage_b_candidate_request = dict(request_fields)
        elif outcome != "rejected_plan_mismatch":
            self._stage_b_candidate_request = None

    def handle_velocity_sweep_plan_limits(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_plan_limits", params)

    def handle_velocity_sweep_plan_geometry(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_plan_geometry", params)

    def handle_velocity_sweep_plan_timing(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_plan_timing", params)

    def handle_velocity_observation_core(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_observation_core", params)

    def handle_velocity_observation_rate(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_observation_rate", params)

    def handle_velocity_observation_stationarity(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_observation_stationarity", params)

    def handle_velocity_observation_disturbance(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_observation_disturbance", params)

    def handle_velocity_rung_consensus_core(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_rung_consensus_core", params)

    def handle_velocity_rung_consensus_component(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_rung_consensus_component", params)

    def handle_velocity_rung_consensus_pool(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_rung_consensus_pool", params)

    def handle_velocity_structured_boundary(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_structured_boundary", params)

    def handle_velocity_directional_region_core(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_directional_region_core", params)

    def handle_velocity_directional_region_model(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_directional_region_model", params)

    def handle_velocity_directional_region_rates(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_directional_region_rates", params)

    def handle_velocity_directional_region_boundary(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_directional_region_boundary", params)

    def handle_velocity_joint_region(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_joint_region", params)

    def handle_velocity_stage_b_handoff_core(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_handoff_core", params)

    def handle_velocity_stage_b_nomination(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_nomination", params)

    def handle_velocity_stage_b_directional_handoff(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_directional_handoff", params)

    def handle_velocity_stage_b_reproduction_v3_core(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_reproduction_v3_core", params)

    def handle_velocity_stage_b_reproduction_v3_membership(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_reproduction_v3_membership", params)

    def handle_velocity_stage_b_reproduction_v3_pooled(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_reproduction_v3_pooled", params)

    def handle_velocity_stage_b_reproduction_v3_common(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_reproduction_v3_common", params)

    def handle_velocity_stage_b_reproduction_v3_coverage(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_reproduction_v3_coverage", params)

    def handle_velocity_stage_b_reproduction_v3_digest(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_reproduction_v3_digest", params)

    def handle_velocity_stage_b_terminal_core(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_terminal_core", params)

    def handle_velocity_stage_b_terminal_identity(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_terminal_identity", params)

    def handle_velocity_stage_b_terminal_interval(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_stage_b_terminal_interval", params)

    def handle_velocity_sweep_terminal_direction(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_terminal_direction", params)

    def handle_velocity_sweep_terminal_integrity(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_terminal_integrity", params)

    def handle_outer_inconclusive(self, params: dict) -> None:
        self._handle_velocity_sweep("handle_outer_inconclusive", params)

    def _format_velocity_sweep_result(self) -> str:
        sweep = self.velocity_sweep
        plan = sweep.plan or {}
        if sweep.terminal is not None:
            valid_regions = [
                region
                for region in sweep.directional_regions
                if region["kind"] == "valid"
            ]
            region_text = []
            for direction, name in ((0, "forward"), (1, "reverse")):
                selected = [
                    region
                    for region in valid_regions
                    if int(region["direction"]) == direction
                    and int(region["member_mask"])
                    == int(sweep.terminal["selected_memberships"][direction])
                ]
                if selected:
                    region = selected[0]
                    region_text.append(
                        "%s mask=0x%08x D_eq=[%d,%d] common=[%d,%d]"
                        % (
                            name,
                            region["member_mask"],
                            region["pooled_low_q16"],
                            region["pooled_high_q16"],
                            region["common_low_q16"],
                            region["common_high_q16"],
                        )
                    )
            message = (
                "stage b %s: nominated_P=%d model_mask=0x%02x "
                "coverage=0x%02x regions=%d/%d fragments=%d/%d cause=%d"
                % (
                    sweep.outcome,
                    sweep.terminal["nominated_p"],
                    sweep.terminal["model_direction_mask"],
                    sweep.terminal["coverage_mask"],
                    sweep.terminal["forward_region_count"],
                    sweep.terminal["reverse_region_count"],
                    sweep.terminal["forward_fragment_count"],
                    sweep.terminal["reverse_fragment_count"],
                    sweep.terminal["cause"],
                )
            )
            if region_text:
                message += "; " + "; ".join(region_text)
            if sweep.remediation:
                message += "; remediation: %s" % sweep.remediation
            return message
        directions = sweep.terminal_directions
        direction_text = []
        for name, report in zip(("forward", "reverse"), directions):
            direction_text.append(
                "%s P=%d..%d D_eq=%d [%d,%d] quality=[%d,%d]"
                % (
                    name,
                    report.get("p_low", 0),
                    report.get("p_high", 0),
                    report.get("pooled_q16", 0),
                    report.get("pooled_low_q16", 0),
                    report.get("pooled_high_q16", 0),
                    report.get("common_low_q16", 0),
                    report.get("common_high_q16", 0),
                )
            )
        message = (
            "velocity sweep %s: requested=%dmrev/s planned=%dmrev/s target=%dRPM "
            "clamp=0x%04x binding=%d runtime=%dms rungs=%d cause=%d; %s"
            % (
                sweep.outcome,
                plan.get("requested_velocity_mrev_s", 0),
                plan.get("planned_velocity_mrev_s", 0),
                plan.get("target_velocity_rpm", 0),
                plan.get("clamp_flags", 0),
                plan.get("binding_source", 0),
                plan.get("maximum_workflow_ms", 0),
                plan.get("rung_count", 0),
                (sweep.integrity or {}).get("cause", 0),
                "; ".join(direction_text),
            )
        )
        if sweep.remediation:
            message += "; remediation: %s" % sweep.remediation
        return message

    def _format_outer_safety_fault(self) -> str:
        fault = self.outer_safety_fault
        if not fault:
            return ""
        reason_code = int(fault.get("reason", 0))
        reason = OUTER_SAFETY_FAULT_NAMES.get(
            reason_code,
            "unknown_%d" % reason_code,
        )
        return (
            "outer safety %s: delta_counts=%d dt_us=%d "
            "velocity_counts_per_ms=%d cap_counts_per_ms=%d "
            "position_counts=%d/%d elapsed_us=%d/%d "
            "budget=%dmrev/%dmrev_s/%dms dir=0x%02x"
            % (
                reason,
                fault.get("delta_counts", 0),
                fault.get("dt_us", 0),
                fault.get("velocity_counts_per_ms", 0),
                fault.get("velocity_cap_counts_per_ms", 0),
                fault.get("position_counts", 0),
                fault.get("position_window_counts", 0),
                fault.get("elapsed_us", 0),
                fault.get("duration_cap_us", 0),
                fault.get("max_travel_mrev", 0),
                fault.get("max_velocity_mrev_s", 0),
                fault.get("max_duration_ms", 0),
                fault.get("direction_mask", 0),
            )
        )

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

            inner_warning_flags = readiness.inner_warning_flags

            self.done = False
            self.result = None
            self.outer_safety_fault = None
            self.velocity_sweep = VelocitySweepAssembler()
            self.velocity_sweep_error = None
            self.driver.commissioning.error_code = 0

            request_fields = self._request_for_stage_b_dispatch(
                {
                    "profile_code": PROFILE_MAP[profile_name],
                    "mode_code": MODE_MAP[mode_name],
                    "inner_lambda": inner_lambda,
                    "theta_e": theta_e,
                    "current_ringing": ringing,
                    "current_bw": bandwidth,
                    "inner_warning_flags": inner_warning_flags,
                    "requested_velocity_mrev_s": (
                        motion_budget.requested_velocity_mrev_s
                    ),
                    "machine_velocity_ceiling_mrev_s": (
                        motion_budget.machine_velocity_ceiling_mrev_s
                    ),
                    "requested_velocity_source": (
                        motion_budget.requested_velocity_source
                    ),
                    "max_stroke_travel_mrev": motion_budget.max_stroke_travel_mrev,
                    "settle_travel_reserve_mrev": (
                        motion_budget.settle_travel_reserve_mrev
                    ),
                    "negative_position_headroom_mrev": (
                        motion_budget.negative_position_headroom_mrev
                    ),
                    "positive_position_headroom_mrev": (
                        motion_budget.positive_position_headroom_mrev
                    ),
                    "max_duration_ms": motion_budget.max_duration_ms,
                }
            )
            self.driver.protocol.run_tune(**request_fields)

            reactor = self.driver.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + VELOCITY_SWEEP_PLAN_TIMEOUT_S
            plan_timeout_armed = False
            while not self.done and not self.velocity_sweep.done:
                eventtime = reactor.pause(eventtime + 0.1)
                if self.velocity_sweep_error is not None:
                    raise gcmd.error(
                        "FOCI %s: velocity sweep transport failure: %s"
                        % (self.driver.name, self.velocity_sweep_error)
                    )
                if self.velocity_sweep.plan_ready and not plan_timeout_armed:
                    timeout = (
                        eventtime
                        + self.velocity_sweep.maximum_duration_s
                        + VELOCITY_SWEEP_COMMS_MARGIN_S
                    )
                    plan_timeout_armed = True
                if eventtime > timeout:
                    phase = "run" if plan_timeout_armed else "waiting for plan"
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE timed out %s"
                        % (self.driver.name, phase)
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

            if self.velocity_sweep.done:
                self._retain_stage_b_request_from_terminal(request_fields)
                gcmd.respond_info(
                    "FOCI %s: %s"
                    % (self.driver.name, self._format_velocity_sweep_result())
                )
                if self.velocity_sweep.outcome == "fault":
                    safety_detail = self._format_outer_safety_fault()
                    detail_suffix = "; %s" % safety_detail if safety_detail else ""
                    raise gcmd.error(
                        "FOCI %s: velocity sweep fault (cause=%d)%s"
                        % (
                            self.driver.name,
                            self.velocity_sweep.integrity.get("cause", 0),
                            detail_suffix,
                        )
                    )
                return

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
                    safety_detail = self._format_outer_safety_fault()
                    detail_suffix = "; %s" % safety_detail if safety_detail else ""
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE safety fault: %s%s "
                        "(motor disabled by firmware)"
                        % (self.driver.name, error_name, detail_suffix)
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
