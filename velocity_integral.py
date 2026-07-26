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

SCHEMA_FIVE_POSITIVE_I = (1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
PLAN_RECOVERY_QUANTIZATION_EXPOSED = 1 << 0
PLAN_PROBE_CONSTRAINED_TEST_POINT = 1 << 1
TERMINAL_RECOVERY_UNAVAILABLE = 1 << 0
TERMINAL_RECOVERED_WITH_CURRENT_HEADROOM = 1 << 1
TERMINAL_RECOVERY_QUANTIZATION_EXPOSED = 1 << 2
TERMINAL_PROBE_CONSTRAINED_TEST_POINT = 1 << 3


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
        if shape not in (0, 1, 2):
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
        if int(params.get("schema_revision", -1)) not in (2, 3, 4, 5, 6, 7):
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
            raise VelocityIntegralProtocolError(
                "integral-response maximum is below nominal"
            )
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
            known_flags = PLAN_RECOVERY_QUANTIZATION_EXPOSED
            if schema_revision >= 7:
                known_flags |= PLAN_PROBE_CONSTRAINED_TEST_POINT
            if flags < 0 or flags & ~known_flags:
                raise VelocityIntegralProtocolError("invalid plan recovery flags")
        self._plan_parts.append(dict(params))

    def handle_recovery_summary(self, params: dict) -> None:
        """Accept one compact recovery summary after its causal rung."""
        self._require_plan()
        if int(params.get("stage", -1)) != 1:
            raise VelocityIntegralProtocolError(
                "Stage-C recovery summary named the wrong stage"
            )
        self._require_run(params)
        rung_index = int(params.get("rung_index", -1))
        if rung_index in self.recoveries:
            raise VelocityIntegralProtocolError("duplicate rung recovery")
        self._require_event_identity(params)
        if self._last_evidence != ("rung", rung_index):
            raise VelocityIntegralProtocolError(
                "recovery did not immediately follow its rung"
            )
        if int(params.get("p_raw", -1)) != int(self.plan["final_p"]):
            raise VelocityIntegralProtocolError("recovery summary changed fixed P")
        if int(params.get("binding_source", -1)) not in range(7):
            raise VelocityIntegralProtocolError("invalid recovery binding source")
        maximum_outcome = 5 if int(self.plan["schema_revision"]) >= 6 else 4
        if int(params.get("outcome", -1)) not in range(maximum_outcome + 1):
            raise VelocityIntegralProtocolError("invalid recovery outcome")
        self.recoveries[rung_index] = _metadata_free(params)
        self._next_evidence_sequence += 1
        self._last_evidence = ("recovery", rung_index)

    def handle_plan_rung(self, params: dict) -> None:
        if self.plan is not None:
            raise VelocityIntegralProtocolError(
                "duplicate plan rung after complete plan"
            )
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
            raise VelocityIntegralProtocolError(
                "reverse rung preceded forward components"
            )
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
        self._require_terminal_identity(params)
        if self._summary is not None:
            raise VelocityIntegralProtocolError("duplicate run summary")
        self._require_fragment(params, 0)
        if int(params.get("opening_available_mask", -1)) & ~0b11:
            raise VelocityIntegralProtocolError("invalid opening availability mask")
        if int(params.get("bookend_available_mask", -1)) & ~0b11:
            raise VelocityIntegralProtocolError("invalid bookend availability mask")
        self._summary = _metadata_free(params)
        for direction, key in enumerate(
            ("forward_eligible_mask", "reverse_eligible_mask")
        ):
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
                raise VelocityIntegralProtocolError(
                    "curve interval is outside eligible mask"
                )
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
            raise VelocityIntegralProtocolError(
                "invalid Stage-B comparison availability"
            )
        self.stage_b_comparison[direction] = _metadata_free(params)

    def handle_reproduction_core(self, params: dict) -> None:
        self._require_summary(params)
        if self.reproduction is not None:
            raise VelocityIntegralProtocolError("duplicate reproduction core")
        self.reproduction = {
            **_metadata_free(params),
            "masks": {},
            "reproduced": [dict(), dict()],
            "divergent": [dict(), dict()],
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
            raise VelocityIntegralProtocolError(
                "schema-5 terminal omitted rest-boundary reference"
            )
        if schema_revision >= 6:
            flags = int(params.get("recovery_flags", -1))
            known_flags = (
                TERMINAL_RECOVERY_UNAVAILABLE
                | TERMINAL_RECOVERED_WITH_CURRENT_HEADROOM
                | TERMINAL_RECOVERY_QUANTIZATION_EXPOSED
            )
            if schema_revision >= 7:
                known_flags |= TERMINAL_PROBE_CONSTRAINED_TEST_POINT
            if flags < 0 or flags & ~known_flags:
                raise VelocityIntegralProtocolError("invalid terminal recovery flags")
        rung = int(params.get("rest_boundary_rung_plus_one", 0))
        slot = int(params.get("rest_boundary_slot_plus_one", 0))
        if (rung == 0) != (slot == 0):
            raise VelocityIntegralProtocolError("partial rest-boundary reference")
        if rung and (
            rung not in range(1, int(self.plan["positive_rung_count"]) + 1)
            or slot not in range(1, 9)
        ):
            raise VelocityIntegralProtocolError("invalid rest-boundary reference")
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
        terminal["run_completed_us"] = _u64(
            timing["completed_low"], timing["completed_high"]
        )
        rung = int(core.get("rest_boundary_rung_plus_one", 0))
        slot = int(core.get("rest_boundary_slot_plus_one", 0))
        terminal["rest_boundary"] = (
            None if rung == 0 else {"positive_rung_index": rung - 1, "slot": slot - 1}
        )
        if self.plan is None:
            terminal["recovery_unavailable"] = 0
            terminal["recovered_with_current_headroom"] = False
            terminal["recovery_quantization_exposed"] = False
            terminal["probe_constrained_test_point"] = True
        elif int(self.plan["schema_revision"]) >= 6:
            flags = int(terminal["recovery_flags"])
            terminal["recovery_unavailable"] = int(
                bool(flags & TERMINAL_RECOVERY_UNAVAILABLE)
            )
            terminal["recovered_with_current_headroom"] = bool(
                flags & TERMINAL_RECOVERED_WITH_CURRENT_HEADROOM
            )
            terminal["recovery_quantization_exposed"] = bool(
                flags & TERMINAL_RECOVERY_QUANTIZATION_EXPOSED
            )
            terminal["probe_constrained_test_point"] = bool(
                flags & TERMINAL_PROBE_CONSTRAINED_TEST_POINT
            )
        self.terminal = terminal
        self.outcome = OUTCOME_NAMES.get(int(core["outcome"]))
        if self.outcome is None:
            raise VelocityIntegralProtocolError("invalid terminal outcome")
        self.validate_complete()
        self.done = True

    def validate_complete(self) -> None:
        """Revalidate every completeness and exact-identity invariant."""
        if self.plan is None:
            self._validate_failed_admission()
            return
        if self.plan is None or self._summary is None or self.terminal is None:
            raise VelocityIntegralProtocolError("terminal report is incomplete")
        if int(self.terminal["plan_digest"]) != int(self.plan["plan_digest"]):
            raise VelocityIntegralProtocolError("terminal plan digest mismatch")
        if int(self.terminal["expected_observations"]) != int(
            self.plan["expected_observations"]
        ):
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
        if self.outcome == "fault" and required_recoveries:
            terminal_rung = max(required_recoveries)
            if terminal_rung not in self.recoveries:
                if self._last_evidence != ("rung", terminal_rung):
                    raise VelocityIntegralProtocolError(
                        "missing terminal recovery did not immediately follow its rung"
                    )
                required_recoveries.remove(terminal_rung)
        if set(self.recoveries) != required_recoveries:
            raise VelocityIntegralProtocolError(
                "recovery records do not match fully acquired rungs"
            )
        for direction, curve in enumerate(self.curves):
            if curve["opening"] is None or self.drift[direction] is None:
                raise VelocityIntegralProtocolError("missing anchor or drift evidence")
            if set(curve["positive"]) != self._mask_bits(curve["eligible_mask"]):
                raise VelocityIntegralProtocolError(
                    "curve does not cover eligible mask"
                )
            bookend_expected = bool(
                int(self._summary["bookend_available_mask"]) & (1 << direction)
            )
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
        if self.outcome == "complete" and self.reproduction is None:
            raise VelocityIntegralProtocolError(
                "complete integral response omitted reproduction evidence"
            )
        if int(self.plan["schema_revision"]) >= 6:
            if bool(self.terminal["recovery_quantization_exposed"]) != bool(
                self.plan["recovery_quantization_exposed"]
            ):
                raise VelocityIntegralProtocolError(
                    "plan and terminal recovery exposure differ"
                )
            recovered = any(
                int(recovery["outcome"]) == 5 for recovery in self.recoveries.values()
            )
            if bool(self.terminal["recovered_with_current_headroom"]) != recovered:
                raise VelocityIntegralProtocolError(
                    "recovered terminal flag lacks causal recovery outcome"
                )
        if int(self.plan["schema_revision"]) >= 7:
            if bool(self.terminal["probe_constrained_test_point"]) != bool(
                self.plan["probe_constrained_test_point"]
            ):
                raise VelocityIntegralProtocolError(
                    "plan and terminal probe constraint differ"
                )

    def _finish_plan(self) -> None:
        core, geometry, timing, travel, recovery = self._plan_parts
        plan = self._merge((core, geometry, timing, travel, recovery))
        plan["plan_digest"] = self._reported_plan_digest(core)
        plan["stage_b_plan_digest"] = _u64(
            core["stage_b_digest_low"], core["stage_b_digest_high"]
        )
        plan["authorities"] = list(self._authorities)
        plan["positive_i"] = [int(rung["i_raw"]) for rung in self._plan_rungs]
        plan["rungs"] = list(self._plan_rungs)
        if int(plan["schema_revision"]) >= 6:
            plan["recovery_quantization_exposed"] = bool(
                int(plan["flags"]) & PLAN_RECOVERY_QUANTIZATION_EXPOSED
            )
        if int(plan["schema_revision"]) >= 7:
            plan["probe_constrained_test_point"] = bool(
                int(plan["flags"]) & PLAN_PROBE_CONSTRAINED_TEST_POINT
            )
        if int(plan["schema_revision"]) >= 5:
            expected = {
                "i_start": 1,
                "family_size": 56,
                "total_rung_count": 14,
                "expected_observations": 112,
                "nominal_workflow_ms": 165_950,
                "maximum_workflow_ms": 182_512,
                "slot_count": 14,
            }
            if tuple(plan["positive_i"]) != SCHEMA_FIVE_POSITIVE_I:
                raise VelocityIntegralProtocolError("invalid schema-5 integral ladder")
            for field, value in expected.items():
                if int(plan[field]) != value:
                    raise VelocityIntegralProtocolError(
                        f"invalid schema-5 integral {field}"
                    )
            if (
                int(self.workflow_plan["shape"]) == 2
                and int(self.workflow_plan["maximum_workflow_ms"])
                != expected["maximum_workflow_ms"]
            ):
                raise VelocityIntegralProtocolError(
                    "direct Stage-C workflow maximum changed"
                )
        self.plan = plan

    def _finish_observation(self) -> None:
        core, rate, quality = self._observation_parts
        observation = self._merge((core, rate, quality))
        key = (int(core["rung_index"]), int(core["slot"]))
        if key in self.observations:
            raise VelocityIntegralProtocolError("duplicate observation")
        if key[1] not in range(8) or int(core["direction"]) != key[1] & 1:
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
            raise VelocityIntegralProtocolError(
                "rung identity changed between directions"
            )
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
            raise VelocityIntegralProtocolError(
                "missing or reordered observation fragment"
            )
        self._require_event_identity(params)
        self._require_fragment(params, fragment)
        self._observation_parts.append(dict(params))

    def _accept_terminal_part(self, params: dict, fragment: int) -> None:
        if len(self._terminal_parts) != fragment:
            raise VelocityIntegralProtocolError(
                "missing or reordered terminal fragment"
            )
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
        if self.workflow_plan is None:
            raise VelocityIntegralProtocolError(
                "terminal preceded commissioning workflow plan"
            )
        if int(self.workflow_plan["shape"]) == 0 or self._plan_parts:
            raise VelocityIntegralProtocolError("terminal preceded exact plan")
        self._require_run(params)
        expected = {
            "evidence_sequence": 0,
            "fragment": 0,
            "outcome": 5,
            "cause": 11,
            "recovery_flags": TERMINAL_PROBE_CONSTRAINED_TEST_POINT,
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
            raise VelocityIntegralProtocolError(
                "failed admission carried motion evidence"
            )
        if int(terminal["plan_digest"]) == 0 or int(terminal["digest"]) != 0:
            raise VelocityIntegralProtocolError(
                "failed admission terminal identity is invalid"
            )

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
            raise VelocityIntegralProtocolError(
                "integral-response plan sequence is not zero"
            )

    def _require_event_identity(self, params: dict) -> None:
        self._require_run(params)
        evidence_sequence = int(params.get("evidence_sequence", -1))
        self._resolve_trace_only_current(evidence_sequence)
        if evidence_sequence != self._next_evidence_sequence:
            raise VelocityIntegralProtocolError(
                "integral-response evidence sequence gap"
            )

    def _resolve_trace_only_current(self, evidence_sequence: int) -> None:
        if not self._trace_only_current_pending:
            return
        if evidence_sequence == self._next_evidence_sequence:
            self._trace_only_current_pending = False
        elif evidence_sequence == self._next_evidence_sequence + 1:
            self._next_evidence_sequence += 1
            self._trace_only_current_pending = False

    def _require_terminal_identity(self, params: dict) -> None:
        self._require_plan()
        self._require_event_identity(params)

    def _require_summary(self, params: dict) -> None:
        if self._summary is None:
            raise VelocityIntegralProtocolError(
                "terminal evidence preceded run summary"
            )
        self._require_terminal_identity(params)

    def _require_reproduction(self, params: dict) -> dict:
        self._require_summary(params)
        if self.reproduction is None:
            raise VelocityIntegralProtocolError("reproduction detail preceded core")
        return self.reproduction

    def _require_run(self, params: dict) -> None:
        if (
            self._run_sequence is None
            or int(params.get("run_sequence", -1)) != self._run_sequence
        ):
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
                    raise VelocityIntegralProtocolError(
                        f"fragment metadata differs for {key}"
                    )
                merged[key] = value
        return merged
