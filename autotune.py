"""Stage 2 autotune workflow for FOCI host commands."""

from __future__ import annotations

import logging

from .acceptance_matrix import (
    AcceptanceMatrixAssembler,
    AcceptanceMatrixProtocolError,
    parse_autotune_action,
)
from .autotune_budget import (
    AutotuneBudgetError,
    compute_autotune_motion_budget,
    format_safe_pose_move,
)
from .commissioning import (
    COMMISSION_ERROR_NAMES,
    HARD_FAULT_CODES,
    PROFILE_MAP,
    format_inner_warning_flags,
)
from .readiness import POLICY_UNAVAILABLE, resolve_autotune_readiness
from .robustness_reversal import (
    ROBUSTNESS_CAUSE_NAMES,
    RobustnessReversalProtocolError,
)
from .robustness_reversal import handle_cycle_evidence as parse_robustness_cycle_evidence
from .robustness_reversal import handle_terminal as parse_robustness_reversal_terminal
from .velocity_integral import (
    BREAKAWAY_PHASE_NAMES,
    BREAKAWAY_TERMINAL_CAUSE_NAMES,
    BREAKAWAY_TERMINAL_REMEDIATION,
    FLOOR_ORIGIN_NAMES,
    STAGE_C_TERMINAL_CAUSE_NAMES,
    STAGE_C_TERMINAL_CAUSE_REMEDIATION,
    BreakawayCampaignAssembler,
    BreakawayCampaignProtocolError,
    VelocityIntegralAssembler,
    VelocityIntegralProtocolError,
)

MODE_MAP: dict[str, int] = {
    "unloaded": 0,
    "nominal": 1,
    "high_inertia": 2,
}

IDLE_PRINT_STATES = frozenset(("standby", "complete", "cancelled"))
COMMISSIONING_WORKFLOW_PLAN_TIMEOUT_S = 5.0
COMMISSIONING_WORKFLOW_COMMS_MARGIN_S = 5.0

OUTER_SAFETY_FAULT_NAMES = {
    0: "none",
    1: "invalid_budget",
    2: "unusable_budget",
    3: "duration",
    4: "velocity",
    5: "position",
    6: "post_switch_settle",
    7: "observation_gap",
    8: "quarter_turn",
    9: "current",
    10: "recovery_wrong_way",
    11: "position_local",
}


def _stage_c_cause_text(cause: int) -> str:
    """Render a Stage-C terminal cause as its number and dispatch name.

    The number stays because `cause` shares its numeric range with the engine's
    own causes and with `CommissionError` status codes, so the name only
    identifies the value when the dispatch namespace is the producer.
    """
    name = STAGE_C_TERMINAL_CAUSE_NAMES.get(cause)
    return str(cause) if name is None else f"{cause} ({name})"


def _robustness_reversal_cause_text(cause: int) -> str:
    """Render a robustness-reversal terminal cause as its number and name."""
    name = ROBUSTNESS_CAUSE_NAMES.get(cause)
    return str(cause) if name is None else f"{cause} ({name})"


def _robustness_direction_text(index: int, direction: dict) -> str:
    """Render one robustness-reversal direction summary.

    A `valid_cycles == 0` direction (the fault/early-abort paths still
    produce these) must render as "not measured", never as zero-millisecond
    medians -- firmware never wrote those fields for an unmeasured direction.
    """
    valid_cycles = int(direction.get("valid_cycles", 0))
    trip_count = int(direction.get("trip_count", 0))
    retry_count = int(direction.get("retry_count", 0))
    inconclusive = bool(direction.get("inconclusive", False))
    if valid_cycles == 0:
        return (
            f"dir{index}: not measured (trip_count={trip_count} retries={retry_count} "
            f"inconclusive={inconclusive})"
        )
    return (
        f"dir{index}: median_reconvergence={int(direction.get('median_reconvergence_ms', 0))}ms "
        f"max_reconvergence={int(direction.get('max_reconvergence_ms', 0))}ms "
        f"median_forward_settle={int(direction.get('median_forward_settle_ms', 0))}ms "
        f"overshoot_peak={int(direction.get('overshoot_peak_counts', 0))}counts "
        f"valid_cycles={valid_cycles} trip_count={trip_count} retries={retry_count} "
        f"inconclusive={inconclusive}"
    )


