"""Parse tests for the reversal-standstill robustness terminal and evidence replies."""

import struct

import pytest
from klipper_foci.registers import REGISTERS
from klipper_foci.robustness_reversal import (
    ROBUSTNESS_CAUSE_NAMES,
    ROBUSTNESS_CYCLES_PER_DIRECTION,
    ROBUSTNESS_OUTCOME_NAMES,
    ROBUSTNESS_SCHEMA_REVISION,
    RobustnessReversalProtocolError,
    handle_cycle_evidence,
    handle_terminal,
)

from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    make_driver,
)

RUN_SEQUENCE = 0x1122_3344
CYCLE_SENTINEL = 0xFFFF

_DIRECTION_DEFAULTS = {
    "median_reconvergence_ms": 145,
    "max_reconvergence_ms": 210,
    "median_forward_settle_ms": 88,
    "overshoot_peak_counts": 12,
    "valid_cycles": 5,
    "trip_count": 0,
    "retry_count": 1,
    "inconclusive": 0,
}


def _direction_bytes(overrides: dict | None = None) -> bytes:
    fields = {**_DIRECTION_DEFAULTS, **(overrides or {})}
    return struct.pack(
        "<HHHHBBBB",
        fields["median_reconvergence_ms"],
        fields["max_reconvergence_ms"],
        fields["median_forward_settle_ms"],
        fields["overshoot_peak_counts"],
        fields["valid_cycles"],
        fields["trip_count"],
        fields["retry_count"],
        fields["inconclusive"],
    )


def build_terminal_payload(
    *,
    schema_revision=ROBUSTNESS_SCHEMA_REVISION,
    run_sequence=RUN_SEQUENCE,
    outcome=0,
    cause=0,
    selected_p=1_024,
    selected_i=512,
    target_velocity_rpm=-1_500,
    plant_rate_q=60_000,
    iae_max_q_qs=120_000,
    forward=None,
    reverse=None,
    **shared_direction_overrides,
) -> bytes:
    """Build a 51-byte schema-3 robustness-terminal payload for tests.

    `forward`/`reverse` override one direction only; any keyword also present
    in `_DIRECTION_DEFAULTS` (e.g. `valid_cycles`) is applied to both
    directions unless that direction has its own override.
    """
    header = struct.pack(
        "<BIBBHHi",
        schema_revision,
        run_sequence,
        outcome,
        cause,
        selected_p,
        selected_i,
        target_velocity_rpm,
    )
    forward_overrides = {**shared_direction_overrides, **(forward or {})}
    reverse_overrides = {**shared_direction_overrides, **(reverse or {})}
    tail = struct.pack("<qi", plant_rate_q, iae_max_q_qs)
    return header + _direction_bytes(forward_overrides) + _direction_bytes(reverse_overrides) + tail


def build_cycle_evidence_payload(
    *,
    direction=0,
    schema_revision=ROBUSTNESS_SCHEMA_REVISION,
    residual_median_q=125,
    iae_median_qs=45_000,
    cycles=None,
    tail_count=0,
    displaced_tail=None,
) -> bytes:
    """Build a 47-byte schema-2 cycle-evidence payload for tests.

    `cycles` fills slots in order (each a `(reconvergence_ms, overshoot_counts,
    forward_settle_ms)` triple); any of the 5 slots left uncovered pack as the
    0xFFFF sentinel on all three fields, matching firmware's unfilled-slot
    encoding. `displaced_tail` is a single such triple, or `None` for the
    all-0xFFFF no-grace-tail sentinel.
    """
    cycles = list(cycles or [])
    if len(cycles) > ROBUSTNESS_CYCLES_PER_DIRECTION:
        raise ValueError("too many cycles for a single evidence payload")
    slots = []
    for index in range(ROBUSTNESS_CYCLES_PER_DIRECTION):
        if index < len(cycles):
            slots.extend(cycles[index])
        else:
            slots.extend((CYCLE_SENTINEL, CYCLE_SENTINEL, CYCLE_SENTINEL))
    displaced_tail_fields = (
        displaced_tail
        if displaced_tail is not None
        else (CYCLE_SENTINEL, CYCLE_SENTINEL, CYCLE_SENTINEL)
    )
    return struct.pack(
        "<BBii" + "H" * (3 * ROBUSTNESS_CYCLES_PER_DIRECTION) + "B" + "H" * 3,
        direction,
        schema_revision,
        residual_median_q,
        iae_median_qs,
        *slots,
        tail_count,
        *displaced_tail_fields,
    )


