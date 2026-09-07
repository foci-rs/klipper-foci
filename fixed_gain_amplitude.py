"""Strict relay for firmware-authored fixed-I fixed-gain amplitude validation runs."""

from __future__ import annotations

import itertools
import struct

# Firmware also defines mirrored amplitude actions (wire 3 and 4). They are
# removed and reserved. A mirrored amplitude run could produce a better
# shared floor and would then function as a favourable re-roll of a spent
# retention lifecycle, so firmware never decodes them via
# `AutotuneAction::from_u8`, and the host cannot even name them since
# they're absent from the generated `ACTION_CODES`. Stage C carries the
# same slot-order confound and is not lifecycle-limited, so
# breakaway_seeded is the production and measurement path.
from ._vocabulary_generated import (
    ACTION_CODES,
    SHAPE_FIXED_GAIN_AMPLITUDE_ASCENDING,
    SHAPE_FIXED_GAIN_AMPLITUDE_DESCENDING,
    WORKFLOW_SHAPE_TO_AMPLITUDE_ORDER,
)

FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3
AMPLITUDE_SCHEMA_REVISION = 7
AMPLITUDE_SCHEMA_REVISIONS = (1, 2, 3, 4, 5, 6, AMPLITUDE_SCHEMA_REVISION)
PLAN_REPLY_FRAGMENTS = 2
AMPLITUDE_COUNT = 5
AMPLITUDE_EXPECTED_OBSERVATIONS = 40
AMPLITUDE_MASK = (1 << AMPLITUDE_COUNT) - 1
AMPLITUDE_ORDER_ASCENDING = 1
AMPLITUDE_ORDER_DESCENDING = 2
SLOT_ORDER_FORWARD_FIRST = 0
SLOT_ORDER_REVERSE_FIRST = 1

OUTCOME_NAMES = {
    0: "complete",
    1: "inconclusive",
    2: "fault",
    3: "failed",
}
CAUSE_NAMES = {
    0: "none",
    1: "insufficient_shared_floor",
    2: "recovery_unavailable",
    3: "missing_acceptance_point",
    4: "acceptance_point_identity_mismatch",
    5: "amplitude_order_mismatch",
    6: "evidence_capacity",
    7: "evidence_integrity",
    53: "velocity_rest_not_confirmed",
}

_PLAN_V1 = struct.Struct("<HIBQQHH5hHHBII")
_PLAN_V2 = struct.Struct("<HIBQQHH5hHHBIIQQ")
_TERMINAL = struct.Struct("<HIHBBQQ8sHBH")


class FixedGainAmplitudeProtocolError(Exception):
    """Raised when a compact amplitude relay violates its wire contract."""


def parse_autotune_action(value: str | None) -> int:
    """Map the sole host-authored selector to its firmware wire value."""
    name = "breakaway_seeded" if value is None else str(value).lower()
    try:
        return ACTION_CODES[name]
    except KeyError as err:
        raise FixedGainAmplitudeProtocolError(
            f"unknown ACTION '{name}' (expected: {', '.join(sorted(ACTION_CODES))})"
        ) from err


def _fnv1a(data: bytes) -> int:
    digest = FNV1A64_OFFSET
    for byte in data:
        digest ^= byte
        digest = (digest * FNV1A64_PRIME) & 0xFFFF_FFFF_FFFF_FFFF
    return digest


def _raw_payload(params: dict, kind: str) -> bytes:
    try:
        return bytes(params["payload"])
    except (KeyError, TypeError, ValueError) as err:
        raise FixedGainAmplitudeProtocolError(f"{kind} payload is missing") from err


def _payload(params: dict, size: int, kind: str) -> bytes:
    payload = _raw_payload(params, kind)
    if len(payload) != size:
        raise FixedGainAmplitudeProtocolError(
            f"{kind} payload has {len(payload)} bytes, expected {int(size)}"
        )
    return payload


