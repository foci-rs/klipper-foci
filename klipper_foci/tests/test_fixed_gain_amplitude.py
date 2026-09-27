"""Strict relay tests for fixed-I fixed-gain amplitude validation runs."""

import logging
import struct

import pytest

from klipper_foci._vocabulary_generated import ACTION_CODES
from klipper_foci.fixed_gain_amplitude import (
    AMPLITUDE_ORDER_ASCENDING,
    FixedGainAmplitudeAssembler,
    FixedGainAmplitudeProtocolError,
    parse_autotune_action,
)
from klipper_foci.registers import REGISTERS
from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    make_driver,
)

PLAN_DIGEST = 0x0123_4567_89AB_CDEF
ACCEPTANCE_DIGEST = 0xFEDC_BA98_7654_3210
RUN_SEQUENCE = 17
TARGETS = (16, 33, 66, 132, 263)
RECOVERY_BOUNDS = (13_217_792, 12_827_648)


def ready_driver():
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


def workflow(assembler, shape=1):
    params = {
        "oid": 1,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": 60_541,
        "maximum_workflow_ms": 66_456,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(params)
    assembler.handle_workflow_plan(params)


def plan_payload(
    order=1,
    targets=TARGETS,
    schema=6,
    recovery_bounds=RECOVERY_BOUNDS,
    nominal_ms=60_541,
    maximum_ms=66_456,
):
    prefix = struct.pack(
        "<HIBQQHH5hHHBII",
        schema,
        RUN_SEQUENCE,
        order,
        PLAN_DIGEST,
        ACCEPTANCE_DIGEST,
        1024,
        1024,
        *targets,
        20,
        40,
        5,
        nominal_ms,
        maximum_ms,
    )
    if schema == 1:
        return prefix
    return prefix + struct.pack("<QQ", *recovery_bounds)


def terminal_payload(
    *,
    outcome=0,
    cause=0,
    plan_digest=PLAN_DIGEST,
    digest=0x1111_2222_3333_4444,
    attempted=(0x1F, 0x1F),
    eligible=(0x1F, 0x1F),
    current=(0, 0),
    unattempted=(0, 0),
    emitted_observations=40,
    emitted_amplitudes=5,
    schema=6,
    evidence_sequence=41,
):
    return struct.pack(
        "<HIHBBQQ8sHBH",
        schema,
        RUN_SEQUENCE,
        evidence_sequence,
        outcome,
        cause,
        plan_digest,
        digest,
        bytes((*attempted, *eligible, *current, *unattempted)),
        emitted_observations,
        emitted_amplitudes,
        0x12,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, 7),
        ("amplitude_up", 1),
        ("amplitude_down", 2),
        ("integral_resume", 8),
        ("robustness_reversal", 9),
    ),
)
def test_action_mapping_is_selector_only(value, expected):
    assert parse_autotune_action(value) == expected


def test_unknown_action_is_rejected():
    with pytest.raises(FixedGainAmplitudeProtocolError, match="unknown ACTION"):
        parse_autotune_action("pick_p_1024")


@pytest.mark.parametrize("name", ("combined", "combined_mirrored", "combined_paired"))
def test_removed_combined_actions_are_rejected(name):
    """The combined acquisition path is retired.

    Firmware rejects wire actions 0/5/6 outright; the host mirrors that by
    dropping the names from ACTION_CODES entirely, so they now fail the same
    unknown-ACTION path as any other unrecognized selector.
    """
    with pytest.raises(FixedGainAmplitudeProtocolError, match="unknown ACTION"):
        parse_autotune_action(name)


def test_unknown_action_rejects_before_any_mcu_command():
    driver = ready_driver()
    with pytest.raises(CommandError, match="unknown ACTION"):
        driver.autotune.autotune(MockGCmd({"ACTION": "pick_p_1024"}))
    assert driver.protocol.commands.tune.last_args is None


def test_action_codes_admit_only_live_actions():
    assert set(ACTION_CODES.values()) == {1, 2, 7, 8, 9, 10}
    assert set(ACTION_CODES.values()).isdisjoint({0, 3, 4, 5, 6})


