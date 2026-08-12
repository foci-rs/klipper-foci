"""Reassemble firmware-authored velocity-integral response evidence."""

from __future__ import annotations

import struct

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
# mirrored order. Firmware records this without moving the Stage-C schema, so
# unlike the older bits it is accepted at every schema revision.
PLAN_SLOT_ORDER_SHIFT = 2
PLAN_SLOT_ORDER_MASK = 0b11 << PLAN_SLOT_ORDER_SHIFT

SLOT_ORDER_FORWARD_FIRST = 0
SLOT_ORDER_REVERSE_FIRST = 1
SLOT_ORDER_PAIRED_OUT_AND_BACK = 2


def slot_direction_index(slot_order: int, slot: int) -> int:
    """Return 0 for forward and 1 for reverse travel in the declared order.

    The three orders differ only in a parity twist applied to the same-direction
    observation ordinal: none for forward-first, a fixed inversion for
    reverse-first, and an alternating one for the paired F,R,R,F order.
    """
    if slot_order == SLOT_ORDER_FORWARD_FIRST:
        twist = 0
    elif slot_order == SLOT_ORDER_REVERSE_FIRST:
        twist = 1
    elif slot_order == SLOT_ORDER_PAIRED_OUT_AND_BACK:
        twist = (slot >> 1) & 1
    else:
        raise VelocityIntegralProtocolError("unknown observation slot order")
    return (slot & 1) ^ twist


TERMINAL_RECOVERY_UNAVAILABLE = 1 << 0
TERMINAL_RECOVERED_WITH_CURRENT_HEADROOM = 1 << 1
TERMINAL_RECOVERY_QUANTIZATION_EXPOSED = 1 << 2
TERMINAL_PROBE_CONSTRAINED_TEST_POINT = 1 << 3
TERMINAL_COMBINED_TARGET_SHIFT = 4
TERMINAL_COMBINED_TARGET_MASK = 0b111 << TERMINAL_COMBINED_TARGET_SHIFT
TERMINAL_COMBINED_WORKFLOW = 1 << 7
COMBINED_TARGET_NAMES = {
    0: "target_reached",
    1: "target_reached_sparse",
    2: "current_headroom",
    3: "target_not_reached_at_cap",
}
INTEGRAL_CAUSE_TOO_FEW_RUNGS = 1
INTEGRAL_CAUSE_CURRENT_AFTER_SUFFICIENCY = 3
INTEGRAL_CAUSE_BOOKEND_UNAVAILABLE = 8
INTEGRAL_CAUSE_REST_BOUNDARY_AFTER_SUFFICIENCY = 10


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


