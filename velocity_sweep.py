"""Reassemble and verify firmware-authored velocity-sweep evidence."""

from __future__ import annotations

SUPPORTED_STAGE_B_REPRODUCTION_SCHEMAS = (8, 10, 13)

OUTCOME_NAMES = {
    0: "complete_candidate",
    1: "complete",
    2: "inconclusive",
    3: "fault",
    4: "rejected_plan_mismatch",
}
LEGACY_OUTCOME_NAMES = {0: "complete", 1: "inconclusive", 2: "fault"}
INCONCLUSIVE_REMEDIATION = {
    1: "one direction has no valid model region; inspect its fragments and boundaries",
    2: "no joint operable region supports nomination; inspect the safe rung curve",
    3: "firmware report integrity failed; retain the trace and redeploy a matched build",
    4: "current headroom ended the sweep; review current headroom if evidence is insufficient",
    5: "the sufficient run did not reproduce; compare the reported memberships and intervals",
    6: "the second request changed the frozen plan; rerun with identical request fields",
}

CONSENSUS_ELIGIBLE = 0
CONSENSUS_AMBIGUOUS = 1
CONSENSUS_INSUFFICIENT = 2
CONSENSUS_INCOMPLETE = 3
# Fallback only, for firmware that publishes no revision and sends a plan with no
# schema field. Not a gate: a duration outside this table is not an error.
COMBINED_STAGE_B_WORKFLOW_SCHEMAS = {
    (449_173, 494_128): 8,
    (451_573, 496_528): 10,
    (452_073, 496_528): 11,
    (470_573, 496_528): 12,
}
# Stage-B revisions this host understands. Schema gating is the compatibility
# boundary; workflow durations are firmware-authored and no longer asserted.
COMBINED_STAGE_B_REVISIONS = frozenset({8, 10, 11, 12, 13, 14})


class VelocitySweepProtocolError(Exception):
    """Raised when the streamed sweep evidence violates its wire contract."""