@pytest.mark.parametrize(
    "selector", ("combined", "combined_mirrored", "combined_paired", "pick_p_1024")
)
def test_reserved_selectors_issue_no_mcu_command(selector):
    driver = ready_driver()
    with pytest.raises(CommandError, match="unknown ACTION"):
        driver.autotune.autotune(MockGCmd({"ACTION": selector}))
    assert driver.protocol.commands.tune.last_args is None


def test_only_compact_amplitude_replies_are_registered():
    driver = make_driver()
    registrations = {
        name
        for _callback, name, oid in driver.mcu._serial.responses
        if oid == driver.oid and "fixed_gain_amplitude" in name
    }
    assert registrations == {
        "foci_fixed_gain_amplitude_plan",
        "foci_fixed_gain_amplitude_terminal",
    }


@pytest.mark.parametrize(("shape", "order"), ((1, 1), (2, 2)))
def test_exact_plan_and_terminal_close_one_amplitude(shape, order):
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler, shape)
    targets = TARGETS if order == 1 else tuple(reversed(TARGETS))
    assembler.handle_plan({"oid": 1, "payload": plan_payload(order, targets)})
    assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.plan["targets_rpm"] == targets
    assert assembler.plan["recovery_lower_rate_q"] == RECOVERY_BOUNDS
    assert assembler.terminal["eligible_masks"] == (0x1F, 0x1F)


@pytest.mark.parametrize("schema", [1, 2, 5, 7])
def test_amplitude_plan_rejects_schemas_firmware_no_longer_sends(schema):
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)

    with pytest.raises(FixedGainAmplitudeProtocolError, match="unsupported amplitude schema"):
        assembler.handle_plan({"oid": 1, "payload": plan_payload(schema=schema)})


@pytest.mark.parametrize("schema", [2, 7])
def test_amplitude_terminal_rejects_schemas_firmware_no_longer_sends(schema):
    assembler = FixedGainAmplitudeAssembler()

    with pytest.raises(FixedGainAmplitudeProtocolError, match="unsupported amplitude schema"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload(schema=schema)})


def test_schema_two_requires_exact_nonzero_recovery_bounds_and_matching_terminal():
    invalid_payloads = [
        bytearray(plan_payload(schema=1)),
        plan_payload(recovery_bounds=(0, RECOVERY_BOUNDS[1])),
        plan_payload(recovery_bounds=(RECOVERY_BOUNDS[0], 0)),
    ]
    invalid_payloads[0][0:2] = (2).to_bytes(2, "little")

    for payload in invalid_payloads:
        assembler = FixedGainAmplitudeAssembler()
        workflow(assembler)
        with pytest.raises(FixedGainAmplitudeProtocolError):
            assembler.handle_plan({"oid": 1, "payload": bytes(payload)})

    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload()})
    with pytest.raises(FixedGainAmplitudeProtocolError, match="schema"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload(schema=1)})


