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
INCONCLUSIVE_REMEDIATION = {
    1: "one direction has no valid model region; inspect its fragments and boundaries",
    2: "no joint operable region supports nomination; inspect the safe rung curve",
    3: "firmware report integrity failed; retain the trace and redeploy a matched build",
    4: "current headroom ended the sweep; review current headroom if evidence is insufficient",
    5: "the sufficient run did not reproduce; compare the reported memberships and intervals",
    6: "the second request changed the frozen plan; rerun with identical request fields",
}


class VelocitySweepProtocolError(Exception):
    """Raised when the streamed sweep evidence violates its wire contract."""


class VelocitySweepAssembler:
    """Strictly reassemble one firmware-authored velocity-sweep report."""

    def __init__(self) -> None:
        self.plan: dict | None = None
        self.observations: dict[tuple[int, int], dict] = {}
        self.rungs: dict[int, dict] = {}
        self.recoveries: dict[int, dict] = {}
        self.directional_regions: list[dict] = []
        self.handoff: dict | None = None
        self.reproduction: dict | None = None
        self.terminal: dict | None = None
        self.terminal_directions: list[dict] = []
        self.integrity: dict | None = None
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

    def configure_workflow_shape(
        self,
        shape: int,
        nominal_workflow_ms: int | None = None,
        maximum_workflow_ms: int | None = None,
    ) -> None:
        """Bind terminal interpretation to the firmware-disclosed workflow.

        Shape 6 (the breakaway-seeded campaign) shares this same command-level
        envelope but never emits any Stage-B sweep evidence of its own -- the
        campaign's probe/discovery/confirmation phases are relayed by
        ``BreakawayCampaignAssembler`` instead. Binding it here, like shape 2
        (Stage-C resume), keeps this assembler's terminal-interpretation gate
        inert rather than raising on evidence this assembler will never see.
        """
        if shape not in (0, 1, 2, 3, 6):
            raise VelocitySweepProtocolError("invalid workflow shape")
        if self.plan is not None or self._group_parts or self._last_evidence is not None:
            raise VelocitySweepProtocolError("workflow shape arrived after sweep evidence")
        if self._workflow_shape is not None:
            raise VelocitySweepProtocolError("duplicate workflow shape")
        if (nominal_workflow_ms is None) != (maximum_workflow_ms is None):
            raise VelocitySweepProtocolError("incomplete workflow duration")
        self._workflow_shape = shape

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

    def handle_recovery_summary(self, params: dict) -> None:
        """Accept one compact recovery summary after its causal rung."""
        if self.plan is None:
            raise VelocitySweepProtocolError("recovery summary arrived before plan")
        if int(params.get("stage", -1)) != 0:
            raise VelocitySweepProtocolError("Stage-B recovery summary named the wrong stage")
        self._validate_run(params)
        rung_index = int(params.get("rung_index", -1))
        if rung_index in self.recoveries:
            raise VelocitySweepProtocolError("duplicate rung recovery")
        outcome = int(params.get("outcome", -1))
        self._accept_recovery_rest_sequence_position("recovery", int(params["evidence_sequence"]))
        if self._last_evidence != ("rung", rung_index):
            raise VelocitySweepProtocolError("recovery did not immediately follow its rung")
        if int(params.get("p_raw", -1)) != int(self.rungs[rung_index]["velocity_p"]):
            raise VelocitySweepProtocolError("recovery summary changed the rung gain")
        if int(params.get("binding_source", -1)) not in range(7):
            raise VelocitySweepProtocolError("invalid recovery binding source")
        if outcome not in range(5):
            raise VelocitySweepProtocolError("invalid recovery outcome")
        self.recoveries[rung_index] = self._strip_metadata(params)
        self._next_evidence_sequence += 1
        self._last_evidence = ("recovery", rung_index)

    def handle_stage_b_terminal_core(self, params: dict) -> None:
        self._accept_group_fragment("stage b terminal", 4, 0, params)

    def handle_stage_b_terminal_identity(self, params: dict) -> None:
        self._accept_group_fragment("stage b terminal", 4, 1, params)

    def handle_stage_b_terminal_interval(self, params: dict) -> None:
        self._accept_group_fragment(
            "stage b terminal", 4, 2 + int(params.get("direction", -1)), params
        )

    def _accept_group_fragment(
        self,
        kind: str,
        fragment_count: int,
        expected_fragment: int,
        params: dict,
    ) -> None:
        if self._unframed_kind is not None:
            raise VelocitySweepProtocolError(f"{kind} interrupted {self._unframed_kind}")
        fragment = int(params.get("fragment", -1))
        if fragment != expected_fragment:
            raise VelocitySweepProtocolError(
                f"unexpected {kind} fragment {int(fragment)} (expected {int(expected_fragment)})"
            )
        if self._group_kind is None:
            if fragment != 0:
                raise VelocitySweepProtocolError("fragment group did not start at zero")
            if self.plan is None and kind not in ("plan", "stage b terminal"):
                raise VelocitySweepProtocolError("velocity sweep plan must arrive first")
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

    def _validate_run(self, params: dict) -> None:
        run_sequence = int(params["run_sequence"])
        if self._run_sequence is None:
            self._run_sequence = run_sequence
        elif run_sequence != self._run_sequence:
            raise VelocitySweepProtocolError("run sequence changed")

    @staticmethod
    def _strip_metadata(params: dict) -> dict:
        return {
            key: value for key, value in params.items() if key != "oid" and not key.startswith("#")
        }

    def _start_group(self, kind: str, fragment_count: int, params: dict) -> None:
        run_sequence = int(params["run_sequence"])
        evidence_sequence = int(params["evidence_sequence"])
        if self._run_sequence is None:
            self._run_sequence = run_sequence
        elif run_sequence != self._run_sequence:
            raise VelocitySweepProtocolError("run sequence changed")
        self._resolve_trace_only_current(evidence_sequence)
        if kind == "stage b terminal":
            self._accept_recovery_rest_sequence_position(kind, evidence_sequence)
        elif evidence_sequence != self._next_evidence_sequence:
            raise VelocitySweepProtocolError(
                f"evidence sequence gap: got {int(evidence_sequence)}, expected "
                f"{int(self._next_evidence_sequence)}"
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
        if kind == "stage b terminal":
            self._finish_stage_b_terminal(parts)
        else:
            raise VelocitySweepProtocolError("unknown fragment group")
        self._group_kind = None
        self._group_parts = []
        self._group_fragments = 0

    def _resolve_trace_only_current(self, evidence_sequence: int) -> None:
        if not self._trace_only_current_pending:
            return
        if evidence_sequence == self._next_evidence_sequence:
            self._trace_only_current_pending = False
        elif evidence_sequence == self._next_evidence_sequence + 1:
            self._next_evidence_sequence += 1
            self._trace_only_current_pending = False

    def _accept_recovery_rest_sequence_position(self, kind: str, evidence_sequence: int) -> None:
        if evidence_sequence != self._next_evidence_sequence:
            raise VelocitySweepProtocolError(f"{kind} evidence sequence gap")

    @staticmethod
    def _merge(parts: list[dict]) -> dict:
        merged: dict = {}
        for part in parts:
            for key, value in part.items():
                if key in ("fragment", "oid") or key.startswith("#"):
                    continue
                if key in merged and merged[key] != value:
                    raise VelocitySweepProtocolError(f"fragment metadata differs for {key}")
                merged[key] = value
        return merged

    def _finish_stage_b_terminal(self, parts: list[dict]) -> None:
        core, identity, forward, reverse = parts
        self._validate_recovery_completeness(core)
        if int(forward["direction"]) != 0 or int(reverse["direction"]) != 1:
            raise VelocitySweepProtocolError("stage b terminal direction order mismatch")
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
            planned_observations = planned_rungs * int(self.plan["observations_per_direction"]) * 2
            if expected_rungs != planned_rungs or expected_observations != planned_observations:
                raise VelocitySweepProtocolError(
                    "stage b terminal expected counts disagree with plan"
                )
        elif expected_observations != 0 or expected_rungs != 0:
            raise VelocitySweepProtocolError("preflight rejection declared executed evidence")
        if int(core["emitted_observations"]) != len(self.observations):
            raise VelocitySweepProtocolError("stage b terminal observation count mismatch")
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
                region["pooled_interval_q16"] for region in self.handoff["selected_regions"]
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
        terminal["digest"] = int(identity["digest_low"]) | (int(identity["digest_high"]) << 32)
        if self.plan is None and terminal["digest"] != 0:
            raise VelocitySweepProtocolError("preflight rejection carried an evidence digest")
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
        reverse_started = int(reverse["started_low"]) | (int(reverse["started_high"]) << 32)
        reverse_completed = int(reverse["completed_low"]) | (int(reverse["completed_high"]) << 32)
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

    def _validate_recovery_completeness(self, terminal: dict | None = None) -> None:
        if self.plan is None or "recovery_slot_count" not in self.plan:
            return
        observations_per_rung = 2 * int(self.plan["observations_per_direction"])
        required = {
            rung_index
            for rung_index in self.rungs
            if sum(key[0] == rung_index for key in self.observations) == observations_per_rung
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
            raise VelocitySweepProtocolError("recovery records do not match fully acquired rungs")
