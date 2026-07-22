"""Reassemble and verify firmware-authored velocity-sweep evidence."""

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
        self._digest = FNV1A64_OFFSET
        self._canonical_events: list[bytes] = []
        self._unframed_kind: str | None = None
        self._unframed_parts: list[dict] = []
        self._recovery_parts: list[dict] = []
        self._last_evidence: tuple[str, int] | None = None

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

    def handle_recovery_core(self, params: dict) -> None:
        if self._recovery_parts:
            raise VelocitySweepProtocolError("duplicate recovery core")
        if int(params.get("stage", -1)) != 0:
            raise VelocitySweepProtocolError("Stage-B recovery named the wrong stage")
        self._validate_run(params)
        if int(params["evidence_sequence"]) != self._next_evidence_sequence:
            raise VelocitySweepProtocolError("recovery evidence sequence gap")
        rung_index = int(params.get("rung_index", -1))
        if self._last_evidence != ("rung", rung_index):
            raise VelocitySweepProtocolError(
                "recovery did not immediately follow its rung"
            )
        if rung_index in self.recoveries:
            raise VelocitySweepProtocolError("duplicate rung recovery")
        self._recovery_parts.append(dict(params))

    def handle_recovery_position(self, params: dict) -> None:
        self._accept_recovery_part(params, 1)

    def handle_recovery_timing(self, params: dict) -> None:
        self._accept_recovery_part(params, 2)

    def handle_recovery_limits(self, params: dict) -> None:
        self._accept_recovery_part(params, 3)
        core, position, timing, limits = self._recovery_parts
        recovery = self._merge([core, position, timing, limits])
        recovery["lower_rate_q"] = int(limits["lower_rate_low"]) | (
            int(limits["lower_rate_high"]) << 32
        )
        rung_index = int(core["rung_index"])
        self.recoveries[rung_index] = recovery
        encoded = self._encode_recovery(recovery)
        self._canonical_events.append(encoded)
        for byte in encoded:
            self._digest ^= byte
            self._digest = (self._digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
        self._next_evidence_sequence += 1
        self._last_evidence = ("recovery", rung_index)
        self._recovery_parts = []

    def _accept_recovery_part(self, params: dict, expected: int) -> None:
        if len(self._recovery_parts) != expected:
            raise VelocitySweepProtocolError("missing or reordered recovery fragment")
        core = self._recovery_parts[0]
        self._validate_run(params)
        if int(params["evidence_sequence"]) != int(core["evidence_sequence"]):
            raise VelocitySweepProtocolError("recovery fragment identity changed")
        self._recovery_parts.append(dict(params))

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
        self._canonical_events.append(self._encode_structured_boundary(params))

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

    def handle_stage_b_reproduction_v3_core(self, params: dict) -> None:
        if int(params.get("schema_revision", -1)) != 4:
            raise VelocitySweepProtocolError("unsupported stage b reproduction schema")
        self._accept_unframed("stage b reproduction v3", 0, params)

    def handle_stage_b_reproduction_v3_membership(self, params: dict) -> None:
        object_index = int(params.get("object", -1))
        if object_index not in (0, 1, 2):
            raise VelocitySweepProtocolError("invalid reproduction membership object")
        self._accept_unframed("stage b reproduction v3", 1 + object_index, params)

    def handle_stage_b_reproduction_v3_pooled(self, params: dict) -> None:
        direction = self._reproduction_direction(params)
        self._accept_unframed("stage b reproduction v3", 4 + direction, params)

    def handle_stage_b_reproduction_v3_common(self, params: dict) -> None:
        direction = self._reproduction_direction(params)
        self._accept_unframed("stage b reproduction v3", 6 + direction, params)

    def handle_stage_b_reproduction_v3_coverage(self, params: dict) -> None:
        direction = self._reproduction_direction(params)
        self._accept_unframed("stage b reproduction v3", 8 + direction, params)

    def handle_stage_b_reproduction_v3_digest(self, params: dict) -> None:
        self._accept_unframed("stage b reproduction v3", 10, params)

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
        for slot in range(8):
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
            "stage b reproduction v3": 11,
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
        elif kind == "stage b reproduction v3":
            self._finish_stage_b_reproduction_v3(parts)
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
        if evidence_sequence != self._next_evidence_sequence:
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
        elif kind == "terminal":
            self._finish_terminal(parts)
        elif kind == "stage b terminal":
            self._finish_stage_b_terminal(parts)
        else:
            raise VelocitySweepProtocolError("unknown fragment group")
        self._group_kind = None
        self._group_parts = []
        self._group_fragments = 0

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
        self.plan = plan
        self._hash_plan(plan)

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
        self._hash_observation(observation)
        self._canonical_events.append(self._encode_observation(observation))
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
        self._hash_rung(rung)
        self._canonical_events.append(self._encode_rung(rung))
        self._last_evidence = ("rung", rung_index)

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
        self._canonical_events.append(self._encode_directional_region(region))

    def _finish_joint_region(self, params: dict) -> None:
        membership = int(params["member_mask"])
        bounds = int(params["rung_bounds"])
        region = dict(params)
        region["first_rung"] = bounds & 0xFF
        region["last_rung"] = bounds >> 8
        if membership == 0 or int(region["member_count"]) != membership.bit_count():
            raise VelocitySweepProtocolError("joint region membership is inconsistent")
        self.joint_regions.append(region)
        self._canonical_events.append(self._encode_joint_region(region))

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
            selected.append(region)
        if not any(
            int(region["member_mask"]) == int(core["joint_member_mask"])
            for region in self.joint_regions
        ):
            raise VelocitySweepProtocolError(
                "stage b handoff names unknown joint region"
            )
        handoff = dict(core)
        for key, value in nomination.items():
            if key not in ("flags", "nominated_p"):
                handoff[key] = value
        handoff["nomination_flags"] = int(nomination["flags"])
        handoff["nominated_rung"] = nominated_rung
        handoff["selected_regions"] = selected
        handoff["directions"] = [forward, reverse]
        self.handoff = handoff
        for region in self.directional_regions:
            region["covers_nominated_p"] = bool(
                int(region["member_mask"]) & (1 << nominated_rung)
            )
        self._canonical_events.append(self._encode_handoff(handoff))

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
        self._canonical_events.append(self._encode_reproduction(reproduction))

    def _finish_stage_b_reproduction_v3(self, parts: list[dict]) -> None:
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
        self._canonical_events.extend(self._encode_reproduction_v3(reproduction))

    @staticmethod
    def _record(fields: tuple[tuple[str, int], ...]) -> bytes:
        return b"".join(struct.pack("<" + fmt, int(value)) for fmt, value in fields)

    def _encode_plan(self, plan_digest: int) -> bytes:
        plan = self.plan
        if plan is None:
            return b""
        return self._record(
            (
                ("B", 1),
                ("I", plan["run_sequence"]),
                ("H", plan["evidence_sequence"]),
                ("I", plan_digest & 0xFFFF_FFFF),
                ("I", plan_digest >> 32),
                ("I", plan["requested_velocity_mrev_s"]),
                ("B", plan["requested_velocity_source"]),
                ("I", plan["planned_velocity_mrev_s"]),
                ("I", plan["effective_ceiling_mrev_s"]),
                ("H", plan["clamp_flags"]),
                ("B", plan["binding_source"]),
                ("i", plan["target_velocity_rpm"]),
                ("H", plan["p_start"]),
                ("H", plan["p_top"]),
                ("B", plan["rung_count"]),
                ("H", plan["observations_per_direction"]),
                ("I", plan["moving_stroke_us"]),
                ("I", plan["zero_settle_us"]),
                ("I", plan["nominal_workflow_ms"]),
                ("I", plan["maximum_workflow_ms"]),
                ("I", plan["origin_band_counts"]),
                ("I", plan["nominal_slot_us"]),
                ("I", plan["maximum_slot_us"]),
                ("B", plan["slot_count"]),
                ("I", plan["max_stroke_travel_mrev"]),
                ("I", plan["settle_travel_reserve_mrev"]),
                ("I", plan["negative_position_headroom_mrev"]),
                ("I", plan["positive_position_headroom_mrev"]),
                ("H", plan["hard_torque_limit"]),
                ("H", plan["usable_torque_limit"]),
            )
        )

    def _encode_recovery(self, value: dict) -> bytes:
        return self._record(
            (
                ("B", 9),
                ("I", value["run_sequence"]),
                ("H", value["evidence_sequence"]),
                ("B", value["stage"]),
                ("B", value["rung_index"]),
                ("H", value["p_raw"]),
                ("I", value["planned_velocity_mrev_s"]),
                ("i", value["start_offset_counts"]),
                ("i", value["closest_offset_counts"]),
                ("i", value["final_offset_counts"]),
                ("I", value["origin_band_counts"]),
                ("I", value["lower_rate_q"] & 0xFFFF_FFFF),
                ("I", value["lower_rate_q"] >> 32),
                ("I", value["moving_duration_us"]),
                ("I", value["settle_duration_us"]),
                ("I", value["total_duration_us"]),
                ("H", value["peak_torque_target_abs"]),
                ("B", value["binding_source"]),
                ("B", value["outcome"]),
            )
        )

    def _encode_observation(self, value: dict) -> bytes:
        return self._record(
            (
                ("B", 2),
                ("I", value["run_sequence"]),
                ("H", value["evidence_sequence"]),
                ("B", value["rung_index"]),
                ("B", value["slot"]),
                ("i", value["target_velocity_rpm"]),
                ("B", value["classification"]),
                ("B", value["flags"] & 1),
                ("B", value["delta_sign"]),
                ("I", value["delta_mantissa"]),
                ("B", value["delta_shift"]),
                ("I", value["elapsed_mantissa"]),
                ("B", value["elapsed_shift"]),
                ("i", value["rate_low"]),
                ("i", value["rate_mean"]),
                ("i", value["rate_high"]),
                ("i", value["deficit_low"]),
                ("i", value["deficit_high"]),
                ("B", value["rate_shift"]),
                ("H", value["suffix_len"]),
                ("B", value["selected_level"]),
                ("I", value["selected_blocks"]),
                ("I", value["rate_variance_mantissa"]),
                ("B", value["rate_variance_shift"]),
                ("i", value["slope_mantissa"]),
                ("B", value["slope_shift"]),
                ("I", value["slope_half_width_mantissa"]),
                ("B", value["slope_half_width_shift"]),
                ("i", value["lag_one_q"]),
                ("I", value["lag_one_half_width_q"]),
                ("I", value["residual_mantissa"]),
                ("B", value["residual_shift"]),
                ("B", value["tested_suffixes"]),
                ("H", value["velocity_p"]),
                ("i", value["disturbance_q16"]),
                ("i", value["disturbance_low_q16"]),
                ("i", value["disturbance_high_q16"]),
                ("I", value["disturbance_variance_mantissa"]),
                ("B", value["disturbance_variance_shift"]),
                ("H", value["predicted_torque_target_abs"]),
            )
        )

    def _encode_rung(self, value: dict) -> bytes:
        fields: list[tuple[str, int]] = [
            ("B", 3),
            ("I", value["run_sequence"]),
            ("H", value["evidence_sequence"]),
            ("B", value["rung_index"]),
            ("H", value["velocity_p"]),
        ]
        combined_flags = int(value["flags"])
        for direction, prefix in enumerate(("forward", "reverse")):
            directional_flags = ((combined_flags >> direction) & 1) | (
                ((combined_flags >> (direction + 2)) & 1) << 1
            )
            fields.extend(
                (
                    ("B", value[prefix + "_class"]),
                    ("B", value[prefix + "_component_count"]),
                    ("B", value[prefix + "_collected_mask"]),
                    ("B", value[prefix + "_eligible_mask"]),
                    ("B", value[prefix + "_included_mask"]),
                    ("B", value[prefix + "_operable_count"]),
                    ("B", directional_flags),
                )
            )
            components = value["components"][direction]
            for component_index in range(2):
                low, high = (
                    components[component_index]
                    if component_index < len(components)
                    else (0, 0)
                )
                fields.extend((("i", low), ("i", high)))
            pool = value["pools"][direction]
            if pool is None:
                fields.extend((("i", 0), ("i", 0), ("i", 0), ("B", 0)))
                for _ in range(4):
                    fields.extend((("i", 0), ("B", 0)))
            else:
                fields.extend(
                    (
                        ("i", pool["pooled_q16"]),
                        ("i", pool["pooled_low_q16"]),
                        ("i", pool["pooled_high_q16"]),
                        ("B", pool["variance_floor_observations"]),
                    )
                )
                for name in (
                    "mean_min_mantissa",
                    "mean_max_mantissa",
                    "envelope_low_mantissa",
                    "envelope_high_mantissa",
                ):
                    fields.extend((("i", pool[name]), ("B", pool["rate_shift"])))
        return self._record(tuple(fields))

    def _encode_structured_boundary(self, value: dict) -> bytes:
        shift = int(value["rate_shift"])
        return self._record(
            (
                ("B", 7),
                ("I", value["run_sequence"]),
                ("H", value["evidence_sequence"]),
                ("B", value["rung_index"]),
                ("B", value["slot"]),
                ("B", value["passing_suffix_mask"]),
                ("i", value["rate_low_mantissa"]),
                ("B", shift),
                ("i", value["rate_high_mantissa"]),
                ("B", shift),
                ("i", value["slope_margin_mantissa"]),
                ("B", value["slope_margin_shift"]),
                ("i", value["lag_one_margin_q"]),
            )
        )

    def _encode_directional_region(self, value: dict) -> bytes:
        rate_shift = int(value["rate_shift"])
        return self._record(
            (
                ("B", 4),
                ("I", value["run_sequence"]),
                ("H", value["evidence_sequence"]),
                ("I", value["member_mask"]),
                ("B", value["direction"]),
                ("B", 0 if value["kind"] == "valid" else 1),
                ("B", value["closure"]),
                ("B", value["first_rung"]),
                ("B", value["last_rung"]),
                ("H", value["p_low"]),
                ("H", value["p_high"]),
                ("B", value["member_count"]),
                ("i", value["common_low_q16"]),
                ("i", value["common_high_q16"]),
                ("i", value["pooled_q16"]),
                ("i", value["pooled_low_q16"]),
                ("i", value["pooled_high_q16"]),
                ("B", value["variance_floor_observations"]),
                ("i", value["mean_min_mantissa"]),
                ("B", rate_shift),
                ("i", value["mean_max_mantissa"]),
                ("B", rate_shift),
                ("i", value["envelope_low_mantissa"]),
                ("B", rate_shift),
                ("i", value["envelope_high_mantissa"]),
                ("B", rate_shift),
                ("B", value["boundary_rung_plus_one"]),
                ("i", value["tested_low_q16"]),
                ("i", value["tested_high_q16"]),
            )
        )

    def _encode_joint_region(self, value: dict) -> bytes:
        return self._record(
            (
                ("B", 5),
                ("I", value["run_sequence"]),
                ("H", value["evidence_sequence"]),
                ("I", value["member_mask"]),
                ("B", value["first_rung"]),
                ("B", value["last_rung"]),
                ("B", value["member_count"]),
                ("H", value["p_low"]),
                ("H", value["p_high"]),
                ("B", value["closure"]),
            )
        )

    def _encode_handoff(self, value: dict) -> bytes:
        fields: list[tuple[str, int]] = [
            ("B", 6),
            ("I", value["run_sequence"]),
            ("H", value["evidence_sequence"]),
            ("H", value["nominated_p"]),
            ("B", int(value["flags"]) & 0x03),
            ("I", value["joint_member_mask"]),
            ("B", value["nominated_rung"]),
            ("I", value["distance_to_start_q16"]),
            ("I", value["distance_to_top_q16"]),
            ("B", value["nomination_flags"] & 1),
        ]
        for direction, region in zip(value["directions"], value["selected_regions"]):
            fields.extend(
                (
                    ("I", direction["member_mask"]),
                    ("i", region["pooled_low_q16"]),
                    ("i", region["pooled_high_q16"]),
                    ("B", direction["coverage"]),
                    ("B", int(direction["signed_rung_distance"]) & 0xFF),
                    ("H", direction["gain_ratio_num"]),
                    ("H", direction["gain_ratio_den"]),
                    ("i", direction["settled_rate_difference_mantissa"]),
                    ("B", direction["settled_rate_difference_shift"]),
                )
            )
        return self._record(tuple(fields))

    def _encode_reproduction(self, value: dict) -> bytes:
        fields: list[tuple[str, int]] = [
            ("B", 9),
            ("I", value["run_sequence"]),
            ("H", value["evidence_sequence"]),
            ("B", value["outcome"]),
            ("H", value["previous_nominated_p"]),
            ("H", value["current_nominated_p"]),
        ]
        fields.extend(("I", item) for item in value["previous_memberships"])
        fields.extend(("I", item) for item in value["current_memberships"])
        for intervals in (value["previous_intervals"], value["current_intervals"]):
            for low, high in intervals:
                fields.extend((("i", low), ("i", high)))
        fields.extend(
            (
                ("I", value["previous_digest"] & 0xFFFF_FFFF),
                ("I", value["previous_digest"] >> 32),
                ("I", value["current_digest"] & 0xFFFF_FFFF),
                ("I", value["current_digest"] >> 32),
            )
        )
        return self._record(tuple(fields))

    def _encode_reproduction_v3(self, value: dict) -> tuple[bytes, ...]:
        def header(kind: int) -> list[tuple[str, int]]:
            return [
                ("B", kind),
                ("I", value["run_sequence"]),
                ("H", value["evidence_sequence"]),
            ]

        records = [
            self._record(
                tuple(
                    header(10)
                    + [
                        ("B", value["outcome"]),
                        ("B", value["reason_mask"]),
                        ("H", value["previous_provisional_p"]),
                        ("H", value["current_provisional_p"]),
                        ("H", value["final_p"]),
                        ("B", value["reduced_margin"]),
                        ("H", value["schema_revision"]),
                    ]
                )
            )
        ]
        for object_index, item in enumerate(value["memberships"]):
            records.append(
                self._record(
                    tuple(
                        header(11 + object_index)
                        + [("B", object_index)]
                        + [
                            ("I", item[key])
                            for key in (
                                "previous",
                                "current",
                                "core",
                                "previous_only",
                                "current_only",
                            )
                        ]
                        + [("b", item["low_delta"]), ("b", item["high_delta"])]
                    )
                )
            )
        for direction, item in enumerate(value["pooled"]):
            records.append(
                self._record(
                    tuple(
                        header(14 + direction)
                        + [("B", direction)]
                        + [
                            ("i", bound)
                            for key in ("previous", "current", "overlap")
                            for bound in item[key]
                        ]
                    )
                )
            )
        for direction, item in enumerate(value["common"]):
            records.append(
                self._record(
                    tuple(
                        header(16 + direction)
                        + [("B", direction)]
                        + [
                            ("i", bound)
                            for key in ("previous", "current", "conservative")
                            for bound in item[key]
                        ]
                        + [("B", int(item["nonempty"]))]
                    )
                )
            )
        for direction, item in enumerate(value["coverage"]):
            records.append(
                self._record(
                    tuple(
                        header(18 + direction)
                        + [
                            ("B", direction),
                            ("B", item["kind"]),
                            ("i", item["signed_rung_distance"]),
                            ("H", item["gain_ratio_num"]),
                            ("H", item["gain_ratio_den"]),
                        ]
                    )
                )
            )
        records.append(
            self._record(
                tuple(
                    header(20)
                    + [
                        ("I", value["previous_digest"] & 0xFFFF_FFFF),
                        ("I", value["previous_digest"] >> 32),
                        ("I", value["current_digest"] & 0xFFFF_FFFF),
                        ("I", value["current_digest"] >> 32),
                    ]
                )
            )
        )
        return tuple(records)

    def _stage_b_digest(self, plan_digest: int) -> int:
        digest = FNV1A64_OFFSET
        for byte in self._encode_plan(plan_digest) + b"".join(self._canonical_events):
            digest ^= byte
            digest = (digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
        return digest

    def _finish_stage_b_terminal(self, parts: list[dict]) -> None:
        self._validate_recovery_completeness()
        core, identity, forward, reverse = parts
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
        if outcome_code == 1:
            if (
                self.reproduction is None
                or int(self.reproduction.get("schema_revision", 0)) != 4
            ):
                raise VelocitySweepProtocolError(
                    "stage b Complete terminal arrived without schema-3 reproduction"
                )
            if int(self.reproduction["outcome"]) != 1:
                raise VelocitySweepProtocolError(
                    "stage b Complete terminal disagrees with reproduction outcome"
                )
            expected_memberships = tuple(
                int(item["core"]) for item in self.reproduction["memberships"]
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
                int(self.handoff["joint_member_mask"]),
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
        elif terminal["digest"] != self._stage_b_digest(terminal["plan_digest"]):
            raise VelocitySweepProtocolError("stage b evidence digest mismatch")
        terminal["run_started_us"] = int(forward["started_low"]) | (
            int(forward["started_high"]) << 32
        )
        terminal["run_completed_us"] = int(forward["completed_low"]) | (
            int(forward["completed_high"]) << 32
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
        reported_digest = int(integrity["digest_low"]) | (
            int(integrity["digest_high"]) << 32
        )
        if reported_digest != self._digest:
            raise VelocitySweepProtocolError("velocity sweep digest mismatch")
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

    def _validate_recovery_completeness(self) -> None:
        if self.plan is None or "recovery_slot_count" not in self.plan:
            return
        observations_per_rung = 2 * int(self.plan["observations_per_direction"])
        required = {
            rung_index
            for rung_index in self.rungs
            if sum(key[0] == rung_index for key in self.observations)
            == observations_per_rung
        }
        if set(self.recoveries) != required:
            raise VelocitySweepProtocolError(
                "recovery records do not match fully acquired rungs"
            )

    def _hash(self, fmt: str, value: int) -> None:
        for byte in struct.pack("<" + fmt, int(value)):
            self._digest ^= byte
            self._digest = (self._digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF

    def _hash_plan(self, plan: dict) -> None:
        fields = (
            ("B", 1),
            ("I", plan["run_sequence"]),
            ("H", plan["evidence_sequence"]),
            ("I", plan["requested_velocity_mrev_s"]),
            ("B", plan["requested_velocity_source"]),
            ("I", plan["planned_velocity_mrev_s"]),
            ("I", plan["effective_ceiling_mrev_s"]),
            ("H", plan["clamp_flags"]),
            ("B", plan["binding_source"]),
            ("i", plan["target_velocity_rpm"]),
            ("H", plan["p_start"]),
            ("H", plan["p_top"]),
            ("B", plan["rung_count"]),
            ("H", plan["observations_per_direction"]),
            ("I", plan["moving_stroke_us"]),
            ("I", plan["zero_settle_us"]),
            ("I", plan["nominal_workflow_ms"]),
            ("I", plan["maximum_workflow_ms"]),
            ("I", plan["origin_band_counts"]),
            ("I", plan["nominal_slot_us"]),
            ("I", plan["maximum_slot_us"]),
            ("B", plan["slot_count"]),
            ("I", plan["max_stroke_travel_mrev"]),
            ("I", plan["settle_travel_reserve_mrev"]),
            ("I", plan["negative_position_headroom_mrev"]),
            ("I", plan["positive_position_headroom_mrev"]),
            ("H", plan["hard_torque_limit"]),
            ("H", plan["usable_torque_limit"]),
        )
        for fmt, value in fields:
            self._hash(fmt, value)

    def _hash_observation(self, value: dict) -> None:
        fields = (
            ("B", 2),
            ("I", value["run_sequence"]),
            ("H", value["evidence_sequence"]),
            ("B", value["rung_index"]),
            ("B", value["slot"]),
            ("i", value["target_velocity_rpm"]),
            ("B", value["classification"]),
            ("B", value["flags"]),
            ("B", value["delta_sign"]),
            ("I", value["delta_mantissa"]),
            ("B", value["delta_shift"]),
            ("I", value["elapsed_mantissa"]),
            ("B", value["elapsed_shift"]),
            ("i", value["rate_low"]),
            ("i", value["rate_mean"]),
            ("i", value["rate_high"]),
            ("i", value["deficit_low"]),
            ("i", value["deficit_high"]),
            ("B", value["rate_shift"]),
            ("H", value["suffix_len"]),
            ("B", value["selected_level"]),
            ("I", value["selected_blocks"]),
            ("I", value["rate_variance_mantissa"]),
            ("B", value["rate_variance_shift"]),
            ("i", value["slope_mantissa"]),
            ("B", value["slope_shift"]),
            ("I", value["slope_half_width_mantissa"]),
            ("B", value["slope_half_width_shift"]),
            ("i", value["lag_one_q"]),
            ("I", value["lag_one_half_width_q"]),
            ("I", value["residual_mantissa"]),
            ("B", value["residual_shift"]),
            ("B", value["tested_suffixes"]),
            ("H", value["velocity_p"]),
            ("i", value["disturbance_q16"]),
            ("i", value["disturbance_low_q16"]),
            ("i", value["disturbance_high_q16"]),
            ("I", value["disturbance_variance_mantissa"]),
            ("B", value["disturbance_variance_shift"]),
            ("H", value["predicted_torque_target_abs"]),
        )
        for fmt, item in fields:
            self._hash(fmt, item)

    def _hash_rung(self, value: dict) -> None:
        for byte in self._encode_rung(value):
            self._digest ^= byte
            self._digest = (self._digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