class AutotuneWorkflow:
    """Run installed Stage 2 tuning after commissioning and homing."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.result: dict | None = None
        self.outer_safety_fault: dict | None = None
        self.velocity_integral = VelocityIntegralAssembler()
        self.velocity_integral_error: VelocityIntegralProtocolError | None = None
        self.acceptance_matrix = AcceptanceMatrixAssembler()
        self.acceptance_matrix_error: AcceptanceMatrixProtocolError | None = None
        self.breakaway_campaign = BreakawayCampaignAssembler()
        self.breakaway_campaign_error: BreakawayCampaignProtocolError | None = None
        self.robustness_reversal_terminal: dict | None = None
        self.robustness_reversal_error: RobustnessReversalProtocolError | None = None
        self.robustness_cycle_evidence: dict[int, dict] = {}
        self.robustness_workflow_plan: dict | None = None
        self._stage_b_candidate_request: dict | None = None
        self.done = False

    def handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware."""
        self.result = params
        self.done = True

    def handle_outer_safety_fault(self, params: dict) -> None:
        """Handle foci_outer_safety_fault from firmware."""
        self.outer_safety_fault = dict(params)

    def _handle_velocity_integral(self, method_name: str, params: dict) -> None:
        if self.velocity_integral_error is not None:
            return
        workflow = self.velocity_integral.workflow_plan
        if (
            method_name == "handle_plan_core"
            and workflow is not None
            and int(workflow["shape"]) == 6
            and not (self.breakaway_campaign.done and self.breakaway_campaign.accepted)
        ):
            self.velocity_integral_error = VelocityIntegralProtocolError(
                "breakaway Stage-C plan arrived before an accepted campaign terminal"
            )
            return
        try:
            getattr(self.velocity_integral, method_name)(params)
        except VelocityIntegralProtocolError as err:
            self.velocity_integral_error = err
            return
        # Once the breakaway Stage-C plan is fully assembled, cross-check its
        # exact digest against the digest the campaign terminal already
        # disclosed at acceptance time. This is a firmware-identity check --
        # confirming two things firmware itself sent agree -- not a
        # recomputation of either value.
        if (
            method_name == "handle_plan_rung"
            and workflow is not None
            and int(workflow["shape"]) == 6
            and self.velocity_integral.plan is not None
            and int(self.velocity_integral.plan["plan_digest"])
            != self.breakaway_campaign.stage_c_plan_digest
        ):
            self.velocity_integral_error = VelocityIntegralProtocolError(
                "breakaway Stage-C plan digest does not match the accepted campaign terminal"
            )

    def _handle_breakaway_campaign(self, method_name: str, params: dict) -> None:
        if self.breakaway_campaign_error is not None:
            return
        workflow = self.velocity_integral.workflow_plan
        if workflow is None or int(workflow["shape"]) != 6:
            self.breakaway_campaign_error = BreakawayCampaignProtocolError(
                "breakaway campaign evidence arrived without a breakaway workflow plan"
            )
            return
        try:
            getattr(self.breakaway_campaign, method_name)(params)
        except BreakawayCampaignProtocolError as err:
            self.breakaway_campaign_error = err

    def _handle_recovery_summary(self, params: dict) -> None:
        stage = int(params.get("stage", -1))
        if stage != 1:
            self.velocity_integral_error = VelocityIntegralProtocolError(
                "recovery summary named an invalid stage"
            )
            return
        if self.velocity_integral_error is not None:
            return
        try:
            self.velocity_integral.handle_recovery_summary(params)
        except VelocityIntegralProtocolError as err:
            self.velocity_integral_error = err

    def handle_commissioning_workflow_plan(self, params: dict) -> None:
        shape = int(params.get("shape", -1))
        if shape in (4, 5):
            try:
                self.acceptance_matrix.handle_workflow_plan(params)
            except AcceptanceMatrixProtocolError as err:
                self.acceptance_matrix_error = err
            return
        if shape == 7:
            # Robustness reversal: record the run's worst-case duration so the
            # wait loop arms its extended timeout. It does not feed the
            # acceptance-matrix or velocity-integral assemblers.
            self.robustness_workflow_plan = params
            return
        self._handle_velocity_integral("handle_workflow_plan", params)

    def handle_acceptance_matrix_plan(self, params: dict) -> None:
        """Relay one compact firmware-authored matrix plan."""
        if self.acceptance_matrix_error is not None:
            return
        try:
            self.acceptance_matrix.handle_plan(params)
        except AcceptanceMatrixProtocolError as err:
            self.acceptance_matrix_error = err

    def handle_acceptance_matrix_terminal(self, params: dict) -> None:
        """Relay one compact firmware-authored matrix terminal."""
        if self.acceptance_matrix_error is not None:
            return
        try:
            self.acceptance_matrix.handle_terminal(params)
        except AcceptanceMatrixProtocolError as err:
            self.acceptance_matrix_error = err

    def handle_robustness_reversal_terminal(self, params: dict) -> None:
        """Parse one compact firmware-authored robustness-reversal terminal."""
        if self.robustness_reversal_error is not None:
            return
        if self.robustness_reversal_terminal is not None:
            self.robustness_reversal_error = RobustnessReversalProtocolError(
                "duplicate robustness reversal terminal"
            )
            return
        try:
            self.robustness_reversal_terminal = parse_robustness_reversal_terminal(params)
        except RobustnessReversalProtocolError as err:
            self.robustness_reversal_error = err

    def handle_robustness_cycle_evidence(self, params: dict) -> None:
        """Parse one compact firmware-authored robustness per-cycle evidence reply."""
        if self.robustness_reversal_error is not None:
            return
        try:
            evidence = parse_robustness_cycle_evidence(params)
        except RobustnessReversalProtocolError as err:
            self.robustness_reversal_error = err
            return
        self.robustness_cycle_evidence[evidence["direction"]] = evidence

    def handle_breakaway_probe_plan(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_probe_plan", params)

    def handle_breakaway_probe_result(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_probe_result", params)

    def handle_breakaway_probe_terminal(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_probe_terminal", params)

    def handle_breakaway_discovery_plan_identity(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_discovery_plan_identity", params)

    def handle_breakaway_discovery_plan_geometry(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_discovery_plan_geometry", params)

    def handle_breakaway_discovery_ceiling_source(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_discovery_ceiling_source", params)

    def handle_breakaway_discovery_rung_zero_diagnostic(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_discovery_rung_zero_diagnostic", params)

    def handle_breakaway_discovery_terminal(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_discovery_terminal", params)

    def handle_breakaway_confirmation_plan(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_confirmation_plan", params)

    def handle_breakaway_confirmation_terminal_identity(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_confirmation_terminal_identity", params)

    def handle_breakaway_confirmation_terminal_masks(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_confirmation_terminal_masks", params)

    def handle_breakaway_campaign_terminal(self, params: dict) -> None:
        self._handle_breakaway_campaign("handle_campaign_terminal", params)

    def _request_for_stage_b_dispatch(self, request_fields: dict) -> dict:
        """Reuse the exact retained encoding when the explicit request matches."""
        if (
            self._stage_b_candidate_request is not None
            and request_fields == self._stage_b_candidate_request
        ):
            return dict(self._stage_b_candidate_request)
        return request_fields

    def _retain_request_from_terminal(self, request_fields: dict) -> None:
        """Mirror firmware's retained authority/evidence request identity."""
        if not self.velocity_integral.done:
            return
        outcome = self.velocity_integral.outcome
        if outcome in ("complete_candidate", "inconclusive"):
            self._stage_b_candidate_request = dict(request_fields)
        elif outcome != "rejected_plan_mismatch":
            self._stage_b_candidate_request = None

    def _workflow_finished(self) -> bool:
        """Whether the disclosed firmware workflow reached its terminal stage."""
        if self.robustness_reversal_terminal is not None:
            return True
        if self.acceptance_matrix.done:
            return True
        workflow = self.velocity_integral.workflow_plan
        if workflow is None:
            # Only a refusal can complete without an envelope: the exact-plan
            # path refuses to assemble until a Stage-C workflow has arrived. Its
            # terminal is still terminal, and nothing else will follow it.
            return self.velocity_integral.done
        shape = int(workflow["shape"])
        if shape == 6:
            # The breakaway campaign's own campaign terminal is the only
            # phase-independent completion signal. A non-accept terminal ends
            # the workflow immediately; an accepted one only finishes once the
            # handed-off classic Stage-C evidence completes.
            if not self.breakaway_campaign.done:
                return False
            if not self.breakaway_campaign.accepted:
                return True
            return self.velocity_integral.done
        # Stage-C resume (shape 2) and any other enveloped workflow complete on
        # the integral-response terminal.
        return self.velocity_integral.done

    def _synchronize_disarmed_workflow_terminal(self, toolhead) -> None:
        """Mirror a firmware-owned terminal disarm into Klipper state."""
        self.driver.state.is_calibrated = False
        stepper_enable = self.driver.printer.lookup_object("stepper_enable")
        enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
        enable_line.motor_disable(toolhead.get_last_move_time())

    def _format_acceptance_matrix_result(self) -> str:
        terminal = self.acceptance_matrix.terminal or {}
        return (
            f"velocity confidence matrix: {terminal.get('outcome_name', 'unknown')} (namespace="
            f"{terminal.get('outcome_namespace', 'acceptance_matrix')} cause="
            f"{terminal.get('cause_name', 'unknown')} attempted="
            f"{terminal.get('attempted_masks', (0, 0))} eligible="
            f"{terminal.get('eligible_masks', (0, 0))})"
        )

    def _format_robustness_reversal_result(self) -> str:
        terminal = self.robustness_reversal_terminal or {}
        directions = terminal.get("directions") or ({}, {})
        parts = []
        for index, direction in enumerate(directions):
            text = _robustness_direction_text(index, direction)
            evidence = self.robustness_cycle_evidence.get(index)
            if evidence is not None:
                text += (
                    f" iae_median_qs={int(evidence.get('iae_median_qs', 0))}"
                    f" residual_median_q={int(evidence.get('residual_median_q', 0))}"
                )
            parts.append(text)
        direction_text = "; ".join(parts)
        return (
            f"robustness reversal: {terminal.get('outcome_name', 'unknown')} (namespace="
            f"{terminal.get('outcome_namespace', 'robustness_reversal')} cause="
            f"{_robustness_reversal_cause_text(int(terminal.get('cause', 0)))} selected_p="
            f"{int(terminal.get('selected_p', 0))} selected_i="
            f"{int(terminal.get('selected_i', 0))} target_velocity_rpm="
            f"{int(terminal.get('target_velocity_rpm', 0))} plant_rate_q="
            f"{int(terminal.get('plant_rate_q', 0))} iae_max_q_qs="
            f"{int(terminal.get('iae_max_q_qs', 0))}); {direction_text}"
        )

    def handle_rung_origin_recovery_summary(self, params: dict) -> None:
        self._handle_recovery_summary(params)

    def handle_velocity_integral_plan_core(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_core", params)

    def handle_velocity_integral_plan_geometry(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_geometry", params)

    def handle_velocity_integral_plan_authority(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_authority", params)

    def handle_velocity_integral_plan_timing(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_timing", params)

    def handle_velocity_integral_plan_travel(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_travel", params)

    def handle_velocity_integral_plan_recovery(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_recovery", params)

    def handle_velocity_integral_plan_rung(self, params: dict) -> None:
        self._handle_velocity_integral("handle_plan_rung", params)

    def handle_velocity_integral_observation_core(self, params: dict) -> None:
        self._handle_velocity_integral("handle_observation_core", params)

    def handle_velocity_integral_observation_rate(self, params: dict) -> None:
        self._handle_velocity_integral("handle_observation_rate", params)

    def handle_velocity_integral_observation_quality(self, params: dict) -> None:
        self._handle_velocity_integral("handle_observation_quality", params)

    def handle_velocity_integral_rung_core(self, params: dict) -> None:
        self._handle_velocity_integral("handle_rung_core", params)

    def handle_velocity_integral_rung_component(self, params: dict) -> None:
        self._handle_velocity_integral("handle_rung_component", params)

    def handle_velocity_integral_run_summary(self, params: dict) -> None:
        self._handle_velocity_integral("handle_run_summary", params)

    def handle_velocity_integral_curve_interval(self, params: dict) -> None:
        self._handle_velocity_integral("handle_curve_interval", params)

    def handle_velocity_integral_drift(self, params: dict) -> None:
        self._handle_velocity_integral("handle_drift", params)

    def handle_velocity_integral_stage_b_comparison(self, params: dict) -> None:
        self._handle_velocity_integral("handle_stage_b_comparison", params)

    def handle_velocity_integral_reproduction_core(self, params: dict) -> None:
        self._handle_velocity_integral("handle_reproduction_core", params)

    def handle_velocity_integral_reproduction_mask(self, params: dict) -> None:
        self._handle_velocity_integral("handle_reproduction_mask", params)

    def handle_velocity_integral_reproduction_interval(self, params: dict) -> None:
        self._handle_velocity_integral("handle_reproduction_interval", params)

    def handle_velocity_integral_reproduction_digest(self, params: dict) -> None:
        self._handle_velocity_integral("handle_reproduction_digest", params)

    def handle_velocity_integral_terminal_core(self, params: dict) -> None:
        self._handle_velocity_integral("handle_terminal_core", params)

    def handle_velocity_integral_terminal_identity(self, params: dict) -> None:
        self._handle_velocity_integral("handle_terminal_identity", params)

    def handle_velocity_integral_terminal_timing(self, params: dict) -> None:
        self._handle_velocity_integral("handle_terminal_timing", params)

    def _format_velocity_integral_result(self) -> str:
        response = self.velocity_integral
        plan = response.plan or {}
        summary = response.summary or {}
        terminal = response.terminal or {}
        message = (
            f"velocity integral response {terminal.get('outcome_name', response.outcome)}: P="
            f"{int(plan.get('final_p', 0))} velocity={int(plan.get('planned_velocity_mrev_s', 0))}"
            f"mrev/s positive_rungs={int(plan.get('positive_rung_count', 0))} eligible=0x"
            f"{summary.get('forward_eligible_mask', 0):08x}/0x"
            f"{summary.get('reverse_eligible_mask', 0):08x} bookend=0x"
            f"{summary.get('bookend_available_mask', 0):02x} current_terminus="
            f"{int(summary.get('current_terminus_plus_one', 0))} namespace="
            f"{terminal.get('outcome_namespace', 'stage_c')} cause="
            f"{_stage_c_cause_text(int(terminal.get('cause', 0)))}"
        )
        remediation = STAGE_C_TERMINAL_CAUSE_REMEDIATION.get(int(terminal.get("cause", 0)))
        if remediation is not None:
            message = f"{message}; {remediation}"
        if response.reproduction is not None:
            masks = response.reproduction.get("masks", {})
            mask_text = []
            for direction, name in ((0, "forward"), (1, "reverse")):
                values = masks.get(direction, {})
                mask_text.append(
                    f"{name} reproduced=0x{values.get('reproduced_mask', 0):08x} divergent=0x"
                    f"{values.get('divergent_mask', 0):08x}"
                )
            message += "; " + "; ".join(mask_text)
        return message

    def _breakaway_campaign_has_safety_fault(self) -> bool:
        campaign = self.breakaway_campaign
        return bool(
            int((campaign.probe_terminal or {}).get("has_safety_fault", 0))
            or int((campaign.discovery_terminal or {}).get("has_safety_fault", 0))
            or int((campaign.confirmation_terminal or {}).get("has_safety_fault", 0))
        )

    def _format_breakaway_campaign_result(self) -> str:
        """Relay the firmware-authored breakaway campaign report verbatim.

        Every value here is copied straight out of BreakawayCampaignAssembler
        -- the resolved breakaway gain, additive-ladder geometry, the
        nomination margin, confirmation bounds, and terminal cause -- with no
        recomputation. The host does not choose or restate a rung, gain, or
        verdict; it only names the wire codes firmware already sent.
        """
        campaign = self.breakaway_campaign
        terminal = campaign.campaign_terminal or {}
        cause = int(terminal.get("terminal_cause", 0))
        cause_name = BREAKAWAY_TERMINAL_CAUSE_NAMES.get(cause, f"unknown_{int(cause)}")
        phase_name = BREAKAWAY_PHASE_NAMES.get(int(terminal.get("phase", -1)), "unknown")
        message = (
            f"breakaway campaign {'accepted' if campaign.accepted else 'not accepted'} (phase="
            f"{phase_name} cause={cause_name})"
        )
        probe_result = campaign.probe_result
        if probe_result is not None:
            message += (
                f"; breakaway={int(probe_result['breakaway_p_raw'])} rung="
                f"{int(probe_result['rung_index'])} obs={int(probe_result['observation_count'])}"
            )
        discovery = campaign.discovery_plan
        if discovery is not None:
            message += (
                f"; ladder floor={int(discovery.get('floor_p_raw', 0))}("
                f"{FLOOR_ORIGIN_NAMES.get(int(discovery.get('floor_origin', -1)), '?')}) breakaway="
                f"{int(discovery.get('breakaway_p_raw', 0))} ceiling="
                f"{int(discovery.get('ceiling_p_raw', 0))} step="
                f"{int(discovery.get('first_additive_step_raw', 0))} rungs="
                f"{int(discovery.get('rung_count', 0))}"
            )
        confirmation = campaign.confirmation_plan
        if confirmation is not None:
            message += (
                f"; nominated P={int(confirmation.get('candidate_p_raw', 0))} margin="
                f"{int(confirmation.get('nominated_margin_percent_milli', 0))}pm"
            )
        confirmation_terminal = campaign.confirmation_terminal
        if confirmation_terminal is not None:
            message += (
                f"; confirmed P={int(confirmation_terminal.get('confirmed_p_raw', 0))} measured_SE="
                f"{int(confirmation_terminal.get('max_relative_se_permille', 0))}pm required_SE="
                f"{int(confirmation_terminal.get('required_relative_se_permille', 0))}pm"
            )
        remediation = BREAKAWAY_TERMINAL_REMEDIATION.get(cause)
        if remediation:
            message += f"; remediation: {remediation}"
        return message

    def _format_outer_safety_fault(self) -> str:
        fault = self.outer_safety_fault
        if not fault:
            return ""
        reason_code = int(fault.get("reason", 0))
        reason = OUTER_SAFETY_FAULT_NAMES.get(reason_code)
        if reason is None:
            logging.warning(
                "FOCI: unmapped OUTER_SAFETY_FAULT_ code %d -- "
                "OUTER_SAFETY_FAULT_NAMES is out of sync with firmware",
                reason_code,
            )
            reason = f"unknown_{reason_code}"
        # The velocity check evaluates a sliding two-interval window and reports
        # that window's summed counts and elapsed time; every other reason
        # evaluates a single observation. Label them apart so a window total is
        # not read as one long observation.
        windowed = reason == "velocity"
        delta_label = "window_delta_counts" if windowed else "delta_counts"
        dt_label = "window_dt_us" if windowed else "dt_us"
        return (
            f"outer safety {reason}: {delta_label}={int(fault.get('delta_counts', 0))} {dt_label}="
            f"{int(fault.get('dt_us', 0))} velocity_counts_per_ms="
            f"{int(fault.get('velocity_counts_per_ms', 0))} cap_counts_per_ms="
            f"{int(fault.get('velocity_cap_counts_per_ms', 0))} position_counts="
            f"{int(fault.get('position_counts', 0))}/{int(fault.get('position_window_counts', 0))} "
            f"elapsed_us={int(fault.get('elapsed_us', 0))}/{int(fault.get('duration_cap_us', 0))} "
            f"budget={int(fault.get('max_travel_mrev', 0))}mrev/"
            f"{int(fault.get('max_velocity_mrev_s', 0))}mrev_s/"
            f"{int(fault.get('max_duration_ms', 0))}ms dir=0x{fault.get('direction_mask', 0):02x}"
        )

    def _ensure_printer_idle(self, gcmd, toolhead) -> None:
        print_stats = self.driver.printer.lookup_object("print_stats", None)
        if print_stats is None:
            raise gcmd.error(f"FOCI {self.driver.name}: printer idle state unavailable")
        status = print_stats.get_status(toolhead.get_last_move_time())
        state = str(status.get("state", "")).lower()
        if state not in IDLE_PRINT_STATES:
            raise gcmd.error(
                f"FOCI {self.driver.name}: printer is not idle (print_stats state="
                f"{state or 'unknown'})"
            )

    def autotune(self, gcmd) -> None:
        """Stage 2: installed tuning after commissioning and homing."""
        try:
            action = parse_autotune_action(gcmd.get("ACTION", None))
        except AcceptanceMatrixProtocolError as err:
            raise gcmd.error(f"FOCI {self.driver.name}: {err}") from err
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        mode_name = gcmd.get("MODE", "nominal").lower()
        if profile_name not in PROFILE_MAP:
            raise gcmd.error(
                f"FOCI {self.driver.name}: unknown profile '{profile_name}' (expected: "
                f"{', '.join(sorted(PROFILE_MAP))})"
            )
        if mode_name not in MODE_MAP:
            raise gcmd.error(
                f"FOCI {self.driver.name}: unknown mode '{mode_name}' (expected: "
                f"{', '.join(sorted(MODE_MAP))})"
            )

        if not self.driver.state.try_acquire():
            raise gcmd.error(f"FOCI {self.driver.name}: another FOCI operation is in progress")

        try:
            if self.driver.state.inhibited:
                raise gcmd.error(f"FOCI {self.driver.name}: inhibited after failed FOCI_COMMISSION")
            if self.driver.state.runtime_status == "uncommissioned":
                raise gcmd.error(
                    f"FOCI {self.driver.name}: not commissioned. Run FOCI_COMMISSION first."
                )
            if not self.driver.state.is_calibrated:
                raise gcmd.error(
                    f"FOCI {self.driver.name}: not calibrated. Enable motor, re-home, then retry."
                )

            toolhead = self.driver.printer.lookup_object("toolhead")
            self._ensure_printer_idle(gcmd, toolhead)
            try:
                motion_budget = compute_autotune_motion_budget(self.driver, gcmd)
            except AutotuneBudgetError as err:
                raise gcmd.error(f"FOCI {self.driver.name}: {err}") from err

            toolhead.wait_moves()
            self._ensure_printer_idle(gcmd, toolhead)

            if not self.driver.state.is_calibrated:
                raise gcmd.error(f"FOCI {self.driver.name}: calibration lost during wait")
            kin_status = toolhead.get_status(toolhead.get_last_move_time())
            if not {"x", "y"}.issubset(set(kin_status.get("homed_axes", ""))):
                raise gcmd.error(f"FOCI {self.driver.name}: homing lost during wait")

            live_current_gains = self.driver.dump.read_live_current_gains()
            readiness = resolve_autotune_readiness(
                self.driver,
                live_current_gains=live_current_gains,
            )
            if readiness.blocked:
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_AUTOTUNE blocked: "
                    f"{'; '.join(readiness.blockers)}"
                )
            if readiness.stage2_policy == POLICY_UNAVAILABLE:
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_AUTOTUNE stage 2 unavailable inputs: "
                    f"{', '.join(readiness.unavailable_inputs)}"
                )

            if readiness.warnings:
                gcmd.respond_info(
                    f"FOCI {self.driver.name} autotune readiness warnings: "
                    f"{'; '.join(readiness.warnings)}"
                )
            if readiness.unavailable_inputs:
                gcmd.respond_info(
                    f"FOCI {self.driver.name} autotune unavailable inputs: "
                    f"{', '.join(readiness.unavailable_inputs)}"
                )

            gcode = self.driver.printer.lookup_object("gcode")
            gcode.run_script_from_command(format_safe_pose_move(motion_budget))
            toolhead.wait_moves()
            if not self.driver.state.is_calibrated:
                raise gcmd.error(f"FOCI {self.driver.name}: calibration lost during safe-pose move")
            kin_status = toolhead.get_status(toolhead.get_last_move_time())
            if not {"x", "y"}.issubset(set(kin_status.get("homed_axes", ""))):
                raise gcmd.error(f"FOCI {self.driver.name}: homing lost during safe-pose move")

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
            self.velocity_integral = VelocityIntegralAssembler()
            self.velocity_integral_error = None
            self.acceptance_matrix = AcceptanceMatrixAssembler()
            self.acceptance_matrix_error = None
            self.breakaway_campaign = BreakawayCampaignAssembler()
            self.breakaway_campaign_error = None
            self.robustness_reversal_terminal = None
            self.robustness_reversal_error = None
            self.robustness_cycle_evidence = {}
            self.robustness_workflow_plan = None
            self.driver.commissioning.error_code = 0

            request_fields = self._request_for_stage_b_dispatch(
                {
                    "action": action,
                    "profile_code": PROFILE_MAP[profile_name],
                    "mode_code": MODE_MAP[mode_name],
                    "inner_lambda": inner_lambda,
                    "theta_e": theta_e,
                    "current_ringing": ringing,
                    "current_bw": bandwidth,
                    "inner_warning_flags": inner_warning_flags,
                    "requested_velocity_mrev_s": (motion_budget.requested_velocity_mrev_s),
                    "machine_velocity_ceiling_mrev_s": (
                        motion_budget.machine_velocity_ceiling_mrev_s
                    ),
                    "requested_velocity_source": (motion_budget.requested_velocity_source),
                    "max_stroke_travel_mrev": motion_budget.max_stroke_travel_mrev,
                    "settle_travel_reserve_mrev": (motion_budget.settle_travel_reserve_mrev),
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
            timeout = eventtime + COMMISSIONING_WORKFLOW_PLAN_TIMEOUT_S
            workflow_timeout_armed = False
            while not self.done and not self._workflow_finished():
                eventtime = reactor.pause(eventtime + 0.1)
                if self.velocity_integral_error is not None:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: velocity integral transport failure: "
                        f"{self.velocity_integral_error}"
                    )
                if self.acceptance_matrix_error is not None:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: velocity confidence transport failure: "
                        f"{self.acceptance_matrix_error}"
                    )
                if self.breakaway_campaign_error is not None:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: breakaway campaign transport failure: "
                        f"{self.breakaway_campaign_error}"
                    )
                if self.robustness_reversal_error is not None:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: robustness reversal transport failure: "
                        f"{self.robustness_reversal_error}"
                    )
                if (
                    self.velocity_integral.workflow_plan is not None
                    or self.acceptance_matrix.workflow_plan is not None
                    or self.robustness_workflow_plan is not None
                ) and not workflow_timeout_armed:
                    if self.robustness_workflow_plan is not None:
                        maximum_duration_s = (
                            int(self.robustness_workflow_plan["maximum_workflow_ms"]) / 1000.0
                        )
                    elif self.acceptance_matrix.workflow_plan is not None:
                        maximum_duration_s = self.acceptance_matrix.maximum_duration_s
                    else:
                        maximum_duration_s = self.velocity_integral.maximum_duration_s
                    timeout = eventtime + maximum_duration_s + COMMISSIONING_WORKFLOW_COMMS_MARGIN_S
                    workflow_timeout_armed = True
                if eventtime > timeout:
                    phase = "run" if workflow_timeout_armed else "waiting for plan"
                    raise gcmd.error(f"FOCI {self.driver.name}: FOCI_AUTOTUNE timed out {phase}")
                if self.driver.commissioning.error_code != 0:
                    error_name = COMMISSION_ERROR_NAMES.get(
                        self.driver.commissioning.error_code,
                        f"UNKNOWN({int(self.driver.commissioning.error_code)})",
                    )
                    self.driver.commissioning.maybe_clear_calibration_for_chip_reset(
                        self.driver.commissioning.error_code
                    )
                    raise gcmd.error(f"FOCI {self.driver.name}: FOCI_AUTOTUNE failed: {error_name}")

            if self._workflow_finished():
                self._synchronize_disarmed_workflow_terminal(toolhead)
                if self.acceptance_matrix.done:
                    gcmd.respond_info(
                        f"FOCI {self.driver.name}: {self._format_acceptance_matrix_result()}"
                    )
                    if self.acceptance_matrix.outcome in ("fault", "failed"):
                        raise gcmd.error(
                            f"FOCI {self.driver.name}: velocity confidence matrix "
                            f"{self.acceptance_matrix.outcome}"
                        )
                    return
                if self.robustness_reversal_terminal is not None:
                    safety_detail = self._format_outer_safety_fault()
                    detail_suffix = f"; {safety_detail}" if safety_detail else ""
                    gcmd.respond_info(
                        f"FOCI {self.driver.name}: "
                        f"{self._format_robustness_reversal_result()}{detail_suffix}"
                    )
                    self._handle_robustness_verdict(gcmd)
                    return
                if self.breakaway_campaign.done:
                    gcmd.respond_info(
                        f"FOCI {self.driver.name}: {self._format_breakaway_campaign_result()}"
                    )
                    if self._breakaway_campaign_has_safety_fault():
                        safety_detail = self._format_outer_safety_fault()
                        detail_suffix = f"; {safety_detail}" if safety_detail else ""
                        raise gcmd.error(
                            f"FOCI {self.driver.name}: breakaway campaign safety fault"
                            f"{detail_suffix}"
                        )
                    if not self.breakaway_campaign.accepted:
                        # No previously commissioned P is touched here: this
                        # branch never reaches persist_tune_results or the
                        # active_gains assignment below.
                        return
                    if self.velocity_integral.done:
                        gcmd.respond_info(
                            f"FOCI {self.driver.name}: {self._format_velocity_integral_result()}"
                        )
                        if self.velocity_integral.outcome == "fault":
                            safety_detail = self._format_outer_safety_fault()
                            detail_suffix = f"; {safety_detail}" if safety_detail else ""
                            raise gcmd.error(
                                f"FOCI {self.driver.name}: velocity integral response fault "
                                f"(cause={int(self.velocity_integral.terminal.get('cause', 0))}"
                                f"){detail_suffix}"
                            )
                    return
                self._retain_request_from_terminal(request_fields)
                if self.velocity_integral.done:
                    gcmd.respond_info(
                        f"FOCI {self.driver.name}: {self._format_velocity_integral_result()}"
                    )
                    if self.velocity_integral.outcome == "fault":
                        safety_detail = self._format_outer_safety_fault()
                        detail_suffix = f"; {safety_detail}" if safety_detail else ""
                        raise gcmd.error(
                            f"FOCI {self.driver.name}: velocity integral response fault (cause="
                            f"{int(self.velocity_integral.terminal.get('cause', 0))})"
                            f"{detail_suffix}"
                        )
                return

            result = self.result
            status = result.get("status", 255)
            if status > 1:
                error_name = COMMISSION_ERROR_NAMES.get(status, f"UNKNOWN({int(status)})")
                if status == 18:
                    self.driver.commissioning.handle_chip_reset_detected()
                    stepper_enable = self.driver.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_AUTOTUNE chip reset: {error_name} "
                        f"(motor disabled by firmware)"
                    )
                if status in HARD_FAULT_CODES:
                    self.driver.commissioning.on_commission_failure()
                    stepper_enable = self.driver.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.driver.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    safety_detail = self._format_outer_safety_fault()
                    detail_suffix = f"; {safety_detail}" if safety_detail else ""
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_AUTOTUNE safety fault: {error_name}"
                        f"{detail_suffix} (motor disabled by firmware)"
                    )
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_AUTOTUNE failed: {error_name} (motor "
                    f"holding with entry gains)"
                )

            warning_code = result.get("warning_code", 0)
            if status == 1 or warning_code != 0:
                tune_status = "tuned_conservative"
            else:
                tune_status = "tuned"

            self.driver.state.pre_tune_snapshot = self._snapshot_pre_tune_state()
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
                f"FOCI {self.driver.name} tuned ({tune_status}): vel_p="
                f"{int(result['velocity_p'])} pos_p={int(result['position_p'])}"
            )
            if "stiffness_timebase_ms" in result:
                gcmd.respond_info(
                    f"FOCI {self.driver.name} autotune evidence: budget="
                    f"{int(result.get('motion_budget_mrev', 0))}mrev stiffness_timebase="
                    f"{int(result.get('stiffness_timebase_ms', 0))}ms search_stop="
                    f"{int(result.get('velocity_search_stop_reason', 0))} flags=0x"
                    f"{result.get('outer_evidence_flags', 0):02x}"
                )
            if inner_warning_flags:
                gcmd.respond_info(
                    f"FOCI {self.driver.name} inner confidence: "
                    f"{format_inner_warning_flags(inner_warning_flags)}"
                )
        finally:
            self.driver.state.release()

    def _snapshot_pre_tune_state(self) -> dict:
        """Capture the pre-tune state before acceptance overwrites active_gains.

        Sourced from live runtime state, not the connect-time config: within a
        session persist_tune_results stages autotune_status via configfile.set
        without updating driver.config, so config.autotune_status is stale while
        runtime_status tracks same-session tunes.
        """
        gains = self.driver.state.active_gains
        return {
            "active_gains": dict(gains) if gains is not None else None,
            "runtime_status": self.driver.state.runtime_status,
            "autotune_mode": self.driver.config.autotune_mode,
        }

    def _handle_robustness_verdict(self, gcmd) -> None:
        """Revert the deployed gain and config on a non-pass robustness verdict.

        Runs in the separate robustness invocation. Reads the pre-tune snapshot
        captured during the acceptance run; with no snapshot there is nothing to
        revert (report only), except a safety fault, which still inhibits.
        """
        terminal = self.robustness_reversal_terminal
        outcome = int(terminal["outcome"])
        cause = int(terminal["cause"])
        if outcome == 0:  # complete / pass
            self.driver.state.pre_tune_snapshot = None
            return
        if outcome == 3 and cause == 6:  # failed / safety_fault
            self._handle_robustness_safety_fault(gcmd)
            return
        snapshot = self.driver.state.pre_tune_snapshot
        if snapshot is None:
            return
        self._revert_runtime_and_config(snapshot)
        if outcome == 3:  # evidence-integrity / internal fault (cause 7/8)
            raise gcmd.error(
                f"FOCI {self.driver.name}: robustness evidence-integrity fault; "
                f"retained the pre-tune gain"
            )
        if snapshot["runtime_status"] == "commissioned":
            raise gcmd.error(
                f"FOCI {self.driver.name}: robustness reject, no robust gain "
                f"deployed; retained commissioned gains"
            )
        detail = "inconclusive - re-run" if outcome == 2 else "reject"
        gcmd.respond_info(
            f"FOCI {self.driver.name}: robustness {detail}; retained the pre-tune gain"
        )

    def _handle_robustness_safety_fault(self, gcmd) -> None:
        """Revert config and block in-session enable without re-pushing.

        Chip state is unknown after a mid-run safety fault, so the runtime
        re-push is skipped; the prior gain returns on the next startup from the
        reverted config. The enable-inhibit blocks the in-session leak.
        """
        snapshot = self.driver.state.pre_tune_snapshot
        if snapshot is not None:
            self._revert_config_only(snapshot)
        self.driver.state.inhibited = True
        self.driver.state.last_commission_failure = "robustness safety fault"
        self.driver.homing.set_auto_calibrate_on_enable_allowed(False)
        raise gcmd.error(
            f"FOCI {self.driver.name}: robustness safety fault; motor enable "
            f"inhibited until restart"
        )

    def _revert_config_only(self, snapshot: dict) -> None:
        restage_keys = {
            "velocity_p": "pid_velocity_p",
            "velocity_i": "pid_velocity_i",
            "position_p": "pid_position_p",
            "position_i": "pid_position_i",
            "velocity_limit": "pid_velocity_limit",
            "velocity_filter_hz": "velocity_filter_hz",
            "torque_filter_hz": "torque_filter_hz",
            "position_filter_hz": "position_filter_hz",
            "flux_filter_hz": "flux_filter_hz",
        }
        gains = snapshot["active_gains"]
        configfile = self.driver.printer.lookup_object("configfile")
        if gains is not None:
            for gain_key, config_key in restage_keys.items():
                value = gains.get(gain_key)
                if value is not None:
                    configfile.set(self.driver.name, config_key, f"{int(value)}")
        if snapshot.get("autotune_mode") is not None:
            configfile.set(self.driver.name, "autotune_mode", snapshot["autotune_mode"])
        configfile.set(self.driver.name, "autotune_status", snapshot["runtime_status"])

    def _revert_runtime_and_config(self, snapshot: dict) -> None:
        gains = snapshot["active_gains"]
        self.driver.state.active_gains = dict(gains) if gains is not None else None
        self.driver.state.runtime_status = snapshot["runtime_status"]
        self.driver.homing.apply_active_gains_to_firmware()
        self._revert_config_only(snapshot)

    def persist_tune_results(self, result: dict, mode_name: str, status: str) -> None:
        """Persist Stage 2 results to printer.cfg (pending SAVE_CONFIG)."""
        configfile = self.driver.printer.lookup_object("configfile")
        configfile.set(self.driver.name, "pid_velocity_p", f"{int(result['velocity_p'])}")
        configfile.set(self.driver.name, "pid_velocity_i", f"{int(result['velocity_i'])}")
        configfile.set(
            self.driver.name,
            "pid_velocity_limit",
            f"{int(result['velocity_limit'])}",
        )
        configfile.set(self.driver.name, "pid_position_p", f"{int(result['position_p'])}")
        configfile.set(self.driver.name, "pid_position_i", f"{int(result['position_i'])}")
        configfile.set(
            self.driver.name,
            "velocity_filter_hz",
            f"{int(result['velocity_filter_hz'])}",
        )
        configfile.set(
            self.driver.name,
            "position_filter_hz",
            f"{int(result['position_filter_hz'])}",
        )
        configfile.set(
            self.driver.name,
            "flux_filter_hz",
            f"{int(result['flux_filter_hz'])}",
        )
        configfile.set(
            self.driver.name,
            "torque_filter_hz",
            f"{int(result['torque_filter_hz'])}",
        )
        configfile.set(self.driver.name, "identified_j_eff", f"{int(result['j_eff'])}")
        configfile.set(self.driver.name, "identified_b_eff", f"{int(result['b_eff'])}")
        configfile.set(self.driver.name, "autotune_mode", mode_name)
        configfile.set(self.driver.name, "autotune_status", status)