def test_rest_terminal_is_named_inconclusive_rest():
    assembler = FixedGainAmplitudeAssembler()
    params = {
        "oid": 1,
        "run_sequence": RUN_SEQUENCE,
        "shape": 1,
        "nominal_workflow_ms": 63_041,
        "maximum_workflow_ms": 66_456,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(params)
    assembler.handle_workflow_plan(params)
    assembler.handle_plan({"oid": 1, "payload": plan_payload(nominal_ms=63_041)})
    assembler.handle_terminal(
        {
            "oid": 1,
            "payload": terminal_payload(
                outcome=1,
                cause=53,
                emitted_observations=39,
                emitted_amplitudes=5,
            ),
        }
    )

    assert assembler.outcome == "inconclusive"
    assert assembler.terminal["outcome_name"] == "InconclusiveRest"
    assert assembler.terminal["outcome_namespace"] == "fixed_gain_amplitude"
    assert assembler.terminal["cause_name"] == "velocity_rest_not_confirmed"


@pytest.mark.parametrize(
    ("shape", "nominal", "maximum"),
    (
        (0, 60_541, 66_456),
        (3, 60_541, 66_456),
        (4, 60_541, 66_456),
    ),
)
def test_amplitude_workflow_rejects_non_amplitude_shapes(shape, nominal, maximum):
    """Shape is the compatibility gate. Durations are firmware-authored and
    consumed, so a schedule change must not require a host edit."""
    assembler = FixedGainAmplitudeAssembler()
    params = {
        "oid": 1,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": nominal,
        "maximum_workflow_ms": maximum,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(params)
    with pytest.raises(FixedGainAmplitudeProtocolError):
        assembler.handle_workflow_plan(params)


def test_plan_rejects_wrong_order_target_geometry_and_counts():
    # family_size and the workflow durations are firmware-authored and no longer
    # re-derived here; what remains is agreement between the plan and the
    # workflow the host already bound.
    cases = (
        plan_payload(order=2),
        plan_payload(targets=(16, 33, 66, 132, 132)),
    )
    for payload in cases:
        assembler = FixedGainAmplitudeAssembler()
        workflow(assembler)
        with pytest.raises(FixedGainAmplitudeProtocolError):
            assembler.handle_plan({"oid": 1, "payload": bytes(payload)})


def test_terminal_rejects_duplicates_digest_mismatch_and_invalid_masks():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload()})
    assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})
    with pytest.raises(FixedGainAmplitudeProtocolError, match="duplicate terminal"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})

    for payload in (
        terminal_payload(plan_digest=PLAN_DIGEST + 1),
        terminal_payload(eligible=(0x20, 0)),
        terminal_payload(outcome=3, cause=0),
    ):
        candidate = FixedGainAmplitudeAssembler()
        workflow(candidate)
        candidate.handle_plan({"oid": 1, "payload": plan_payload()})
        with pytest.raises(FixedGainAmplitudeProtocolError):
            candidate.handle_terminal({"oid": 1, "payload": payload})


def test_terminal_requires_complete_plan():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    with pytest.raises(FixedGainAmplitudeProtocolError, match="before plan"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})


@pytest.mark.parametrize("cause", (3, 4, 5))
def test_pre_motion_failed_terminal_is_complete_without_plan(cause):
    assembler = FixedGainAmplitudeAssembler()
    assembler.handle_terminal(
        {
            "oid": 1,
            "payload": terminal_payload(
                outcome=3,
                cause=cause,
                plan_digest=0,
                digest=0,
                attempted=(0, 0),
                eligible=(0, 0),
                emitted_observations=0,
                emitted_amplitudes=0,
                evidence_sequence=0,
            ),
        }
    )
    assert assembler.done
    assert assembler.outcome == "failed"


@pytest.mark.parametrize("cause", (3, 4, 5))
def test_pre_motion_failed_terminal_rejects_nonzero_evidence_sequence(cause):
    assembler = FixedGainAmplitudeAssembler()
    with pytest.raises(FixedGainAmplitudeProtocolError, match="evidence"):
        assembler.handle_terminal(
            {
                "oid": 1,
                "payload": terminal_payload(
                    outcome=3,
                    cause=cause,
                    plan_digest=0,
                    digest=0,
                    attempted=(0, 0),
                    eligible=(0, 0),
                    emitted_observations=0,
                    emitted_amplitudes=0,
                    evidence_sequence=1,
                ),
            }
        )


def test_resolved_terminal_rejects_zero_evidence_sequence():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload()})
    with pytest.raises(FixedGainAmplitudeProtocolError, match="evidence"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload(evidence_sequence=0)})