class VelocityIntegralAssembler:
    """Strictly assemble one firmware-authored integral-response report."""

    # The hidden run before a recovery is 0, 1, or 2 depending on which
    # controller exit was taken; neither the schema revision nor the outcome
    # determines it. See docs/specs/2026-08-04-stage-c-evidence-grammar.md.
    MAXIMUM_RECOVERY_HIDDEN_RUN = 2

    def __init__(self) -> None:
        self.workflow_plan: dict | None = None
        self.plan: dict | None = None
        self.observations: dict[tuple[int, int], dict] = {}
        self.rungs: dict[int, dict] = {}
        self.recoveries: dict[int, dict] = {}
        self.curves = [self._new_curve(), self._new_curve()]
        self.drift: list[dict | None] = [None, None]
        self.stage_b_comparison: list[dict | None] = [None, None]
        self.reproduction: dict | None = None
        self.terminal: dict | None = None
        self.outcome: str | None = None
        self.done = False
        self._plan_parts: list[dict] = []
        self._authorities: list[dict] = []
        self._plan_rungs: list[dict] = []
        self._observation_parts: list[dict] = []
        self._rung_parts: list[dict] = []
        self._terminal_parts: list[dict] = []
        self._last_evidence: tuple[str, int] | None = None
        self._summary: dict | None = None
        self._run_sequence: int | None = None
        self._next_evidence_sequence = 1
        self._trace_only_current_pending = False
        self._ordinary_rest_hidden_positions: int | None = None
        self._combined_stage_b_schema: int | None = None
        self._recovery_rest_pending: tuple[int, int, bool] | None = None

    @staticmethod
    def _new_curve() -> dict:
        return {
            "eligible_mask": 0,
            "opening": None,
            "positive": {},
            "bookend": None,
        }

    @property
    def plan_ready(self) -> bool:
        """Whether the exact Stage-C plan has arrived."""
        return self.plan is not None

    @property
    def maximum_duration_s(self) -> float | None:
        """Firmware-declared command-level maximum duration in seconds."""
        if self.workflow_plan is None:
            return None
        return int(self.workflow_plan["maximum_workflow_ms"]) / 1000.0

    @property
    def combined_stage_b_schema(self) -> int | None:
        """Return the Stage-B compatibility revision bound to this combined plan."""
        return self._combined_stage_b_schema

    def bind_combined_stage_b_schema(self, schema_revision: int) -> None:
        """Bind a combined Stage-C plan to its already assembled Stage-B plan."""
        if self._plan_parts or self.plan is not None:
            raise VelocityIntegralProtocolError(
                "combined Stage-B schema arrived after Stage-C evidence"
            )
        if schema_revision not in (8, 10, 11, 12, 13, 14):
            raise VelocityIntegralProtocolError("unsupported combined Stage-B schema")
        if (
            self._combined_stage_b_schema is not None
            and self._combined_stage_b_schema != schema_revision
        ):
            raise VelocityIntegralProtocolError("combined Stage-B schema changed")
        self._combined_stage_b_schema = schema_revision

    @property
    def report(self) -> dict:
        """Return the assembled absolute and reproduction evidence."""
        return {
            "workflow_plan": self.workflow_plan,
            "plan": self.plan,
            "absolute_curves": self.curves,
            "recoveries": self.recoveries,
            "drift": self.drift,
            "stage_b_comparison": self.stage_b_comparison,
            "reproduction": self.reproduction,
            "terminal": self.terminal,
        }

    @property
    def summary(self) -> dict | None:
        """Return the firmware-authored run summary when available."""
        return self._summary

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
        if shape not in (0, 1, 2, 3, 6):
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
            8,
            9,
            10,
            11,
            12,
            13,
            14,
            15,
            16,
        ):
            raise VelocityIntegralProtocolError("unsupported Stage-C evidence schema")
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
            raise VelocityIntegralProtocolError("reversed Stage-B authority interval")
        if int(params.get("directional_validity", -1)) not in range(5):
            raise VelocityIntegralProtocolError("invalid Stage-B directional validity")
        if int(params.get("reduced_margin", -1)) not in (0, 1):
            raise VelocityIntegralProtocolError("invalid Stage-B reduced-margin flag")
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

    def handle_recovery_summary(self, params: dict) -> None:
        """Accept one compact recovery summary after its causal evidence."""
        self._require_plan()
        if int(params.get("stage", -1)) != 1:
            raise VelocityIntegralProtocolError("Stage-C recovery summary named the wrong stage")
        self._require_run(params)
        rung_index = int(params.get("rung_index", -1))
        if rung_index in self.recoveries:
            raise VelocityIntegralProtocolError("duplicate rung recovery")
        outcome = int(params.get("outcome", -1))
        self._require_recovery_identity(params, rung_index, outcome)
        follows_rung = self._last_evidence == ("rung", rung_index)
        observation_count = sum(
            observation_rung == rung_index for observation_rung, _slot in self.observations
        )
        follows_partial_positive = (
            int(self.plan["schema_revision"]) >= 5
            and self._last_evidence == ("observation", rung_index)
            and rung_index in range(1, int(self.plan["positive_rung_count"]) + 1)
            and observation_count in range(1, 8)
        )
        if not follows_rung and not follows_partial_positive:
            raise VelocityIntegralProtocolError(
                "recovery did not immediately follow its causal evidence"
            )
        if int(params.get("p_raw", -1)) != int(self.plan["final_p"]):
            raise VelocityIntegralProtocolError("recovery summary changed fixed P")
        if int(params.get("binding_source", -1)) not in range(7):
            raise VelocityIntegralProtocolError("invalid recovery binding source")
        maximum_outcome = 5 if int(self.plan["schema_revision"]) >= 6 else 4
        if outcome not in range(maximum_outcome + 1):
            raise VelocityIntegralProtocolError("invalid recovery outcome")
        self.recoveries[rung_index] = _metadata_free(params)
        self._next_evidence_sequence += 1
        self._last_evidence = ("recovery", rung_index)
        self._recovery_rest_pending = None

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

    def handle_observation_core(self, params: dict) -> None:
        self._require_plan()
        if self._observation_parts:
            raise VelocityIntegralProtocolError("observation interrupted prior group")
        self._require_event_identity(params)
        self._require_fragment(params, 0)
        if self._reported_plan_digest(params) != int(self.plan["plan_digest"]):
            raise VelocityIntegralProtocolError("observation plan digest mismatch")
        self._observation_parts.append(dict(params))

    def handle_observation_rate(self, params: dict) -> None:
        self._accept_observation_part(params, 1)

    def handle_observation_quality(self, params: dict) -> None:
        self._accept_observation_part(params, 2)
        self._finish_observation()

    def handle_rung_core(self, params: dict) -> None:
        self._require_plan()
        self._require_event_identity(params)
        direction = int(params.get("direction", -1))
        if direction not in (0, 1) or int(params.get("fragment", -1)) != direction:
            raise VelocityIntegralProtocolError("invalid rung direction fragment")
        expected_direction = 0 if not self._rung_parts else 1
        if direction != expected_direction:
            raise VelocityIntegralProtocolError("reordered rung direction")
        if direction == 1 and not self._rung_direction_complete(0):
            raise VelocityIntegralProtocolError("reverse rung preceded forward components")
        self._rung_parts.append(dict(params))
        if int(params["component_count"]) == 0:
            self._finish_rung_if_complete()

    def handle_rung_component(self, params: dict) -> None:
        if not self._rung_parts:
            raise VelocityIntegralProtocolError("rung component preceded core")
        self._require_event_identity(params)
        direction = int(params.get("direction", -1))
        cores = [part for part in self._rung_parts if "classification" in part]
        if not cores or int(cores[-1]["direction"]) != direction:
            raise VelocityIntegralProtocolError("rung component direction mismatch")
        component = int(params.get("component", -1))
        received = sum(
            1
            for part in self._rung_parts
            if "component" in part and int(part["direction"]) == direction
        )
        if component != received or component >= int(cores[-1]["component_count"]):
            raise VelocityIntegralProtocolError("reordered or extra rung component")
        if int(params["low_q"]) > int(params["high_q"]):
            raise VelocityIntegralProtocolError("reversed rung component")
        self._rung_parts.append(dict(params))
        self._finish_rung_if_complete()

    def handle_run_summary(self, params: dict) -> None:
        self._require_terminal_identity(params, allow_recovery_rest=True)
        if self._summary is not None:
            raise VelocityIntegralProtocolError("duplicate run summary")
        self._require_fragment(params, 0)
        if int(params.get("opening_available_mask", -1)) & ~0b11:
            raise VelocityIntegralProtocolError("invalid opening availability mask")
        if int(params.get("bookend_available_mask", -1)) & ~0b11:
            raise VelocityIntegralProtocolError("invalid bookend availability mask")
        self._summary = _metadata_free(params)
        for direction, key in enumerate(("forward_eligible_mask", "reverse_eligible_mask")):
            mask = int(params[key])
            self._validate_mask(mask)
            self.curves[direction]["eligible_mask"] = mask

    def handle_curve_interval(self, params: dict) -> None:
        self._require_summary(params)
        direction = self._direction(params)
        kind = int(params.get("kind", -1))
        interval = self._interval(params)
        curve = self.curves[direction]
        if kind == 0:
            key = "opening"
            if curve[key] is not None:
                raise VelocityIntegralProtocolError("duplicate opening interval")
            curve[key] = interval
        elif kind == 1:
            rung = int(params["rung_index"])
            if not curve["eligible_mask"] & (1 << rung):
                raise VelocityIntegralProtocolError("curve interval is outside eligible mask")
            if rung in curve["positive"]:
                raise VelocityIntegralProtocolError("duplicate positive curve interval")
            curve["positive"][rung] = interval
        elif kind == 2:
            if curve["bookend"] is not None:
                raise VelocityIntegralProtocolError("duplicate bookend interval")
            curve["bookend"] = interval
        else:
            raise VelocityIntegralProtocolError("invalid curve interval kind")

    def handle_drift(self, params: dict) -> None:
        self._require_summary(params)
        direction = self._direction(params)
        if self.drift[direction] is not None:
            raise VelocityIntegralProtocolError("duplicate drift record")
        self.drift[direction] = _metadata_free(params)

    def handle_stage_b_comparison(self, params: dict) -> None:
        self._require_summary(params)
        direction = self._direction(params)
        if self.stage_b_comparison[direction] is not None:
            raise VelocityIntegralProtocolError("duplicate Stage-B comparison")
        if int(params.get("available", -1)) not in (0, 1):
            raise VelocityIntegralProtocolError("invalid Stage-B comparison availability")
        self.stage_b_comparison[direction] = _metadata_free(params)

    def handle_reproduction_core(self, params: dict) -> None:
        self._require_summary(params)
        if self.reproduction is not None:
            raise VelocityIntegralProtocolError("duplicate reproduction core")
        self.reproduction = {
            **_metadata_free(params),
            "masks": {},
            "reproduced": [{}, {}],
            "divergent": [{}, {}],
        }

    def handle_reproduction_mask(self, params: dict) -> None:
        reproduction = self._require_reproduction(params)
        direction = self._direction(params)
        if direction in reproduction["masks"]:
            raise VelocityIntegralProtocolError("duplicate reproduction mask")
        for key in (
            "previous_mask",
            "current_mask",
            "shared_mask",
            "reproduced_mask",
            "divergent_mask",
            "previous_only_mask",
            "current_only_mask",
        ):
            self._validate_mask(int(params[key]))
        reproduction["masks"][direction] = _metadata_free(params)

    def handle_reproduction_interval(self, params: dict) -> None:
        reproduction = self._require_reproduction(params)
        direction = self._direction(params)
        rung = int(params.get("rung_index", -1))
        kind = int(params.get("kind", -1))
        if kind not in (1, 2):
            raise VelocityIntegralProtocolError("invalid reproduction interval kind")
        records = reproduction["reproduced" if kind == 1 else "divergent"][direction]
        if rung in records:
            raise VelocityIntegralProtocolError("duplicate reproduction interval")
        record = _metadata_free(params)
        if kind == 1:
            record["overlap"] = (
                int(params["result_low_or_gap_q"]),
                int(params["result_high_q"]),
            )
        else:
            record["signed_gap_q"] = int(params["result_low_or_gap_q"])
        records[rung] = record

    def handle_reproduction_digest(self, params: dict) -> None:
        reproduction = self._require_reproduction(params)
        if "previous_digest" in reproduction:
            raise VelocityIntegralProtocolError("duplicate reproduction digest")
        reproduction["previous_digest"] = _u64(
            params["previous_digest_low"], params["previous_digest_high"]
        )
        reproduction["current_digest"] = _u64(
            params["current_digest_low"], params["current_digest_high"]
        )

    def handle_terminal_core(self, params: dict) -> None:
        if self.plan is None:
            self._accept_failed_admission_core(params)
            return
        self._require_summary(params)
        if self._terminal_parts:
            raise VelocityIntegralProtocolError("duplicate terminal core")
        self._require_fragment(params, 0)
        schema_revision = int(self.plan["schema_revision"])
        if schema_revision >= 5 and (
            "rest_boundary_rung_plus_one" not in params
            or "rest_boundary_slot_plus_one" not in params
        ):
            raise VelocityIntegralProtocolError("schema-5 terminal omitted rest-boundary reference")
        if schema_revision >= 6:
            flags = int(params.get("recovery_flags", -1))
            known_flags = (
                TERMINAL_RECOVERY_UNAVAILABLE
                | TERMINAL_RECOVERED_WITH_CURRENT_HEADROOM
                | TERMINAL_RECOVERY_QUANTIZATION_EXPOSED
            )
            if schema_revision >= 7:
                known_flags |= TERMINAL_PROBE_CONSTRAINED_TEST_POINT
            if schema_revision >= 8:
                known_flags |= TERMINAL_COMBINED_TARGET_MASK | TERMINAL_COMBINED_WORKFLOW
            if flags < 0 or flags & ~known_flags:
                raise VelocityIntegralProtocolError("invalid terminal recovery flags")
        rung = int(params.get("rest_boundary_rung_plus_one", 0))
        slot = int(params.get("rest_boundary_slot_plus_one", 0))
        combined = schema_revision >= 8 and bool(
            int(params.get("recovery_flags", 0)) & TERMINAL_COMBINED_WORKFLOW
        )
        target_code = (
            int(params.get("recovery_flags", 0)) & TERMINAL_COMBINED_TARGET_MASK
        ) >> TERMINAL_COMBINED_TARGET_SHIFT
        target_reference = combined and target_code in (1, 2) and rung != 0 and slot == 0
        if (rung == 0) != (slot == 0) and not target_reference:
            raise VelocityIntegralProtocolError("partial rest-boundary reference")
        if slot and (
            rung not in range(1, int(self.plan["positive_rung_count"]) + 1)
            or slot not in range(1, 9)
        ):
            raise VelocityIntegralProtocolError("invalid rest-boundary reference")
        if combined and target_code not in range(5):
            raise VelocityIntegralProtocolError("invalid combined target status")
        # The breakaway campaign's Stage-C continuation is not a "combined" plan
        # (StageCAuthority.new_breakaway never fills combined_selected_response),
        # so its terminal never carries the combined-workflow marker. Only the
        # classic combined schema range (8-13, below every breakaway revision,
        # enforced pairwise with shape 3 in _finish_plan) requires it.
        if 8 <= schema_revision <= 13 and not combined:
            raise VelocityIntegralProtocolError(
                "schema-8 terminal omitted combined workflow marker"
            )
        pending = self._recovery_rest_pending
        hidden_rest = pending is not None and pending[2]
        rest_not_confirmed = int(params.get("cause", -1)) == 53
        if hidden_rest and not rest_not_confirmed:
            raise VelocityIntegralProtocolError(
                "hidden recovery-rest sequence lacks a completed-rest terminal"
            )
        if pending is not None and not hidden_rest and rest_not_confirmed:
            raise VelocityIntegralProtocolError(
                "completed-rest terminal omitted hidden recovery-rest evidence"
            )
        if schema_revision >= 12 and pending is None:
            ordinary_positions = self._ordinary_rest_hidden_positions
            if rest_not_confirmed and ordinary_positions != 2:
                raise VelocityIntegralProtocolError(
                    "completed-rest terminal omitted hidden rest evidence"
                )
            if ordinary_positions == 0 and int(params["outcome"]) != 3:
                raise VelocityIntegralProtocolError(
                    "zero-position terminal is not a pre-analysis Fault"
                )
        self._terminal_parts.append(dict(params))

    def handle_terminal_identity(self, params: dict) -> None:
        self._accept_terminal_part(params, 1)

    def handle_terminal_timing(self, params: dict) -> None:
        self._accept_terminal_part(params, 2)
        core, identity, timing = self._terminal_parts
        terminal = self._merge((core, identity, timing))
        terminal["plan_digest"] = self._reported_plan_digest(identity)
        terminal["digest"] = _u64(identity["digest_low"], identity["digest_high"])
        terminal["run_started_us"] = _u64(timing["started_low"], timing["started_high"])
        terminal["run_completed_us"] = _u64(timing["completed_low"], timing["completed_high"])
        rung = int(core.get("rest_boundary_rung_plus_one", 0))
        slot = int(core.get("rest_boundary_slot_plus_one", 0))
        terminal["rest_boundary"] = (
            None if slot == 0 else {"positive_rung_index": rung - 1, "slot": slot - 1}
        )
        if self.plan is None:
            terminal["recovery_unavailable"] = 0
            terminal["recovered_with_current_headroom"] = False
            terminal["recovery_quantization_exposed"] = False
            # Read the flag rather than assuming it. Only the probe-clamp
            # refusal reached a test point to constrain; a refused resume never
            # got that far, and claiming otherwise sends the operator after a
            # clamp that was never applied.
            terminal["probe_constrained_test_point"] = bool(
                int(terminal["recovery_flags"]) & TERMINAL_PROBE_CONSTRAINED_TEST_POINT
            )
        elif int(self.plan["schema_revision"]) >= 6:
            flags = int(terminal["recovery_flags"])
            terminal["recovery_unavailable"] = int(bool(flags & TERMINAL_RECOVERY_UNAVAILABLE))
            terminal["recovered_with_current_headroom"] = bool(
                flags & TERMINAL_RECOVERED_WITH_CURRENT_HEADROOM
            )
            terminal["recovery_quantization_exposed"] = bool(
                flags & TERMINAL_RECOVERY_QUANTIZATION_EXPOSED
            )
            terminal["probe_constrained_test_point"] = bool(
                flags & TERMINAL_PROBE_CONSTRAINED_TEST_POINT
            )
            terminal["combined_workflow"] = bool(flags & TERMINAL_COMBINED_WORKFLOW)
            target_code = (flags & TERMINAL_COMBINED_TARGET_MASK) >> TERMINAL_COMBINED_TARGET_SHIFT
            terminal["target_status"] = COMBINED_TARGET_NAMES.get(target_code - 1)
            terminal["target_terminus"] = (
                rung - 1 if target_code in (1, 2) and rung != 0 and slot == 0 else None
            )
        terminal["outcome_namespace"] = "stage_c"
        terminal["outcome_name"] = (
            "InconclusiveRest"
            if int(core["outcome"]) == 2 and int(core["cause"]) == 53
            else OUTCOME_NAMES.get(int(core["outcome"]))
        )
        self.terminal = terminal
        self.outcome = OUTCOME_NAMES.get(int(core["outcome"]))
        if self.outcome is None:
            raise VelocityIntegralProtocolError("invalid terminal outcome")
        self.validate_complete()
        self.done = True
        self._recovery_rest_pending = None
        self._ordinary_rest_hidden_positions = None

    def validate_complete(self) -> None:
        """Revalidate every completeness and exact-identity invariant."""
        if self.plan is None:
            self._validate_failed_admission()
            return
        if self.plan is None or self._summary is None or self.terminal is None:
            raise VelocityIntegralProtocolError("terminal report is incomplete")
        if int(self.terminal["plan_digest"]) != int(self.plan["plan_digest"]):
            raise VelocityIntegralProtocolError("terminal plan digest mismatch")
        if int(self.terminal["expected_observations"]) != int(self.plan["expected_observations"]):
            raise VelocityIntegralProtocolError("terminal observation plan changed")
        if int(self.terminal["emitted_observations"]) != len(self.observations):
            raise VelocityIntegralProtocolError("terminal observation count mismatch")
        if int(self.terminal["expected_rungs"]) != int(self.plan["total_rung_count"]):
            raise VelocityIntegralProtocolError("terminal rung plan changed")
        if int(self.terminal["emitted_rungs"]) != len(self.rungs):
            raise VelocityIntegralProtocolError("terminal rung count mismatch")
        required_recoveries = {
            rung_index
            for rung_index in self.rungs
            if sum(key[0] == rung_index for key in self.observations) == 8
        }
        cause = int(self.terminal["cause"])
        if cause in (
            INTEGRAL_CAUSE_CURRENT_AFTER_SUFFICIENCY,
            INTEGRAL_CAUSE_BOOKEND_UNAVAILABLE,
            INTEGRAL_CAUSE_REST_BOUNDARY_AFTER_SUFFICIENCY,
        ):
            rest_boundary = self.terminal["rest_boundary"]
            if rest_boundary is not None:
                required_recoveries.add(int(rest_boundary["positive_rung_index"]) + 1)
            current_terminus = int(self._summary["current_terminus_plus_one"])
            if current_terminus:
                required_recoveries.add(current_terminus)
        if self.outcome == "fault" and required_recoveries:
            terminal_rung = max(required_recoveries)
            if terminal_rung not in self.recoveries:
                if self._last_evidence != ("rung", terminal_rung):
                    raise VelocityIntegralProtocolError(
                        "missing terminal recovery did not immediately follow its rung"
                    )
                required_recoveries.remove(terminal_rung)
        opening_anchor_failed = (
            self.outcome == "inconclusive"
            and cause == INTEGRAL_CAUSE_TOO_FEW_RUNGS
            and required_recoveries == {0}
            and self._last_evidence == ("rung", 0)
        )
        if opening_anchor_failed:
            required_recoveries.remove(0)
        if set(self.recoveries) != required_recoveries:
            raise VelocityIntegralProtocolError(
                "recovery records do not match fully acquired rungs"
            )
        for direction, curve in enumerate(self.curves):
            if curve["opening"] is None or self.drift[direction] is None:
                raise VelocityIntegralProtocolError("missing anchor or drift evidence")
            if set(curve["positive"]) != self._mask_bits(curve["eligible_mask"]):
                raise VelocityIntegralProtocolError("curve does not cover eligible mask")
            bookend_expected = bool(int(self._summary["bookend_available_mask"]) & (1 << direction))
            if (curve["bookend"] is not None) != bookend_expected:
                raise VelocityIntegralProtocolError("bookend availability mismatch")
            if self.stage_b_comparison[direction] is None:
                raise VelocityIntegralProtocolError("missing Stage-B comparison")
        if self.reproduction is not None:
            if set(self.reproduction["masks"]) != {0, 1}:
                raise VelocityIntegralProtocolError("missing reproduction masks")
            if "previous_digest" not in self.reproduction:
                raise VelocityIntegralProtocolError("missing reproduction digest")
            for direction, masks in self.reproduction["masks"].items():
                if set(self.reproduction["reproduced"][direction]) != self._mask_bits(
                    int(masks["reproduced_mask"])
                ):
                    raise VelocityIntegralProtocolError("missing reproduced intervals")
                if set(self.reproduction["divergent"][direction]) != self._mask_bits(
                    int(masks["divergent_mask"])
                ):
                    raise VelocityIntegralProtocolError("missing divergent intervals")
        # Neither the classic combined flow (shape 3) nor the breakaway
        # campaign's Stage-C continuation (shape 6) ever has a reproduced
        # Stage-B directional model to compare against -- the combined flow
        # because its Stage-B response was selected live in the same command,
        # the breakaway campaign because StageCAuthority.new_breakaway leaves
        # every directional field empty/zero by construction. Both are
        # therefore exempt from the reproduction-required rule below.
        combined_or_breakaway = int(self.plan["schema_revision"]) >= 8 and int(
            self.workflow_plan["shape"]
        ) in (3, 6)
        if self.outcome == "complete" and self.reproduction is None and not combined_or_breakaway:
            raise VelocityIntegralProtocolError(
                "complete integral response omitted reproduction evidence"
            )
        if int(self.plan["schema_revision"]) >= 6:
            if bool(self.terminal["recovery_quantization_exposed"]) != bool(
                self.plan["recovery_quantization_exposed"]
            ):
                raise VelocityIntegralProtocolError("plan and terminal recovery exposure differ")
            recovered = any(int(recovery["outcome"]) == 5 for recovery in self.recoveries.values())
            if bool(self.terminal["recovered_with_current_headroom"]) != recovered:
                raise VelocityIntegralProtocolError(
                    "recovered terminal flag lacks causal recovery outcome"
                )
        if int(self.plan["schema_revision"]) >= 7 and bool(
            self.terminal["probe_constrained_test_point"]
        ) != bool(self.plan["probe_constrained_test_point"]):
            raise VelocityIntegralProtocolError("plan and terminal probe constraint differ")

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
            workflow_shape = int(self.workflow_plan["shape"])
            if int(plan["schema_revision"]) >= BREAKAWAY_STAGE_C_MIN_SCHEMA_REVISION:
                # The breakaway campaign's Stage-C continuation has no
                # reproduced Stage-B sweep plan to pair against -- Stage C is
                # authorized by the accepted confirmation digest instead (see
                # BreakawayCampaignAssembler), not by a Stage-B/Stage-C schema
                # pairing. Only the workflow shape is exclusive here.
                #
                # A resume replays that same exact plan from retained authority,
                # so it carries the breakaway schema under the resume shape. The
                # campaign is no longer the only way to reach schema 14.
                if workflow_shape not in (6, 2):
                    raise VelocityIntegralProtocolError(
                        "breakaway Stage-C plan requires breakaway workflow"
                    )
            else:
                if workflow_shape != 3:
                    raise VelocityIntegralProtocolError(
                        "combined Stage-C plan requires combined workflow"
                    )
                # Stage-B and Stage-C revisions must be a matching pair. This is a
                # compatibility check, not a re-derivation of firmware's arithmetic.
                expected_stage_b = {11: 12, 12: 13, 13: 14}.get(int(plan["schema_revision"]))
                if (
                    expected_stage_b is not None
                    and self._combined_stage_b_schema != expected_stage_b
                ):
                    raise VelocityIntegralProtocolError(
                        "Stage-B and Stage-C schema revisions are not a matching pair"
                    )
        self.plan = plan

    @property
    def slots_per_rung(self) -> int:
        """Slots per rung, as the plan declares it.

        Firmware owns the schedule geometry. Assuming eight here would reject a
        plan that legitimately declares another count.
        """
        plan = self.plan or {}
        rungs = int(plan.get("total_rung_count", 0))
        observations = int(plan.get("expected_observations", 0))
        if rungs <= 0 or observations <= 0 or observations % rungs:
            return 8
        return observations // rungs

    def _finish_observation(self) -> None:
        core, rate, quality = self._observation_parts
        observation = self._merge((core, rate, quality))
        key = (int(core["rung_index"]), int(core["slot"]))
        if key in self.observations:
            raise VelocityIntegralProtocolError("duplicate observation")
        # The declared slot order gives the travel direction; slot parity alone
        # does not, because the paired order is not a parity function.
        slot_order = int((self.plan or {}).get("slot_order", SLOT_ORDER_FORWARD_FIRST))
        expected_direction = slot_direction_index(slot_order, key[1])
        if key[1] not in range(self.slots_per_rung) or (
            int(core["direction"]) != expected_direction
        ):
            raise VelocityIntegralProtocolError("invalid observation slot or direction")
        if int(rate["deficit_low_q"]) > int(rate["deficit_high_q"]):
            raise VelocityIntegralProtocolError("reversed deficit interval")
        self.observations[key] = observation
        self._next_evidence_sequence += 1
        self._trace_only_current_pending = True
        self._last_evidence = ("observation", key[0])
        self._observation_parts = []

    def _finish_rung_if_complete(self) -> None:
        cores = [part for part in self._rung_parts if "classification" in part]
        if len(cores) != 2 or not self._rung_direction_complete(1):
            return
        rung_index = int(cores[0]["rung_index"])
        if rung_index in self.rungs:
            raise VelocityIntegralProtocolError("duplicate rung")
        if any(int(core["rung_index"]) != rung_index for core in cores):
            raise VelocityIntegralProtocolError("rung identity changed between directions")
        directions = []
        for core in cores:
            direction = int(core["direction"])
            components = [
                self._interval(part)
                for part in self._rung_parts
                if "component" in part and int(part["direction"]) == direction
            ]
            directions.append({**_metadata_free(core), "components": components})
        rung = {
            "run_sequence": int(cores[0]["run_sequence"]),
            "evidence_sequence": int(cores[0]["evidence_sequence"]),
            "rung_index": rung_index,
            "i_raw": int(cores[0]["i_raw"]),
            "directions": directions,
        }
        self.rungs[rung_index] = rung
        self._next_evidence_sequence += 1
        self._last_evidence = ("rung", rung_index)
        if int(self.plan["schema_revision"]) >= 11:
            self._recovery_rest_pending = (1, rung_index, False)
        self._rung_parts = []

    def _rung_direction_complete(self, direction: int) -> bool:
        cores = [
            part
            for part in self._rung_parts
            if "classification" in part and int(part["direction"]) == direction
        ]
        if len(cores) != 1:
            return False
        components = sum(
            1
            for part in self._rung_parts
            if "component" in part and int(part["direction"]) == direction
        )
        return components == int(cores[0]["component_count"])

    def _accept_observation_part(self, params: dict, fragment: int) -> None:
        if len(self._observation_parts) != fragment:
            raise VelocityIntegralProtocolError("missing or reordered observation fragment")
        self._require_event_identity(params)
        self._require_fragment(params, fragment)
        self._observation_parts.append(dict(params))

    def _accept_terminal_part(self, params: dict, fragment: int) -> None:
        if len(self._terminal_parts) != fragment:
            raise VelocityIntegralProtocolError("missing or reordered terminal fragment")
        if self.plan is None:
            self._require_run(params)
            if int(params.get("evidence_sequence", -1)) != 0:
                raise VelocityIntegralProtocolError(
                    "failed admission terminal sequence is not zero"
                )
        else:
            self._require_terminal_identity(params)
        self._require_fragment(params, fragment)
        self._terminal_parts.append(dict(params))

    def _accept_failed_admission_core(self, params: dict) -> None:
        # A request refused before it was planned declares no workflow envelope.
        # The envelope's only content is a duration, and firmware cannot state
        # one for a command it never started; the wait loop does not need it
        # either, because the refusal arrives well inside the plan timeout. When
        # an envelope did arrive, it still has to name a Stage-C shape.
        if self.workflow_plan is not None and int(self.workflow_plan["shape"]) == 0:
            raise VelocityIntegralProtocolError("terminal preceded exact plan")
        if self._plan_parts:
            raise VelocityIntegralProtocolError("terminal preceded exact plan")
        if self._run_sequence is None:
            # Normally the workflow envelope establishes the run. A refusal that
            # declares none is the run's first and only message, so its core
            # sets the sequence the remaining two fragments are checked against.
            self._run_sequence = int(params["run_sequence"])
        self._require_run(params)
        cause = int(params.get("cause", -1))
        if cause not in STAGE_C_FAILED_ADMISSION_CAUSES:
            raise VelocityIntegralProtocolError("terminal preceded exact plan")
        # Only the probe-clamp refusal reached a plan far enough to carry its
        # qualifier. A resume refused before planning carries none.
        probe_clamped = cause == STAGE_C_CAUSE_NO_TRANSITION_CAPABLE_OPERATING_POINT
        expected = {
            "evidence_sequence": 0,
            "fragment": 0,
            "outcome": 5,
            "cause": cause,
            "recovery_flags": TERMINAL_PROBE_CONSTRAINED_TEST_POINT if probe_clamped else 0,
            "rest_boundary_rung_plus_one": 0,
            "rest_boundary_slot_plus_one": 0,
            "expected_observations": 0,
            "emitted_observations": 0,
            "expected_rungs": 0,
            "emitted_rungs": 0,
        }
        if self._terminal_parts or any(
            int(params.get(field, -1)) != value for field, value in expected.items()
        ):
            raise VelocityIntegralProtocolError("terminal preceded exact plan")
        self._terminal_parts.append(dict(params))

    def _validate_failed_admission(self) -> None:
        terminal = self.terminal
        if terminal is None:
            raise VelocityIntegralProtocolError("terminal report is incomplete")
        if self._summary is not None or self.observations or self.rungs:
            raise VelocityIntegralProtocolError("failed admission carried motion evidence")
        # A missing-authority refusal has no plan to name, so it is the one
        # failed admission whose plan digest is legitimately zero. Requiring one
        # would force firmware to fabricate a digest for a plan that was never
        # built.
        missing_authority = int(terminal["cause"]) == STAGE_C_CAUSE_NO_RETAINED_AUTHORITY
        plan_digest = int(terminal["plan_digest"])
        if int(terminal["digest"]) != 0:
            raise VelocityIntegralProtocolError("failed admission terminal identity is invalid")
        if missing_authority:
            if plan_digest != 0:
                raise VelocityIntegralProtocolError(
                    "missing retained authority reported an exact plan"
                )
        elif plan_digest == 0:
            raise VelocityIntegralProtocolError("failed admission terminal identity is invalid")

    def _require_stage_c_workflow(self, params: dict) -> None:
        if self.workflow_plan is None:
            raise VelocityIntegralProtocolError("plan core preceded workflow plan")
        if int(self.workflow_plan["shape"]) == 0:
            raise VelocityIntegralProtocolError(
                "proportional-only workflow emitted integral-response plan"
            )
        self._require_run(params)

    def _require_plan_step(self, expected: str, count: int) -> None:
        if len(self._plan_parts) != count:
            raise VelocityIntegralProtocolError(f"plan step requires {expected}")

    def _require_plan_identity(self, params: dict) -> None:
        self._require_run(params)
        if int(params.get("evidence_sequence", -1)) != 0:
            raise VelocityIntegralProtocolError("integral-response plan sequence is not zero")

    def _require_event_identity(self, params: dict) -> None:
        self._require_run(params)
        evidence_sequence = int(params.get("evidence_sequence", -1))
        self._resolve_trace_only_current(evidence_sequence)
        if evidence_sequence != self._next_evidence_sequence:
            raise VelocityIntegralProtocolError("integral-response evidence sequence gap")
        self._ordinary_rest_hidden_positions = None

    def _require_recovery_identity(self, params: dict, rung_index: int, outcome: int) -> None:
        self._require_run(params)
        evidence_sequence = int(params.get("evidence_sequence", -1))
        self._resolve_trace_only_current(evidence_sequence)
        self._ordinary_rest_hidden_positions = None
        pending = self._recovery_rest_pending
        # Hidden recovery evidence exists only from schema 11, and only for the
        # rung whose completed record set `pending`. Everywhere else the run
        # must be zero, exactly as before this change.
        carries_hidden_evidence = (
            int(self.plan["schema_revision"]) >= 11
            and pending is not None
            and pending[:2] == (1, rung_index)
        )
        maximum_hidden_run = self.MAXIMUM_RECOVERY_HIDDEN_RUN if carries_hidden_evidence else 0
        hidden_run = evidence_sequence - self._next_evidence_sequence
        if hidden_run < 0 or hidden_run > maximum_hidden_run:
            raise VelocityIntegralProtocolError("integral-response evidence sequence gap")
        # Outcomes 1 and 5 are reached only after the settle poll, which always
        # commits a scored-rest selection, so they cannot hide nothing.
        if (
            hidden_run == 0
            and outcome in (1, 5)
            and int(self.plan["schema_revision"]) >= 11
            and pending is not None
        ):
            raise VelocityIntegralProtocolError(
                "moving recovery omitted hidden recovery-rest evidence"
            )
        self._next_evidence_sequence = evidence_sequence
        if hidden_run:
            self._recovery_rest_pending = (1, rung_index, True)

    def _resolve_trace_only_current(
        self, evidence_sequence: int, *, allow_zero: bool = False
    ) -> None:
        if not self._trace_only_current_pending:
            return
        if int(self.plan["schema_revision"]) >= 12:
            if evidence_sequence == self._next_evidence_sequence + 2:
                self._next_evidence_sequence += 2
                self._trace_only_current_pending = False
                self._ordinary_rest_hidden_positions = 2
            elif allow_zero and evidence_sequence == self._next_evidence_sequence:
                self._trace_only_current_pending = False
                self._ordinary_rest_hidden_positions = 0
            else:
                raise VelocityIntegralProtocolError("integral-response evidence sequence gap")
            return
        if evidence_sequence == self._next_evidence_sequence:
            self._trace_only_current_pending = False
        elif evidence_sequence == self._next_evidence_sequence + 1:
            self._next_evidence_sequence += 1
            self._trace_only_current_pending = False

    def _require_terminal_identity(
        self, params: dict, *, allow_recovery_rest: bool = False
    ) -> None:
        self._require_plan()
        if not allow_recovery_rest:
            self._require_event_identity(params)
            return
        self._require_run(params)
        evidence_sequence = int(params.get("evidence_sequence", -1))
        self._resolve_trace_only_current(evidence_sequence, allow_zero=True)
        pending = self._recovery_rest_pending
        # Same gating as the original nonzero branch: hidden recovery evidence
        # exists only from schema 11 and only when a rest is pending. Note this
        # method, unlike the recovery path, has no rung identity to check.
        carries_hidden_evidence = int(self.plan["schema_revision"]) >= 11 and pending is not None
        maximum_hidden_run = self.MAXIMUM_RECOVERY_HIDDEN_RUN if carries_hidden_evidence else 0
        hidden_run = evidence_sequence - self._next_evidence_sequence
        if hidden_run < 0 or hidden_run > maximum_hidden_run:
            raise VelocityIntegralProtocolError("integral-response evidence sequence gap")
        self._next_evidence_sequence = evidence_sequence
        if hidden_run:
            self._recovery_rest_pending = (pending[0], pending[1], True)

    def _require_summary(self, params: dict) -> None:
        if self._summary is None:
            raise VelocityIntegralProtocolError("terminal evidence preceded run summary")
        self._require_run(params)
        if int(params.get("evidence_sequence", -1)) != self._next_evidence_sequence:
            raise VelocityIntegralProtocolError(
                "integral-response terminal evidence sequence changed"
            )

    def _require_reproduction(self, params: dict) -> dict:
        self._require_summary(params)
        if self.reproduction is None:
            raise VelocityIntegralProtocolError("reproduction detail preceded core")
        return self.reproduction

    def _require_run(self, params: dict) -> None:
        if self._run_sequence is None or int(params.get("run_sequence", -1)) != self._run_sequence:
            raise VelocityIntegralProtocolError("run sequence changed")

    def _require_plan(self) -> None:
        if self.plan is None:
            raise VelocityIntegralProtocolError(
                "integral-response evidence arrived before exact plan"
            )

    @staticmethod
    def _require_fragment(params: dict, expected: int) -> None:
        if int(params.get("fragment", -1)) != expected:
            raise VelocityIntegralProtocolError("fragment identity mismatch")

    def _validate_mask(self, mask: int) -> None:
        count = int(self.plan["positive_rung_count"])
        if mask < 0 or mask & ~((1 << count) - 1):
            raise VelocityIntegralProtocolError("mask exceeds declared ladder")

    @staticmethod
    def _mask_bits(mask: int) -> set[int]:
        return {index for index in range(32) if mask & (1 << index)}

    @staticmethod
    def _direction(params: dict) -> int:
        direction = int(params.get("direction", -1))
        if direction not in (0, 1):
            raise VelocityIntegralProtocolError("invalid direction")
        return direction

    @staticmethod
    def _interval(params: dict) -> tuple[int, int]:
        low = int(params["low_q"])
        high = int(params["high_q"])
        if low > high:
            raise VelocityIntegralProtocolError("reversed interval")
        return low, high

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
# The breakaway campaign (StageCPlanShape.BreakawaySeededPThenI = 6) is a
# three-phase acquisition -- a physical-excursion upward probe, an additive
# discovery ladder, and a held-out eight-stroke confirmation block -- that
# firmware runs entirely on its own authority before, on acceptance, handing
# off into the existing Stage-C velocity-integral flow above (schema 14,
# handled by VelocityIntegralAssembler already). BreakawayCampaignAssembler
# below covers only the campaign's own evidence: it validates the firmware's
# digest chain (each phase's plan names the prior phase's digest) and the
# wire's own internal structure (direction codes, monotonic indices, interval
# ordering, mask subset relationships), and otherwise relays every firmware
# value unchanged. It never selects a rung, changes a family size, retries a
# candidate, or synthesizes a value firmware did not send -- see
# tests/test_velocity_integral.py's dumb-host proof tests.