def handle_and_return(payload: bytes) -> dict:
    return handle_terminal({"oid": 1, "payload": payload})


def test_wire_layout_is_fifty_one_bytes():
    assert len(build_terminal_payload()) == 51


def test_terminal_parse_decodes_header_and_namespace():
    terminal = handle_and_return(build_terminal_payload())

    assert terminal["outcome_namespace"] == "robustness_reversal"
    assert terminal["outcome"] == 0
    assert terminal["outcome_name"] == "complete"
    assert terminal["run_sequence"] == RUN_SEQUENCE
    assert terminal["selected_p"] == 1_024
    assert terminal["selected_i"] == 512
    assert terminal["target_velocity_rpm"] == -1_500


def test_terminal_parse_reports_cause_name_for_cause_one():
    terminal = handle_and_return(build_terminal_payload(outcome=1, cause=1))

    assert terminal["cause"] == 1
    assert terminal["cause_name"] == "reconvergence_time_exceeded"


def test_terminal_parse_decodes_per_direction_metrics():
    terminal = handle_and_return(
        build_terminal_payload(
            forward={
                "median_reconvergence_ms": 120,
                "max_reconvergence_ms": 180,
                "median_forward_settle_ms": 70,
                "overshoot_peak_counts": 9,
                "valid_cycles": 5,
                "trip_count": 1,
                "retry_count": 2,
                "inconclusive": 0,
            },
            reverse={
                "median_reconvergence_ms": 260,
                "max_reconvergence_ms": 310,
                "median_forward_settle_ms": 95,
                "overshoot_peak_counts": 3,
                "valid_cycles": 4,
                "trip_count": 0,
                "retry_count": 1,
                "inconclusive": 1,
            },
        )
    )

    forward, reverse = terminal["directions"]
    assert forward["median_reconvergence_ms"] == 120
    assert forward["max_reconvergence_ms"] == 180
    assert forward["median_forward_settle_ms"] == 70
    assert forward["overshoot_peak_counts"] == 9
    assert forward["valid_cycles"] == 5
    assert forward["trip_count"] == 1
    assert forward["retry_count"] == 2
    assert forward["inconclusive"] is False

    assert reverse["median_reconvergence_ms"] == 260
    assert reverse["max_reconvergence_ms"] == 310
    assert reverse["median_forward_settle_ms"] == 95
    assert reverse["overshoot_peak_counts"] == 3
    assert reverse["valid_cycles"] == 4
    assert reverse["trip_count"] == 0
    assert reverse["retry_count"] == 1
    assert reverse["inconclusive"] is True


def test_terminal_parse_decodes_plant_rate_and_iae_max():
    terminal = handle_and_return(
        build_terminal_payload(plant_rate_q=4_200_000, iae_max_q_qs=8_400_000)
    )

    assert terminal["plant_rate_q"] == 4_200_000
    assert terminal["iae_max_q_qs"] == 8_400_000


def test_cause_names_cover_firmware_values_zero_through_ten():
    assert set(ROBUSTNESS_CAUSE_NAMES) == set(range(11))
    assert ROBUSTNESS_CAUSE_NAMES[7] == "evidence_integrity"
    assert ROBUSTNESS_CAUSE_NAMES[8] == "internal_fault"
    assert ROBUSTNESS_CAUSE_NAMES[9] == "rest_not_confirmed"
    assert ROBUSTNESS_CAUSE_NAMES[10] == "tail_repeated"


def test_outcome_names_cover_firmware_values_zero_through_three():
    assert set(ROBUSTNESS_OUTCOME_NAMES) == set(range(4))
    assert ROBUSTNESS_OUTCOME_NAMES[3] == "failed"


def test_terminal_rejects_wrong_size_payload():
    with pytest.raises(RobustnessReversalProtocolError, match="expected"):
        handle_terminal({"oid": 1, "payload": build_terminal_payload()[:-1]})


def test_terminal_rejects_missing_payload():
    with pytest.raises(RobustnessReversalProtocolError, match="missing"):
        handle_terminal({"oid": 1})


def test_terminal_rejects_invalid_outcome():
    with pytest.raises(RobustnessReversalProtocolError, match="taxonomy"):
        handle_and_return(build_terminal_payload(outcome=4))