def test_autotune_relays_one_complete_amplitude_without_host_decisions():
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def finish_amplitude(deadline):
        reactor._time = deadline
        params = {
            "oid": driver.oid,
            "run_sequence": RUN_SEQUENCE,
            "shape": 1,
            "nominal_workflow_ms": 60_541,
            "maximum_workflow_ms": 66_456,
        }
        params["digest_low"], params["digest_high"] = (
            driver.autotune.fixed_gain_amplitude.workflow_digest_halves(params)
        )
        driver.autotune.handle_commissioning_workflow_plan(params)
        driver.autotune.handle_fixed_gain_amplitude_plan(
            {"oid": driver.oid, "payload": plan_payload()}
        )
        driver.autotune.handle_fixed_gain_amplitude_terminal(
            {"oid": driver.oid, "payload": terminal_payload()}
        )
        return reactor._time

    reactor.pause = finish_amplitude
    gcmd = MockGCmd({"ACTION": "amplitude_up"})
    driver.autotune.autotune(gcmd)

    assert driver.protocol.commands.tune.last_args[1] == 1
    assert gcmd._responses[0] == "FOCI_AUTOTUNE stepper_x: SUCCEEDED — complete."


def test_autotune_prints_failed_summary_on_fixed_gain_amplitude_failure():
    # outcome=3 ("failed") is a pre-motion failure: no plan/workflow may have
    # been disclosed yet, and (per handle_terminal's expected_causes table)
    # it only pairs with cause in {3, 4, 5, 7} -- cause=3 here
    # ("missing_acceptance_point"), not the post-motion cause=1
    # ("insufficient_shared_floor") that pairs only with outcome=1.
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def finish_amplitude(deadline):
        reactor._time = deadline
        driver.autotune.handle_fixed_gain_amplitude_terminal(
            {
                "oid": driver.oid,
                "payload": terminal_payload(
                    outcome=3,
                    cause=3,
                    plan_digest=0,
                    digest=0,
                    attempted=(0, 0),
                    eligible=(0, 0),
                    emitted_observations=0,
                    emitted_amplitudes=0,
                    evidence_sequence=0,
                ),
            }
        )
        return reactor._time

    reactor.pause = finish_amplitude
    gcmd = MockGCmd({"ACTION": "amplitude_up"})

    with pytest.raises(CommandError, match="fixed-gain amplitude validation failed"):
        driver.autotune.autotune(gcmd)

    assert gcmd._responses[0] == ("FOCI_AUTOTUNE stepper_x: FAILED — missing acceptance point.")


def test_fixed_gain_amplitude_detail_is_absent_from_log_when_debug_disabled(caplog):
    driver = ready_driver()  # debug defaults to False, per make_driver()
    reactor = driver.printer.get_reactor()

    def finish_amplitude(deadline):
        reactor._time = deadline
        params = {
            "oid": driver.oid,
            "run_sequence": RUN_SEQUENCE,
            "shape": 1,
            "nominal_workflow_ms": 60_541,
            "maximum_workflow_ms": 66_456,
        }
        params["digest_low"], params["digest_high"] = (
            driver.autotune.fixed_gain_amplitude.workflow_digest_halves(params)
        )
        driver.autotune.handle_commissioning_workflow_plan(params)
        driver.autotune.handle_fixed_gain_amplitude_plan(
            {"oid": driver.oid, "payload": plan_payload()}
        )
        driver.autotune.handle_fixed_gain_amplitude_terminal(
            {"oid": driver.oid, "payload": terminal_payload()}
        )
        return reactor._time

    reactor.pause = finish_amplitude
    gcmd = MockGCmd({"ACTION": "amplitude_up"})

    with caplog.at_level(logging.INFO, logger="klipper_foci.autotune"):
        driver.autotune.autotune(gcmd)

    assert "klipper_foci.autotune" not in {r.name for r in caplog.records}
    assert gcmd._responses[0] == "FOCI_AUTOTUNE stepper_x: SUCCEEDED — complete."


PLAN_FRAGMENT_BYTES = 33
PLAN_FRAGMENTS = 2


def feed_plan_fragments(assembler, payload: bytes, *, oid: int = 1) -> None:
    """Deliver a plan the way firmware sends it: two equal fragments."""
    for index in range(PLAN_FRAGMENTS):
        chunk = payload[index * PLAN_FRAGMENT_BYTES : (index + 1) * PLAN_FRAGMENT_BYTES]
        assembler.handle_plan({"oid": oid, "fragment": index, "payload": chunk})


