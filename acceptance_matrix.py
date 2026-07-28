"""Strict relay for firmware-authored fixed-I confidence matrices."""

from __future__ import annotations

import struct

FNV1A64_OFFSET = 0xCBF29CE484222325
FNV1A64_PRIME = 0x100000001B3
MATRIX_SCHEMA_REVISION = 3
MATRIX_SCHEMA_REVISIONS = (1, 2, MATRIX_SCHEMA_REVISION)
MATRIX_NOMINAL_WORKFLOW_MS = 63_041
MATRIX_MAXIMUM_WORKFLOW_MS = 66_456
MATRIX_SCHEMA_DURATIONS = {
    1: (60_541, MATRIX_MAXIMUM_WORKFLOW_MS),
    2: (60_541, MATRIX_MAXIMUM_WORKFLOW_MS),
    3: (MATRIX_NOMINAL_WORKFLOW_MS, MATRIX_MAXIMUM_WORKFLOW_MS),
}
MATRIX_AMPLITUDE_COUNT = 5
MATRIX_FAMILY_SIZE = 20
MATRIX_EXPECTED_OBSERVATIONS = 40
MATRIX_MASK = (1 << MATRIX_AMPLITUDE_COUNT) - 1
MATRIX_ORDER_ASCENDING = 1
MATRIX_ORDER_DESCENDING = 2

WORKFLOW_SHAPE_TO_MATRIX_ORDER = {
    4: MATRIX_ORDER_ASCENDING,
    5: MATRIX_ORDER_DESCENDING,
}

ACTION_CODES = {
    "combined": 0,
    "matrix_ascending": 1,
    "matrix_descending": 2,
}
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
    5: "matrix_order_mismatch",
    6: "evidence_capacity",
    7: "evidence_integrity",
}

_PLAN_V1 = struct.Struct("<HIBQQHH5hHHBII")
_PLAN_V2 = struct.Struct("<HIBQQHH5hHHBIIQQ")
_TERMINAL = struct.Struct("<HIBBQQ8sHBH")


class AcceptanceMatrixProtocolError(Exception):
    """Raised when a compact matrix relay violates its wire contract."""


