"""Strict relay for the reversal-standstill robustness terminal and evidence replies.

The terminal wire layout is frozen at 39 bytes (schema revision 2) and must
match firmware's `encode_robustness_terminal_reply` in
`foci-firmware/src/commissioning/outer/velocity/robustness_reporting.rs`
byte-for-byte: a 15-byte header, then two 12-byte per-direction summary
blocks.

The per-cycle evidence reply is a separate, per-direction 40-byte message
(`encode_robustness_cycle_evidence` in the same firmware module) that
carries up to `ROBUSTNESS_CYCLES_PER_DIRECTION` individual cycle samples.
Unfilled slots are the sentinel 0xFFFF on all three per-cycle fields and are
elided from the parsed `cycles` list rather than surfaced as zeros.
"""

from __future__ import annotations

import struct

ROBUSTNESS_SCHEMA_REVISION = 2
ROBUSTNESS_TERMINAL_REPLY_BYTES = 39
ROBUSTNESS_CYCLE_EVIDENCE_REPLY_BYTES = 40
ROBUSTNESS_CYCLES_PER_DIRECTION = 5

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
    8: "internal_fault",
    9: "rest_not_confirmed",
    10: "tail_repeated",
}

_HEADER = "<BIBBHHi"
_DIRECTION = "HHHHBBBB"
_TERMINAL = struct.Struct(_HEADER + _DIRECTION * 2)
_DIRECTION_FIELD_COUNT = 8

_CYCLE_EVIDENCE_HEADER = "<BBii"
_CYCLE_FIELDS_PER_SLOT = 3
_CYCLE_EVIDENCE = struct.Struct(
    _CYCLE_EVIDENCE_HEADER + "H" * (_CYCLE_FIELDS_PER_SLOT * ROBUSTNESS_CYCLES_PER_DIRECTION)
)
_CYCLE_SENTINEL = 0xFFFF


class RobustnessReversalProtocolError(Exception):
    """Raised when a robustness-reversal reply violates its wire contract."""


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


def _cycle_evidence_payload(params: dict) -> bytes:
    try:
        payload = bytes(params["payload"])
    except (KeyError, TypeError, ValueError) as err:
        raise RobustnessReversalProtocolError(
            "robustness cycle evidence payload is missing"
        ) from err
    if len(payload) != _CYCLE_EVIDENCE.size:
        raise RobustnessReversalProtocolError(
            f"robustness cycle evidence payload has {len(payload)} bytes, expected "
            f"{int(_CYCLE_EVIDENCE.size)}"
        )
    return payload


def _direction_from_fields(fields: tuple) -> dict:
    (
        median_reconvergence_ms,
        max_reconvergence_ms,
        median_forward_settle_ms,
        overshoot_peak_counts,
        valid_cycles,
        trip_count,
        retry_count,
        inconclusive,
    ) = fields
    return {
        "median_reconvergence_ms": median_reconvergence_ms,
        "max_reconvergence_ms": max_reconvergence_ms,
        "median_forward_settle_ms": median_forward_settle_ms,
        "overshoot_peak_counts": overshoot_peak_counts,
        "valid_cycles": valid_cycles,
        "trip_count": trip_count,
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


def handle_cycle_evidence(params: dict) -> dict:
    """Parse one compact robustness-reversal per-cycle evidence reply.

    Unfilled cycle slots (all three fields equal to the 0xFFFF sentinel) are
    elided from the returned `cycles` list rather than surfaced as zeros.
    """
    unpacked = _CYCLE_EVIDENCE.unpack(_cycle_evidence_payload(params))
    (
        direction,
        schema,
        residual_median_q,
        iae_median_qs,
        *cycle_fields,
    ) = unpacked
    if schema != ROBUSTNESS_SCHEMA_REVISION:
        raise RobustnessReversalProtocolError("unsupported robustness cycle evidence schema")
    cycles = []
    for index in range(ROBUSTNESS_CYCLES_PER_DIRECTION):
        reconvergence_ms, overshoot_counts, forward_settle_ms = cycle_fields[
            index * _CYCLE_FIELDS_PER_SLOT : (index + 1) * _CYCLE_FIELDS_PER_SLOT
        ]
        if (
            reconvergence_ms == _CYCLE_SENTINEL
            and overshoot_counts == _CYCLE_SENTINEL
            and forward_settle_ms == _CYCLE_SENTINEL
        ):
            continue
        cycles.append(
            {
                "reconvergence_ms": reconvergence_ms,
                "overshoot_counts": overshoot_counts,
                "forward_settle_ms": forward_settle_ms,
            }
        )
    return {
        "direction": direction,
        "residual_median_q": residual_median_q,
        "iae_median_qs": iae_median_qs,
        "cycles": cycles,
    }
