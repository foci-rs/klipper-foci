"""Reassemble firmware-authored velocity-integral response evidence."""

from __future__ import annotations

import struct

from ._vocabulary_generated import (
    BREAKAWAY_PHASE_NAMES,
    SHAPE_BREAKAWAY_SEEDED,
    SHAPE_FIXED_GAIN_AMPLITUDE_ASCENDING,
    SHAPE_FIXED_GAIN_AMPLITUDE_DESCENDING,
    SHAPE_RESUME,
    SHAPE_ROBUSTNESS_REVERSAL,
)

FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3

OUTCOME_NAMES = {
    0: "complete_candidate",
    1: "complete",
    2: "inconclusive",
    3: "fault",
    4: "rejected_plan_mismatch",
    5: "failed",
}

PLAN_RECOVERY_QUANTIZATION_EXPOSED = 1 << 0
PLAN_PROBE_CONSTRAINED_TEST_POINT = 1 << 1
# Set when a combined run executed its forward and reverse observation slots in
# mirrored order. Firmware records this without moving the velocity-integral schema, so
# unlike the older bits it is accepted at every schema revision.
PLAN_SLOT_ORDER_SHIFT = 2
PLAN_SLOT_ORDER_MASK = 0b11 << PLAN_SLOT_ORDER_SHIFT

SLOT_ORDER_REVERSE_FIRST = 1

TERMINAL_REST_REJECTION_AFTER_SUFFICIENCY = 1 << 4
TERMINAL_REST_REJECTION_OWNER_SHIFT = 5
TERMINAL_REST_REJECTION_OWNER_MASK = 0b11 << TERMINAL_REST_REJECTION_OWNER_SHIFT

REST_REJECTION_OWNER_NAMES = {
    0b00: "stage_c_anchor",
    0b01: "stage_c_positive_observation",
    0b10: "stage_c_recovery",
    0b11: "stage_c_cleanup",
}

VELOCITY_INTEGRAL_TERMINAL_SCHEMA_REVISION = 1


class VelocityIntegralProtocolError(Exception):
    """Raised when integral-response records violate their causal wire contract."""


def _u64(low: int, high: int) -> int:
    return int(low) | (int(high) << 32)


def _metadata_free(params: dict) -> dict:
    return {
        key: value
        for key, value in params.items()
        if key not in ("oid", "fragment") and not key.startswith("#")
    }