def test_plan_assembles_from_two_firmware_fragments():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    payload = plan_payload()

    feed_plan_fragments(assembler, payload)

    assert assembler.plan is not None
    assert assembler.plan["schema_revision"] == 6
    assert assembler.plan["targets_rpm"] == TARGETS


def test_plan_is_incomplete_until_its_second_fragment():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    payload = plan_payload()

    assembler.handle_plan({"oid": 1, "fragment": 0, "payload": payload[:PLAN_FRAGMENT_BYTES]})

    assert assembler.plan is None


def test_plan_rejects_a_reordered_fragment():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    payload = plan_payload()

    with pytest.raises(FixedGainAmplitudeProtocolError, match="reordered amplitude plan fragment"):
        assembler.handle_plan({"oid": 1, "fragment": 1, "payload": payload[PLAN_FRAGMENT_BYTES:]})


def recovery_wide_workflow(assembler, shape=1):
    """Workflow envelope for schemas that use the recovery-wide duration."""
    params = {
        "oid": 1,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": 63_041,
        "maximum_workflow_ms": 66_456,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(params)
    assembler.handle_workflow_plan(params)


def test_breakaway_seeded_action_resolves_to_firmware_wire_code_seven():
    """AutotuneAction::BreakawaySeeded = 7 (foci-firmware src/tmc.rs) is
    reachable from FOCI_AUTOTUNE ACTION=breakaway_seeded."""
    assert parse_autotune_action("breakaway_seeded") == 7


def test_plan_unpacks_the_packed_schedule_order_byte():
    """Slot order rides in the high nibble of the amplitude-order byte."""
    assembler = FixedGainAmplitudeAssembler()
    recovery_wide_workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload(0x11, TARGETS, nominal_ms=63_041)})

    assert assembler.plan["order"] == AMPLITUDE_ORDER_ASCENDING
    assert assembler.plan["slot_order"] == 1


def test_plan_accepts_the_unmirrored_order():
    assembler = FixedGainAmplitudeAssembler()
    recovery_wide_workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload(0x01, TARGETS, nominal_ms=63_041)})

    assert assembler.plan["order"] == AMPLITUDE_ORDER_ASCENDING
    assert assembler.plan["slot_order"] == 0


def test_plan_rejects_an_unusable_packed_schedule_order_byte():
    for order_byte in (0x00, 0x03, 0x21):
        assembler = FixedGainAmplitudeAssembler()
        recovery_wide_workflow(assembler)
        with pytest.raises(FixedGainAmplitudeProtocolError):
            assembler.handle_plan(
                {
                    "oid": 1,
                    "payload": plan_payload(order_byte, TARGETS, schema=5, nominal_ms=63_041),
                }
            )


def test_terminal_carries_the_evidence_sequence():
    assembler = FixedGainAmplitudeAssembler()
    workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload()})
    payload = struct.pack(
        "<HIHBBQQ8sHBH",
        6,
        RUN_SEQUENCE,
        91,
        0,
        0,
        PLAN_DIGEST,
        0x1111_2222_3333_4444,
        bytes((0x1F, 0x1F, 0x1F, 0x1F, 0, 0, 0, 0)),
        40,
        5,
        0x12,
    )

    assembler.handle_terminal({"oid": 1, "payload": payload})

    assert assembler.terminal["evidence_sequence"] == 91


def test_amplitude_schema_six_plan_and_terminal_are_accepted():
    """Each amplitude schema gate fails closed and silently, so this asserts
    acceptance of the current firmware revision rather than the absence of a
    crash."""
    assembler = FixedGainAmplitudeAssembler()
    recovery_wide_workflow(assembler)
    assembler.handle_plan(
        {"oid": 1, "payload": plan_payload(0x01, TARGETS, schema=6, nominal_ms=63_041)}
    )

    assembler.handle_terminal(
        {"oid": 1, "payload": terminal_payload(schema=6)},
    )

    assert assembler.plan["schema_revision"] == 6
    assert assembler.terminal["schema_revision"] == 6
