"""Reassemble and verify firmware-authored velocity-sweep evidence."""

from __future__ import annotations

import struct


FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3

OUTCOME_NAMES = {0: "complete", 1: "inconclusive", 2: "fault"}
INCONCLUSIVE_REMEDIATION = {
    1: "one direction lacks sufficient evidence; inspect directional preload or binding",
    2: "both directions lack sufficient evidence; review TUNE_VELOCITY, travel, and current headroom",
    3: "firmware report integrity failed; retain the trace and redeploy a matched build",
}


class VelocitySweepProtocolError(Exception):
    """Raised when the streamed sweep evidence violates its wire contract."""


class VelocitySweepAssembler:
    """Strictly reassemble one firmware-authored velocity-sweep report."""

    def __init__(self) -> None:
        self.plan: dict | None = None
        self.observations: dict[tuple[int, int], dict] = {}
        self.rungs: dict[int, dict] = {}
        self.terminal_directions: list[dict] = []
        self.integrity: dict | None = None
        self.outer_inconclusive: dict | None = None
        self.outcome: str | None = None
        self.sufficient_direction_mask = 0
        self.done = False
        self._run_sequence: int | None = None
        self._next_evidence_sequence = 0
        self._group_kind: str | None = None
        self._group_parts: list[dict] = []
        self._group_fragments = 0
        self._digest = FNV1A64_OFFSET

    @property
    def plan_ready(self) -> bool:
        """Whether all three pre-motion plan fragments arrived."""
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
        self._accept_group_fragment("plan", 3, 0, params)

    def handle_plan_geometry(self, params: dict) -> None:
        self._accept_group_fragment("plan", 3, 1, params)

    def handle_plan_timing(self, params: dict) -> None:
        self._accept_group_fragment("plan", 3, 2, params)

    def handle_observation_core(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 0, params)

    def handle_observation_rate(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 1, params)

    def handle_observation_stationarity(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 2, params)

    def handle_observation_disturbance(self, params: dict) -> None:
        self._accept_group_fragment("observation", 4, 3, params)

    def handle_rung_band(self, params: dict) -> None:
        self._accept_group_fragment("rung", 2, 0, params)

    def handle_rung_quality(self, params: dict) -> None:
        self._accept_group_fragment("rung", 2, 1, params)

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
        fragment = int(params.get("fragment", -1))
        if fragment != expected_fragment:
            raise VelocitySweepProtocolError(
                "unexpected %s fragment %d (expected %d)"
                % (kind, fragment, expected_fragment)
            )
        if self._group_kind is None:
            if fragment != 0:
                raise VelocitySweepProtocolError("fragment group did not start at zero")
            if self.plan is None and kind != "plan":
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
        elif kind == "rung":
            self._finish_rung(parts)
            self._next_evidence_sequence += 1
        elif kind == "terminal":
            self._finish_terminal(parts)
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
                if key in ("fragment", "oid"):
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
        if key[1] not in range(4):
            raise VelocitySweepProtocolError("invalid observation slot")
        self.observations[key] = observation
        self._hash_observation(observation)

    def _finish_rung(self, parts: list[dict]) -> None:
        rung = self._merge(parts)
        rung_index = int(rung["rung_index"])
        if rung_index in self.rungs:
            raise VelocitySweepProtocolError("duplicate rung")
        observations = [self.observations.get((rung_index, slot)) for slot in range(4)]
        if any(observation is None for observation in observations):
            raise VelocitySweepProtocolError("rung arrived before four observations")
        for observation in observations:
            if int(observation["velocity_p"]) != int(rung["velocity_p"]):
                raise VelocitySweepProtocolError("rung gain disagrees with observation")
        for slots, prefix in (((0, 2), "forward"), ((1, 3), "reverse")):
            low = max(
                int(observations[index]["disturbance_low_q16"]) for index in slots
            )
            high = min(
                int(observations[index]["disturbance_high_q16"]) for index in slots
            )
            if low != int(rung[prefix + "_low_q16"]) or high != int(
                rung[prefix + "_high_q16"]
            ):
                raise VelocitySweepProtocolError(
                    "firmware rung verdict disagrees with observation intervals"
                )
        self.rungs[rung_index] = rung
        self._hash_rung(rung)

    def _finish_terminal(self, parts: list[dict]) -> None:
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
        if expected_observations != len(self.observations) or expected_rungs != len(
            self.rungs
        ):
            raise VelocitySweepProtocolError("velocity sweep evidence is incomplete")
        reported_digest = int(integrity["digest_low"]) | (
            int(integrity["digest_high"]) << 32
        )
        if reported_digest != self._digest:
            raise VelocitySweepProtocolError("velocity sweep digest mismatch")
        outcome_code = int(integrity["outcome"])
        if outcome_code not in OUTCOME_NAMES:
            raise VelocitySweepProtocolError("unknown velocity sweep outcome")
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
        self.outcome = OUTCOME_NAMES[outcome_code]
        self.sufficient_direction_mask = mask
        if self.outcome != "inconclusive":
            self.done = True

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
            ("I", plan["used_velocity_mrev_s"]),
            ("I", plan["effective_ceiling_mrev_s"]),
            ("H", plan["clamp_flags"]),
            ("B", plan["binding_source"]),
            ("i", plan["target_velocity_register"]),
            ("H", plan["p_start"]),
            ("H", plan["p_top"]),
            ("B", plan["rung_count"]),
            ("H", plan["observations_per_direction"]),
            ("I", plan["moving_stroke_us"]),
            ("I", plan["zero_settle_us"]),
            ("I", plan["nominal_workflow_ms"]),
            ("I", plan["maximum_workflow_ms"]),
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
            ("i", value["target_velocity_register"]),
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
        fields = (
            ("B", 3),
            ("I", value["run_sequence"]),
            ("H", value["evidence_sequence"]),
            ("B", value["rung_index"]),
            ("H", value["velocity_p"]),
            ("i", value["forward_low_q16"]),
            ("i", value["forward_high_q16"]),
            ("i", value["reverse_low_q16"]),
            ("i", value["reverse_high_q16"]),
            ("H", value["forward_p_low"]),
            ("H", value["forward_p_high"]),
            ("H", value["reverse_p_low"]),
            ("H", value["reverse_p_high"]),
            ("B", value["forward_class"]),
            ("B", value["reverse_class"]),
            ("B", value["forward_closure"]),
            ("B", value["reverse_closure"]),
            ("B", value["flags"]),
            ("B", value["forward_eligible_rungs"]),
            ("B", value["reverse_eligible_rungs"]),
            ("H", value["forward_eligible_observations"]),
            ("H", value["reverse_eligible_observations"]),
        )
        for fmt, item in fields:
            self._hash(fmt, item)