BREAKAWAY_PHASE_NAMES = {0: "probe", 1: "discovery", 2: "confirmation"}

STAGE_C_CAUSE_EVIDENCE_INTEGRITY = 4
STAGE_C_CAUSE_REPRODUCTION_MISMATCH = 6
STAGE_C_CAUSE_PLAN_MISMATCH = 7
STAGE_C_CAUSE_NO_TRANSITION_CAPABLE_OPERATING_POINT = 11
STAGE_C_CAUSE_NO_RETAINED_AUTHORITY = 12

# Dispatch-namespace causes attached to a Stage-C terminal. These share their
# numeric range with the engine's own `INTEGRAL_CAUSE_*` values and with
# `CommissionError::status_code()`; a value is
# only unambiguous once the reader knows which producer emitted it.
STAGE_C_TERMINAL_CAUSE_NAMES = {
    STAGE_C_CAUSE_EVIDENCE_INTEGRITY: "evidence_integrity",
    STAGE_C_CAUSE_REPRODUCTION_MISMATCH: "reproduction_mismatch",
    STAGE_C_CAUSE_PLAN_MISMATCH: "plan_mismatch",
    STAGE_C_CAUSE_NO_TRANSITION_CAPABLE_OPERATING_POINT: ("no_transition_capable_operating_point"),
    STAGE_C_CAUSE_NO_RETAINED_AUTHORITY: "no_retained_stage_c_authority",
}

