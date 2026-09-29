"""Strict relay for the reversal-standstill robustness terminal and evidence replies."""

from __future__ import annotations

import struct

ROBUSTNESS_SCHEMA_REVISION = 4
ROBUSTNESS_TERMINAL_REPLY_BYTES = 51
ROBUSTNESS_CYCLE_EVIDENCE_REPLY_BYTES = 51
ROBUSTNESS_CYCLES_PER_DIRECTION = 5

ROBUSTNESS_OUTCOME_COMPLETE = 0
ROBUSTNESS_OUTCOME_INCONCLUSIVE = 2
ROBUSTNESS_OUTCOME_FAILED = 3

ROBUSTNESS_OUTCOME_NAMES = {
    0: "complete",
    1: "rejected",
    2: "inconclusive",
    3: "failed",
}

ROBUSTNESS_CAUSE_IAE_EXCEEDED = 3
ROBUSTNESS_CAUSE_SAFETY_FAULT = 6

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
    11: "origin_not_recovered",
    12: "io_fault",
    13: "safety_arm_failed",
    14: "recovery_plan_invalid",
    15: "invalid_gains",
    16: "deadline_overflow",
    17: "analysis_timeout",
    18: "analysis_poll_failed",
    19: "scoring_failed",
    20: "unexpected_state",
    21: "origin_recovery_fault",
    22: "dispatch_abort",
}

_HEADER = "<BIBBHHi"
_DIRECTION = "HHHHBBBB"
_TERMINAL_TAIL = "qi"
_TERMINAL = struct.Struct(_HEADER + _DIRECTION * 2 + _TERMINAL_TAIL)
_DIRECTION_FIELD_COUNT = 8

_CYCLE_EVIDENCE_HEADER = "<BBiii"
_CYCLE_FIELDS_PER_SLOT = 3
_CYCLE_EVIDENCE = struct.Struct(
    _CYCLE_EVIDENCE_HEADER
    + "H" * (_CYCLE_FIELDS_PER_SLOT * ROBUSTNESS_CYCLES_PER_DIRECTION)
    + "B"
    + "H" * _CYCLE_FIELDS_PER_SLOT
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
        *direction_and_tail_fields,
    ) = unpacked
    if schema != ROBUSTNESS_SCHEMA_REVISION:
        raise RobustnessReversalProtocolError("unsupported robustness reversal schema")
    if outcome not in ROBUSTNESS_OUTCOME_NAMES or cause not in ROBUSTNESS_CAUSE_NAMES:
        raise RobustnessReversalProtocolError("invalid robustness reversal terminal taxonomy")
    direction_span = _DIRECTION_FIELD_COUNT * 2
    direction_fields = direction_and_tail_fields[:direction_span]
    plant_rate_q, iae_max_q_qs = direction_and_tail_fields[direction_span:]
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
        "plant_rate_q": plant_rate_q,
        "iae_max_q_qs": iae_max_q_qs,
    }


def _cycle_slot_or_none(fields: tuple) -> dict | None:
    """Decode one `(reconvergence_ms, overshoot_counts, forward_settle_ms)` slot."""
    reconvergence_ms, overshoot_counts, forward_settle_ms = fields
    if (
        reconvergence_ms == _CYCLE_SENTINEL
        and overshoot_counts == _CYCLE_SENTINEL
        and forward_settle_ms == _CYCLE_SENTINEL
    ):
        return None
    return {
        "reconvergence_ms": reconvergence_ms,
        "overshoot_counts": overshoot_counts,
        "forward_settle_ms": forward_settle_ms,
    }


def handle_cycle_evidence(params: dict) -> dict:
    """Parse one compact robustness-reversal per-cycle evidence reply."""
    unpacked = _CYCLE_EVIDENCE.unpack(_cycle_evidence_payload(params))
    direction, schema, residual_median_q, iae_median_qs, dac_rms_median_q = unpacked[:5]
    if schema != ROBUSTNESS_SCHEMA_REVISION:
        raise RobustnessReversalProtocolError("unsupported robustness cycle evidence schema")
    if direction > 1:
        raise RobustnessReversalProtocolError("invalid robustness cycle evidence direction")
    cycle_span = _CYCLE_FIELDS_PER_SLOT * ROBUSTNESS_CYCLES_PER_DIRECTION
    cycle_fields = unpacked[5 : 5 + cycle_span]
    tail_count = unpacked[5 + cycle_span]
    displaced_tail_fields = unpacked[5 + cycle_span + 1 :]
    cycles = []
    for index in range(ROBUSTNESS_CYCLES_PER_DIRECTION):
        slot = _cycle_slot_or_none(
            cycle_fields[index * _CYCLE_FIELDS_PER_SLOT : (index + 1) * _CYCLE_FIELDS_PER_SLOT]
        )
        if slot is not None:
            cycles.append(slot)
    return {
        "direction": direction,
        "residual_median_q": residual_median_q,
        "iae_median_qs": iae_median_qs,
        "dac_rms_median_q": dac_rms_median_q,
        "cycles": cycles,
        "tail_count": tail_count,
        "displaced_tail": _cycle_slot_or_none(displaced_tail_fields),
    }
