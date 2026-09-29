"""Velocity-autotune workflow for FOCI host commands."""

from __future__ import annotations

import contextlib
import logging
from enum import StrEnum

from ._vocabulary_generated import (
    SHAPE_BREAKAWAY_SEEDED,
    SHAPE_FIXED_GAIN_AMPLITUDE_ASCENDING,
    SHAPE_FIXED_GAIN_AMPLITUDE_DESCENDING,
    SHAPE_POSITION_TUNE,
    SHAPE_ROBUSTNESS_REVERSAL,
)
from .autotune_budget import (
    AutotuneBudgetError,
    compute_autotune_motion_budget,
    format_safe_pose_move,
)
from .commissioning import (
    COMMISSION_REASON_NAMES,
    HARD_FAULT_CODES,
    PROFILE_MAP,
    format_inner_warning_flags,
)
from .diagnostics.active import ActiveDiagnostics
from .fixed_gain_amplitude import (
    ACTION_CODES,
    FixedGainAmplitudeAssembler,
    FixedGainAmplitudeProtocolError,
    parse_autotune_action,
)
from .readiness import POLICY_UNAVAILABLE, resolve_autotune_readiness
from .report import humanize, report_detail, report_summary
from .robustness_reversal import (
    ROBUSTNESS_CAUSE_IAE_EXCEEDED,
    ROBUSTNESS_CAUSE_NAMES,
    ROBUSTNESS_CAUSE_SAFETY_FAULT,
    ROBUSTNESS_OUTCOME_COMPLETE,
    ROBUSTNESS_OUTCOME_FAILED,
    ROBUSTNESS_OUTCOME_INCONCLUSIVE,
    RobustnessReversalProtocolError,
)
from .robustness_reversal import (
    handle_cycle_evidence as parse_robustness_cycle_evidence,
)
from .robustness_reversal import (
    handle_terminal as parse_robustness_reversal_terminal,
)
from .velocity_integral import (
    BREAKAWAY_PHASE_NAMES,
    BREAKAWAY_TERMINAL_CAUSE_NAMES,
    BREAKAWAY_TERMINAL_REMEDIATION,
    FLOOR_ORIGIN_NAMES,
    INTEGRAL_CAUSE_DISPATCH_NAMESPACE,
    INTEGRAL_CAUSE_NAMESPACE_NAMES,
    INTEGRAL_TERMINAL_CAUSE_NAMES,
    INTEGRAL_TERMINAL_CAUSE_REMEDIATION,
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

log = logging.getLogger(__name__)

OUTER_SAFETY_REASON_NAMES = {
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

_OUTER_SAFETY_REASON_PHRASES = {
    "duration": "run duration exceeded",
    "velocity": "velocity limit exceeded",
    "position": "position limit exceeded",
    "quarter_turn": "quarter-turn safety limit",
    "current": "current limit exceeded",
    "recovery_wrong_way": "recovery moved the wrong way",
    "position_local": "local position limit exceeded",
}


def _outer_safety_reason_phrase(reason_name: str) -> str:
    return _OUTER_SAFETY_REASON_PHRASES.get(reason_name, humanize(reason_name))


class DispatchOutcome(StrEnum):
    """Marker returned by `_run_one_dispatch` when it handled the workflow inline."""

    TUNE_RESULT = "tune_result"
    FIXED_GAIN_AMPLITUDE = "fixed_gain_amplitude"
    ROBUSTNESS_REVERSAL = "robustness_reversal"
    BREAKAWAY_CAMPAIGN = "breakaway_campaign"
    VELOCITY_INTEGRAL_INCOMPLETE = "velocity_integral_incomplete"


# Wire code 0 is reserved to mean "not applicable" and never appears here.
# 1 (AccelerationFitRejected), 2, 3, and 5 (FloorCeilingConflict) are retired
# from the P-only torque-step floor design and are reserved, not reused.
POSITION_TUNE_OUTCOME_NAMES: dict[int, str] = {
    4: "configuration_invalid",
    6: "sweep_exhausted",
    7: "capture_empty",
    8: "conflict",
    9: "stimulus_rejected",
    10: "restoration_timeout",
}

_VELOCITY_INTEGRAL_SUCCESS_PHRASES = {
    "first_run_retained": "integral gain candidate found, confirming repeatability",
    "repeatability_confirmed": "integral gain confirmed",
}

_ROBUSTNESS_REJECT_PHRASES = {
    4: ("gain robustness check inconclusive, motor did not settle within the measurement window"),
    11: (
        "robustness check failed, could not reposition for the next "
        "reversal leg; existing gains retained"
    ),
}


def _format_robustness_reject_phrase(cause: int) -> str:
    if cause in _ROBUSTNESS_REJECT_PHRASES:
        return _ROBUSTNESS_REJECT_PHRASES[cause]
    cause_name = ROBUSTNESS_CAUSE_NAMES.get(cause, "unknown")
    return f"robustness check rejected, {humanize(cause_name)}"


FEEDFORWARD_PATH_NAMES: tuple[str, ...] = (
    "velocity",
    "transient",
    "accel",
    "decoupling",
    "phase_advance",
)


def _format_feedforward_paths(mask: int) -> str:
    return ",".join(name for bit, name in enumerate(FEEDFORWARD_PATH_NAMES) if mask & (1 << bit))


TAU_Q16 = 411_775


def _nominal_bandwidth_hz(last_rung_p: int) -> int:
    """Nominal position-loop bandwidth, mirroring firmware's pure function."""
    numerator = last_rung_p * 16_777_216
    denominator = 60 * TAU_Q16
    return (numerator + denominator // 2) // denominator


def _position_tune_evidence(result: dict) -> str:
    """Render the last measured rung's evidence for a position-tune failure."""
    if int(result.get("rungs_measured", 0)) == 0:
        return ""
    last_rung_p = int(result.get("last_rung_p", 0))
    homing_peak = int(result.get("homing_peak_abs_units", 0))
    motion_cruise = int(result.get("motion_cruise_mean_abs_units", 0))
    overshoot = int(result.get("motion_overshoot_units", 0))
    message = (
        f" (last rung: p={last_rung_p} homing_peak={homing_peak}u "
        f"motion_cruise={motion_cruise}u overshoot={overshoot}u"
    )
    min_overshoot_p = int(result.get("min_overshoot_p", 0))
    if min_overshoot_p:
        min_overshoot_units = int(result.get("min_overshoot_units", 0))
        message += f"; min overshoot {min_overshoot_units}u at p={min_overshoot_p}"
    return message + ")"


def _integral_cause_namespace_text(cause_namespace: int) -> str:
    """Render a velocity-integral terminal's cause namespace as its wire-carried name."""
    return INTEGRAL_CAUSE_NAMESPACE_NAMES.get(cause_namespace, "unknown")


def _integral_cause_text(cause_namespace: int, cause: int) -> str:
    """Render a velocity-integral terminal cause as a number, plus its name for a dispatch cause."""
    name = (
        INTEGRAL_TERMINAL_CAUSE_NAMES.get(cause)
        if cause_namespace == INTEGRAL_CAUSE_DISPATCH_NAMESPACE
        else None
    )
    return str(cause) if name is None else f"{cause} ({name})"


def _robustness_reversal_cause_text(cause: int) -> str:
    """Render a robustness-reversal terminal cause as its number and name."""
    name = ROBUSTNESS_CAUSE_NAMES.get(cause)
    return str(cause) if name is None else f"{cause} ({name})"


_REST_REJECTION_OWNER_TEXT = {
    "integral_anchor": "velocity-integral anchor",
    "integral_positive_observation": "velocity-integral positive-current observation",
    "integral_recovery": "velocity-integral origin recovery",
    "integral_cleanup": "velocity-integral cleanup",
}


def _rest_rejection_owner_text(owner: str | None) -> str | None:
    if owner is None:
        return None
    return _REST_REJECTION_OWNER_TEXT.get(owner, owner)


def _robustness_direction_text(index: int, direction: dict) -> str:
    """Render one robustness-reversal direction summary."""
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
    """Run installed tuning after commissioning and homing."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.result: dict | None = None
        self.outer_safety_fault: dict | None = None
        self.velocity_integral = VelocityIntegralAssembler()
        self.velocity_integral_error: VelocityIntegralProtocolError | None = None
        self.fixed_gain_amplitude = FixedGainAmplitudeAssembler()
        self.fixed_gain_amplitude_error: FixedGainAmplitudeProtocolError | None = None
        self.breakaway_campaign = BreakawayCampaignAssembler()
        self.breakaway_campaign_error: BreakawayCampaignProtocolError | None = None
        self.robustness_reversal_terminal: dict | None = None
        self.robustness_reversal_error: RobustnessReversalProtocolError | None = None
        self.robustness_cycle_evidence: dict[int, dict] = {}
        self.robustness_workflow_plan: dict | None = None
        self.position_tune_workflow_plan: dict | None = None
        self._proportional_candidate_request: dict | None = None
        self.tune_position_evidence_fragments: dict[int, tuple[int, dict[str, dict]]] = {}
        self.done = False

    def handle_tune_position_evidence(self, params: dict) -> None:
        """Cache foci_tune_position_evidence until the terminal arrives."""
        ActiveDiagnostics._stash_fragment(self.tune_position_evidence_fragments, params, "evidence")

    def handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware."""
        result = dict(params)
        fragments = ActiveDiagnostics._pop_fragments(
            self.tune_position_evidence_fragments,
            params.get("oid", 0),
            params.get("report_seq", 0),
        )
        if int(params.get("rungs_measured", 0)) > 0:
            evidence = fragments.get("evidence")
            if evidence:
                skip_keys = ("oid", "report_seq")
                result.update({k: v for k, v in evidence.items() if k not in skip_keys})
            if "last_rung_p" not in result:
                result["missing"] = ["evidence"]
        self.result = result
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
            and int(workflow["shape"]) == SHAPE_BREAKAWAY_SEEDED
            and not (self.breakaway_campaign.done and self.breakaway_campaign.accepted)
        ):
            self.velocity_integral_error = VelocityIntegralProtocolError(
                "breakaway velocity-integral plan arrived before an accepted campaign terminal"
            )
            return
        try:
            getattr(self.velocity_integral, method_name)(params)
        except VelocityIntegralProtocolError as err:
            self.velocity_integral_error = err
            return
        if (
            method_name == "handle_plan_rung"
            and workflow is not None
            and int(workflow["shape"]) == SHAPE_BREAKAWAY_SEEDED
            and self.velocity_integral.plan is not None
            and int(self.velocity_integral.plan["plan_digest"])
            != self.breakaway_campaign.integral_plan_digest
        ):
            self.velocity_integral_error = VelocityIntegralProtocolError(
                "breakaway velocity-integral plan digest does not match the accepted "
                "campaign terminal"
            )

    def _handle_breakaway_campaign(self, method_name: str, params: dict) -> None:
        if self.breakaway_campaign_error is not None:
            return
        workflow = self.velocity_integral.workflow_plan
        if workflow is None or int(workflow["shape"]) != SHAPE_BREAKAWAY_SEEDED:
            self.breakaway_campaign_error = BreakawayCampaignProtocolError(
                "breakaway campaign evidence arrived without a breakaway workflow plan"
            )
            return
        try:
            getattr(self.breakaway_campaign, method_name)(params)
        except BreakawayCampaignProtocolError as err:
            self.breakaway_campaign_error = err

    def handle_commissioning_workflow_plan(self, params: dict) -> None:
        shape = int(params.get("shape", -1))
        if shape in (SHAPE_FIXED_GAIN_AMPLITUDE_ASCENDING, SHAPE_FIXED_GAIN_AMPLITUDE_DESCENDING):
            try:
                self.fixed_gain_amplitude.handle_workflow_plan(params)
            except FixedGainAmplitudeProtocolError as err:
                self.fixed_gain_amplitude_error = err
            return
        if shape == SHAPE_ROBUSTNESS_REVERSAL:
            self.robustness_workflow_plan = params
            return
        if shape == SHAPE_POSITION_TUNE:
            self.position_tune_workflow_plan = params
            return
        self._handle_velocity_integral("handle_workflow_plan", params)

    def handle_fixed_gain_amplitude_plan(self, params: dict) -> None:
        """Relay one compact firmware-authored amplitude plan."""
        if self.fixed_gain_amplitude_error is not None:
            return
        try:
            self.fixed_gain_amplitude.handle_plan(params)
        except FixedGainAmplitudeProtocolError as err:
            self.fixed_gain_amplitude_error = err

    def handle_fixed_gain_amplitude_terminal(self, params: dict) -> None:
        """Relay one compact firmware-authored amplitude terminal."""
        if self.fixed_gain_amplitude_error is not None:
            return
        try:
            self.fixed_gain_amplitude.handle_terminal(params)
        except FixedGainAmplitudeProtocolError as err:
            self.fixed_gain_amplitude_error = err

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

    def _evidence_by_direction(self, key: str) -> list[int]:
        return [(self.robustness_cycle_evidence.get(index) or {}).get(key, 0) for index in (0, 1)]

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

    def _request_for_proportional_dispatch(self, request_fields: dict) -> dict:
        """Reuse the exact retained encoding when the explicit request matches."""
        if (
            self._proportional_candidate_request is not None
            and request_fields == self._proportional_candidate_request
        ):
            return dict(self._proportional_candidate_request)
        return request_fields

    def _retain_request_from_terminal(self, request_fields: dict) -> None:
        """Mirror firmware's retained authority/evidence request identity."""
        if not self.velocity_integral.done:
            return
        outcome = self.velocity_integral.outcome
        if outcome in ("first_run_retained", "inconclusive"):
            self._proportional_candidate_request = dict(request_fields)
        elif outcome != "rejected_plan_mismatch":
            self._proportional_candidate_request = None

    def _workflow_finished(self) -> bool:
        """Whether the disclosed firmware workflow reached its terminal stage."""
        if self.robustness_reversal_terminal is not None:
            return True
        if self.fixed_gain_amplitude.done:
            return True
        workflow = self.velocity_integral.workflow_plan
        if workflow is None:
            return self.velocity_integral.done
        shape = int(workflow["shape"])
        if shape == SHAPE_BREAKAWAY_SEEDED:
            if not self.breakaway_campaign.done:
                return False
            if not self.breakaway_campaign.accepted:
                return True
            return self.velocity_integral.done
        return self.velocity_integral.done

    def _synchronize_disarmed_workflow_terminal(self, toolhead) -> None:
        """Mirror a firmware-owned terminal disarm into Klipper state."""
        self._disable_kinematic_motors(toolhead)

    def _disable_kinematic_motors(self, toolhead) -> None:
        """Disable every Klipper motor coupled to this autotune workflow."""
        self.driver.state.is_calibrated = False
        stepper_enable = self.driver.printer.lookup_object("stepper_enable")
        print_time = toolhead.get_last_move_time()
        for stepper_name in self.driver.homing.kinematic_motor_names_for_stepper():
            enable_line = stepper_enable.lookup_enable(stepper_name)
            enable_line.motor_disable(print_time)

    def _resync_step_clock_after_stimulus(self) -> None:
        """Re-sync the tuned stepper after a firmware-driven step-queue stimulus."""
        self.driver._find_linked_stepper().note_homing_end()

    def _cancel_inflight_dispatch(self, toolhead) -> None:
        """Cancel a tune dispatch that left firmware running without a terminal."""
        reactor = self.driver.printer.get_reactor()
        self.driver.commissioning.cancel_and_await_quiescence(
            reactor, lambda: self.done or self._workflow_finished(), reactor.monotonic()
        )
        self._disable_kinematic_motors(toolhead)

    def _debug_enabled(self) -> bool:
        return self.driver.global_config.debug

    def _summary_prefix(self) -> str:
        return f"FOCI_AUTOTUNE {self.driver.stepper_name}"

    def _format_fixed_gain_amplitude_result(self) -> str:
        terminal = self.fixed_gain_amplitude.terminal or {}
        return (
            f"fixed-gain amplitude validation: {terminal.get('outcome_name', 'unknown')} "
            f"(namespace="
            f"{terminal.get('outcome_namespace', 'fixed_gain_amplitude')} cause="
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

    def handle_velocity_integral_terminal(self, params: dict) -> None:
        self._handle_velocity_integral("handle_terminal", params)

    def _format_velocity_integral_result(self) -> str:
        response = self.velocity_integral
        plan = response.plan or {}
        terminal = response.terminal or {}
        cause_namespace = int(terminal.get("cause_namespace", -1))
        cause = int(terminal.get("cause", 0))
        message = (
            f"velocity integral response {terminal.get('outcome_name', response.outcome)}: P="
            f"{int(plan.get('fixed_p', 0))} velocity={int(plan.get('planned_velocity_mrev_s', 0))}"
            f"mrev/s positive_rungs={int(plan.get('positive_rung_count', 0))} eligible=0x"
            f"{terminal.get('forward_eligible_mask', 0):08x}/0x"
            f"{terminal.get('reverse_eligible_mask', 0):08x} bookend=0x"
            f"{terminal.get('bookend_available_mask', 0):02x} current_terminus="
            f"{int(terminal.get('current_terminus_plus_one', 0))} namespace="
            f"{_integral_cause_namespace_text(cause_namespace)} cause="
            f"{_integral_cause_text(cause_namespace, cause)}"
        )
        remediation = (
            INTEGRAL_TERMINAL_CAUSE_REMEDIATION.get(cause)
            if cause_namespace == INTEGRAL_CAUSE_DISPATCH_NAMESPACE
            else None
        )
        if remediation is not None:
            message = f"{message}; {remediation}"
        if terminal.get("rest_rejection_after_sufficiency"):
            message = (
                f"{message}; sufficiency reached before rest rejected "
                f"(owner={_rest_rejection_owner_text(terminal.get('rest_rejection_owner'))})"
            )
        if response.reproduction is not None:
            mask_text = [
                f"{name} reproduced=0x{values.get('reproduced_mask', 0):08x} divergent=0x"
                f"{values.get('divergent_mask', 0):08x}"
                for name, values in response.reproduction.items()
            ]
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
        """Relay the firmware-authored breakaway campaign report verbatim."""
        campaign = self.breakaway_campaign
        terminal = campaign.campaign_terminal or {}
        cause = int(terminal.get("terminal_cause", 0))
        cause_name = BREAKAWAY_TERMINAL_CAUSE_NAMES.get(cause, f"unknown_{int(cause)}")
        phase_name = BREAKAWAY_PHASE_NAMES.get(int(terminal.get("phase", -1)), "unknown")
        error_code = int(terminal.get("error_code", 0))
        error_suffix = ""
        if error_code:
            error_name = COMMISSION_REASON_NAMES.get(error_code, f"unknown_{error_code}")
            error_suffix = f" error={error_name}"
        message = (
            f"breakaway campaign {'accepted' if campaign.accepted else 'not accepted'} (phase="
            f"{phase_name} cause={cause_name}{error_suffix})"
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
        discovery_terminal = campaign.discovery_terminal
        if discovery_terminal is not None:
            message += (
                f"; discovery stop_rung={int(discovery_terminal.get('stop_rung_index', 0))} "
                f"in_band={int(discovery_terminal.get('collected_count', 0))}"
            )
        confirmation = campaign.confirmation_plan
        if confirmation is not None:
            message += (
                f"; nominated P={int(confirmation.get('nominated_p_raw', 0))} margin="
                f"{int(confirmation.get('nominated_margin_percent_milli', 0))}pctm"
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

    def _format_proportional_gain_accepted(self) -> str:
        confirmed_p = int(
            (self.breakaway_campaign.confirmation_terminal or {}).get("confirmed_p_raw", 0)
        )
        return f"SUCCEEDED, proportional gain accepted (P={confirmed_p})."

    def _format_outer_safety_fault(self) -> str:
        fault = self.outer_safety_fault
        if not fault:
            return ""
        reason_code = int(fault.get("reason", 0))
        reason = OUTER_SAFETY_REASON_NAMES.get(reason_code)
        if reason is None:
            logging.warning(
                "FOCI: unmapped OUTER_SAFETY_FAULT_ code %d -- "
                "OUTER_SAFETY_REASON_NAMES is out of sync with firmware",
                reason_code,
            )
            reason = f"unknown_{reason_code}"
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

    def _reset_dispatch_state(self) -> None:
        """Clear the per-dispatch assemblers before issuing one firmware dispatch."""
        self.done = False
        self.result = None
        self.outer_safety_fault = None
        self.velocity_integral = VelocityIntegralAssembler()
        self.velocity_integral_error = None
        self.fixed_gain_amplitude = FixedGainAmplitudeAssembler()
        self.fixed_gain_amplitude_error = None
        self.breakaway_campaign = BreakawayCampaignAssembler()
        self.breakaway_campaign_error = None
        self.robustness_reversal_terminal = None
        self.robustness_reversal_error = None
        self.robustness_cycle_evidence = {}
        self.robustness_workflow_plan = None
        self.position_tune_workflow_plan = None
        self.tune_position_evidence_fragments = {}
        self.driver.commissioning.error_code = 0
        self.driver.commissioning.phase_label_override = None

    def _finish_velocity_integral_terminal(self, gcmd, request_fields: dict) -> str:
        """Report a velocity-integral terminal, raise on fault, and retain the request identity
        for a possible velocity_i_tune dispatch.
        """
        report_detail(
            log,
            self._debug_enabled(),
            f"FOCI {self.driver.name}: {self._format_velocity_integral_result()}",
        )
        if self.velocity_integral.outcome == "fault":
            safety_detail = self._format_outer_safety_fault()
            detail_suffix = f"; {safety_detail}" if safety_detail else ""
            raise gcmd.error(
                f"FOCI {self.driver.stepper_name}: velocity integral response fault{detail_suffix}"
            )
        phrase = _VELOCITY_INTEGRAL_SUCCESS_PHRASES.get(
            self.velocity_integral.outcome, humanize(self.velocity_integral.outcome)
        )
        candidate_i = (self.velocity_integral.terminal or {}).get("candidate_i")
        suffix = f" (velocity_i={int(candidate_i)})" if candidate_i is not None else ""
        report_summary(gcmd, f"{self._summary_prefix()}: SUCCEEDED, {phrase}{suffix}.")
        self._retain_request_from_terminal(request_fields)
        return self.velocity_integral.outcome

    def _rehome_and_center(self, gcmd, toolhead, safe_pose_move: str) -> None:
        """Re-home the FOCI axes, re-align the encoder, and re-center."""
        gcode = self.driver.printer.lookup_object("gcode")
        had_lock = self.driver.state.operation_lock
        if had_lock:
            self.driver.state.release()
        try:
            gcode.run_script_from_command("G28 X Y")
        except Exception as err:
            if had_lock:
                self.driver.state.try_acquire("autotune")
            raise gcmd.error(
                f"FOCI {self.driver.name}: autotune aborted -- homing failed: {err}"
            ) from err
        if had_lock and not self.driver.state.try_acquire("autotune"):
            raise gcmd.error(f"FOCI {self.driver.name}: another FOCI operation is in progress")
        gcode.run_script_from_command(safe_pose_move)
        toolhead.wait_moves()
        self.driver.homing.invalidate_homing()

    def _run_one_dispatch(
        self,
        gcmd,
        action_code: int,
        request_fields: dict,
        toolhead,
        safe_pose_move: str,
        orchestrated: bool = False,
    ) -> str:
        """Issue one firmware dispatch and wait for its terminal.

        Returns "tune_result" once a full TuneResult reply arrived (``self.done``). Returns the
        velocity-integral outcome name (for example "first_run_retained" or "inconclusive") when the
        workflow finished via a plain velocity-integral evidence terminal instead. Any other
        workflow (velocity confidence amplitude, robustness reversal, or breakaway campaign) is
        fully handled inline -- including raising on fault -- and returns its own marker, since none
        of those retry through a second dispatch.
        """
        self._rehome_and_center(gcmd, toolhead, safe_pose_move)
        dispatch_fields = dict(request_fields, action=action_code)
        self.driver.protocol.run_tune(**dispatch_fields)

        reactor = self.driver.printer.get_reactor()
        eventtime = reactor.monotonic()
        timeout = eventtime + COMMISSIONING_WORKFLOW_PLAN_TIMEOUT_S
        workflow_timeout_armed = False
        try:
            while not self.done and not self._workflow_finished():
                eventtime = reactor.pause(eventtime + 0.1)
                if self.velocity_integral_error is not None:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: velocity integral transport failure: "
                        f"{self.velocity_integral_error}"
                    )
                if self.fixed_gain_amplitude_error is not None:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: velocity confidence transport failure: "
                        f"{self.fixed_gain_amplitude_error}"
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
                    or self.fixed_gain_amplitude.workflow_plan is not None
                    or self.robustness_workflow_plan is not None
                    or self.position_tune_workflow_plan is not None
                ) and not workflow_timeout_armed:
                    if self.robustness_workflow_plan is not None:
                        maximum_duration_s = (
                            int(self.robustness_workflow_plan["maximum_workflow_ms"]) / 1000.0
                        )
                    elif self.position_tune_workflow_plan is not None:
                        maximum_duration_s = (
                            int(self.position_tune_workflow_plan["maximum_workflow_ms"]) / 1000.0
                        )
                    elif self.fixed_gain_amplitude.workflow_plan is not None:
                        maximum_duration_s = self.fixed_gain_amplitude.maximum_duration_s
                    else:
                        maximum_duration_s = self.velocity_integral.maximum_duration_s
                    timeout = eventtime + maximum_duration_s + COMMISSIONING_WORKFLOW_COMMS_MARGIN_S
                    workflow_timeout_armed = True
                if eventtime > timeout:
                    phase = "run" if workflow_timeout_armed else "waiting for plan"
                    raise gcmd.error(f"FOCI {self.driver.name}: FOCI_AUTOTUNE timed out {phase}")
                if self.driver.commissioning.error_code != 0:
                    error_name = COMMISSION_REASON_NAMES.get(
                        self.driver.commissioning.error_code,
                        f"UNKNOWN({int(self.driver.commissioning.error_code)})",
                    )
                    self.driver.commissioning.maybe_clear_calibration_for_chip_reset(
                        self.driver.commissioning.error_code
                    )
                    raise gcmd.error(f"FOCI {self.driver.name}: FOCI_AUTOTUNE failed: {error_name}")
        except Exception:
            self._cancel_inflight_dispatch(toolhead)
            if action_code == ACTION_CODES["position_p_tune"] and self.done:
                self._resync_step_clock_after_stimulus()
            raise
        if action_code == ACTION_CODES["position_p_tune"]:
            self._resync_step_clock_after_stimulus()

        if not self._workflow_finished():
            return DispatchOutcome.TUNE_RESULT

        self._synchronize_disarmed_workflow_terminal(toolhead)
        if self.fixed_gain_amplitude.done:
            report_detail(
                log,
                self._debug_enabled(),
                f"FOCI {self.driver.name}: {self._format_fixed_gain_amplitude_result()}",
            )
            outcome_name = (self.fixed_gain_amplitude.terminal or {}).get(
                "outcome_name", self.fixed_gain_amplitude.outcome
            )
            if self.fixed_gain_amplitude.outcome in ("fault", "failed"):
                fail_cause = (self.fixed_gain_amplitude.terminal or {}).get(
                    "cause_name", outcome_name
                )
                report_summary(gcmd, f"{self._summary_prefix()}: FAILED, {humanize(fail_cause)}.")
                raise gcmd.error(
                    f"FOCI {self.driver.name}: fixed-gain amplitude validation "
                    f"{self.fixed_gain_amplitude.outcome}"
                )
            report_summary(gcmd, f"{self._summary_prefix()}: SUCCEEDED, {humanize(outcome_name)}.")
            return DispatchOutcome.FIXED_GAIN_AMPLITUDE
        if self.robustness_reversal_terminal is not None:
            safety_detail = self._format_outer_safety_fault()
            detail_suffix = f"; {safety_detail}" if safety_detail else ""
            report_detail(
                log,
                self._debug_enabled(),
                f"FOCI {self.driver.name}: "
                f"{self._format_robustness_reversal_result()}{detail_suffix}",
            )
            terminal = self.robustness_reversal_terminal
            if orchestrated:
                iae_by_direction = self._evidence_by_direction("iae_median_qs")
                dac_rms_by_direction = self._evidence_by_direction("dac_rms_median_q")
                with contextlib.suppress(Exception):
                    logging.info(
                        "foci-gain-search %s: candidate p=%d i=%d verdict=rejected cause=%s "
                        "iae_median_qs=%s dac_rms_median_q=%s",
                        self.driver.name,
                        int(terminal.get("selected_p", 0)),
                        int(terminal.get("selected_i", 0)),
                        _robustness_reversal_cause_text(int(terminal.get("cause", 0))),
                        iae_by_direction,
                        dac_rms_by_direction,
                    )
                if int(terminal["outcome"]) == 3 and int(terminal["cause"]) == 6:
                    self._inhibit_orchestrated_safety_fault(gcmd)
                if int(terminal.get("cause", 0)) == ROBUSTNESS_CAUSE_IAE_EXCEEDED:
                    measured = max(
                        int(
                            (self.robustness_cycle_evidence.get(index) or {}).get(
                                "iae_median_qs", 0
                            )
                        )
                        for index in (0, 1)
                    )
                    report_summary(
                        gcmd,
                        f"{self._summary_prefix()}: FAILED, no robust gain within the "
                        "response band.",
                    )
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: no robust gain within the response band. "
                        "The most aggressive in-band candidate "
                        f"(P={int(terminal.get('selected_p', 0))} "
                        f"I={int(terminal.get('selected_i', 0))}) failed the robustness gate: "
                        f"measured IAE {measured} exceeds bound "
                        f"{int(terminal.get('iae_max_q_qs', 0))}. "
                        f"The plant cannot be robustly controlled within the response band."
                    )
                cause = int(terminal.get("cause", 0))
                raise gcmd.error(
                    f"FOCI {self.driver.stepper_name}: FOCI_AUTOTUNE "
                    f"{_format_robustness_reject_phrase(cause)}."
                )
            if int(terminal.get("outcome", -1)) == 0:
                report_summary(
                    gcmd,
                    f"{self._summary_prefix()}: SUCCEEDED, "
                    f"{humanize(terminal.get('outcome_name', 'unknown'))}.",
                )
            self._handle_robustness_verdict(gcmd)
            return DispatchOutcome.ROBUSTNESS_REVERSAL
        if self.breakaway_campaign.done:
            report_detail(
                log,
                self._debug_enabled(),
                f"FOCI {self.driver.name}: {self._format_breakaway_campaign_result()}",
            )
            if self._breakaway_campaign_has_safety_fault():
                safety_detail = self._format_outer_safety_fault()
                detail_suffix = f"; {safety_detail}" if safety_detail else ""
                terminal = self.breakaway_campaign.campaign_terminal or {}
                cause_name = BREAKAWAY_TERMINAL_CAUSE_NAMES.get(
                    int(terminal.get("terminal_cause", 0)), "unknown"
                )
                raise gcmd.error(
                    f"FOCI {self.driver.stepper_name}: breakaway campaign safety fault "
                    f"({humanize(cause_name)}){detail_suffix}"
                )
            if not self.breakaway_campaign.accepted:
                terminal = self.breakaway_campaign.campaign_terminal or {}
                cause = int(terminal.get("terminal_cause", 0))
                remediation = BREAKAWAY_TERMINAL_REMEDIATION.get(cause)
                if remediation is None:
                    cause_name = BREAKAWAY_TERMINAL_CAUSE_NAMES.get(cause)
                    remediation = (
                        humanize(cause_name) if cause_name else "an unrecognized breakaway failure"
                    )
                cause_suffix = " Safe to retry." if cause == 23 else ""
                raise gcmd.error(
                    f"FOCI {self.driver.stepper_name}: FOCI_AUTOTUNE {remediation}; "
                    f"existing gains retained.{cause_suffix}"
                )
            if self.velocity_integral.done:
                report_summary(
                    gcmd, f"{self._summary_prefix()}: {self._format_proportional_gain_accepted()}"
                )
                return self._finish_velocity_integral_terminal(gcmd, request_fields)
            report_summary(
                gcmd, f"{self._summary_prefix()}: {self._format_proportional_gain_accepted()}"
            )
            return DispatchOutcome.BREAKAWAY_CAMPAIGN
        if self.velocity_integral.done:
            return self._finish_velocity_integral_terminal(gcmd, request_fields)
        return DispatchOutcome.VELOCITY_INTEGRAL_INCOMPLETE

    def autotune(self, gcmd) -> None:
        """Installed tuning after commissioning."""
        action_param = gcmd.get("ACTION", None)
        try:
            action = parse_autotune_action(action_param)
        except FixedGainAmplitudeProtocolError as err:
            raise gcmd.error(f"FOCI {self.driver.name}: {err}") from err
        chain_position_tune = action_param is None
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

        if not self.driver.state.try_acquire("autotune"):
            raise gcmd.error(f"FOCI {self.driver.name}: another FOCI operation is in progress")

        try:
            if self.driver.state.inhibited:
                reason = self.driver.state.last_commission_failure or "failed FOCI_SETUP"
                raise gcmd.error(f"FOCI {self.driver.name}: inhibited: {reason}")
            if self.driver.state.runtime_status == "uncommissioned":
                raise gcmd.error(
                    f"FOCI {self.driver.name}: not commissioned. Run FOCI_SETUP first."
                )
            toolhead = self.driver.printer.lookup_object("toolhead")
            self._ensure_printer_idle(gcmd, toolhead)
            try:
                motion_budget = compute_autotune_motion_budget(self.driver, gcmd)
            except AutotuneBudgetError as err:
                raise gcmd.error(f"FOCI {self.driver.name}: {err}") from err

            readiness = resolve_autotune_readiness(self.driver)
            if readiness.blocked:
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_AUTOTUNE blocked: "
                    f"{'; '.join(readiness.blockers)}"
                )
            if readiness.installed_tuning_policy == POLICY_UNAVAILABLE:
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_AUTOTUNE installed-tuning unavailable "
                    f"inputs: "
                    f"{', '.join(readiness.unavailable_inputs)}"
                )

            if readiness.warnings:
                report_summary(
                    gcmd,
                    f"{self._summary_prefix()} readiness warnings: {'; '.join(readiness.warnings)}",
                )
            if readiness.unavailable_inputs:
                report_summary(
                    gcmd,
                    f"{self._summary_prefix()} unavailable inputs: "
                    f"{', '.join(readiness.unavailable_inputs)}",
                )

            safe_pose_move = format_safe_pose_move(motion_budget)

            if self.driver.state.commissioned_result is not None:
                inner_lambda = self.driver.state.commissioned_result["lambda_us"]
                theta_e = self.driver.state.commissioned_result["theta_e_us"]
                bandwidth = self.driver.state.commissioned_result["bandwidth_hz"]
            else:
                config = self.driver.config
                inner_lambda = config.identified_lambda_us
                theta_e = config.identified_theta_e_us
                bandwidth = config.identified_bandwidth_hz

            inner_warning_flags = readiness.inner_warning_flags

            self._reset_dispatch_state()

            request_fields = self._request_for_proportional_dispatch(
                {
                    "action": action,
                    "profile_code": PROFILE_MAP[profile_name],
                    "mode_code": MODE_MAP[mode_name],
                    "inner_lambda": inner_lambda,
                    "theta_e": theta_e,
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
                    "homing_speed_mrev_s": motion_budget.homing_speed_mrev_s,
                    "max_accel_mrev_s2": motion_budget.max_accel_mrev_s2,
                }
            )

            outcome = self._run_one_dispatch(gcmd, action, request_fields, toolhead, safe_pose_move)
            if outcome == "first_run_retained":
                self._reset_dispatch_state()
                self.driver.commissioning.phase_label_override = (
                    "Confirming integral gain repeatability"
                )
                try:
                    outcome = self._run_one_dispatch(
                        gcmd,
                        ACTION_CODES["velocity_i_tune"],
                        request_fields,
                        toolhead,
                        safe_pose_move,
                    )
                finally:
                    self.driver.commissioning.phase_label_override = None
                if outcome == "repeatability_confirmed":
                    self._reset_dispatch_state()
                    outcome = self._run_one_dispatch(
                        gcmd,
                        ACTION_CODES["velocity_tune_check"],
                        request_fields,
                        toolhead,
                        safe_pose_move,
                        orchestrated=True,
                    )
                    if outcome != DispatchOutcome.TUNE_RESULT:
                        # Defensive: the orchestrated dispatch above raises
                        # for every non-pass terminal (ordinary reject and
                        # safety fault alike), so this is unreachable today.
                        raise gcmd.error(
                            f"FOCI {self.driver.name}: robustness reversal after "
                            f"reproduced resume did not pass (outcome={outcome})"
                        )
                elif outcome != DispatchOutcome.TUNE_RESULT:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: velocity-integral resume did not reproduce "
                        f"the accepted candidate (outcome={outcome})"
                    )
            elif outcome != DispatchOutcome.TUNE_RESULT:
                return

            chained_velocity_evidence = None
            if chain_position_tune and int((self.result or {}).get("status", 255)) <= 1:
                chained_velocity_evidence = (
                    self._evidence_by_direction("iae_median_qs"),
                    self._evidence_by_direction("dac_rms_median_q"),
                )
                self._reset_dispatch_state()
                self._synchronize_disarmed_workflow_terminal(toolhead)
                outcome = self._run_one_dispatch(
                    gcmd,
                    ACTION_CODES["position_p_tune"],
                    request_fields,
                    toolhead,
                    safe_pose_move,
                )
                if outcome != DispatchOutcome.TUNE_RESULT:
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_AUTOTUNE position tune chain did not "
                        f"produce a result (outcome={outcome})"
                    )

            result = self.result
            status = result.get("status", 255)
            if status > 1:
                error_name = COMMISSION_REASON_NAMES.get(status, f"UNKNOWN({int(status)})")
                evidence = _position_tune_evidence(result)
                if status == 18:
                    self.driver.commissioning.handle_chip_reset_detected()
                    self._disable_kinematic_motors(toolhead)
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_AUTOTUNE chip reset: {error_name} "
                        f"(motor disabled by firmware){evidence}"
                    )
                if status in HARD_FAULT_CODES:
                    self.driver.commissioning.on_commission_failure()
                    self._disable_kinematic_motors(toolhead)
                    safety_detail = self._format_outer_safety_fault()
                    detail_suffix = f"; {safety_detail}" if safety_detail else ""
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_AUTOTUNE safety fault: {error_name}"
                        f"{detail_suffix} (motor disabled by firmware){evidence}"
                    )
                position_tune_outcome_code = int(result.get("position_tune_outcome_code", 0))
                if position_tune_outcome_code:
                    outcome_name = POSITION_TUNE_OUTCOME_NAMES.get(
                        position_tune_outcome_code,
                        f"unknown_{position_tune_outcome_code}",
                    )
                    if chained_velocity_evidence is not None:
                        raise gcmd.error(
                            f"FOCI {self.driver.name}: FOCI_AUTOTUNE position tune failed: "
                            f"{outcome_name} (velocity tune succeeded but was not persisted "
                            f"because the chained position tune failed; motor holding with "
                            f"the newly installed, unpersisted velocity gains){evidence}"
                        )
                    raise gcmd.error(
                        f"FOCI {self.driver.name}: FOCI_AUTOTUNE position tune failed: "
                        f"{outcome_name} (motor holding with entry gains){evidence}"
                    )
                raise gcmd.error(
                    f"FOCI {self.driver.name}: FOCI_AUTOTUNE failed: {error_name} (motor "
                    f"holding with entry gains){evidence}"
                )

            tune_status = "tuned"

            self.driver.state.pre_tune_snapshot = self._snapshot_pre_tune_state()
            active_gains = self.driver.state.active_gains
            # velocity_limit, position_i and the filter values no longer
            # arrive on the wire terminal (frame-budget split); this dispatch
            # never tunes them, so carry the entry values forward unchanged.
            self.driver.state.active_gains = {
                "flux_p": active_gains["flux_p"],
                "flux_i": active_gains["flux_i"],
                "torque_p": active_gains["torque_p"],
                "torque_i": active_gains["torque_i"],
                "velocity_p": result["velocity_p"],
                "velocity_i": result["velocity_i"],
                "position_p": result["position_p"],
                "position_i": active_gains["position_i"],
                "velocity_limit": active_gains["velocity_limit"],
                "velocity_filter_hz": active_gains["velocity_filter_hz"],
                "torque_filter_hz": active_gains["torque_filter_hz"],
                "position_filter_hz": active_gains["position_filter_hz"],
                "flux_filter_hz": active_gains["flux_filter_hz"],
            }
            self.driver.state.runtime_status = tune_status

            # persist_tune_results still reads these keys directly off
            # `result`; fold in the active_gains-sourced values above so its
            # persisted-key set and the summary text below stay unchanged.
            result.update(
                {
                    key: self.driver.state.active_gains[key]
                    for key in (
                        "position_i",
                        "velocity_limit",
                        "velocity_filter_hz",
                        "torque_filter_hz",
                        "position_filter_hz",
                        "flux_filter_hz",
                    )
                }
            )
            self.persist_tune_results(result, mode_name, tune_status)

            evidence_missing = "evidence" in (result.get("missing") or [])
            nominal_bandwidth_hz = _nominal_bandwidth_hz(int(result.get("last_rung_p", 0)))
            gain_text = (
                f"velocity_p={int(result['velocity_p'])}, velocity_i={int(result['velocity_i'])}"
            )
            summary_suffix = (
                f", position_p={int(result['position_p'])})." if nominal_bandwidth_hz else ")."
            )
            summary_line = (
                f"{self._summary_prefix()}: SUCCEEDED, tuned ({gain_text}{summary_suffix}"
            )
            if evidence_missing:
                summary_line += " missing=evidence"
            report_summary(gcmd, summary_line)
            if nominal_bandwidth_hz:
                report_detail(
                    log,
                    self.driver.global_config.debug,
                    f"FOCI {self.driver.name} position tune: p={int(result['position_p'])} "
                    f"bound={int(result['bound_units'])}u "
                    f"start_p={int(result['predicted_start_p'])} "
                    f"last_p={int(result['last_rung_p'])} "
                    f"homing_peak={int(result['homing_peak_abs_units'])}u "
                    f"motion_cruise={int(result['motion_cruise_mean_abs_units'])}u "
                    f"overshoot={int(result['motion_overshoot_units'])}u "
                    f"cruise_rms={int(result['motion_cruise_rms_units'])}u "
                    f"homing_speed={int(result['homing_speed_mrev_s'])}mrev_s "
                    f"motion_speed={int(result['motion_speed_mrev_s'])}mrev_s "
                    f"nominal_bw={nominal_bandwidth_hz}Hz "
                    f"dither_margin={int(result['dither_margin_milli']) / 1000.0:.2f}x "
                    f"rungs={int(result['rungs_measured'])} "
                    f"ff={_format_feedforward_paths(int(result['stimulus_feedforward_paths']))}",
                )
            if inner_warning_flags:
                report_detail(
                    log,
                    self.driver.global_config.debug,
                    f"FOCI {self.driver.name} inner confidence: "
                    f"{format_inner_warning_flags(inner_warning_flags)}",
                )
            self._disable_kinematic_motors(toolhead)
            if chained_velocity_evidence is not None:
                iae_by_direction, dac_rms_by_direction = chained_velocity_evidence
            else:
                iae_by_direction = self._evidence_by_direction("iae_median_qs")
                dac_rms_by_direction = self._evidence_by_direction("dac_rms_median_q")
            logging.info(
                "foci-gain-search %s: candidate p=%d i=%d verdict=passed "
                "iae_median_qs=%s dac_rms_median_q=%s",
                self.driver.name,
                int(result["velocity_p"]),
                int(result["velocity_i"]),
                iae_by_direction,
                dac_rms_by_direction,
            )
        finally:
            self.driver.state.release()

    def _snapshot_pre_tune_state(self) -> dict:
        """Capture the pre-tune state before acceptance overwrites active_gains."""
        gains = self.driver.state.active_gains
        return {
            "active_gains": dict(gains) if gains is not None else None,
            "runtime_status": self.driver.state.runtime_status,
            "autotune_mode": self.driver.config.autotune_mode,
        }

    def _handle_robustness_verdict(self, gcmd) -> None:
        """Revert the deployed gain and config on a non-pass robustness verdict."""
        terminal = self.robustness_reversal_terminal
        outcome = int(terminal["outcome"])
        cause = int(terminal["cause"])
        if outcome == ROBUSTNESS_OUTCOME_COMPLETE:
            self.driver.state.pre_tune_snapshot = None
            return
        if outcome == ROBUSTNESS_OUTCOME_FAILED and cause == ROBUSTNESS_CAUSE_SAFETY_FAULT:
            self._handle_robustness_safety_fault(gcmd)
            return
        snapshot = self.driver.state.pre_tune_snapshot
        if snapshot is None:
            return
        self._revert_runtime_and_config(snapshot)
        if outcome == ROBUSTNESS_OUTCOME_FAILED:
            raise gcmd.error(
                f"FOCI {self.driver.name}: robustness evidence-integrity fault; "
                f"retained the pre-tune gain"
            )
        if snapshot["runtime_status"] == "commissioned":
            raise gcmd.error(
                f"FOCI {self.driver.stepper_name}: robustness check rejected the "
                f"candidate gain; nothing deployed (commissioned gains retained)."
            )
        detail = "inconclusive - re-run" if outcome == ROBUSTNESS_OUTCOME_INCONCLUSIVE else "reject"
        report_summary(
            gcmd,
            f"{self._summary_prefix()}: FAILED, robustness check {detail}; retained "
            "the pre-tune gain.",
        )

    def _handle_robustness_safety_fault(self, gcmd) -> None:
        """Revert config and block in-session enable without re-pushing."""
        snapshot = self.driver.state.pre_tune_snapshot
        if snapshot is not None:
            self._revert_config_only(snapshot)
        self._inhibit_enable_for_safety_fault()
        self._raise_robustness_safety_fault(gcmd)

    def _outer_safety_fault_reason_name(self) -> str | None:
        fault = self.outer_safety_fault
        if not fault:
            return None
        reason_code = int(fault.get("reason", 0))
        return OUTER_SAFETY_REASON_NAMES.get(reason_code)

    def _raise_robustness_safety_fault(self, gcmd) -> None:
        reason_name = self._outer_safety_fault_reason_name()
        reason_suffix = f" ({_outer_safety_reason_phrase(reason_name)})" if reason_name else ""
        raise gcmd.error(
            f"FOCI {self.driver.stepper_name}: robustness safety fault{reason_suffix}; "
            f"motor enable inhibited until restart."
        )

    def _inhibit_enable_for_safety_fault(self) -> None:
        """Block a subsequent SET_STEPPER_ENABLE until restart."""
        self.driver.state.inhibited = True
        self.driver.state.last_commission_failure = "robustness safety fault"
        self.driver.homing.set_auto_calibrate_on_enable_allowed(False)

    def _inhibit_orchestrated_safety_fault(self, gcmd) -> None:
        """Inhibit enable for an orchestrated safety fault without touching config."""
        self._inhibit_enable_for_safety_fault()
        self._raise_robustness_safety_fault(gcmd)

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
        """Persist installed-tuning results to printer.cfg (pending SAVE_CONFIG)."""
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
        for key in (
            "velocity_filter_hz",
            "position_filter_hz",
            "flux_filter_hz",
            "torque_filter_hz",
        ):
            if result[key] is not None:
                configfile.set(self.driver.name, key, f"{int(result[key])}")
        probed_velocity_mrev_s = int(result.get("probed_velocity_mrev_s", 0))
        if probed_velocity_mrev_s:
            configfile.set(
                self.driver.name,
                "autotune_probed_velocity_mrev_s",
                f"{probed_velocity_mrev_s}",
            )
            configfile.set(self.driver.name, "autotune_d_eq_q", f"{int(result['d_eq_q'])}")
            configfile.set(
                self.driver.name, "autotune_confidence_q", f"{int(result['confidence_q'])}"
            )
            configfile.set(
                self.driver.name,
                "autotune_band_lower_percent",
                f"{int(result['band_lower_percent'])}",
            )
            configfile.set(
                self.driver.name,
                "autotune_band_upper_percent",
                f"{int(result['band_upper_percent'])}",
            )
            configfile.set(
                self.driver.name, "autotune_band_position_q", f"{int(result['band_position_q'])}"
            )
        evidence_missing = "evidence" in (result.get("missing") or [])
        if evidence_missing:
            self.driver.printer.lookup_object("gcode").respond_info(
                f"FOCI {self.driver.name}: position-tune evidence was lost "
                "(frame drop); position bound/homing-peak/motion-cruise "
                "config keys were not updated"
            )
        else:
            nominal_bandwidth_hz = _nominal_bandwidth_hz(int(result.get("last_rung_p", 0)))
            if nominal_bandwidth_hz:
                configfile.set(
                    self.driver.name,
                    "autotune_position_bound_units",
                    f"{int(result['bound_units'])}",
                )
                configfile.set(
                    self.driver.name,
                    "autotune_position_homing_peak_units",
                    f"{int(result['homing_peak_abs_units'])}",
                )
                configfile.set(
                    self.driver.name,
                    "autotune_position_motion_cruise_units",
                    f"{int(result['motion_cruise_mean_abs_units'])}",
                )
        configfile.set(self.driver.name, "autotune_mode", mode_name)
        configfile.set(self.driver.name, "autotune_status", status)