# Causes a Stage-C terminal may carry when it arrives with no exact plan: the
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
        "no retained Stage C authority; run a campaign first, in this power cycle"
    ),
    STAGE_C_CAUSE_PLAN_MISMATCH: (
        "request does not reproduce the retained Stage C plan; reissue with the "
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
}

# Advisory text only -- relays what the disclosed cause means, not a
# host-computed remedy. Mirrors velocity_sweep.py's INCONCLUSIVE_REMEDIATION.
BREAKAWAY_TERMINAL_REMEDIATION = {
    1: "no rung showed repeatable motion within the probe's authority; check current limits",
    5: "probe authority was exhausted before repeatable motion resolved",
    6: "probe stopped on a safety fault; inspect retained safety evidence",
    7: "discovery skipped the target band; inspect the resolved ladder",
    8: "current headroom ended discovery before the target band; review headroom",
    9: "the additive span between breakaway and ceiling was insufficient",
    10: "the additive ladder exceeded its resolution budget",
    11: "discovery evidence was excluded; retain the trace and inspect stationarity",
    12: "discovery stopped on a safety fault; inspect retained safety evidence",
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
BREAKAWAY_STAGE_C_SCHEMA_REVISION = 16
# First revision of each breakaway stream. These are boundaries, not sets: every
# revision at or above them is a breakaway plan, and Stage-C 8-13 below the
# boundary stays combined. The upper end stays bounded by the current revision
# above, so a stream from firmware newer than this host is refused rather than
# mis-parsed against rules that may no longer hold.
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
                "campaign accepted flag disagrees with the Stage-C plan digest"
            )
        confirmation_accepted = bool(int((self.confirmation_terminal or {}).get("accepted", 0)))
        if self.confirmation_terminal is not None and bool(accepted) != confirmation_accepted:
            raise BreakawayCampaignProtocolError(
                "campaign terminal disagrees with the confirmation terminal's own acceptance"
            )
        self.campaign_terminal = _metadata_free(params)
        self.accepted = bool(accepted)
        self.stage_c_plan_digest = digest
        self.done = True