def test_terminal_rejects_invalid_cause():
    with pytest.raises(RobustnessReversalProtocolError, match="taxonomy"):
        handle_and_return(build_terminal_payload(cause=11))


def test_terminal_rejects_unsupported_schema():
    with pytest.raises(RobustnessReversalProtocolError, match="schema"):
        handle_and_return(build_terminal_payload(schema_revision=1))


def test_cycle_evidence_wire_layout_is_forty_seven_bytes():
    assert len(build_cycle_evidence_payload()) == 47


def test_cycle_evidence_round_trip_elides_sentinel_slots():
    evidence = handle_cycle_evidence(
        {
            "oid": 1,
            "payload": build_cycle_evidence_payload(
                direction=1,
                residual_median_q=-4_200,
                iae_median_qs=987_654,
                cycles=[
                    (100, 2, 90),
                    (110, 0, 95),
                    (105, 1, 92),
                ],
            ),
        }
    )

    assert evidence["direction"] == 1
    assert evidence["residual_median_q"] == -4_200
    assert evidence["iae_median_qs"] == 987_654
    assert evidence["cycles"] == [
        {"reconvergence_ms": 100, "overshoot_counts": 2, "forward_settle_ms": 90},
        {"reconvergence_ms": 110, "overshoot_counts": 0, "forward_settle_ms": 95},
        {"reconvergence_ms": 105, "overshoot_counts": 1, "forward_settle_ms": 92},
    ]


def test_cycle_evidence_round_trip_with_no_filled_slots_returns_empty_list():
    evidence = handle_cycle_evidence(
        {"oid": 1, "payload": build_cycle_evidence_payload(direction=0)}
    )

    assert evidence["cycles"] == []


def test_cycle_evidence_round_trip_decodes_tail_count_and_displaced_tail():
    evidence = handle_cycle_evidence(
        {
            "oid": 1,
            "payload": build_cycle_evidence_payload(
                direction=0,
                tail_count=2,
                displaced_tail=(50, 1, 45),
            ),
        }
    )

    assert evidence["tail_count"] == 2
    assert evidence["displaced_tail"] == {
        "reconvergence_ms": 50,
        "overshoot_counts": 1,
        "forward_settle_ms": 45,
    }


def test_cycle_evidence_round_trip_with_no_grace_tail_returns_none():
    evidence = handle_cycle_evidence(
        {"oid": 1, "payload": build_cycle_evidence_payload(direction=0, tail_count=0)}
    )

    assert evidence["tail_count"] == 0
    assert evidence["displaced_tail"] is None


def test_cycle_evidence_rejects_wrong_size_payload():
    with pytest.raises(RobustnessReversalProtocolError, match="expected"):
        handle_cycle_evidence({"oid": 1, "payload": build_cycle_evidence_payload()[:-1]})


def test_cycle_evidence_rejects_missing_payload():
    with pytest.raises(RobustnessReversalProtocolError, match="missing"):
        handle_cycle_evidence({"oid": 1})


def test_cycle_evidence_rejects_unsupported_schema():
    with pytest.raises(RobustnessReversalProtocolError, match="schema"):
        handle_cycle_evidence(
            {"oid": 1, "payload": build_cycle_evidence_payload(schema_revision=1)}
        )


def test_cycle_evidence_rejects_invalid_direction():
    with pytest.raises(RobustnessReversalProtocolError, match="direction"):
        handle_cycle_evidence({"oid": 1, "payload": build_cycle_evidence_payload(direction=2)})


def test_robustness_reply_handlers_are_registered():
    """Guard against a reply handler existing but never reaching the wire.

    `handle_robustness_cycle_evidence` previously existed without a matching
    `serial.register_response(...)` call in `protocol/bindings.py`, so
    firmware's `foci_robustness_cycle_evidence` replies would silently never
    reach it. This asserts both robustness reply names are registered for
    the driver's oid, and that each maps to its expected handler method.
    """
    driver = make_driver()
    registrations = {
        name: callback
        for callback, name, oid in driver.mcu._serial.responses
        if oid == driver.oid and "robustness" in name
    }
    assert set(registrations) == {
        "foci_robustness_reversal_terminal",
        "foci_robustness_cycle_evidence",
    }
    assert registrations["foci_robustness_reversal_terminal"] == (
        driver.autotune.handle_robustness_reversal_terminal
    )
    assert registrations["foci_robustness_cycle_evidence"] == (
        driver.autotune.handle_robustness_cycle_evidence
    )