def parse_autotune_action(value: str | None) -> int:
    """Map the sole host-authored selector to its firmware wire value."""
    name = "combined" if value is None else str(value).lower()
    try:
        return ACTION_CODES[name]
    except KeyError as err:
        raise AcceptanceMatrixProtocolError(
            "unknown ACTION '%s' (expected: %s)"
            % (name, ", ".join(sorted(ACTION_CODES)))
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
        raise AcceptanceMatrixProtocolError("%s payload is missing" % kind) from err


def _payload(params: dict, size: int, kind: str) -> bytes:
    payload = _raw_payload(params, kind)
    if len(payload) != size:
        raise AcceptanceMatrixProtocolError(
            "%s payload has %d bytes, expected %d" % (kind, len(payload), size)
        )
    return payload


class AcceptanceMatrixAssembler:
    """Validate and relay one firmware-authored matrix without re-deciding it."""

    def __init__(self) -> None:
        self.workflow_plan: dict | None = None
        self.plan: dict | None = None
        self.terminal: dict | None = None
        self.outcome: str | None = None
        self.done = False

    @property
    def maximum_duration_s(self) -> float | None:
        """Return the disclosed fixed matrix timeout."""
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
            raise AcceptanceMatrixProtocolError("duplicate workflow plan")
        shape = int(params.get("shape", -1))
        if shape not in (4, 5):
            raise AcceptanceMatrixProtocolError("invalid matrix workflow shape")
        duration = (
            int(params["nominal_workflow_ms"]),
            int(params["maximum_workflow_ms"]),
        )
        if duration not in set(MATRIX_SCHEMA_DURATIONS.values()):
            raise AcceptanceMatrixProtocolError("matrix workflow duration changed")
        expected = self.workflow_digest_halves(params)
        reported = (int(params["digest_low"]), int(params["digest_high"]))
        if reported != expected:
            raise AcceptanceMatrixProtocolError("workflow digest mismatch")
        self.workflow_plan = {
            "run_sequence": int(params["run_sequence"]),
            "shape": shape,
            "nominal_workflow_ms": duration[0],
            "maximum_workflow_ms": duration[1],
            "digest": reported[0] | (reported[1] << 32),
        }

    def handle_plan(self, params: dict) -> None:
        if self.plan is not None:
            raise AcceptanceMatrixProtocolError("duplicate matrix plan")
        if self.workflow_plan is None:
            raise AcceptanceMatrixProtocolError("matrix plan arrived before workflow")
        payload = _raw_payload(params, "matrix plan")
        if len(payload) < 2:
            raise AcceptanceMatrixProtocolError("matrix plan payload is truncated")
        schema = struct.unpack_from("<H", payload)[0]
        plan_struct = {1: _PLAN_V1, 2: _PLAN_V2, 3: _PLAN_V2}.get(schema)
        if plan_struct is None:
            raise AcceptanceMatrixProtocolError("unsupported matrix schema")
        if len(payload) != plan_struct.size:
            raise AcceptanceMatrixProtocolError(
                "matrix plan payload has %d bytes, expected %d"
                % (len(payload), plan_struct.size)
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
        targets = tuple(tail[:MATRIX_AMPLITUDE_COUNT])
        family_size, observations, amplitude_count, nominal_ms, maximum_ms = tail[
            MATRIX_AMPLITUDE_COUNT : MATRIX_AMPLITUDE_COUNT + 5
        ]
        recovery_lower_rate_q = (
            None if schema == 1 else tuple(tail[MATRIX_AMPLITUDE_COUNT + 5 :])
        )
        expected_order = WORKFLOW_SHAPE_TO_MATRIX_ORDER[
            int(self.workflow_plan["shape"])
        ]
        if run_sequence != self.workflow_plan["run_sequence"]:
            raise AcceptanceMatrixProtocolError("matrix plan run sequence changed")
        if order != expected_order:
            raise AcceptanceMatrixProtocolError("matrix order disagrees with workflow")
        ordered = (
            all(left < right for left, right in zip(targets, targets[1:]))
            if order == MATRIX_ORDER_ASCENDING
            else all(left > right for left, right in zip(targets, targets[1:]))
        )
        if not ordered or any(target <= 0 for target in targets):
            raise AcceptanceMatrixProtocolError("invalid matrix target order")
        if (
            plan_digest == 0
            or acceptance_digest == 0
            or selected_p == 0
            or selected_i == 0
        ):
            raise AcceptanceMatrixProtocolError("matrix authority is incomplete")
        expected_duration = MATRIX_SCHEMA_DURATIONS[schema]
        if (
            family_size != MATRIX_FAMILY_SIZE
            or observations != MATRIX_EXPECTED_OBSERVATIONS
            or amplitude_count != MATRIX_AMPLITUDE_COUNT
            or (nominal_ms, maximum_ms) != expected_duration
            or (
                int(self.workflow_plan["nominal_workflow_ms"]),
                int(self.workflow_plan["maximum_workflow_ms"]),
            )
            != expected_duration
        ):
            raise AcceptanceMatrixProtocolError("matrix plan geometry changed")
        if schema >= 2 and (
            recovery_lower_rate_q is None
            or any(value == 0 for value in recovery_lower_rate_q)
        ):
            raise AcceptanceMatrixProtocolError(
                "matrix recovery authority is incomplete"
            )
        self.plan = {
            "schema_revision": schema,
            "run_sequence": run_sequence,
            "order": order,
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
            raise AcceptanceMatrixProtocolError("duplicate terminal")
        unpacked = _TERMINAL.unpack(_payload(params, _TERMINAL.size, "matrix terminal"))
        (
            schema,
            run_sequence,
            outcome,
            cause,
            plan_digest,
            digest,
            packed_masks,
            emitted_observations,
            emitted_amplitudes,
            qualifier_bits,
        ) = unpacked
        if schema not in MATRIX_SCHEMA_REVISIONS:
            raise AcceptanceMatrixProtocolError("unsupported matrix schema")
        if self.plan is not None and schema != self.plan["schema_revision"]:
            raise AcceptanceMatrixProtocolError(
                "matrix terminal schema disagrees with plan"
            )
        if outcome not in OUTCOME_NAMES or cause not in CAUSE_NAMES:
            raise AcceptanceMatrixProtocolError("invalid matrix terminal taxonomy")
        expected_causes = {
            0: {0},
            1: {1, 2},
            2: {6, 7},
            3: {3, 4, 5, 7},
        }
        if cause not in expected_causes[outcome]:
            raise AcceptanceMatrixProtocolError("matrix outcome and cause disagree")
        masks = tuple(packed_masks)
        if any(mask & ~MATRIX_MASK for mask in masks):
            raise AcceptanceMatrixProtocolError("matrix mask exceeds five amplitudes")
        attempted = masks[0:2]
        eligible = masks[2:4]
        current = masks[4:6]
        unattempted = masks[6:8]
        for direction in range(2):
            if eligible[direction] & ~attempted[direction]:
                raise AcceptanceMatrixProtocolError("eligible mask was not attempted")
            if current[direction] & ~attempted[direction]:
                raise AcceptanceMatrixProtocolError(
                    "current-terminus mask was not attempted"
                )
            if attempted[direction] & unattempted[direction]:
                raise AcceptanceMatrixProtocolError(
                    "attempted and unattempted masks overlap"
                )
            if (
                outcome != 3
                and attempted[direction] | unattempted[direction] != MATRIX_MASK
            ):
                raise AcceptanceMatrixProtocolError(
                    "attempted and unattempted masks do not cover the plan"
                )
        if emitted_observations > MATRIX_EXPECTED_OBSERVATIONS:
            raise AcceptanceMatrixProtocolError("too many matrix observations")
        if emitted_amplitudes > MATRIX_AMPLITUDE_COUNT:
            raise AcceptanceMatrixProtocolError("too many matrix amplitudes")

        if outcome == 3:
            if self.workflow_plan is not None or self.plan is not None:
                raise AcceptanceMatrixProtocolError(
                    "pre-motion failure followed matrix disclosure"
                )
            if plan_digest != 0 or digest != 0:
                raise AcceptanceMatrixProtocolError(
                    "pre-motion failure carried evidence digests"
                )
            if any(masks) or emitted_observations or emitted_amplitudes:
                raise AcceptanceMatrixProtocolError(
                    "pre-motion failure carried matrix evidence"
                )
        else:
            if self.workflow_plan is None or self.plan is None:
                raise AcceptanceMatrixProtocolError(
                    "matrix terminal arrived before plan"
                )
            if run_sequence != self.plan["run_sequence"]:
                raise AcceptanceMatrixProtocolError(
                    "matrix terminal run sequence changed"
                )
            if plan_digest != self.plan["plan_digest"]:
                raise AcceptanceMatrixProtocolError("matrix plan digest changed")
            if outcome == 0 and any(mask.bit_count() < 3 for mask in eligible):
                raise AcceptanceMatrixProtocolError(
                    "complete matrix lacks directional floor"
                )

        self.terminal = {
            "schema_revision": schema,
            "run_sequence": run_sequence,
            "outcome": outcome,
            "outcome_name": OUTCOME_NAMES[outcome],
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