class FixedGainAmplitudeAssembler:
    """Validate and relay one firmware-authored amplitude without re-deciding it."""

    def __init__(self) -> None:
        self.workflow_plan: dict | None = None
        self.plan: dict | None = None
        self._plan_fragments: list[bytes] = []
        self.terminal: dict | None = None
        self.outcome: str | None = None
        self.done = False

    @property
    def maximum_duration_s(self) -> float | None:
        """Return the disclosed fixed amplitude timeout."""
        if self.workflow_plan is None:
            return None
        return self.workflow_plan["maximum_workflow_ms"] / 1000.0

    @staticmethod
    def workflow_digest_halves(params: dict) -> tuple[int, int]:
        """Recompute the command envelope digest for transport integrity."""
        encoded = struct.pack(
            "<IBII",
            int(params["run_sequence"]),
            int(params["shape"]),
            int(params["nominal_workflow_ms"]),
            int(params["maximum_workflow_ms"]),
        )
        digest = _fnv1a(encoded)
        return digest & 0xFFFF_FFFF, digest >> 32

    def handle_workflow_plan(self, params: dict) -> None:
        if self.workflow_plan is not None:
            raise FixedGainAmplitudeProtocolError("duplicate workflow plan")
        shape = int(params.get("shape", -1))
        if shape not in (
            SHAPE_FIXED_GAIN_AMPLITUDE_ASCENDING,
            SHAPE_FIXED_GAIN_AMPLITUDE_DESCENDING,
        ):
            raise FixedGainAmplitudeProtocolError("invalid amplitude workflow shape")
        duration = (
            int(params["nominal_workflow_ms"]),
            int(params["maximum_workflow_ms"]),
        )
        expected = self.workflow_digest_halves(params)
        reported = (int(params["digest_low"]), int(params["digest_high"]))
        if reported != expected:
            raise FixedGainAmplitudeProtocolError("workflow digest mismatch")
        self.workflow_plan = {
            "run_sequence": int(params["run_sequence"]),
            "shape": shape,
            "nominal_workflow_ms": duration[0],
            "maximum_workflow_ms": duration[1],
            "digest": reported[0] | (reported[1] << 32),
        }

    def _collect_plan_payload(self, params: dict) -> bytes | None:
        """Reassemble the fragmented plan reply, or pass a whole payload through.

        The 66-byte plan exceeds the ordinary reply budget, so firmware ships it
        as ``PLAN_REPLY_FRAGMENTS`` equal fragments. Retained single-message
        captures predate fragmentation and carry no ``fragment`` field.
        """
        payload = _raw_payload(params, "amplitude plan")
        if "fragment" not in params:
            self._plan_fragments = []
            return payload
        fragment = int(params["fragment"])
        if fragment != len(self._plan_fragments):
            self._plan_fragments = []
            raise FixedGainAmplitudeProtocolError("reordered amplitude plan fragment")
        self._plan_fragments.append(payload)
        if len(self._plan_fragments) < PLAN_REPLY_FRAGMENTS:
            return None
        assembled = b"".join(self._plan_fragments)
        self._plan_fragments = []
        return assembled

    def handle_plan(self, params: dict) -> None:
        if self.plan is not None:
            raise FixedGainAmplitudeProtocolError("duplicate amplitude plan")
        if self.workflow_plan is None:
            raise FixedGainAmplitudeProtocolError("amplitude plan arrived before workflow")
        payload = self._collect_plan_payload(params)
        if payload is None:
            return
        if len(payload) < 2:
            raise FixedGainAmplitudeProtocolError("amplitude plan payload is truncated")
        schema = struct.unpack_from("<H", payload)[0]
        plan_struct = {
            1: _PLAN_V1,
            2: _PLAN_V2,
            3: _PLAN_V2,
            4: _PLAN_V2,
            5: _PLAN_V2,
            6: _PLAN_V2,
            7: _PLAN_V2,
        }.get(schema)
        if plan_struct is None:
            raise FixedGainAmplitudeProtocolError("unsupported amplitude schema")
        if len(payload) != plan_struct.size:
            raise FixedGainAmplitudeProtocolError(
                f"amplitude plan payload has {len(payload)} bytes, expected {int(plan_struct.size)}"
            )
        unpacked = plan_struct.unpack(payload)
        (
            _schema,
            run_sequence,
            order,
            plan_digest,
            acceptance_digest,
            selected_p,
            selected_i,
            *tail,
        ) = unpacked
        targets = tuple(tail[:AMPLITUDE_COUNT])
        family_size, observations, amplitude_count, nominal_ms, maximum_ms = tail[
            AMPLITUDE_COUNT : AMPLITUDE_COUNT + 5
        ]
        recovery_lower_rate_q = None if schema == 1 else tuple(tail[AMPLITUDE_COUNT + 5 :])
        # From schema 5 the amplitude order occupies the low nibble and the slot
        # order the high one. Forward-first encodes as zero, so earlier schemas
        # decode unchanged.
        amplitude_order = order & 0x0F
        slot_order = order >> 4
        if amplitude_order not in (AMPLITUDE_ORDER_ASCENDING, AMPLITUDE_ORDER_DESCENDING):
            raise FixedGainAmplitudeProtocolError("invalid amplitude order")
        if slot_order not in (SLOT_ORDER_FORWARD_FIRST, SLOT_ORDER_REVERSE_FIRST):
            raise FixedGainAmplitudeProtocolError("invalid amplitude slot order")
        order = amplitude_order
        expected_order = WORKFLOW_SHAPE_TO_AMPLITUDE_ORDER[int(self.workflow_plan["shape"])]
        if run_sequence != self.workflow_plan["run_sequence"]:
            raise FixedGainAmplitudeProtocolError("amplitude plan run sequence changed")
        if order != expected_order:
            raise FixedGainAmplitudeProtocolError("amplitude order disagrees with workflow")
        ordered = (
            all(left < right for left, right in itertools.pairwise(targets))
            if order == AMPLITUDE_ORDER_ASCENDING
            else all(left > right for left, right in itertools.pairwise(targets))
        )
        if not ordered or any(target <= 0 for target in targets):
            raise FixedGainAmplitudeProtocolError("invalid amplitude target order")
        if plan_digest == 0 or acceptance_digest == 0 or selected_p == 0 or selected_i == 0:
            raise FixedGainAmplitudeProtocolError("amplitude authority is incomplete")
        if schema >= 2 and (
            recovery_lower_rate_q is None or any(value == 0 for value in recovery_lower_rate_q)
        ):
            raise FixedGainAmplitudeProtocolError("amplitude recovery authority is incomplete")
        self.plan = {
            "schema_revision": schema,
            "run_sequence": run_sequence,
            "order": order,
            "slot_order": slot_order,
            "plan_digest": plan_digest,
            "acceptance_plan_digest": acceptance_digest,
            "selected_p": selected_p,
            "selected_i": selected_i,
            "targets_rpm": targets,
            "family_size": family_size,
            "expected_observations": observations,
            "amplitude_count": amplitude_count,
            "nominal_workflow_ms": nominal_ms,
            "maximum_workflow_ms": maximum_ms,
            "recovery_lower_rate_q": recovery_lower_rate_q,
        }

    def handle_terminal(self, params: dict) -> None:
        if self.terminal is not None:
            raise FixedGainAmplitudeProtocolError("duplicate terminal")
        unpacked = _TERMINAL.unpack(_payload(params, _TERMINAL.size, "amplitude terminal"))
        (
            schema,
            run_sequence,
            evidence_sequence,
            outcome,
            cause,
            plan_digest,
            digest,
            packed_masks,
            emitted_observations,
            emitted_amplitudes,
            qualifier_bits,
        ) = unpacked
        if schema not in AMPLITUDE_SCHEMA_REVISIONS:
            raise FixedGainAmplitudeProtocolError("unsupported amplitude schema")
        if self.plan is not None and schema != self.plan["schema_revision"]:
            raise FixedGainAmplitudeProtocolError("amplitude terminal schema disagrees with plan")
        if outcome not in OUTCOME_NAMES or cause not in CAUSE_NAMES:
            raise FixedGainAmplitudeProtocolError("invalid amplitude terminal taxonomy")
        expected_causes = {
            0: {0},
            1: {1, 2, 53},
            2: {6, 7},
            3: {3, 4, 5, 7},
        }
        if cause not in expected_causes[outcome]:
            raise FixedGainAmplitudeProtocolError("amplitude outcome and cause disagree")
        masks = tuple(packed_masks)
        if any(mask & ~AMPLITUDE_MASK for mask in masks):
            raise FixedGainAmplitudeProtocolError("amplitude mask exceeds five amplitudes")
        attempted = masks[0:2]
        eligible = masks[2:4]
        current = masks[4:6]
        unattempted = masks[6:8]
        for direction in range(2):
            if eligible[direction] & ~attempted[direction]:
                raise FixedGainAmplitudeProtocolError("eligible mask was not attempted")
            if current[direction] & ~attempted[direction]:
                raise FixedGainAmplitudeProtocolError("current-terminus mask was not attempted")
            if attempted[direction] & unattempted[direction]:
                raise FixedGainAmplitudeProtocolError("attempted and unattempted masks overlap")
            if outcome != 3 and attempted[direction] | unattempted[direction] != AMPLITUDE_MASK:
                raise FixedGainAmplitudeProtocolError(
                    "attempted and unattempted masks do not cover the plan"
                )
        if emitted_observations > AMPLITUDE_EXPECTED_OBSERVATIONS:
            raise FixedGainAmplitudeProtocolError("too many amplitude observations")
        if emitted_amplitudes > AMPLITUDE_COUNT:
            raise FixedGainAmplitudeProtocolError("too many amplitudes")

        if outcome == 3:
            if self.workflow_plan is not None or self.plan is not None:
                raise FixedGainAmplitudeProtocolError(
                    "pre-motion failure followed amplitude disclosure"
                )
            if plan_digest != 0 or digest != 0:
                raise FixedGainAmplitudeProtocolError("pre-motion failure carried evidence digests")
            if any(masks) or emitted_observations or emitted_amplitudes:
                raise FixedGainAmplitudeProtocolError(
                    "pre-motion failure carried amplitude evidence"
                )
            if evidence_sequence != 0:
                raise FixedGainAmplitudeProtocolError(
                    "pre-motion failure carried an evidence sequence"
                )
        else:
            if self.workflow_plan is None or self.plan is None:
                raise FixedGainAmplitudeProtocolError("amplitude terminal arrived before plan")
            if run_sequence != self.plan["run_sequence"]:
                raise FixedGainAmplitudeProtocolError("amplitude terminal run sequence changed")
            if plan_digest != self.plan["plan_digest"]:
                raise FixedGainAmplitudeProtocolError("amplitude plan digest changed")
            if outcome == 0 and any(mask.bit_count() < 3 for mask in eligible):
                raise FixedGainAmplitudeProtocolError("complete amplitude lacks directional floor")
            if evidence_sequence == 0:
                raise FixedGainAmplitudeProtocolError(
                    "resolved amplitude terminal has no evidence sequence"
                )

        outcome_name = (
            "InconclusiveRest" if outcome == 1 and cause == 53 else OUTCOME_NAMES[outcome]
        )
        self.terminal = {
            "schema_revision": schema,
            "run_sequence": run_sequence,
            "evidence_sequence": evidence_sequence,
            "outcome": outcome,
            "outcome_name": outcome_name,
            "outcome_namespace": "fixed_gain_amplitude",
            "cause": cause,
            "cause_name": CAUSE_NAMES[cause],
            "plan_digest": plan_digest,
            "digest": digest,
            "attempted_masks": attempted,
            "eligible_masks": eligible,
            "current_terminus_masks": current,
            "unattempted_masks": unattempted,
            "emitted_observations": emitted_observations,
            "emitted_amplitudes": emitted_amplitudes,
            "qualifier_bits": qualifier_bits,
        }
        self.outcome = OUTCOME_NAMES[outcome]
        self.done = True