class VelocitySweepAssembler:
    """Strictly reassemble one firmware-authored velocity-sweep report."""

    def __init__(self) -> None:
        self.plan: dict | None = None
        self.observations: dict[tuple[int, int], dict] = {}
        self.rungs: dict[int, dict] = {}
        self.recoveries: dict[int, dict] = {}
        self.structured_boundaries: list[dict] = []
        self.directional_regions: list[dict] = []
        self.joint_regions: list[dict] = []
        self.handoff: dict | None = None
        self.reproduction: dict | None = None
        self.terminal: dict | None = None
        self.terminal_directions: list[dict] = []
        self.integrity: dict | None = None
        self.outer_inconclusive: dict | None = None
        self.outcome: str | None = None
        self.sufficient_direction_mask = 0
        self.full_plan_executed = False
        self.done = False
        self._run_sequence: int | None = None
        self._next_evidence_sequence = 0
        self._group_kind: str | None = None
        self._group_parts: list[dict] = []
        self._group_fragments = 0
        self._rung_expected_fragments: set[int] = set()
        self._rung_expected_order: list[int] = []
        self._unframed_kind: str | None = None
        self._unframed_parts: list[dict] = []
        self._last_evidence: tuple[str, int] | None = None
        self._trace_only_current_pending = False
        self._workflow_shape: int | None = None
        self._workflow_duration: tuple[int, int] | None = None
        self._combined_stage_b_schema: int | None = None
        self._firmware_stage_b_schema: int | None = None
        self._recovery_rest_pending: tuple[int, int, bool] | None = None

    def bind_firmware_stage_b_schema(self, schema_revision: int) -> None:
        """Bind the Stage-B revision published by the connected firmware.

        Stage-B plan records carry no ``schema_revision`` field, and revisions 12
        and 13 share the combined workflow duration ``470,573 / 496,528`` ms, so
        the duration alone cannot tell them apart. The firmware-published
        revision is the authority whenever the plan omits its own field.
        """
        if self.plan is not None:
            raise VelocitySweepProtocolError(
                "firmware Stage-B revision arrived after the plan"
            )
        if schema_revision not in COMBINED_STAGE_B_REVISIONS:
            raise VelocitySweepProtocolError("unknown firmware Stage-B revision")
        self._firmware_stage_b_schema = schema_revision

    def configure_workflow_shape(
        self,
        shape: int,
        nominal_workflow_ms: int | None = None,
        maximum_workflow_ms: int | None = None,
    ) -> None:
        """Bind terminal interpretation to the firmware-disclosed workflow."""
        if shape not in (0, 1, 2, 3):
            raise VelocitySweepProtocolError("invalid workflow shape")
        if (
            self.plan is not None
            or self._group_parts
            or self._last_evidence is not None
        ):
            raise VelocitySweepProtocolError(
                "workflow shape arrived after sweep evidence"
            )
        if self._workflow_shape is not None:
            raise VelocitySweepProtocolError("duplicate workflow shape")
        if (nominal_workflow_ms is None) != (maximum_workflow_ms is None):
            raise VelocitySweepProtocolError("incomplete workflow duration")
        self._workflow_shape = shape
        if nominal_workflow_ms is not None:
            self._workflow_duration = (
                int(nominal_workflow_ms),
                int(maximum_workflow_ms),
            )

    @property
    def combined_stage_b_schema(self) -> int | None:
        """Return the combined Stage-B compatibility revision bound by the workflow."""
        return self._combined_stage_b_schema

    @property
    def plan_ready(self) -> bool:
        """Whether every pre-motion plan fragment arrived."""
        return self.plan is not None

    @property
    def maximum_duration_s(self) -> float | None:
        """Firmware-declared maximum workflow duration in seconds."""
        if self.plan is None:
            return None
        return self.plan["maximum_workflow_ms"] / 1000.0

    @property
    def remediation(self) -> str:
        """Return actionable text for the detailed terminal outcome."""
        if self.integrity is None:
            return ""
        cause = int(self.integrity.get("cause", 0))
        if self.outcome == "inconclusive":
            return INCONCLUSIVE_REMEDIATION.get(
                cause, "inspect the directional evidence and rerun unchanged first"
            )
        if self.outcome == "fault":
            return "firmware aborted fail-closed; inspect the reported safety cause"
        return ""

    def handle_plan_limits(self, params: dict) -> None:
        self._accept_group_fragment("plan", 4, 0, params)

    def handle_plan_geometry(self, params: dict) -> None:
        self._accept_group_fragment("plan", 4, 1, params)

    def handle_plan_timing(self, params: dict) -> None:
        self._accept_group_fragment("plan", 4, 2, params)

    def handle_plan_recovery(self, params: dict) -> None:
        recovery = dict(params)
        recovery["fragment"] = 3
        self._accept_group_fragment("plan", 4, 3, recovery)

    def handle_recovery_summary(self, params: dict) -> None:
        """Accept one compact recovery summary after its causal rung."""
        if self.plan is None:
            raise VelocitySweepProtocolError("recovery summary arrived before plan")
        if int(params.get("stage", -1)) != 0:
            raise VelocitySweepProtocolError(
                "Stage-B recovery summary named the wrong stage"
            )
        self._validate_run(params)
        rung_index = int(params.get("rung_index", -1))
        if rung_index in self.recoveries:
            raise VelocitySweepProtocolError("duplicate rung recovery")
        outcome = int(params.get("outcome", -1))
        self._accept_recovery_rest_sequence_position(
            "recovery",
            int(params["evidence_sequence"]),
            rung_index=rung_index,
            outcome=outcome,
        )
        if self._last_evidence != ("rung", rung_index):
            raise VelocitySweepProtocolError(
                "recovery did not immediately follow its rung"
            )
        if int(params.get("p_raw", -1)) != int(self.rungs[rung_index]["velocity_p"]):
            raise VelocitySweepProtocolError("recovery summary changed the rung gain")
        if int(params.get("binding_source", -1)) not in range(7):
            raise VelocitySweepProtocolError("invalid recovery binding source")
        if outcome not in range(5):
            raise VelocitySweepProtocolError("invalid recovery outcome")
        self.recoveries[rung_index] = self._strip_metadata(params)
        self._next_evidence_sequence += 1
        self._last_evidence = ("recovery", rung_index)
        self._recovery_rest_pending = None

    def handle_observation_core(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 0, params)

    def handle_observation_rate(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 1, params)

    def handle_observation_stationarity(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 2, params)

    def handle_observation_disturbance(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 3, params)

    def handle_rung_consensus_core(self, params: dict) -> None:
        """Start one firmware-authored consensus record group."""
        if self._group_kind is not None:
            raise VelocitySweepProtocolError(
                "consensus core interrupted fragment group"
            )
        if self._unframed_kind is not None:
            raise VelocitySweepProtocolError(
                "consensus core interrupted unframed record"
            )
        if self.plan is None:
            raise VelocitySweepProtocolError("rung consensus arrived before plan")
        if int(params.get("fragment", -1)) != 0:
            raise VelocitySweepProtocolError("consensus group did not start at core")
        self._validate_consensus_core(params)
        expected_order = [0]
        for direction, prefix in enumerate(("forward", "reverse")):
            component_count = int(params[prefix + "_component_count"])
            expected_order.extend(
                1 + direction * 2 + index for index in range(component_count)
            )
            if int(params[prefix + "_class"]) == CONSENSUS_ELIGIBLE:
                expected_order.append(5 + direction)
        self._start_group("rung consensus", len(expected_order), params)
        self._rung_expected_order = expected_order
        self._rung_expected_fragments = set(expected_order)
        self._group_parts.append(dict(params))
        self._finish_consensus_if_complete()

    def handle_rung_consensus_component(self, params: dict) -> None:
        """Append one exact directional consensus component."""
        direction = int(params.get("direction", -1))
        component_index = int(params.get("component_index", -1))
        if direction not in (0, 1) or component_index not in (0, 1):
            raise VelocitySweepProtocolError("invalid consensus component identity")
        fragment = 1 + direction * 2 + component_index
        self._accept_consensus_part(params, fragment)

    def handle_rung_consensus_pool(self, params: dict) -> None:
        """Append one eligible direction's firmware-authored pool."""
        direction = int(params.get("direction", -1))
        if direction not in (0, 1):
            raise VelocitySweepProtocolError("invalid consensus pool direction")
        self._accept_consensus_part(params, 5 + direction)

    def handle_structured_boundary(self, params: dict) -> None:
        """Retain a diagnostic emitted after its owning observation."""
        if self.plan is None:
            raise VelocitySweepProtocolError("structured boundary arrived before plan")
        self._validate_run(params)
        if int(params["evidence_sequence"]) + 1 != self._next_evidence_sequence:
            raise VelocitySweepProtocolError(
                "structured boundary does not follow its observation"
            )
        key = (int(params["rung_index"]), int(params["slot"]))
        if key not in self.observations:
            raise VelocitySweepProtocolError(
                "structured boundary has no owning observation"
            )
        if any(
            (int(item["rung_index"]), int(item["slot"])) == key
            for item in self.structured_boundaries
        ):
            raise VelocitySweepProtocolError("duplicate structured boundary")
        self.structured_boundaries.append(self._strip_metadata(params))

    def handle_directional_region_core(self, params: dict) -> None:
        self._accept_unframed("directional region", 0, params)

    def handle_directional_region_model(self, params: dict) -> None:
        self._accept_unframed("directional region", 1, params)

    def handle_directional_region_rates(self, params: dict) -> None:
        self._accept_unframed("directional region", 2, params)

    def handle_directional_region_boundary(self, params: dict) -> None:
        self._accept_unframed("directional region", 3, params)

    def handle_joint_region(self, params: dict) -> None:
        self._accept_unframed("joint region", 0, params)

    def handle_stage_b_handoff_core(self, params: dict) -> None:
        self._accept_unframed("stage b handoff", 0, params)

    def handle_stage_b_nomination(self, params: dict) -> None:
        self._accept_unframed("stage b handoff", 1, params)

    def handle_stage_b_directional_handoff(self, params: dict) -> None:
        expected = 2 + int(params.get("direction", -1))
        self._accept_unframed("stage b handoff", expected, params)

    def handle_stage_b_reproduction_core(self, params: dict) -> None:
        self._accept_unframed("stage b reproduction", 0, params)

    def handle_stage_b_reproduction_membership(self, params: dict) -> None:
        self._accept_unframed("stage b reproduction", 1, params)

    def handle_stage_b_reproduction_interval(self, params: dict) -> None:
        expected = 2 + int(params.get("direction", -1))
        self._accept_unframed("stage b reproduction", expected, params)

    def handle_stage_b_reproduction_digest(self, params: dict) -> None:
        self._accept_unframed("stage b reproduction", 4, params)

    def handle_stage_b_reproduction_v4_core(self, params: dict) -> None:
        if (
            int(params.get("schema_revision", -1))
            not in SUPPORTED_STAGE_B_REPRODUCTION_SCHEMAS
        ):
            raise VelocitySweepProtocolError("unsupported stage b reproduction schema")
        self._accept_unframed("stage b reproduction v4", 0, params)

    def handle_stage_b_reproduction_v4_membership(self, params: dict) -> None:
        object_index = int(params.get("object", -1))
        if object_index not in (0, 1, 2):
            raise VelocitySweepProtocolError("invalid reproduction membership object")
        self._accept_unframed("stage b reproduction v4", 1 + object_index, params)

    def handle_stage_b_reproduction_v4_pooled(self, params: dict) -> None:
        direction = self._reproduction_direction(params)
        self._accept_unframed("stage b reproduction v4", 4 + direction, params)

    def handle_stage_b_reproduction_v4_common(self, params: dict) -> None:
        direction = self._reproduction_direction(params)
        self._accept_unframed("stage b reproduction v4", 6 + direction, params)

    def handle_stage_b_reproduction_v4_coverage(self, params: dict) -> None:
        direction = self._reproduction_direction(params)
        self._accept_unframed("stage b reproduction v4", 8 + direction, params)

    def handle_stage_b_reproduction_v4_digest(self, params: dict) -> None:
        self._accept_unframed("stage b reproduction v4", 10, params)

    @staticmethod
    def _reproduction_direction(params: dict) -> int:
        direction = int(params.get("direction", -1))
        if direction not in (0, 1):
            raise VelocitySweepProtocolError("invalid reproduction direction")
        return direction

    def handle_stage_b_terminal_core(self, params: dict) -> None:
        self._accept_group_fragment("stage b terminal", 4, 0, params)

    def handle_stage_b_terminal_identity(self, params: dict) -> None:
        self._accept_group_fragment("stage b terminal", 4, 1, params)

    def handle_stage_b_terminal_interval(self, params: dict) -> None:
        self._accept_group_fragment(
            "stage b terminal", 4, 2 + int(params.get("direction", -1)), params
        )

    def handle_terminal_direction(self, params: dict) -> None:
        self._accept_group_fragment("terminal", 3, len(self._group_parts), params)

    def handle_terminal_integrity(self, params: dict) -> None:
        self._accept_group_fragment("terminal", 3, 2, params)

    def handle_outer_inconclusive(self, params: dict) -> None:
        """Validate the generic inconclusive terminal against detailed evidence."""
        if self.integrity is None or self.outcome != "inconclusive":
            raise VelocitySweepProtocolError("unexpected outer inconclusive terminal")
        self._validate_identity(params, expected_fragment=3)
        for key in (
            "sufficient_direction_mask",
            "cause",
            "digest_low",
            "digest_high",
        ):
            if int(params[key]) != int(self.integrity[key]):
                raise VelocitySweepProtocolError(
                    "outer inconclusive does not match detailed terminal"
                )
        if int(params["phase"]) != 10:
            raise VelocitySweepProtocolError("outer inconclusive names wrong phase")
        self.outer_inconclusive = dict(params)
        self.done = True

    def _accept_group_fragment(
        self,
        kind: str,
        fragment_count: int,
        expected_fragment: int,
        params: dict,
    ) -> None:
        if self._unframed_kind is not None:
            raise VelocitySweepProtocolError(
                "%s interrupted %s" % (kind, self._unframed_kind)
            )
        fragment = int(params.get("fragment", -1))
        if fragment != expected_fragment:
            raise VelocitySweepProtocolError(
                "unexpected %s fragment %d (expected %d)"
                % (kind, fragment, expected_fragment)
            )
        if self._group_kind is None:
            if fragment != 0:
                raise VelocitySweepProtocolError("fragment group did not start at zero")
            if self.plan is None and kind not in ("plan", "stage b terminal"):
                raise VelocitySweepProtocolError(
                    "velocity sweep plan must arrive first"
                )
            if self.plan is not None and kind == "plan":
                raise VelocitySweepProtocolError("duplicate velocity sweep plan")
            self._start_group(kind, fragment_count, params)
        else:
            if kind != self._group_kind:
                raise VelocitySweepProtocolError("fragment type changed within group")
            self._validate_identity(params, expected_fragment=fragment)
            if fragment != len(self._group_parts):
                raise VelocitySweepProtocolError("duplicate or reordered fragment")
        self._group_parts.append(dict(params))
        if len(self._group_parts) == self._group_fragments:
            self._finish_group()

    def _accept_consensus_part(self, params: dict, expected_fragment: int) -> None:
        if self._group_kind != "rung consensus":
            raise VelocitySweepProtocolError("consensus fragment arrived without core")
        fragment = int(params.get("fragment", -1))
        if fragment != expected_fragment:
            raise VelocitySweepProtocolError("consensus fragment identity mismatch")
        if fragment not in self._rung_expected_fragments:
            raise VelocitySweepProtocolError("unexpected consensus fragment")
        if any(int(part["fragment"]) == fragment for part in self._group_parts):
            raise VelocitySweepProtocolError("duplicate consensus fragment")
        if fragment != self._rung_expected_order[len(self._group_parts)]:
            raise VelocitySweepProtocolError("reordered consensus fragment")
        self._validate_identity(params, expected_fragment=fragment)
        core = self._group_parts[0]
        if int(params.get("rung_index", -1)) != int(core["rung_index"]):
            raise VelocitySweepProtocolError("consensus rung identity mismatch")
        if fragment in (1, 2, 3, 4):
            direction = int(params["direction"])
            component_index = int(params["component_index"])
            prefix = ("forward", "reverse")[direction]
            if component_index >= int(core[prefix + "_component_count"]):
                raise VelocitySweepProtocolError("undeclared consensus component")
            if int(params["low_q16"]) > int(params["high_q16"]):
                raise VelocitySweepProtocolError("reversed consensus component")
        else:
            direction = int(params["direction"])
            prefix = ("forward", "reverse")[direction]
            if int(core[prefix + "_class"]) != CONSENSUS_ELIGIBLE:
                raise VelocitySweepProtocolError(
                    "pool supplied for ineligible consensus"
                )
            if int(params["pooled_low_q16"]) > int(params["pooled_high_q16"]):
                raise VelocitySweepProtocolError("reversed consensus pool interval")
        self._group_parts.append(dict(params))
        self._finish_consensus_if_complete()

    def _finish_consensus_if_complete(self) -> None:
        received = {int(part["fragment"]) for part in self._group_parts}
        if received != self._rung_expected_fragments:
            return
        self._finish_rung_consensus(self._group_parts)
        self._next_evidence_sequence += 1
        self._group_kind = None
        self._group_parts = []
        self._group_fragments = 0
        self._rung_expected_fragments = set()
        self._rung_expected_order = []

    def _validate_consensus_core(self, core: dict) -> None:
        rung_index = int(core["rung_index"])
        if rung_index in self.rungs:
            raise VelocitySweepProtocolError("duplicate rung")
        if int(self.plan["observations_per_direction"]) != 4:
            raise VelocitySweepProtocolError(
                "consensus requires four observations per direction"
            )
        for direction, prefix in enumerate(("forward", "reverse")):
            classification = int(core[prefix + "_class"])
            component_count = int(core[prefix + "_component_count"])
            expected_components = {
                CONSENSUS_ELIGIBLE: 1,
                CONSENSUS_AMBIGUOUS: 2,
                CONSENSUS_INSUFFICIENT: 0,
                CONSENSUS_INCOMPLETE: 0,
            }.get(classification)
            if expected_components is None or component_count != expected_components:
                raise VelocitySweepProtocolError(
                    "invalid consensus class/component count"
                )
            collected = int(core[prefix + "_collected_mask"])
            eligible = int(core[prefix + "_eligible_mask"])
            included = int(core[prefix + "_included_mask"])
            if any(mask & ~0x0F for mask in (collected, eligible, included)):
                raise VelocitySweepProtocolError(
                    "consensus mask exceeds four observations"
                )
            if eligible & ~collected or included & ~eligible:
                raise VelocitySweepProtocolError("consensus masks are not nested")
            if classification == CONSENSUS_ELIGIBLE and included.bit_count() < 3:
                raise VelocitySweepProtocolError("eligible consensus lacks three votes")
            if classification != CONSENSUS_ELIGIBLE and included != 0:
                raise VelocitySweepProtocolError(
                    "ineligible consensus includes observations"
                )
            operable_count = int(core[prefix + "_operable_count"])
            if operable_count not in range(5):
                raise VelocitySweepProtocolError("invalid consensus operable count")
            observed_slots = {
                slot
                for member in range(4)
                if collected & (1 << member)
                for slot in (2 * member + direction,)
            }
            if any(
                (rung_index, slot) not in self.observations for slot in observed_slots
            ):
                raise VelocitySweepProtocolError(
                    "rung arrived before its declared collected observations"
                )
            actual_slots = {
                slot
                for observed_rung, slot in self.observations
                if observed_rung == rung_index and slot % 2 == direction
            }
            if actual_slots != observed_slots:
                raise VelocitySweepProtocolError(
                    "consensus collected mask disagrees with stream"
                )
        # Slots per rung is firmware geometry; the plan declares it.
        for slot in range(2 * int(self.plan["observations_per_direction"])):
            observation = self.observations.get((rung_index, slot))
            if observation is not None and int(observation["velocity_p"]) != int(
                core["velocity_p"]
            ):
                raise VelocitySweepProtocolError("rung gain disagrees with observation")

    def _accept_unframed(self, kind: str, expected_part: int, params: dict) -> None:
        part_counts = {
            "directional region": 4,
            "joint region": 1,
            "stage b handoff": 4,
            "stage b reproduction": 5,
            "stage b reproduction v4": 11,
        }
        if self._group_kind is not None:
            raise VelocitySweepProtocolError(
                "%s interrupted a fragmented record" % kind
            )
        if self.plan is None:
            raise VelocitySweepProtocolError("%s arrived before plan" % kind)
        if self._unframed_kind is None:
            if expected_part != 0:
                raise VelocitySweepProtocolError(
                    "%s record did not start with its first part" % kind
                )
            self._start_unframed(kind, params)
        else:
            if self._unframed_kind != kind:
                raise VelocitySweepProtocolError(
                    "%s interrupted %s" % (kind, self._unframed_kind)
                )
            self._validate_unframed_identity(params)
            if expected_part != len(self._unframed_parts):
                raise VelocitySweepProtocolError("reordered %s record" % kind)
        self._unframed_parts.append(self._strip_metadata(params))
        if len(self._unframed_parts) == part_counts[kind]:
            self._finish_unframed(kind)

    def _start_unframed(self, kind: str, params: dict) -> None:
        self._validate_run(params)
        self._resolve_trace_only_current(int(params["evidence_sequence"]))
        if int(params["evidence_sequence"]) != self._next_evidence_sequence:
            raise VelocitySweepProtocolError("%s evidence sequence gap" % kind)
        self._unframed_kind = kind

    def _validate_unframed_identity(self, params: dict) -> None:
        self._validate_run(params)
        if int(params["evidence_sequence"]) != self._next_evidence_sequence:
            raise VelocitySweepProtocolError(
                "%s evidence sequence changed" % self._unframed_kind
            )

    def _validate_run(self, params: dict) -> None:
        run_sequence = int(params["run_sequence"])
        if self._run_sequence is None:
            self._run_sequence = run_sequence
        elif run_sequence != self._run_sequence:
            raise VelocitySweepProtocolError("run sequence changed")

    @staticmethod
    def _strip_metadata(params: dict) -> dict:
        return {
            key: value
            for key, value in params.items()
            if key != "oid" and not key.startswith("#")
        }

    def _finish_unframed(self, kind: str) -> None:
        parts = self._unframed_parts
        if kind == "directional region":
            self._finish_directional_region(parts)
        elif kind == "joint region":
            self._finish_joint_region(parts[0])
        elif kind == "stage b handoff":
            self._finish_stage_b_handoff(parts)
        elif kind == "stage b reproduction":
            self._finish_stage_b_reproduction(parts)
        elif kind == "stage b reproduction v4":
            self._finish_stage_b_reproduction_v4(parts)
        else:
            raise VelocitySweepProtocolError("unknown unframed record")
        self._next_evidence_sequence += 1
        self._unframed_kind = None
        self._unframed_parts = []

    def _start_group(self, kind: str, fragment_count: int, params: dict) -> None:
        run_sequence = int(params["run_sequence"])
        evidence_sequence = int(params["evidence_sequence"])
        if self._run_sequence is None:
            self._run_sequence = run_sequence
        elif run_sequence != self._run_sequence:
            raise VelocitySweepProtocolError("run sequence changed")
        self._resolve_trace_only_current(
            evidence_sequence,
            kind=kind,
            outcome=int(params.get("outcome", -1)),
        )
        if kind == "stage b terminal":
            self._accept_recovery_rest_sequence_position(kind, evidence_sequence)
        elif evidence_sequence != self._next_evidence_sequence:
            raise VelocitySweepProtocolError(
                "evidence sequence gap: got %d, expected %d"
                % (evidence_sequence, self._next_evidence_sequence)
            )
        self._group_kind = kind
        self._group_fragments = fragment_count

    def _validate_identity(self, params: dict, *, expected_fragment: int) -> None:
        if int(params["run_sequence"]) != self._run_sequence:
            raise VelocitySweepProtocolError("run sequence changed")
        if int(params["evidence_sequence"]) != self._next_evidence_sequence:
            raise VelocitySweepProtocolError("evidence sequence changed within group")
        if int(params["fragment"]) != expected_fragment:
            raise VelocitySweepProtocolError("fragment identity mismatch")

    def _finish_group(self) -> None:
        kind = self._group_kind
        parts = self._group_parts
        if kind == "plan":
            self._finish_plan(parts)
            self._next_evidence_sequence += 1
        elif kind == "observation":
            self._finish_observation(parts)
            self._next_evidence_sequence += 1
            self._trace_only_current_pending = True
        elif kind == "terminal":
            self._finish_terminal(parts)
        elif kind == "stage b terminal":
            self._finish_stage_b_terminal(parts)
        else:
            raise VelocitySweepProtocolError("unknown fragment group")
        self._group_kind = None
        self._group_parts = []
        self._group_fragments = 0

    def _resolve_trace_only_current(
        self,
        evidence_sequence: int,
        *,
        kind: str | None = None,
        outcome: int = -1,
    ) -> None:
        if not self._trace_only_current_pending:
            return
        if self._combined_stage_b_schema == 13:
            if evidence_sequence == self._next_evidence_sequence + 2:
                self._next_evidence_sequence += 2
                self._trace_only_current_pending = False
            elif (
                evidence_sequence == self._next_evidence_sequence
                and kind == "stage b terminal"
                and outcome == 3
            ):
                self._trace_only_current_pending = False
                return
            else:
                raise VelocitySweepProtocolError(
                    f"{kind or 'evidence'} evidence sequence gap"
                )
            return
        if evidence_sequence == self._next_evidence_sequence:
            self._trace_only_current_pending = False
        elif evidence_sequence == self._next_evidence_sequence + 1:
            self._next_evidence_sequence += 1
            self._trace_only_current_pending = False

    def _accept_recovery_rest_sequence_position(
        self,
        kind: str,
        evidence_sequence: int,
        *,
        rung_index: int | None = None,
        outcome: int | None = None,
    ) -> None:
        hidden_positions = 2 if self._combined_stage_b_schema == 13 else 1
        if evidence_sequence == self._next_evidence_sequence:
            if (
                self._combined_stage_b_schema in (12, 13)
                and kind == "recovery"
                and outcome == 1
            ):
                raise VelocitySweepProtocolError(
                    "moving recovery omitted hidden recovery-rest evidence"
                )
            return
        pending = self._recovery_rest_pending
        if (
            self._combined_stage_b_schema in (11, 12, 13)
            and evidence_sequence == self._next_evidence_sequence + hidden_positions
            and pending is not None
            and pending[0] == 0
            and kind in ("recovery", "stage b terminal")
        ):
            if (
                self._combined_stage_b_schema in (12, 13)
                and kind == "recovery"
                and (rung_index != pending[1] or outcome != 1)
            ):
                raise VelocitySweepProtocolError(
                    "hidden recovery-rest evidence changed its causal rung"
                )
            self._next_evidence_sequence += hidden_positions
            self._recovery_rest_pending = (pending[0], pending[1], True)
            return
        raise VelocitySweepProtocolError(f"{kind} evidence sequence gap")

    @staticmethod
    def _merge(parts: list[dict]) -> dict:
        merged: dict = {}
        for part in parts:
            for key, value in part.items():
                if key in ("fragment", "oid") or key.startswith("#"):
                    continue
                if key in merged and merged[key] != value:
                    raise VelocitySweepProtocolError(
                        "fragment metadata differs for %s" % key
                    )
                merged[key] = value
        return merged

    def _finish_plan(self, parts: list[dict]) -> None:
        plan = self._merge(parts)
        if int(plan["maximum_workflow_ms"]) < int(plan["nominal_workflow_ms"]):
            raise VelocitySweepProtocolError("plan maximum is below nominal duration")
        if self._workflow_shape == 3:
            # Precedence: the plan's own field, then the revision the MCU
            # publishes, then duration inference. Inference is a fallback for
            # firmware that publishes neither, not a gate: the duration tables
            # only ever listed the values produced at previously-run TRAVEL
            # settings, so gating on them rejected valid acquisitions elsewhere.
            schema_revision = plan.get("schema_revision")
            if schema_revision is not None:
                schema_revision = int(schema_revision)
            elif self._firmware_stage_b_schema is not None:
                schema_revision = self._firmware_stage_b_schema
            elif self._workflow_duration is not None:
                schema_revision = COMBINED_STAGE_B_WORKFLOW_SCHEMAS.get(
                    self._workflow_duration
                )
            # Nothing to bind from is not an error here; a consumer that needs
            # the revision reports its own absence more usefully than this can.
            if schema_revision is not None:
                self._combined_stage_b_schema = schema_revision
        self.plan = plan

    def _finish_observation(self, parts: list[dict]) -> None:
        renamed_parts = []
        for index, part in enumerate(parts):
            part = dict(part)
            if index == 1:
                part["rate_variance_mantissa"] = part.pop("variance_mantissa")
                part["rate_variance_shift"] = part.pop("variance_shift")
            elif index == 3:
                part["disturbance_variance_mantissa"] = part.pop("variance_mantissa")
                part["disturbance_variance_shift"] = part.pop("variance_shift")
            renamed_parts.append(part)
        observation = self._merge(renamed_parts)
        key = (int(observation["rung_index"]), int(observation["slot"]))
        if key in self.observations:
            raise VelocitySweepProtocolError("duplicate observation")
        slot_count = 2 * int(self.plan["observations_per_direction"])
        if key[1] not in range(slot_count):
            raise VelocitySweepProtocolError("invalid observation slot")
        self.observations[key] = observation
        self._last_evidence = ("observation", key[0])

    def _finish_rung_consensus(self, parts: list[dict]) -> None:
        core = dict(parts[0])
        components: list[list[tuple[int, int]]] = [[], []]
        pools: list[dict | None] = [None, None]
        for part in parts[1:]:
            fragment = int(part["fragment"])
            direction = int(part["direction"])
            if fragment in (1, 2, 3, 4):
                components[direction].append(
                    (int(part["low_q16"]), int(part["high_q16"]))
                )
            else:
                pools[direction] = self._strip_metadata(part)
        rung = self._strip_metadata(core)
        rung["components"] = components
        rung["pools"] = pools
        rung_index = int(rung["rung_index"])
        self.rungs[rung_index] = rung
        self._last_evidence = ("rung", rung_index)
        if self._combined_stage_b_schema in (11, 12, 13):
            self._recovery_rest_pending = (0, rung_index, False)

    def _finish_directional_region(self, parts: list[dict]) -> None:
        core, model, rates, boundary = parts
        membership = int(core["member_mask"])
        if membership == 0:
            raise VelocitySweepProtocolError("directional region membership is empty")
        for part in (model, rates, boundary):
            if int(part["member_mask"]) != membership:
                raise VelocitySweepProtocolError(
                    "directional region membership changed between parts"
                )
        packed = int(core["direction_kind_closure"])
        direction = packed & 1
        kind = (packed >> 1) & 1
        closure = packed >> 2
        bounds = int(core["rung_bounds"])
        region = self._merge(parts)
        region.update(
            {
                "direction": direction,
                "kind": "valid" if kind == 0 else "fragment",
                "closure": closure,
                "first_rung": bounds & 0xFF,
                "last_rung": bounds >> 8,
                "common_interval_q16": (
                    int(model["common_low_q16"]),
                    int(model["common_high_q16"]),
                ),
                "pooled_interval_q16": (
                    int(model["pooled_low_q16"]),
                    int(model["pooled_high_q16"]),
                ),
            }
        )
        self.directional_regions.append(region)

    def _finish_joint_region(self, params: dict) -> None:
        membership = int(params["member_mask"])
        bounds = int(params["rung_bounds"])
        region = dict(params)
        region["first_rung"] = bounds & 0xFF
        region["last_rung"] = bounds >> 8
        if membership == 0 or int(region["member_count"]) != membership.bit_count():
            raise VelocitySweepProtocolError("joint region membership is inconsistent")
        self.joint_regions.append(region)

    def _find_region(self, direction: int, member_mask: int) -> dict:
        matches = [
            region
            for region in self.directional_regions
            if int(region["direction"]) == direction
            and int(region["member_mask"]) == member_mask
        ]
        if len(matches) != 1:
            raise VelocitySweepProtocolError(
                "selected directional membership does not name one region"
            )
        return matches[0]

    def _finish_stage_b_handoff(self, parts: list[dict]) -> None:
        core, nomination, forward, reverse = parts
        if int(core["nominated_p"]) != int(nomination["nominated_p"]):
            raise VelocitySweepProtocolError("stage b nomination changed between parts")
        if int(forward["direction"]) != 0 or int(reverse["direction"]) != 1:
            raise VelocitySweepProtocolError(
                "stage b directional handoff order mismatch"
            )
        nominated_rung = int(nomination["nominated_rung"])
        selected = []
        for direction, part, key in (
            (0, forward, "forward_member_mask"),
            (1, reverse, "reverse_member_mask"),
        ):
            membership = int(part["member_mask"])
            if membership != int(core[key]):
                raise VelocitySweepProtocolError(
                    "stage b handoff membership changed between parts"
                )
            region = self._find_region(direction, membership)
            expected_class = 1 if region["kind"] == "valid" else 0
            if int(part.get("region_class", -1)) != expected_class:
                raise VelocitySweepProtocolError(
                    "stage b handoff region class changed between records"
                )
            selected.append(region)
        selected_joint_mask = int(nomination["selected_joint_mask"])
        if selected_joint_mask & ~int(core["joint_member_mask"]):
            raise VelocitySweepProtocolError(
                "selected joint component lies outside the reported union"
            )
        if not any(
            int(region["member_mask"]) == selected_joint_mask
            for region in self.joint_regions
        ):
            raise VelocitySweepProtocolError(
                "stage b nomination names unknown joint component"
            )
        handoff = dict(core)
        for key, value in nomination.items():
            if key not in ("flags", "nominated_p"):
                handoff[key] = value
        handoff["nomination_flags"] = int(nomination["flags"])
        handoff["nominated_rung"] = nominated_rung
        handoff["joint_union_mask"] = int(core["joint_member_mask"])
        handoff["selected_joint_mask"] = selected_joint_mask
        handoff["selected_regions"] = selected
        handoff["directions"] = [forward, reverse]
        self.handoff = handoff
        for region in self.directional_regions:
            region["covers_nominated_p"] = bool(
                int(region["member_mask"]) & (1 << nominated_rung)
            )

    def _finish_stage_b_reproduction(self, parts: list[dict]) -> None:
        core, memberships, forward, reverse, digest = parts
        if int(forward["direction"]) != 0 or int(reverse["direction"]) != 1:
            raise VelocitySweepProtocolError(
                "stage b reproduction direction order mismatch"
            )
        reproduction = self._merge([core, memberships, digest])
        reproduction["previous_memberships"] = (
            int(memberships["previous_forward_mask"]),
            int(memberships["previous_reverse_mask"]),
            int(memberships["previous_joint_mask"]),
        )
        reproduction["current_memberships"] = (
            int(memberships["current_forward_mask"]),
            int(memberships["current_reverse_mask"]),
            int(memberships["current_joint_mask"]),
        )
        reproduction["previous_intervals"] = (
            (int(forward["previous_low_q16"]), int(forward["previous_high_q16"])),
            (int(reverse["previous_low_q16"]), int(reverse["previous_high_q16"])),
        )
        reproduction["current_intervals"] = (
            (int(forward["current_low_q16"]), int(forward["current_high_q16"])),
            (int(reverse["current_low_q16"]), int(reverse["current_high_q16"])),
        )
        reproduction["previous_digest"] = int(digest["previous_digest_low"]) | (
            int(digest["previous_digest_high"]) << 32
        )
        reproduction["current_digest"] = int(digest["current_digest_low"]) | (
            int(digest["current_digest_high"]) << 32
        )
        self.reproduction = reproduction

    def _finish_stage_b_reproduction_v4(self, parts: list[dict]) -> None:
        core = parts[0]
        memberships = parts[1:4]
        pooled = parts[4:6]
        common = parts[6:8]
        coverage = parts[8:10]
        digest = parts[10]
        if [int(item["object"]) for item in memberships] != [0, 1, 2]:
            raise VelocitySweepProtocolError("reproduction membership order mismatch")
        for label, values in (
            ("pooled", pooled),
            ("common", common),
            ("coverage", coverage),
        ):
            if [int(item["direction"]) for item in values] != [0, 1]:
                raise VelocitySweepProtocolError(
                    "stage b reproduction %s direction order mismatch" % label
                )
        if int(core["reduced_margin"]) not in (0, 1):
            raise VelocitySweepProtocolError("invalid reproduction reduced-margin flag")
        if int(core["selected_member_count"]) not in range(1, 33):
            raise VelocitySweepProtocolError("invalid selected joint component count")
        selected_joint_mask = int(core["selected_joint_mask"])
        if selected_joint_mask.bit_count() != int(core["selected_member_count"]):
            raise VelocitySweepProtocolError(
                "selected joint component count disagrees with membership"
            )
        if selected_joint_mask & (1 << int(core["selected_first_rung"])) == 0:
            raise VelocitySweepProtocolError(
                "selected joint component does not contain its first rung"
            )
        for key in ("forward_validity", "reverse_validity"):
            if int(core[key]) not in range(5):
                raise VelocitySweepProtocolError(
                    "invalid reproduction directional validity"
                )
        if int(core["outcome"]) not in (1, 2):
            raise VelocitySweepProtocolError("invalid reproduction outcome")
        if int(core["reason_mask"]) & ~0x1F:
            raise VelocitySweepProtocolError("invalid reproduction reason mask")
        for item in memberships:
            if (
                not -128 <= int(item["low_delta"]) <= 127
                or not -128 <= int(item["high_delta"]) <= 127
            ):
                raise VelocitySweepProtocolError("reproduction edge delta exceeds i8")
        for item in common:
            if int(item["nonempty"]) not in (0, 1):
                raise VelocitySweepProtocolError("invalid common nonempty flag")
        for item in coverage:
            if int(item["coverage"]) not in (0, 1):
                raise VelocitySweepProtocolError("invalid reproduction coverage")
        reproduction = dict(core)
        reproduction["memberships"] = [
            {
                "previous": int(item["previous_mask"]),
                "current": int(item["current_mask"]),
                "core": int(item["core_mask"]),
                "previous_only": int(item["previous_only_mask"]),
                "current_only": int(item["current_only_mask"]),
                "low_delta": int(item["low_delta"]),
                "high_delta": int(item["high_delta"]),
            }
            for item in memberships
        ]
        reproduction["pooled"] = [
            {
                "previous": [
                    int(item["previous_low_q16"]),
                    int(item["previous_high_q16"]),
                ],
                "current": [
                    int(item["current_low_q16"]),
                    int(item["current_high_q16"]),
                ],
                "overlap": [
                    int(item["overlap_low_q16"]),
                    int(item["overlap_high_q16"]),
                ],
            }
            for item in pooled
        ]
        reproduction["common"] = [
            {
                "previous": [
                    int(item["previous_low_q16"]),
                    int(item["previous_high_q16"]),
                ],
                "current": [
                    int(item["current_low_q16"]),
                    int(item["current_high_q16"]),
                ],
                "conservative": [
                    int(item["conservative_low_q16"]),
                    int(item["conservative_high_q16"]),
                ],
                "nonempty": bool(int(item["nonempty"])),
            }
            for item in common
        ]
        reproduction["coverage"] = [
            {
                "kind": int(item["coverage"]),
                "signed_rung_distance": int(item["signed_rung_distance"]),
                "gain_ratio_num": int(item["gain_ratio_num"]),
                "gain_ratio_den": int(item["gain_ratio_den"]),
            }
            for item in coverage
        ]
        reproduction["previous_digest"] = int(digest["previous_digest_low"]) | (
            int(digest["previous_digest_high"]) << 32
        )
        reproduction["current_digest"] = int(digest["current_digest_low"]) | (
            int(digest["current_digest_high"]) << 32
        )
        self.reproduction = reproduction

    def _finish_stage_b_terminal(self, parts: list[dict]) -> None:
        core, identity, forward, reverse = parts
        pending = self._recovery_rest_pending
        hidden_rest = pending is not None and pending[2]
        selected_rest = (
            int(core["outcome"]) == 2
            and int(core["cause"]) == 7
            and bool(int(core["recovery_unavailable"]))
        )
        ordinary_rest = int(core["cause"]) == 53
        if hidden_rest and not (
            selected_rest
            or (self._combined_stage_b_schema in (12, 13) and ordinary_rest)
        ):
            if self._combined_stage_b_schema == 11:
                raise VelocitySweepProtocolError(
                    "hidden selected-rest sequence requires cause-7 terminal"
                )
            raise VelocitySweepProtocolError(
                "hidden recovery-rest sequence lacks a completed-rest terminal"
            )
        if (
            self._combined_stage_b_schema in (12, 13)
            and pending is not None
            and not hidden_rest
            and ordinary_rest
        ):
            raise VelocitySweepProtocolError(
                "completed-rest terminal omitted hidden recovery-rest evidence"
            )
        self._recovery_rest_pending = None
        self._validate_recovery_completeness(core)
        if int(forward["direction"]) != 0 or int(reverse["direction"]) != 1:
            raise VelocitySweepProtocolError(
                "stage b terminal direction order mismatch"
            )
        outcome_code = int(core["outcome"])
        if outcome_code not in OUTCOME_NAMES:
            raise VelocitySweepProtocolError("unknown stage b terminal outcome")
        preflight_rejection = self.plan is None and outcome_code in (3, 4)
        if self.plan is None and not preflight_rejection:
            raise VelocitySweepProtocolError("stage b terminal arrived without plan")
        expected_observations = int(core["expected_observations"])
        expected_rungs = int(core["expected_rungs"])
        if self.plan is not None:
            planned_rungs = int(self.plan["rung_count"])
            planned_observations = (
                planned_rungs * int(self.plan["observations_per_direction"]) * 2
            )
            if (
                expected_rungs != planned_rungs
                or expected_observations != planned_observations
            ):
                raise VelocitySweepProtocolError(
                    "stage b terminal expected counts disagree with plan"
                )
        elif expected_observations != 0 or expected_rungs != 0:
            raise VelocitySweepProtocolError(
                "preflight rejection declared executed evidence"
            )
        if int(core["emitted_observations"]) != len(self.observations):
            raise VelocitySweepProtocolError(
                "stage b terminal observation count mismatch"
            )
        if int(core["emitted_rungs"]) != len(self.rungs):
            raise VelocitySweepProtocolError("stage b terminal rung count mismatch")
        counts = {
            (direction, kind): sum(
                int(region["direction"]) == direction and region["kind"] == kind
                for region in self.directional_regions
            )
            for direction in range(2)
            for kind in ("valid", "fragment")
        }
        reported_counts = (
            int(core["forward_region_count"]),
            int(core["reverse_region_count"]),
            int(core["forward_fragment_count"]),
            int(core["reverse_fragment_count"]),
        )
        actual_counts = (
            counts[(0, "valid")],
            counts[(1, "valid")],
            counts[(0, "fragment")],
            counts[(1, "fragment")],
        )
        if reported_counts != actual_counts:
            raise VelocitySweepProtocolError("stage b terminal region counts mismatch")
        memberships = (
            int(identity["forward_member_mask"]),
            int(identity["reverse_member_mask"]),
            int(identity["joint_member_mask"]),
        )
        intervals = (
            (int(forward["pooled_low_q16"]), int(forward["pooled_high_q16"])),
            (int(reverse["pooled_low_q16"]), int(reverse["pooled_high_q16"])),
        )
        combined_response = self._workflow_shape == 3
        if outcome_code == 1 and combined_response:
            if self.reproduction is not None:
                raise VelocitySweepProtocolError(
                    "combined Stage B carried reproduction evidence"
                )
            if int(identity["nominated_p"]) == 0 or any(
                interval[0] > interval[1] for interval in intervals
            ):
                raise VelocitySweepProtocolError(
                    "combined Stage B selected response is invalid"
                )
        elif outcome_code == 1:
            if (
                self.reproduction is None
                or int(self.reproduction.get("schema_revision", 0))
                not in SUPPORTED_STAGE_B_REPRODUCTION_SCHEMAS
            ):
                raise VelocitySweepProtocolError(
                    "stage b Complete terminal arrived without schema-8 reproduction"
                )
            if int(self.reproduction["outcome"]) != 1:
                raise VelocitySweepProtocolError(
                    "stage b Complete terminal disagrees with reproduction outcome"
                )
            expected_memberships = (
                int(self.reproduction["memberships"][0]["core"]),
                int(self.reproduction["memberships"][1]["core"]),
                int(self.reproduction["selected_joint_mask"]),
            )
            expected_nomination = int(self.reproduction["final_p"])
            expected_intervals = tuple(
                tuple(int(bound) for bound in item["overlap"])
                for item in self.reproduction["pooled"]
            )
            if memberships != expected_memberships:
                raise VelocitySweepProtocolError(
                    "stage b Complete memberships disagree with reproduction"
                )
            if int(identity["nominated_p"]) != expected_nomination:
                raise VelocitySweepProtocolError(
                    "stage b Complete nomination disagrees with reproduction"
                )
            if intervals != expected_intervals:
                raise VelocitySweepProtocolError(
                    "stage b Complete intervals disagree with reproduction"
                )
        elif self.handoff is not None:
            expected_memberships = (
                int(self.handoff["forward_member_mask"]),
                int(self.handoff["reverse_member_mask"]),
                int(self.handoff["joint_union_mask"]),
            )
            if memberships != expected_memberships:
                raise VelocitySweepProtocolError(
                    "stage b terminal memberships disagree with handoff"
                )
            if int(identity["nominated_p"]) != int(self.handoff["nominated_p"]):
                raise VelocitySweepProtocolError(
                    "stage b terminal nomination disagrees with handoff"
                )
            expected_intervals = tuple(
                region["pooled_interval_q16"]
                for region in self.handoff["selected_regions"]
            )
            if intervals != expected_intervals:
                raise VelocitySweepProtocolError(
                    "stage b terminal intervals disagree with selected regions"
                )
        terminal = self._merge([core, identity])
        terminal["selected_memberships"] = memberships
        terminal["selected_intervals"] = intervals
        if combined_response:
            terminal["selected_response_intervals"] = intervals
        terminal["plan_digest"] = int(identity["plan_digest_low"]) | (
            int(identity["plan_digest_high"]) << 32
        )
        terminal["digest"] = int(identity["digest_low"]) | (
            int(identity["digest_high"]) << 32
        )
        if self.plan is None:
            if terminal["digest"] != 0:
                raise VelocitySweepProtocolError(
                    "preflight rejection carried an evidence digest"
                )
        terminal["run_started_us"] = int(forward["started_low"]) | (
            int(forward["started_high"]) << 32
        )
        terminal["run_completed_us"] = int(forward["completed_low"]) | (
            int(forward["completed_high"]) << 32
        )
        terminal["outcome_namespace"] = "stage_b"
        terminal["outcome_name"] = (
            "InconclusiveRest"
            if outcome_code == 2 and int(core["cause"]) == 53
            else OUTCOME_NAMES[outcome_code]
        )
        reverse_started = int(reverse["started_low"]) | (
            int(reverse["started_high"]) << 32
        )
        reverse_completed = int(reverse["completed_low"]) | (
            int(reverse["completed_high"]) << 32
        )
        if (
            reverse_started != terminal["run_started_us"]
            or reverse_completed != terminal["run_completed_us"]
        ):
            raise VelocitySweepProtocolError("stage b terminal timestamps disagree")
        self.terminal = terminal
        self.integrity = terminal
        self.outcome = OUTCOME_NAMES[outcome_code]
        self.sufficient_direction_mask = int(core["model_direction_mask"])
        self.full_plan_executed = expected_observations == len(
            self.observations
        ) and expected_rungs == len(self.rungs)
        self.done = True

    def _finish_terminal(self, parts: list[dict]) -> None:
        self._validate_recovery_completeness()
        directions = [dict(parts[0]), dict(parts[1])]
        integrity = dict(parts[2])
        expected_observations = int(integrity["expected_observations"])
        expected_rungs = int(integrity["expected_rungs"])
        if self.plan is None:
            raise VelocitySweepProtocolError("terminal arrived without plan")
        planned_rungs = int(self.plan["rung_count"])
        planned_observations = (
            planned_rungs * int(self.plan["observations_per_direction"]) * 2
        )
        if (
            expected_rungs != planned_rungs
            or expected_observations != planned_observations
        ):
            raise VelocitySweepProtocolError(
                "terminal expected counts disagree with plan"
            )
        if int(integrity["emitted_observations"]) != len(self.observations):
            raise VelocitySweepProtocolError("terminal observation count mismatch")
        if int(integrity["emitted_rungs"]) != len(self.rungs):
            raise VelocitySweepProtocolError("terminal rung count mismatch")
        self.full_plan_executed = expected_observations == len(
            self.observations
        ) and expected_rungs == len(self.rungs)
        integrity["digest"] = int(integrity["digest_low"]) | (
            int(integrity["digest_high"]) << 32
        )
        outcome_code = int(integrity["outcome"])
        if outcome_code not in LEGACY_OUTCOME_NAMES:
            raise VelocitySweepProtocolError("unknown velocity sweep outcome")
        cause = int(integrity["cause"])
        if not self.full_plan_executed and outcome_code != 2 and cause != 4:
            raise VelocitySweepProtocolError(
                "velocity sweep evidence is incomplete without an early terminus"
            )
        mask = int(integrity["sufficient_direction_mask"])
        direction_mask = 0
        for index, direction in enumerate(directions):
            direction_code = int(direction["direction_closure"]) & 1
            if direction_code != index:
                raise VelocitySweepProtocolError("terminal direction order mismatch")
            if int(direction["flags"]) & 1:
                direction_mask |= 1 << index
        if direction_mask != mask:
            raise VelocitySweepProtocolError("terminal sufficiency verdict mismatch")
        self.terminal_directions = directions
        self.integrity = integrity
        self.outcome = LEGACY_OUTCOME_NAMES[outcome_code]
        self.sufficient_direction_mask = mask
        if self.outcome != "inconclusive":
            self.done = True

    def _validate_recovery_completeness(self, terminal: dict | None = None) -> None:
        if self.plan is None or "recovery_slot_count" not in self.plan:
            return
        observations_per_rung = 2 * int(self.plan["observations_per_direction"])
        required = {
            rung_index
            for rung_index in self.rungs
            if sum(key[0] == rung_index for key in self.observations)
            == observations_per_rung
        }
        missing_terminal_recovery_allowed = terminal is not None and (
            int(terminal.get("recovery_unavailable", 0)) == 1
            or int(terminal.get("outcome", -1)) == 3
        )
        if missing_terminal_recovery_allowed and self.rungs:
            terminal_rung = max(self.rungs)
            if terminal_rung not in self.recoveries and self._last_evidence != (
                "rung",
                terminal_rung,
            ):
                raise VelocitySweepProtocolError(
                    "missing terminal recovery did not immediately follow its rung"
                )
            required.discard(terminal_rung)
        if set(self.recoveries) != required:
            raise VelocitySweepProtocolError(
                "recovery records do not match fully acquired rungs"
            )
