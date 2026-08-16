"""Strict relay for the reversal-standstill robustness terminal reply.

The wire layout is frozen at 54 bytes and must match firmware's
`encode_robustness_terminal_reply` in
`foci-firmware/src/commissioning/outer/velocity/robustness_reporting.rs`
byte-for-byte: a 16-byte header, then two 19-byte per-direction blocks.
`reconvergence_ratio_ppm` is deliberately absent from the wire (both of its
inputs are encoded), so the host derives it instead of firmware shipping a
third, redundant field.
"""

from __future__ import annotations

import struct

ROBUSTNESS_SCHEMA_REVISION = 1
ROBUSTNESS_TERMINAL_REPLY_BYTES = 54

ROBUSTNESS_OUTCOME_NAMES = {
    0: "complete",
    1: "rejected",
    2: "inconclusive",
    3: "failed",
}

ROBUSTNESS_CAUSE_NAMES = {
    0: "pass",
    1: "reconvergence_time_exceeded",
    2: "residual_exceeded",
    3: "iae_exceeded",
    4: "reconvergence_inconclusive",
    5: "no_accepted_candidate",
    6: "safety_fault",
    7: "evidence_integrity",
}

_HEADER = "<HIBBHHi"
_DIRECTION = "IiiIBBB"
_TERMINAL = struct.Struct(_HEADER + _DIRECTION * 2)
_DIRECTION_FIELD_COUNT = 7


class RobustnessReversalProtocolError(Exception):
    """Raised when a robustness-reversal terminal reply violates its wire contract."""


def _payload(params: dict) -> bytes:
    try:
        payload = bytes(params["payload"])
    except (KeyError, TypeError, ValueError) as err:
        raise RobustnessReversalProtocolError(
            "robustness reversal terminal payload is missing"
        ) from err
    if len(payload) != _TERMINAL.size:
        raise RobustnessReversalProtocolError(
            f"robustness reversal terminal payload has {len(payload)} bytes, expected "
            f"{int(_TERMINAL.size)}"
        )
    return payload


def _direction_from_fields(fields: tuple) -> dict:
    (
        reconvergence_time_us,
        settled_residual_q,
        recovery_iae_q,
        forward_settle_time_us,
        tripped,
        retry_count,
        inconclusive,
    ) = fields
    reconvergence_ratio_ppm = (
        0
        if forward_settle_time_us == 0
        else reconvergence_time_us * 1_000_000 // forward_settle_time_us
    )
    return {
        "reconvergence_time_us": reconvergence_time_us,
        "settled_residual_q": settled_residual_q,
        "recovery_iae_q": recovery_iae_q,
        "forward_settle_time_us": forward_settle_time_us,
        "reconvergence_ratio_ppm": reconvergence_ratio_ppm,
        "tripped": tripped,
        "retry_count": retry_count,
        "inconclusive": bool(inconclusive),
    }


def handle_terminal(params: dict) -> dict:
    """Parse one compact robustness-reversal terminal reply."""
    unpacked = _TERMINAL.unpack(_payload(params))
    (
        schema,
        run_sequence,
        outcome,
        cause,
        selected_p,
        selected_i,
        target_velocity_rpm,
        *direction_fields,
    ) = unpacked
    if schema != ROBUSTNESS_SCHEMA_REVISION:
        raise RobustnessReversalProtocolError("unsupported robustness reversal schema")
    if outcome not in ROBUSTNESS_OUTCOME_NAMES or cause not in ROBUSTNESS_CAUSE_NAMES:
        raise RobustnessReversalProtocolError("invalid robustness reversal terminal taxonomy")
    directions = [
        _direction_from_fields(
            tuple(
                direction_fields[
                    index * _DIRECTION_FIELD_COUNT : (index + 1) * _DIRECTION_FIELD_COUNT
                ]
            )
        )
        for index in range(2)
    ]
    return {
        "schema_revision": schema,
        "run_sequence": run_sequence,
        "outcome": outcome,
        "outcome_name": ROBUSTNESS_OUTCOME_NAMES[outcome],
        "outcome_namespace": "robustness_reversal",
        "cause": cause,
        "cause_name": ROBUSTNESS_CAUSE_NAMES[cause],
        "selected_p": selected_p,
        "selected_i": selected_i,
        "target_velocity_rpm": target_velocity_rpm,
        "directions": directions,
    }