def _fnv1a(data: bytes, digest: int = FNV1A64_OFFSET) -> int:
    for byte in data:
        digest ^= byte
        digest = (digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
    return digest


def _pack(values: tuple[tuple[str, int], ...]) -> bytes:
    return b"".join(struct.pack("<" + kind, int(value)) for kind, value in values)


_TERMINAL = struct.Struct("<BIBBBBIIBBBIIII")


def _terminal_payload(params: dict) -> bytes:
    try:
        payload = bytes(params["payload"])
    except (KeyError, TypeError, ValueError) as err:
        raise VelocityIntegralProtocolError(
            "velocity-integral terminal payload is missing"
        ) from err
    if len(payload) != _TERMINAL.size:
        raise VelocityIntegralProtocolError(
            f"velocity-integral terminal payload has {len(payload)} bytes, expected "
            f"{int(_TERMINAL.size)}"
        )
    return payload


class VelocityIntegralAssembler:
    """Strictly assemble one firmware-authored integral-response report."""

    def __init__(self) -> None:
        self.workflow_plan: dict | None = None
        self.plan: dict | None = None
        self.terminal: dict | None = None
        self.reproduction: dict | None = None
        self.outcome: str | None = None
        self.done = False
        self._plan_parts: list[dict] = []
        self._authorities: list[dict] = []
        self._plan_rungs: list[dict] = []
        self._run_sequence: int | None = None

    @property
    def plan_ready(self) -> bool:
        """Whether the exact velocity-integral plan has arrived."""
        return self.plan is not None

    @property
    def maximum_duration_s(self) -> float | None:
        """Firmware-declared command-level maximum duration in seconds."""
        if self.workflow_plan is None:
            return None
        return int(self.workflow_plan["maximum_workflow_ms"]) / 1000.0

    @property
    def report(self) -> dict:
        """Return the assembled plan and terminal evidence."""
        return {
            "workflow_plan": self.workflow_plan,
            "plan": self.plan,
            "terminal": self.terminal,
            "reproduction": self.reproduction,
        }

    @staticmethod
    def workflow_digest_halves(params: dict) -> tuple[int, int]:
        """Compute the envelope digest used only for transport integrity."""
        encoded = _pack(
            (
                ("I", params["run_sequence"]),
                ("B", params["shape"]),
                ("I", params["nominal_workflow_ms"]),
                ("I", params["maximum_workflow_ms"]),
            )
        )
        digest = _fnv1a(encoded)
        return digest & 0xFFFF_FFFF, digest >> 32

    def handle_workflow_plan(self, params: dict) -> None:
        if self.workflow_plan is not None:
            raise VelocityIntegralProtocolError("duplicate workflow plan")
        shape = int(params.get("shape", -1))
        if shape not in (
            SHAPE_RESUME,
            SHAPE_FIXED_GAIN_AMPLITUDE_ASCENDING,
            SHAPE_FIXED_GAIN_AMPLITUDE_DESCENDING,
            SHAPE_BREAKAWAY_SEEDED,
            SHAPE_ROBUSTNESS_REVERSAL,
        ):
            raise VelocityIntegralProtocolError("invalid workflow shape")
        if int(params["maximum_workflow_ms"]) < int(params["nominal_workflow_ms"]):
            raise VelocityIntegralProtocolError("workflow maximum is below nominal")
        expected = self.workflow_digest_halves(params)
        reported = (int(params["digest_low"]), int(params["digest_high"]))
        if reported != expected:
            raise VelocityIntegralProtocolError("workflow digest mismatch")
        self._run_sequence = int(params["run_sequence"])
        self.workflow_plan = _metadata_free(params)
        self.workflow_plan["digest"] = _u64(*reported)

    def handle_plan_core(self, params: dict) -> None:
        if self.plan is not None or self._plan_parts:
            raise VelocityIntegralProtocolError("duplicate plan core")
        self._require_stage_c_workflow(params)
        if int(params.get("schema_revision", -1)) not in (
            2,
            3,
            4,
            5,
            6,
            7,
            14,
            15,
            16,
            17,
            18,
        ):
            raise VelocityIntegralProtocolError("unsupported velocity-integral evidence schema")
        self._require_fragment(params, 0)
        self._plan_parts.append(dict(params))

    def handle_plan_geometry(self, params: dict) -> None:
        self._require_plan_step("plan core", 1)
        self._require_fragment(params, 1)
        self._require_plan_identity(params)
        count = int(params["positive_rung_count"])
        if count not in range(1, 31):
            raise VelocityIntegralProtocolError("invalid positive rung count")
        if int(params["family_size"]) != 4 * (count + 2):
            raise VelocityIntegralProtocolError("invalid integral-response family size")
        self._plan_parts.append(dict(params))

    def handle_plan_authority(self, params: dict) -> None:
        self._require_plan_step("plan geometry", 2)
        self._require_plan_identity(params)
        direction = int(params.get("direction", -1))
        if direction != len(self._authorities) or direction not in (0, 1):
            raise VelocityIntegralProtocolError("reordered plan authority")
        if int(params["pooled_low_q16"]) > int(params["pooled_high_q16"]):
            raise VelocityIntegralProtocolError("reversed breakaway authority interval")
        if int(params.get("directional_validity", -1)) not in range(5):
            raise VelocityIntegralProtocolError("invalid breakaway directional validity")
        if int(params.get("reduced_margin", -1)) not in (0, 1):
            raise VelocityIntegralProtocolError("invalid breakaway reduced-margin flag")
        self._authorities.append(_metadata_free(params))

    def handle_plan_timing(self, params: dict) -> None:
        if len(self._authorities) != 2:
            raise VelocityIntegralProtocolError("plan timing preceded authorities")
        self._require_plan_step("plan geometry", 2)
        self._require_fragment(params, 2)
        self._require_plan_identity(params)
        if int(params["maximum_workflow_ms"]) < int(params["nominal_workflow_ms"]):
            raise VelocityIntegralProtocolError("integral-response maximum is below nominal")
        self._plan_parts.append(dict(params))

    def handle_plan_travel(self, params: dict) -> None:
        self._require_plan_step("plan timing", 3)
        self._require_fragment(params, 3)
        self._require_plan_identity(params)
        self._plan_parts.append(dict(params))

    def handle_plan_recovery(self, params: dict) -> None:
        self._require_plan_step("plan travel", 4)
        self._require_plan_identity(params)
        schema_revision = int(self._plan_parts[0]["schema_revision"])
        if schema_revision >= 6:
            flags = int(params.get("flags", -1))
            known_flags = PLAN_RECOVERY_QUANTIZATION_EXPOSED | PLAN_SLOT_ORDER_MASK
            if schema_revision >= 7:
                known_flags |= PLAN_PROBE_CONSTRAINED_TEST_POINT
            if flags < 0 or flags & ~known_flags:
                raise VelocityIntegralProtocolError("invalid plan recovery flags")
        self._plan_parts.append(dict(params))

    def handle_plan_rung(self, params: dict) -> None:
        if self.plan is not None:
            raise VelocityIntegralProtocolError("duplicate plan rung after complete plan")
        self._require_plan_step("plan recovery", 5)
        self._require_plan_identity(params)
        rung_index = int(params.get("rung_index", -1))
        if rung_index != len(self._plan_rungs):
            raise VelocityIntegralProtocolError("reordered or duplicate plan rung")
        self._plan_rungs.append(_metadata_free(params))
        count = int(self._plan_parts[1]["positive_rung_count"])
        if len(self._plan_rungs) == count:
            self._finish_plan()

    def handle_terminal(self, params: dict) -> None:
        (
            schema,
            run_sequence,
            outcome,
            cause,
            cause_namespace,
            recovery_flags,
            forward_eligible_mask,
            reverse_eligible_mask,
            bookend_available_mask,
            current_terminus_plus_one,
            reproduction_available,
            forward_reproduced_mask,
            forward_divergent_mask,
            reverse_reproduced_mask,
            reverse_divergent_mask,
        ) = _TERMINAL.unpack(_terminal_payload(params))
        if schema != VELOCITY_INTEGRAL_TERMINAL_SCHEMA_REVISION:
            raise VelocityIntegralProtocolError("unsupported velocity-integral terminal schema")
        outcome_name = OUTCOME_NAMES.get(outcome)
        if outcome_name is None:
            raise VelocityIntegralProtocolError("invalid terminal outcome")
        if reproduction_available not in (0, 1):
            raise VelocityIntegralProtocolError("invalid reproduction availability")
        if not reproduction_available and (
            forward_reproduced_mask
            or forward_divergent_mask
            or reverse_reproduced_mask
            or reverse_divergent_mask
        ):
            raise VelocityIntegralProtocolError(
                "reproduction masks present without reproduction evidence"
            )
        if self.plan is None and (
            self._plan_parts or outcome != 5 or cause not in STAGE_C_FAILED_ADMISSION_CAUSES
        ):
            raise VelocityIntegralProtocolError("terminal preceded exact plan")
        if self._run_sequence is None:
            self._run_sequence = run_sequence
        elif run_sequence != self._run_sequence:
            raise VelocityIntegralProtocolError("run sequence changed")
        breakaway = (
            self.plan is not None
            and int(self.plan["schema_revision"]) >= 8
            and self.workflow_plan is not None
            and int(self.workflow_plan["shape"]) == SHAPE_BREAKAWAY_SEEDED
        )
        if outcome_name == "complete" and not reproduction_available and not breakaway:
            raise VelocityIntegralProtocolError(
                "complete integral response omitted reproduction evidence"
            )
        rest_rejection_after_sufficiency = bool(
            recovery_flags & TERMINAL_REST_REJECTION_AFTER_SUFFICIENCY
        )
        rest_rejection_owner = (
            REST_REJECTION_OWNER_NAMES[
                (recovery_flags & TERMINAL_REST_REJECTION_OWNER_MASK)
                >> TERMINAL_REST_REJECTION_OWNER_SHIFT
            ]
            if rest_rejection_after_sufficiency
            else None
        )
        self.terminal = {
            "schema_revision": schema,
            "run_sequence": run_sequence,
            "outcome": outcome,
            "outcome_name": ("InconclusiveRest" if outcome == 2 and cause == 53 else outcome_name),
            "outcome_namespace": "stage_c",
            "cause": cause,
            "cause_namespace": cause_namespace,
            "rest_rejection_after_sufficiency": rest_rejection_after_sufficiency,
            "rest_rejection_owner": rest_rejection_owner,
            "forward_eligible_mask": forward_eligible_mask,
            "reverse_eligible_mask": reverse_eligible_mask,
            "bookend_available_mask": bookend_available_mask,
            "current_terminus_plus_one": current_terminus_plus_one,
        }
        self.reproduction = (
            {
                "forward": {
                    "reproduced_mask": forward_reproduced_mask,
                    "divergent_mask": forward_divergent_mask,
                },
                "reverse": {
                    "reproduced_mask": reverse_reproduced_mask,
                    "divergent_mask": reverse_divergent_mask,
                },
            }
            if reproduction_available
            else None
        )
        self.outcome = outcome_name
        self.done = True

    def _finish_plan(self) -> None:
        core, geometry, timing, travel, recovery = self._plan_parts
        plan = self._merge((core, geometry, timing, travel, recovery))
        plan["plan_digest"] = self._reported_plan_digest(core)
        plan["stage_b_plan_digest"] = _u64(core["stage_b_digest_low"], core["stage_b_digest_high"])
        plan["authorities"] = list(self._authorities)
        plan["positive_i"] = [int(rung["i_raw"]) for rung in self._plan_rungs]
        plan["rungs"] = list(self._plan_rungs)
        if int(plan["schema_revision"]) >= 6:
            plan["recovery_quantization_exposed"] = bool(
                int(plan["flags"]) & PLAN_RECOVERY_QUANTIZATION_EXPOSED
            )
            plan["slot_order"] = (
                int(plan["flags"]) & PLAN_SLOT_ORDER_MASK
            ) >> PLAN_SLOT_ORDER_SHIFT
            plan["mirrored_slot_order"] = plan["slot_order"] == SLOT_ORDER_REVERSE_FIRST
        if int(plan["schema_revision"]) >= 7:
            plan["probe_constrained_test_point"] = bool(
                int(plan["flags"]) & PLAN_PROBE_CONSTRAINED_TEST_POINT
            )
        if int(plan["schema_revision"]) >= 8:
            # Every reachable schema here is >= BREAKAWAY_STAGE_C_MIN_SCHEMA_REVISION
            # (handle_plan_core no longer admits the classic combined range 8-13).
            # The breakaway campaign's velocity-integral continuation has no
            # reproduced breakaway sweep plan to pair against -- it is authorized
            # by the accepted confirmation digest instead (see
            # BreakawayCampaignAssembler), not by a breakaway/velocity-integral
            # schema pairing. Only the workflow shape is exclusive here.
            #
            # A resume replays that same exact plan from retained authority, so it
            # carries the breakaway schema under the resume shape. The campaign is
            # no longer the only way to reach schema 14.
            workflow_shape = int(self.workflow_plan["shape"])
            if workflow_shape not in (SHAPE_BREAKAWAY_SEEDED, SHAPE_RESUME):
                raise VelocityIntegralProtocolError(
                    "breakaway velocity-integral plan requires breakaway workflow"
                )
        self.plan = plan

    @staticmethod
    def _require_fragment(params: dict, expected: int) -> None:
        if int(params.get("fragment", -1)) != expected:
            raise VelocityIntegralProtocolError("fragment identity mismatch")

    def _require_stage_c_workflow(self, params: dict) -> None:
        if self.workflow_plan is None:
            raise VelocityIntegralProtocolError("plan core preceded workflow plan")
        self._require_run(params)

    def _require_plan_step(self, expected: str, count: int) -> None:
        if len(self._plan_parts) != count:
            raise VelocityIntegralProtocolError(f"plan step requires {expected}")

    def _require_plan_identity(self, params: dict) -> None:
        self._require_run(params)
        if int(params.get("evidence_sequence", -1)) != 0:
            raise VelocityIntegralProtocolError("integral-response plan sequence is not zero")

    def _require_run(self, params: dict) -> None:
        if self._run_sequence is None or int(params.get("run_sequence", -1)) != self._run_sequence:
            raise VelocityIntegralProtocolError("run sequence changed")

    @staticmethod
    def _reported_plan_digest(params: dict) -> int:
        return _u64(params["plan_digest_low"], params["plan_digest_high"])

    @staticmethod
    def _merge(parts) -> dict:
        merged = {}
        for part in parts:
            for key, value in _metadata_free(part).items():
                if key in merged and merged[key] != value:
                    raise VelocityIntegralProtocolError(f"fragment metadata differs for {key}")
                merged[key] = value
        return merged


# ============================================================================
# Breakaway-seeded campaign reporting
# ============================================================================
#
# The breakaway campaign
# (VelocityAutotuneWorkflowKind.BreakawaySeededProportionalThenIntegral = 3) is a
# three-phase acquisition -- a physical-excursion upward probe, an additive
# discovery ladder, and a held-out eight-stroke confirmation block -- that
# firmware runs entirely on its own authority before, on acceptance, handing
# off into the existing velocity-integral flow above (schema 14,
# handled by VelocityIntegralAssembler already). BreakawayCampaignAssembler
# below covers only the campaign's own evidence: it validates the firmware's
# digest chain (each phase's plan names the prior phase's digest) and the
# wire's own internal structure (direction codes, monotonic indices, interval
# ordering, mask subset relationships), and otherwise relays every firmware
# value unchanged. It never selects a rung, changes a family size, retries a
# candidate, or synthesizes a value firmware did not send -- see
# tests/test_velocity_integral.py's dumb-host proof tests.

STAGE_C_CAUSE_EVIDENCE_INTEGRITY = 4
STAGE_C_CAUSE_REPRODUCTION_MISMATCH = 6
STAGE_C_CAUSE_PLAN_MISMATCH = 7
STAGE_C_CAUSE_NO_TRANSITION_CAPABLE_OPERATING_POINT = 11
STAGE_C_CAUSE_NO_RETAINED_AUTHORITY = 12

# A velocity-integral terminal's `cause` number is only unambiguous once paired with
# `cause_namespace`: the engine, error, and dispatch producers each number
# their own causes independently and can emit the same raw value.
STAGE_C_CAUSE_NAMESPACE_NAMES = {0: "engine", 1: "error", 2: "dispatch"}
STAGE_C_CAUSE_DISPATCH_NAMESPACE = 2

# Dispatch-namespace causes attached to a velocity-integral terminal.
STAGE_C_TERMINAL_CAUSE_NAMES = {
    STAGE_C_CAUSE_EVIDENCE_INTEGRITY: "evidence_integrity",
    STAGE_C_CAUSE_REPRODUCTION_MISMATCH: "reproduction_mismatch",
    STAGE_C_CAUSE_PLAN_MISMATCH: "plan_mismatch",
    STAGE_C_CAUSE_NO_TRANSITION_CAPABLE_OPERATING_POINT: ("no_transition_capable_operating_point"),
    STAGE_C_CAUSE_NO_RETAINED_AUTHORITY: "no_retained_velocity_integral_authority",
}

# Causes a velocity-integral terminal may carry when it arrives with no exact plan: the
# probe clamp left no operating point, the request disagreed with what was
# retained, or there was nothing retained to resume. Every other cause implies a
# plan the assembler should already have seen.
STAGE_C_FAILED_ADMISSION_CAUSES = frozenset(
    (
        STAGE_C_CAUSE_PLAN_MISMATCH,
        STAGE_C_CAUSE_NO_TRANSITION_CAPABLE_OPERATING_POINT,
        STAGE_C_CAUSE_NO_RETAINED_AUTHORITY,
    )
)

STAGE_C_TERMINAL_CAUSE_REMEDIATION = {
    STAGE_C_CAUSE_NO_RETAINED_AUTHORITY: (
        "no retained velocity-integral authority; run a campaign first, in this power cycle"
    ),
    STAGE_C_CAUSE_PLAN_MISMATCH: (
        "request does not reproduce the retained velocity-integral plan; reissue with the "
        "parameters the campaign ran with, or run a new campaign"
    ),
}

BREAKAWAY_TERMINAL_CAUSE_NAMES = {
    0: "none",
    1: "probe_no_repeatable_motion_at_authority",
    5: "probe_authority_failure",
    6: "probe_safety_fault",
    7: "discovery_target_band_skipped",
    8: "discovery_current_headroom_before_band",
    9: "discovery_insufficient_additive_span",
    10: "discovery_additive_ladder_resolution_budget_exceeded",
    11: "discovery_evidence_excluded",
    12: "discovery_safety_fault",
    13: "confirmation_target_band_unconfirmable_from_discovery",
    14: "confirmation_target_band_not_reached_at_authority",
    15: "confirmation_response_location",
    16: "confirmation_excessive_uncertainty",
    17: "confirmation_loss_of_consensus",
    18: "confirmation_current_authority",
    19: "confirmation_evidence_excluded",
    20: "confirmation_safety_fault",
    21: "accepted",
    22: "probe_excursion_evidence_invalid",
    23: "probe_internal_fault",
    24: "discovery_internal_fault",
    25: "confirmation_internal_fault",
    26: "confirmation_stage_c_plan_refused",
    27: "confirmation_no_transition_capable_candidate",
}

# Advisory text only -- relays what the disclosed cause means, not a
# host-computed remedy.
BREAKAWAY_TERMINAL_REMEDIATION = {
    1: "no rung showed repeatable motion within the probe's authority; check current limits",
    5: "probe authority was exhausted before repeatable motion resolved",
    6: "probe stopped on a safety fault; inspect retained safety evidence",
    7: "discovery skipped the target band; inspect the resolved ladder",
    8: "current headroom ended discovery before the target band; review headroom",
    9: "the additive span between breakaway and ceiling was insufficient",
    10: "the additive ladder exceeded its resolution budget",
    11: "discovery evidence was excluded; retain the trace and inspect stationarity",
    12: (
        "discovery stopped on a safety fault; any in-band rungs already retained "
        "are diagnostic only and were not confirmed -- inspect the retained safety "
        "evidence, then re-commission to retry"
    ),
    13: "no discovery rung could be confirmed; inspect the nomination margins",
    14: "the target band was not reached at the discovery authority ceiling",
    15: "the confirmed response left the 70-80% band; inspect confirmation bounds",
    16: "confirmation uncertainty exceeded the containable range",
    17: "forward and reverse confirmation strokes lost consensus",
    18: "confirmation ended on current authority instead of the target band",
    19: "confirmation evidence was excluded; retain the trace and inspect stationarity",
    20: "confirmation stopped on a safety fault; inspect retained safety evidence",
    22: "probe excursion evidence was invalid; inspect the retained trace checkpoint",
}

FLOOR_ORIGIN_NAMES = {0: "predecessor", 1: "clamped_at_breakaway"}
CEILING_BINDING_SOURCE_NAMES = {0: "current_limit", 1: "representability_clamp"}

# Firmware's `combined_plan::BREAKAWAY_STAGE_B_SCHEMA_REVISION`: the only
# discovery-plan-geometry schema this host currently understands.
# Current firmware revisions, used when this host authors a request.
BREAKAWAY_DISCOVERY_SCHEMA_REVISION = 17
BREAKAWAY_STAGE_C_SCHEMA_REVISION = 18
# First revision of each breakaway stream. These are boundaries, not sets: every
# revision at or above them is a breakaway plan. Stage-C 8-13 was the classic
# combined schema range; firmware never emits it after Stage 2, and
# handle_plan_core no longer admits it. The upper end stays bounded by the
# current revision above, so a stream from firmware newer than this host is
# refused rather than mis-parsed against rules that may no longer hold.
BREAKAWAY_DISCOVERY_MIN_SCHEMA_REVISION = 15
BREAKAWAY_STAGE_C_MIN_SCHEMA_REVISION = 14

BREAKAWAY_PROBE_MAX_OBSERVATIONS = 128
BREAKAWAY_PROBE_MAX_CAPTURE_INTERVAL_US = 2_000
BREAKAWAY_PROBE_MAX_SEARCH_RUNGS = 32


class BreakawayCampaignProtocolError(Exception):
    """Raised when breakaway-campaign evidence violates its wire contract."""


class BreakawayCampaignAssembler:
    """Strictly relay one firmware-authored breakaway-campaign report.

    This assembler never decides anything: it validates that each phase's
    plan names the previous phase's exact digest, that individual records are
    internally well-formed (ordering, interval and mask
    sanity), and that a batch's declared count matches the records actually
    received -- then stores every firmware value unchanged for the operator
    report. No rung, family size, candidate, or retry is ever chosen here.
    """

    def __init__(self) -> None:
        self.probe_plan: dict | None = None
        self.probe_result: dict | None = None
        self.probe_terminal: dict | None = None
        self.discovery_plan: dict | None = None
        self.discovery_ceiling_source: dict | None = None
        self.discovery_rung_zero: dict | None = None
        self.discovery_terminal: dict | None = None
        self.confirmation_plan: dict | None = None
        self.confirmation_terminal: dict | None = None
        self.campaign_terminal: dict | None = None
        self.accepted = False
        self.stage_c_plan_digest: int | None = None
        self.done = False
        self._run_sequence: int | None = None
        self._last_evidence_sequence: int | None = None
        self._discovery_identity: dict | None = None
        self._confirmation_terminal_identity: dict | None = None

    # -- shared identity/sequence plumbing ---------------------------------

    def _bind_run(self, params: dict) -> None:
        if self._run_sequence is not None:
            raise BreakawayCampaignProtocolError("duplicate probe plan")
        run_sequence = int(params.get("run_sequence", -1))
        if run_sequence < 0:
            raise BreakawayCampaignProtocolError("missing run sequence")
        self._run_sequence = run_sequence

    def _require_run(self, params: dict) -> None:
        if self._run_sequence is None or int(params.get("run_sequence", -1)) != self._run_sequence:
            raise BreakawayCampaignProtocolError("run sequence changed")

    def _track_sequence(self, params: dict) -> int:
        self._require_run(params)
        sequence = int(params.get("evidence_sequence", -1))
        if sequence < 0:
            raise BreakawayCampaignProtocolError("missing evidence sequence")
        if self._last_evidence_sequence is not None and sequence < self._last_evidence_sequence:
            raise BreakawayCampaignProtocolError("evidence sequence went backwards")
        self._last_evidence_sequence = sequence
        return sequence

    @staticmethod
    def _reported_plan_digest(params: dict) -> int:
        return _u64(params["plan_digest_low"], params["plan_digest_high"])

    def _require_probe_plan(self, params: dict) -> None:
        if self.probe_plan is None:
            raise BreakawayCampaignProtocolError("breakaway evidence arrived before the probe plan")
        self._require_run(params)

    def _require_probe_resolved(self, params: dict) -> None:
        self._require_probe_plan(params)
        if self.probe_result is None or self.probe_terminal is not None:
            raise BreakawayCampaignProtocolError(
                "discovery evidence arrived without a resolved probe breakaway"
            )

    def _require_discovery_plan(self, params: dict) -> None:
        if self.discovery_plan is None:
            raise BreakawayCampaignProtocolError(
                "breakaway evidence arrived before the discovery plan"
            )
        self._require_run(params)

    def _require_confirmation_plan(self, params: dict) -> None:
        if self.confirmation_plan is None:
            raise BreakawayCampaignProtocolError(
                "breakaway evidence arrived before the confirmation plan"
            )
        self._require_run(params)

    # The live host no longer reconciles per-stroke confirmation evidence:
    # the per-stroke observation replies were removed, so it validates
    # only the confirmation terminal's own mask structure (in
    # handle_confirmation_terminal_masks). foci-trace owns per-stroke and
    # collected-mask reconciliation from the canonical trace.

    # -- probe phase ---------------------------------------------------------

    def handle_probe_plan(self, params: dict) -> None:
        if self.probe_plan is not None:
            raise BreakawayCampaignProtocolError("duplicate probe plan")
        self._bind_run(params)
        if int(params.get("evidence_sequence", -1)) != 0:
            raise BreakawayCampaignProtocolError("probe plan sequence is not zero")
        self._last_evidence_sequence = 0
        max_observations = int(params["max_observations"])
        if max_observations != BREAKAWAY_PROBE_MAX_OBSERVATIONS:
            raise BreakawayCampaignProtocolError(
                "probe observation budget is not the fixed 128-stroke contract"
            )
        search_count = int(params["search_count"])
        if not 1 <= search_count <= BREAKAWAY_PROBE_MAX_SEARCH_RUNGS:
            raise BreakawayCampaignProtocolError("empty probe search grid")
        if not 0 < int(params["p_start_raw"]) <= int(params["p_top_raw"]):
            raise BreakawayCampaignProtocolError("reversed probe search grid")
        if int(params["motion_threshold_counts"]) <= 0:
            raise BreakawayCampaignProtocolError("zero probe motion threshold")
        if int(params["max_capture_interval_us"]) != BREAKAWAY_PROBE_MAX_CAPTURE_INTERVAL_US:
            raise BreakawayCampaignProtocolError(
                "probe capture interval does not match the fixed contract"
            )
        if self._reported_plan_digest(params) == 0:
            raise BreakawayCampaignProtocolError("zero probe plan digest")
        self.probe_plan = _metadata_free(params)
        self.probe_plan["plan_digest"] = self._reported_plan_digest(params)

    def handle_probe_result(self, params: dict) -> None:
        self._require_probe_plan(params)
        if self.probe_result is not None:
            raise BreakawayCampaignProtocolError("duplicate probe result")
        if self.probe_terminal is not None:
            raise BreakawayCampaignProtocolError(
                "probe result arrived after a probe failure terminal"
            )
        if self._track_sequence(params) == 0:
            raise BreakawayCampaignProtocolError("probe result sequence is not after the plan")
        if self._reported_plan_digest(params) != self.probe_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError("probe result plan digest mismatch")
        rung_index = int(params["rung_index"])
        if not 0 <= rung_index < int(self.probe_plan["search_count"]):
            raise BreakawayCampaignProtocolError("probe result rung is outside the search grid")
        breakaway = int(params["breakaway_p_raw"])
        if (
            not int(self.probe_plan["p_start_raw"])
            <= breakaway
            <= int(self.probe_plan["p_top_raw"])
        ):
            raise BreakawayCampaignProtocolError("probe result gain is outside the search grid")
        if int(params["motion_threshold_counts"]) != int(
            self.probe_plan["motion_threshold_counts"]
        ):
            raise BreakawayCampaignProtocolError("probe result motion threshold mismatch")
        observations = int(params["observation_count"])
        if not 1 <= observations <= int(self.probe_plan["max_observations"]):
            raise BreakawayCampaignProtocolError("invalid probe result observation count")
        self.probe_result = _metadata_free(params)

    def handle_probe_terminal(self, params: dict) -> None:
        self._require_probe_plan(params)
        if self.probe_terminal is not None:
            raise BreakawayCampaignProtocolError("duplicate probe terminal")
        if self.probe_result is not None:
            raise BreakawayCampaignProtocolError(
                "probe terminal arrived after a resolved breakaway"
            )
        self._track_sequence(params)
        if self._reported_plan_digest(params) != self.probe_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError("probe terminal plan digest mismatch")
        cause = int(params["terminal_cause"])
        if cause not in BREAKAWAY_TERMINAL_CAUSE_NAMES or cause == 0:
            raise BreakawayCampaignProtocolError("invalid probe terminal cause")
        self.probe_terminal = _metadata_free(params)

    # -- discovery phase -------------------------------------------------

    def handle_discovery_plan_identity(self, params: dict) -> None:
        if self._discovery_identity is not None or self.discovery_plan is not None:
            raise BreakawayCampaignProtocolError("duplicate discovery plan identity")
        self._require_probe_resolved(params)
        self._track_sequence(params)
        prior = _u64(params["prior_plan_digest_low"], params["prior_plan_digest_high"])
        if prior != self.probe_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError(
                "discovery plan does not chain from the probe plan"
            )
        self._discovery_identity = _metadata_free(params)
        self._discovery_identity["plan_digest"] = self._reported_plan_digest(params)

    def handle_discovery_plan_geometry(self, params: dict) -> None:
        if self._discovery_identity is None:
            raise BreakawayCampaignProtocolError("discovery geometry preceded discovery identity")
        if self.discovery_plan is not None:
            raise BreakawayCampaignProtocolError("duplicate discovery plan geometry")
        self._require_run(params)
        if int(params.get("evidence_sequence", -1)) != int(
            self._discovery_identity["evidence_sequence"]
        ):
            raise BreakawayCampaignProtocolError(
                "discovery geometry evidence sequence does not match its identity"
            )
        if not (
            BREAKAWAY_DISCOVERY_MIN_SCHEMA_REVISION
            <= int(params["schema_revision"])
            <= BREAKAWAY_DISCOVERY_SCHEMA_REVISION
        ):
            raise BreakawayCampaignProtocolError("unsupported breakaway discovery evidence schema")
        floor = int(params["floor_p_raw"])
        breakaway = int(params["breakaway_p_raw"])
        ceiling = int(params["ceiling_p_raw"])
        if not floor <= breakaway <= ceiling:
            raise BreakawayCampaignProtocolError(
                "discovery geometry gains are not ordered floor<=breakaway<=ceiling"
            )
        if breakaway != int(self.probe_result["breakaway_p_raw"]):
            raise BreakawayCampaignProtocolError(
                "discovery breakaway gain does not match the probe result"
            )
        if int(params["rung_count"]) < 1:
            raise BreakawayCampaignProtocolError("empty discovery ladder")
        if int(params["floor_origin"]) not in FLOOR_ORIGIN_NAMES:
            raise BreakawayCampaignProtocolError("invalid discovery floor origin")
        if int(params["maximum_workflow_ms"]) == 0:
            raise BreakawayCampaignProtocolError("zero discovery workflow reservation")
        self.discovery_plan = {**self._discovery_identity, **_metadata_free(params)}
        self._discovery_identity = None

    def handle_discovery_ceiling_source(self, params: dict) -> None:
        self._require_discovery_plan(params)
        if self.discovery_ceiling_source is not None:
            raise BreakawayCampaignProtocolError("duplicate discovery ceiling source")
        if self._reported_plan_digest(params) != self.discovery_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError("discovery ceiling source plan digest mismatch")
        if int(params["binding_source"]) not in CEILING_BINDING_SOURCE_NAMES:
            raise BreakawayCampaignProtocolError("invalid discovery ceiling binding source")
        self.discovery_ceiling_source = _metadata_free(params)

    def handle_discovery_rung_zero_diagnostic(self, params: dict) -> None:
        self._require_discovery_plan(params)
        if self.discovery_terminal is not None:
            raise BreakawayCampaignProtocolError(
                "rung-zero diagnostic arrived after the discovery terminal"
            )
        if self.discovery_rung_zero is not None:
            raise BreakawayCampaignProtocolError("duplicate rung-zero diagnostic")
        if self._reported_plan_digest(params) != self.discovery_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError("rung-zero diagnostic plan digest mismatch")
        self.discovery_rung_zero = _metadata_free(params)

    def handle_discovery_terminal(self, params: dict) -> None:
        self._require_discovery_plan(params)
        if self.discovery_terminal is not None:
            raise BreakawayCampaignProtocolError("duplicate discovery terminal")
        prior = _u64(params["prior_plan_digest_low"], params["prior_plan_digest_high"])
        if prior != self.probe_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError(
                "discovery terminal does not chain from the probe plan"
            )
        if self._reported_plan_digest(params) != self.discovery_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError("discovery terminal plan digest mismatch")
        cause = int(params["terminal_cause"])
        if cause not in BREAKAWAY_TERMINAL_CAUSE_NAMES:
            raise BreakawayCampaignProtocolError("invalid discovery terminal cause")
        self.discovery_terminal = _metadata_free(params)

    # -- confirmation phase ------------------------------------------------

    def handle_confirmation_plan(self, params: dict) -> None:
        if self.discovery_plan is None:
            raise BreakawayCampaignProtocolError(
                "confirmation plan arrived before the discovery plan"
            )
        if self.confirmation_plan is not None:
            raise BreakawayCampaignProtocolError("duplicate confirmation plan")
        self._require_run(params)
        prior = _u64(params["prior_plan_digest_low"], params["prior_plan_digest_high"])
        if prior != self.discovery_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError(
                "confirmation plan does not chain from the discovery plan"
            )
        family_size = int(params["family_size"])
        observations_per_direction = int(params["observations_per_direction"])
        if family_size != 2 * observations_per_direction:
            raise BreakawayCampaignProtocolError(
                "confirmation family size does not match the observation budget"
            )
        lower = int(params["band_lower_percent"])
        upper = int(params["band_upper_percent"])
        if not 0 <= lower < upper <= 100:
            raise BreakawayCampaignProtocolError("invalid confirmation band")
        self.confirmation_plan = _metadata_free(params)
        self.confirmation_plan["plan_digest"] = self._reported_plan_digest(params)

    def handle_confirmation_terminal_identity(self, params: dict) -> None:
        self._require_confirmation_plan(params)
        if self.confirmation_terminal is not None or (
            self._confirmation_terminal_identity is not None
        ):
            raise BreakawayCampaignProtocolError("duplicate confirmation terminal identity")
        prior = _u64(params["prior_plan_digest_low"], params["prior_plan_digest_high"])
        if prior != self.discovery_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError(
                "confirmation terminal does not chain from the discovery plan"
            )
        if self._reported_plan_digest(params) != self.confirmation_plan["plan_digest"]:
            raise BreakawayCampaignProtocolError(
                "confirmation terminal identity plan digest mismatch"
            )
        cause = int(params["terminal_cause"])
        if cause not in BREAKAWAY_TERMINAL_CAUSE_NAMES:
            raise BreakawayCampaignProtocolError("invalid confirmation terminal cause")
        self._confirmation_terminal_identity = _metadata_free(params)

    def handle_confirmation_terminal_masks(self, params: dict) -> None:
        if self._confirmation_terminal_identity is None:
            raise BreakawayCampaignProtocolError(
                "confirmation terminal masks preceded its identity"
            )
        if self.confirmation_terminal is not None:
            raise BreakawayCampaignProtocolError("duplicate confirmation terminal masks")
        self._require_run(params)
        for prefix in ("forward", "reverse"):
            collected = int(params[f"{prefix}_collected_mask"])
            eligible = int(params[f"{prefix}_eligible_mask"])
            included = int(params[f"{prefix}_included_mask"])
            for mask in (collected, eligible, included):
                if mask & ~0b1111:
                    raise BreakawayCampaignProtocolError(
                        "confirmation mask exceeds the four-observation schedule"
                    )
            if eligible & ~collected:
                raise BreakawayCampaignProtocolError(
                    "confirmation eligible mask exceeds its collected mask"
                )
            if included & ~eligible:
                raise BreakawayCampaignProtocolError(
                    "confirmation included mask exceeds its eligible mask"
                )
        accepted = int(params["accepted"])
        if accepted not in (0, 1):
            raise BreakawayCampaignProtocolError("invalid confirmation accepted flag")
        confirmed_p_raw = int(params["confirmed_p_raw"])
        if bool(accepted) != (confirmed_p_raw != 0):
            raise BreakawayCampaignProtocolError(
                "confirmation accepted flag disagrees with the confirmed gain"
            )
        self.confirmation_terminal = {
            **self._confirmation_terminal_identity,
            **_metadata_free(params),
        }
        self._confirmation_terminal_identity = None

    # Per-stroke raw-observation replies were removed: the family-free
    # mean/variance/target inputs and the frozen classify/consensus inputs are
    # detailed trace-only evidence that foci-trace decodes and reconstructs. The
    # live host neither receives nor relays them.

    # -- campaign closure ----------------------------------------------------

    def handle_campaign_terminal(self, params: dict) -> None:
        self._require_run(params)
        if self.campaign_terminal is not None:
            raise BreakawayCampaignProtocolError("duplicate campaign terminal")
        phase = int(params.get("phase", -1))
        if phase not in BREAKAWAY_PHASE_NAMES:
            raise BreakawayCampaignProtocolError("invalid campaign terminal phase")
        terminal_cause = int(params.get("terminal_cause", -1))
        if terminal_cause not in BREAKAWAY_TERMINAL_CAUSE_NAMES:
            raise BreakawayCampaignProtocolError("invalid campaign terminal cause")
        accepted = int(params.get("accepted", -1))
        if accepted not in (0, 1):
            raise BreakawayCampaignProtocolError("invalid campaign accepted flag")
        digest = _u64(params["stage_c_plan_digest_low"], params["stage_c_plan_digest_high"])
        if bool(accepted) != (digest != 0):
            raise BreakawayCampaignProtocolError(
                "campaign accepted flag disagrees with the velocity-integral plan digest"
            )
        confirmation_accepted = bool(int((self.confirmation_terminal or {}).get("accepted", 0)))
        # A confirmed acceptance whose velocity-integral plan build was refused
        # legitimately leaves accepted=False with a confirmed confirmation
        # terminal -- confirmation and velocity-integral admission are
        # deliberately separate, stacked gates. Only the reverse direction (a
        # velocity-integral plan materializing without a confirmed acceptance) is
        # structurally impossible and remains a genuine protocol violation.
        # The message text is unchanged from before this fix (only the
        # *condition* narrowed from symmetric to one-directional) so it keeps
        # matching `test_breakaway_campaign_terminal_requires_agreement_with_confirmation`'s
        # existing `match="own acceptance"` assertion in test_velocity_integral.py.
        if accepted and self.confirmation_terminal is not None and not confirmation_accepted:
            raise BreakawayCampaignProtocolError(
                "campaign terminal disagrees with the confirmation terminal's own acceptance"
            )
        self.campaign_terminal = _metadata_free(params)
        self.accepted = bool(accepted)
        self.stage_c_plan_digest = digest
        self.done = True