def test_autotune_router_stores_the_parsed_terminal():
    driver = make_driver()
    payload = build_terminal_payload(outcome=1, cause=1)

    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    terminal = driver.autotune.robustness_reversal_terminal
    assert terminal is not None
    assert terminal["outcome_name"] == "rejected"
    assert terminal["cause_name"] == "reconvergence_time_exceeded"
    assert driver.autotune.robustness_reversal_error is None


def test_autotune_router_rejects_a_duplicate_terminal():
    driver = make_driver()
    payload = build_terminal_payload()

    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})
    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    assert isinstance(driver.autotune.robustness_reversal_error, RobustnessReversalProtocolError)
    assert "duplicate" in str(driver.autotune.robustness_reversal_error)


def test_autotune_router_stores_parsed_cycle_evidence_by_direction():
    driver = make_driver()

    driver.autotune.handle_robustness_cycle_evidence(
        {
            "oid": driver.oid,
            "payload": build_cycle_evidence_payload(direction=0, cycles=[(100, 1, 90)]),
        }
    )
    driver.autotune.handle_robustness_cycle_evidence(
        {
            "oid": driver.oid,
            "payload": build_cycle_evidence_payload(direction=1, cycles=[(200, 0, 180)]),
        }
    )

    evidence = driver.autotune.robustness_cycle_evidence
    assert evidence[0]["cycles"] == [
        {"reconvergence_ms": 100, "overshoot_counts": 1, "forward_settle_ms": 90}
    ]
    assert evidence[1]["cycles"] == [
        {"reconvergence_ms": 200, "overshoot_counts": 0, "forward_settle_ms": 180}
    ]
    assert driver.autotune.robustness_reversal_error is None


def test_autotune_router_reports_cycle_evidence_transport_failure():
    driver = make_driver()
    bad_payload = build_cycle_evidence_payload()[:-1]

    driver.autotune.handle_robustness_cycle_evidence({"oid": driver.oid, "payload": bad_payload})

    assert isinstance(driver.autotune.robustness_reversal_error, RobustnessReversalProtocolError)


def test_formatted_message_reports_direction_medians_and_overshoot():
    driver = make_driver()
    payload = build_terminal_payload(
        outcome=1,
        cause=1,
        forward={
            "median_reconvergence_ms": 150,
            "max_reconvergence_ms": 220,
            "median_forward_settle_ms": 30,
            "overshoot_peak_counts": 14,
            "valid_cycles": 5,
        },
    )
    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    message = driver.autotune._format_robustness_reversal_result()

    assert "robustness reversal: rejected" in message
    assert "cause=1 (reconvergence_time_exceeded)" in message
    assert "dir0: median_reconvergence=150ms" in message
    assert "max_reconvergence=220ms" in message
    assert "median_forward_settle=30ms" in message
    assert "overshoot_peak=14counts" in message
    assert "valid_cycles=5" in message


def test_formatted_message_reports_the_constructed_plant_rate_and_iae_max():
    """`plant_rate_q`/`iae_max_q` are the gate's constructed threshold inputs.

    They are run-level (identical for both reversal directions), so they
    render once on the result line rather than per-direction -- captured for
    a later on-target calibration pass to read back what the gate actually
    used.
    """
    driver = make_driver()
    payload = build_terminal_payload(plant_rate_q=4_200_000, iae_max_q_qs=8_400_000)
    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    message = driver.autotune._format_robustness_reversal_result()

    assert "plant_rate_q=4200000" in message
    assert "iae_max_q_qs=8400000" in message


def test_formatted_message_renders_unmeasured_direction_as_not_measured():
    driver = make_driver()
    payload = build_terminal_payload(
        outcome=3,
        cause=6,
        forward={"valid_cycles": 0, "trip_count": 0, "retry_count": 0, "inconclusive": 0},
    )
    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    message = driver.autotune._format_robustness_reversal_result()

    assert "dir0: not measured" in message
    assert "median_reconvergence=0ms" not in message
    assert "median_forward_settle=0ms" not in message


def ready_driver():
    """Build a driver that passes FOCI_AUTOTUNE's readiness gates.

    Mirrors `ready_driver()` in `test_acceptance_matrix.py`: the robustness
    reversal terminal reaches the same wait/report loop in `autotune()`, so
    exercising it end to end needs the same commissioned/calibrated setup.
    """
    driver = make_driver(
        stepper_name="stepper_x",
        kinematics=MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
        homed_axes="xyz",
    )
    driver.state.is_calibrated = True
    driver.state.runtime_status = "commissioned"
    driver.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
    driver.config.identified_lambda_us = 700
    driver.config.identified_tau_e_us = 730
    driver.config.identified_theta_e_us = 160
    driver.config.identified_ringing_count = 7
    driver.config.identified_bandwidth_hz = 1600
    driver.config.identified_inner_warning_flags = 0
    driver.config.identified_current_gains_source = 1
    driver.config.identified_current_gains_tier = 1
    driver.config.identified_current_retry_budget_exhausted = 0
    driver.config.identified_current_failure_reason = 0
    driver.config.identified_l_source = 1
    driver.config.identified_l_reactance_count_ratio_milli = 8600
    driver.config.identified_l_saliency_status = 1
    driver.config.identified_r_count_slope_milli = 1042

    def dump_registers():
        for addr, value in {
            REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 416,
            REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 416,
        }.items():
            driver.dump.handle_dump_value({"addr": addr, "value": value})
        driver.dump.handle_dump_done({})

    driver.protocol.dump_registers = dump_registers
    return driver


def test_autotune_reports_the_robustness_reversal_terminal():
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def finish_robustness(deadline):
        reactor._time = deadline
        payload = build_terminal_payload(
            outcome=1,
            cause=1,
            forward={
                "median_reconvergence_ms": 150,
                "max_reconvergence_ms": 220,
                "median_forward_settle_ms": 30,
                "overshoot_peak_counts": 3,
                "valid_cycles": 5,
            },
        )
        driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})
        return reactor._time

    reactor.pause = finish_robustness
    gcmd = MockGCmd({"ACTION": "robustness_reversal"})
    driver.autotune.autotune(gcmd)

    assert "robustness reversal: rejected" in gcmd.last_info
    assert "cause=1 (reconvergence_time_exceeded)" in gcmd.last_info
    assert "median_forward_settle=30ms" in gcmd.last_info


def test_robustness_safety_fault_reports_outer_envelope_detail():
    """A cause=6 robustness terminal must surface the outer-envelope detail and
    inhibit motor enable until restart.

    Regression guard for the reporting gap: the robustness gate's most
    important failure mode (safety_fault) previously reached the host with
    only `cause=6` and no evidence of which envelope check tripped. It now also
    blocks in-session enable (chip state is unknown after a safety fault).
    """
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def finish_with_safety_fault(deadline):
        reactor._time = deadline
        driver.autotune.handle_outer_safety_fault(
            {
                "reason": 4,
                "max_travel_mrev": 750,
                "max_velocity_mrev_s": 6000,
                "max_duration_ms": 3000,
                "direction_mask": 3,
                "delta_counts": -125,
                "dt_us": 4000,
                "velocity_counts_per_ms": -31,
                "velocity_cap_counts_per_ms": 24,
                "position_counts": -373,
                "position_window_counts": 3000,
                "elapsed_us": 120000,
                "duration_cap_us": 3000000,
            }
        )
        payload = build_terminal_payload(outcome=3, cause=6, inconclusive=1)
        driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})
        return reactor._time

    reactor.pause = finish_with_safety_fault
    gcmd = MockGCmd({"ACTION": "robustness_reversal"})
    with pytest.raises(CommandError, match="robustness safety fault"):
        driver.autotune.autotune(gcmd)

    message = gcmd.last_info
    assert "robustness reversal: failed" in message
    assert "cause=6 (safety_fault)" in message
    assert "outer safety velocity" in message
    assert "window_delta_counts=-125" in message
    assert "velocity_counts_per_ms=-31" in message
    assert "cap_counts_per_ms=24" in message
    assert "budget=750mrev/6000mrev_s/3000ms dir=0x03" in message
    assert driver.state.inhibited


def test_autotune_raises_on_robustness_reversal_transport_failure():
    """A parse error must surface as a command error, not hang to timeout."""
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def fail_robustness(deadline):
        reactor._time = deadline
        bad_payload = build_terminal_payload()[:-1]
        driver.autotune.handle_robustness_reversal_terminal(
            {"oid": driver.oid, "payload": bad_payload}
        )
        return reactor._time

    reactor.pause = fail_robustness
    gcmd = MockGCmd({"ACTION": "robustness_reversal"})

    with pytest.raises(CommandError, match="robustness reversal transport failure"):
        driver.autotune.autotune(gcmd)
