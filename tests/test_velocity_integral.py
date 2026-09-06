"""Velocity-integral stream reassembly and integrity tests."""

import struct

import pytest
from klipper_foci.velocity_integral import (
    BREAKAWAY_DISCOVERY_SCHEMA_REVISION,
    TERMINAL_REST_REJECTION_AFTER_SUFFICIENCY,
    TERMINAL_REST_REJECTION_OWNER_SHIFT,
    VELOCITY_INTEGRAL_TERMINAL_SCHEMA_REVISION,
    BreakawayCampaignAssembler,
    BreakawayCampaignProtocolError,
    VelocityIntegralAssembler,
    VelocityIntegralProtocolError,
)

PLAN_DIGEST = 0x0123_4567_89AB_CDEF
STAGE_B_DIGEST = 0xFEDC_BA98_7654_3210
RUN_SEQUENCE = 9
POSITIVE_I = (5, 10, 20)
NATIVE_Q4_12_POSITIVE_I = (1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
COMBINED_Q4_12_POSITIVE_I = (*NATIVE_Q4_12_POSITIVE_I, 1310)


def feed_workflow(assembler, shape=0, maximum_ms=70_000, nominal_ms=None):
    if nominal_ms is None:
        nominal_ms = maximum_ms
    params = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": nominal_ms,
        "maximum_workflow_ms": maximum_ms,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(params)
    assembler.handle_workflow_plan(params)


def feed_plan(
    assembler,
    schema_revision=2,
    *,
    positive_i=POSITIVE_I,
    nominal_workflow_ms=49_920,
    maximum_workflow_ms=49_920,
    recovery_flags=0,
    final_p=1448,
    joint_membership=0x0038_0000,
):
    common = {"oid": 0, "run_sequence": RUN_SEQUENCE, "evidence_sequence": 0}
    assembler.handle_plan_core(
        {
            **common,
            "fragment": 0,
            "plan_digest_low": PLAN_DIGEST & 0xFFFF_FFFF,
            "plan_digest_high": PLAN_DIGEST >> 32,
            "stage_b_digest_low": STAGE_B_DIGEST & 0xFFFF_FFFF,
            "stage_b_digest_high": STAGE_B_DIGEST >> 32,
            "build_revision": 7,
            "schema_revision": schema_revision,
            "channel": 0,
            "final_p": final_p,
        }
    )
    assembler.handle_plan_geometry(
        {
            **common,
            "fragment": 1,
            "planned_velocity_mrev_s": 2929,
            "target_velocity_rpm": 176,
            "pwm_hz": 25_000,
            "encoder_counts_per_rev": 4000,
            "i_start": positive_i[0],
            "positive_rung_count": len(positive_i),
            "family_size": 4 * (len(positive_i) + 2),
            "total_rung_count": len(positive_i) + 2,
            "expected_observations": 8 * (len(positive_i) + 2),
            "hard_torque_limit": 2816,
            "usable_torque_limit": 2534,
        }
    )
    for direction, interval in enumerate(((15_000_000, 17_000_000), (-19_000_000, -17_000_000))):
        assembler.handle_plan_authority(
            {
                **common,
                "direction": direction,
                "directional_membership": 0x0038_0000,
                "joint_membership": joint_membership,
                "directional_validity": (2, 1)[direction],
                "reduced_margin": 1,
                "pooled_low_q16": interval[0],
                "pooled_high_q16": interval[1],
            }
        )
    assembler.handle_plan_timing(
        {
            **common,
            "fragment": 2,
            "moving_stroke_us": 512_000,
            "zero_settle_us": 500_000,
            "analysis_budget_us": 236_000,
            "nominal_workflow_ms": nominal_workflow_ms,
            "maximum_workflow_ms": maximum_workflow_ms,
        }
    )
    assembler.handle_plan_travel(
        {
            **common,
            "fragment": 3,
            "max_stroke_travel_mrev": 10_000,
            "settle_travel_reserve_mrev": 100,
            "negative_position_headroom_mrev": 20_000,
            "positive_position_headroom_mrev": 20_000,
        }
    )
    recovery = {
        **common,
        "origin_band_counts": 1000,
        "nominal_slot_us": 1_816_958,
        "maximum_slot_us": 3_000_000,
        "slot_count": len(positive_i) + 2,
    }
    if schema_revision >= 6:
        recovery["flags"] = recovery_flags
    assembler.handle_plan_recovery(recovery)
    for rung_index, i_raw in enumerate(positive_i):
        assembler.handle_plan_rung(
            {
                **common,
                "rung_index": rung_index,
                "i_raw": i_raw,
                "tau_us": 2_621_440 // i_raw,
            }
        )


def test_schema_four_assembles_minimum_positive_ladder_and_timeout():
    assembler = VelocityIntegralAssembler()
    positive_i = (1, 2, 4, 8, 16, 32, 64)
    feed_workflow(assembler, maximum_ms=116_856)

    feed_plan(
        assembler,
        schema_revision=4,
        positive_i=positive_i,
        nominal_workflow_ms=106_209,
        maximum_workflow_ms=116_856,
    )

    assert assembler.plan["schema_revision"] == 4
    assert assembler.plan["positive_i"] == list(positive_i)
    assert assembler.plan["family_size"] == 36
    assert assembler.plan["total_rung_count"] == 9
    assert assembler.plan["expected_observations"] == 72
    assert assembler.plan["slot_count"] == 9
    assert assembler.maximum_duration_s == 116.856


def test_schema_five_assembles_exact_native_q4_12_plan():
    assembler = VelocityIntegralAssembler()
    positive_i = (1, 2, 3, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=5,
        positive_i=positive_i,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
    )

    assert assembler.plan["positive_i"] == list(positive_i)
    assert assembler.plan["family_size"] == 56
    assert assembler.plan["expected_observations"] == 112
    assert assembler.plan["slot_count"] == 14
    assert assembler.maximum_duration_s == 182.512


def test_schema_six_assembles_firmware_recovery_flags():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)

    feed_plan(
        assembler,
        schema_revision=6,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
        recovery_flags=1,
    )

    assert assembler.plan["schema_revision"] == 6
    assert assembler.plan["recovery_quantization_exposed"] is True


def test_schema_six_rejects_reserved_plan_recovery_flags():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)

    with pytest.raises(VelocityIntegralProtocolError, match="plan recovery flags"):
        feed_plan(
            assembler,
            schema_revision=6,
            positive_i=NATIVE_Q4_12_POSITIVE_I,
            nominal_workflow_ms=165_950,
            maximum_workflow_ms=182_512,
            recovery_flags=2,
        )


def test_schema_seven_exposes_firmware_selected_probe_constrained_test_point():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=7,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
        recovery_flags=0b10,
        final_p=724,
        joint_membership=0x000E_0000,
    )

    assert assembler.plan["schema_revision"] == 7
    assert assembler.plan["final_p"] == 724
    assert assembler.plan["authorities"][0]["joint_membership"] == 0x000E_0000
    assert assembler.plan["probe_constrained_test_point"] is True


def test_firmware_authored_durations_are_consumed_not_asserted():
    """A schedule change must not require a host edit.

    Durations are derived by firmware from stroke, settle, and rung counts. The
    host previously memorised the answers per schema, so any timing change broke
    it. Re-hosted on the breakaway continuation (shape 6, schema 14) now that the
    classic combined schema range (8-13) is no longer accepted -- the
    firmware-authored-duration guarantee this pins is generic Stage-C behaviour,
    not combined-specific.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    feed_plan(
        assembler,
        schema_revision=14,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=999_999,
        maximum_workflow_ms=1_000_000,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["nominal_workflow_ms"] == 999_999
    assert assembler.plan["maximum_workflow_ms"] == 1_000_000


@pytest.mark.parametrize("shape", [0, 1, 2])
def test_workflow_shapes_preserve_exact_digest_and_duration(shape):
    assembler = VelocityIntegralAssembler()
    maximum_ms = 300_000 + shape
    nominal_ms = maximum_ms

    feed_workflow(assembler, shape=shape, nominal_ms=nominal_ms, maximum_ms=maximum_ms)

    assert assembler.workflow_plan["shape"] == shape
    assert assembler.workflow_plan["digest"] > 0xFFFF_FFFF
    assert assembler.maximum_duration_s == maximum_ms / 1000


def test_workflow_timeout_uses_firmware_composite_maximum_verbatim():
    assembler = VelocityIntegralAssembler()

    feed_workflow(assembler, shape=1, maximum_ms=389_520)

    assert assembler.maximum_duration_s == 389.52


def test_rejects_plan_fragment_reordering_and_duplicates():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="plan core"):
        assembler.handle_plan_geometry({"fragment": 1})

    feed_plan(assembler)
    with pytest.raises(VelocityIntegralProtocolError, match="duplicate plan"):
        assembler.handle_plan_rung(
            {
                "run_sequence": RUN_SEQUENCE,
                "evidence_sequence": 0,
                "rung_index": 0,
                "i_raw": 5,
                "tau_us": 524_288,
            }
        )


def test_breakaway_schema_plan_is_accepted_under_a_resume_workflow():
    """Resuming breakaway authority replays a breakaway-schema plan.

    Schema 14 was previously exclusive to the campaign workflow, because that
    was the only way to reach it. A resume regenerates the same exact plan from
    retained authority, so it carries the same schema under the resume shape.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=0, nominal_ms=49_920, maximum_ms=49_920)

    feed_plan(assembler, schema_revision=14, positive_i=POSITIVE_I, joint_membership=0)

    assert assembler.plan["schema_revision"] == 14


# Every valid shape other than resume (0) and breakaway (3) reaches the
# schema-pairing gate below unrefused -- there is no earlier, shape-specific
# gate any more, since every live shape now names a real firmware workflow.
@pytest.mark.parametrize("shape", (1, 2, 4))
def test_breakaway_schema_plan_is_still_refused_under_any_other_workflow(shape):
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=shape, nominal_ms=49_920, maximum_ms=49_920)

    with pytest.raises(VelocityIntegralProtocolError, match="requires breakaway"):
        feed_plan(assembler, schema_revision=14, positive_i=POSITIVE_I, joint_membership=0)


def test_mirrored_slot_order_flag_is_accepted_at_every_schema():
    """Firmware records the mirrored slot order without moving the schema.

    Bit 2 of the plan recovery flags marks a combined run whose forward and
    reverse observation slots executed in mirrored order. Unlike the older flag
    bits it is not schema-gated, because firmware sets it without a schema bump.
    """
    # Schema 6 predates the probe-constrained bit entirely, so accepting bit 2
    # there proves it is not riding on a later gate.
    for schema_revision in (6, 7):
        assembler = VelocityIntegralAssembler()
        feed_workflow(assembler, maximum_ms=182_512)
        feed_plan(
            assembler,
            schema_revision=schema_revision,
            positive_i=NATIVE_Q4_12_POSITIVE_I,
            nominal_workflow_ms=165_950,
            maximum_workflow_ms=182_512,
            recovery_flags=0b100,
        )
        assert assembler.plan["mirrored_slot_order"] is True
        assert assembler.plan["recovery_quantization_exposed"] is False


def test_reserved_plan_recovery_flags_above_the_known_set_are_still_rejected():
    # Bits 2 and 3 are the slot-order field; bit 4 is the first still-reserved bit.
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)

    with pytest.raises(VelocityIntegralProtocolError, match="plan recovery flags"):
        feed_plan(
            assembler,
            schema_revision=6,
            positive_i=NATIVE_Q4_12_POSITIVE_I,
            nominal_workflow_ms=165_950,
            maximum_workflow_ms=182_512,
            recovery_flags=0b10000,
        )


def test_schema_fourteen_assembles_the_breakaway_stage_c_plan():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=20_000, maximum_ms=20_000)
    feed_plan(
        assembler,
        schema_revision=14,
        positive_i=POSITIVE_I,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["schema_revision"] == 14
    assert assembler.plan["final_p"] == 1024


def test_schema_fourteen_requires_breakaway_workflow():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=1, nominal_ms=20_000, maximum_ms=20_000)

    with pytest.raises(VelocityIntegralProtocolError, match="breakaway workflow"):
        feed_plan(assembler, schema_revision=14, positive_i=POSITIVE_I, joint_membership=0)


def test_breakaway_shape_stage_c_plan_rejects_a_non_breakaway_schema():
    """Schema 13 is below the breakaway floor and, since the classic combined
    range (8-13) is no longer accepted at all, is now rejected at the plan-core
    schema gate rather than at the later shape-pairing check."""
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=20_000, maximum_ms=20_000)

    with pytest.raises(
        VelocityIntegralProtocolError, match="unsupported velocity-integral evidence schema"
    ):
        feed_plan(assembler, schema_revision=13, positive_i=POSITIVE_I, joint_membership=0)


def _terminal_params(
    *,
    schema=VELOCITY_INTEGRAL_TERMINAL_SCHEMA_REVISION,
    run_sequence=RUN_SEQUENCE,
    outcome=1,
    cause=0,
    cause_namespace=0,
    recovery_flags=0,
    forward_eligible_mask=0,
    reverse_eligible_mask=0,
    bookend_available_mask=0,
    current_terminus_plus_one=0,
    reproduction_available=0,
    forward_reproduced_mask=0,
    forward_divergent_mask=0,
    reverse_reproduced_mask=0,
    reverse_divergent_mask=0,
):
    payload = struct.pack(
        "<BIBBBBIIBBBIIII",
        schema,
        run_sequence,
        outcome,
        cause,
        cause_namespace,
        recovery_flags,
        forward_eligible_mask,
        reverse_eligible_mask,
        bookend_available_mask,
        current_terminus_plus_one,
        reproduction_available,
        forward_reproduced_mask,
        forward_divergent_mask,
        reverse_reproduced_mask,
        reverse_divergent_mask,
    )
    return {"oid": 0, "payload": payload}


def test_handle_terminal_parses_the_compact_payload():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    assembler.handle_terminal(
        _terminal_params(
            outcome=1,
            cause=4,
            cause_namespace=0,
            forward_eligible_mask=0x0000_0007,
            reverse_eligible_mask=0x0000_0003,
            bookend_available_mask=0b01,
            current_terminus_plus_one=4,
            reproduction_available=1,
        )
    )

    assert assembler.done is True
    assert assembler.outcome == "complete"
    assert assembler.terminal["outcome_name"] == "complete"
    assert assembler.terminal["cause"] == 4
    assert assembler.terminal["cause_namespace"] == 0
    assert assembler.terminal["forward_eligible_mask"] == 0x0000_0007
    assert assembler.terminal["reverse_eligible_mask"] == 0x0000_0003
    assert assembler.terminal["bookend_available_mask"] == 0b01
    assert assembler.terminal["current_terminus_plus_one"] == 4
    assert assembler.terminal["rest_rejection_after_sufficiency"] is False
    assert assembler.terminal["rest_rejection_owner"] is None


def test_handle_terminal_rejects_unsupported_schema():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="schema"):
        assembler.handle_terminal(_terminal_params(schema=99))


def test_handle_terminal_rejects_invalid_outcome():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="outcome"):
        assembler.handle_terminal(_terminal_params(outcome=99))


def test_handle_terminal_rejects_run_sequence_mismatch():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="run sequence"):
        assembler.handle_terminal(
            _terminal_params(run_sequence=RUN_SEQUENCE + 1, reproduction_available=1)
        )


def test_handle_terminal_establishes_run_sequence_when_none_preceded_it():
    assembler = VelocityIntegralAssembler()

    assembler.handle_terminal(_terminal_params(run_sequence=41, outcome=5, cause=12))

    assert assembler.done is True
    assert assembler.outcome == "failed"
    assert assembler.terminal["cause"] == 12


def test_handle_terminal_rejects_a_successful_outcome_with_no_preceding_plan():
    assembler = VelocityIntegralAssembler()

    with pytest.raises(VelocityIntegralProtocolError, match="preceded exact plan"):
        assembler.handle_terminal(_terminal_params(run_sequence=41, outcome=1, cause=0))


def test_handle_terminal_rejects_an_unlisted_failed_admission_cause():
    assembler = VelocityIntegralAssembler()

    with pytest.raises(VelocityIntegralProtocolError, match="preceded exact plan"):
        assembler.handle_terminal(_terminal_params(run_sequence=41, outcome=5, cause=1))


def test_handle_terminal_rejects_failed_admission_shape_after_a_partial_plan():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    assembler.handle_plan_core(
        {
            "oid": 0,
            "run_sequence": RUN_SEQUENCE,
            "evidence_sequence": 0,
            "fragment": 0,
            "plan_digest_low": PLAN_DIGEST & 0xFFFF_FFFF,
            "plan_digest_high": PLAN_DIGEST >> 32,
            "stage_b_digest_low": STAGE_B_DIGEST & 0xFFFF_FFFF,
            "stage_b_digest_high": STAGE_B_DIGEST >> 32,
            "build_revision": 7,
            "schema_revision": 2,
            "channel": 0,
            "final_p": 1448,
        }
    )

    with pytest.raises(VelocityIntegralProtocolError, match="preceded exact plan"):
        assembler.handle_terminal(_terminal_params(outcome=5, cause=12))


def test_handle_terminal_rejects_an_unlisted_cause_when_a_workflow_plan_is_present():
    """An unlisted failed-admission cause is rejected the same way whether or
    not a workflow plan has already arrived -- the workflow shape itself no
    longer carries any special-case meaning here."""
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=0)

    with pytest.raises(VelocityIntegralProtocolError, match="preceded exact plan"):
        assembler.handle_terminal(_terminal_params(outcome=5, cause=99))


def test_handle_terminal_decodes_rest_rejection_owner():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    flags = TERMINAL_REST_REJECTION_AFTER_SUFFICIENCY | (
        0b10 << TERMINAL_REST_REJECTION_OWNER_SHIFT
    )

    assembler.handle_terminal(_terminal_params(recovery_flags=flags, reproduction_available=1))

    assert assembler.terminal["rest_rejection_after_sufficiency"] is True
    assert assembler.terminal["rest_rejection_owner"] == "stage_c_recovery"


def test_handle_terminal_marks_inconclusive_rest_by_cause():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    assembler.handle_terminal(_terminal_params(outcome=2, cause=53))

    assert assembler.terminal["outcome_name"] == "InconclusiveRest"


def test_handle_terminal_with_reproduction_exposes_masks_per_direction():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    assembler.handle_terminal(
        _terminal_params(
            reproduction_available=1,
            forward_reproduced_mask=0x0000_0005,
            forward_divergent_mask=0x0000_0002,
            reverse_reproduced_mask=0x0000_0002,
            reverse_divergent_mask=0x0000_0001,
        )
    )

    assert assembler.reproduction == {
        "forward": {"reproduced_mask": 0x0000_0005, "divergent_mask": 0x0000_0002},
        "reverse": {"reproduced_mask": 0x0000_0002, "divergent_mask": 0x0000_0001},
    }


def test_handle_terminal_rejects_invalid_reproduction_availability_value():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="reproduction"):
        assembler.handle_terminal(_terminal_params(outcome=2, reproduction_available=2))


def test_handle_terminal_rejects_reproduction_masks_without_availability_flag():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="reproduction"):
        assembler.handle_terminal(
            _terminal_params(outcome=2, reproduction_available=0, forward_reproduced_mask=1)
        )


def test_handle_terminal_rejects_complete_without_reproduction():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)

    with pytest.raises(VelocityIntegralProtocolError, match="reproduction"):
        assembler.handle_terminal(_terminal_params(outcome=1, reproduction_available=0))


def test_handle_terminal_allows_complete_without_reproduction_for_breakaway_continuation():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=20_000, maximum_ms=20_000)
    feed_plan(
        assembler, schema_revision=14, positive_i=POSITIVE_I, final_p=1024, joint_membership=0
    )

    assembler.handle_terminal(_terminal_params(outcome=1, reproduction_available=0))

    assert assembler.outcome == "complete"


# ============================================================================
# Breakaway-seeded campaign: BreakawayCampaignAssembler
# ============================================================================

BREAKAWAY_RUN_SEQUENCE = 21
PROBE_DIGEST = (0x1111_1111, 0x2222_2222)
DISCOVERY_DIGEST = (0x3333_3333, 0x4444_4444)
CONFIRMATION_DIGEST = (0x5555_5555, 0x6666_6666)
STAGE_C_DIGEST = (0x7777_7777, 0x8888_8888)


def feed_probe_plan(assembler, *, run_sequence=BREAKAWAY_RUN_SEQUENCE, digest=PROBE_DIGEST):
    low, high = digest
    assembler.handle_probe_plan(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 0,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "max_observations": 128,
            "search_count": 10,
            "p_start_raw": 100,
            "p_top_raw": 2000,
            "motion_threshold_counts": 63,
            "max_capture_interval_us": 2000,
        }
    )


def feed_probe_result(assembler, *, run_sequence=BREAKAWAY_RUN_SEQUENCE, digest=PROBE_DIGEST):
    low, high = digest
    assembler.handle_probe_result(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 1,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "rung_index": 5,
            "breakaway_p_raw": 320,
            "motion_threshold_counts": 63,
            "observation_count": 14,
        }
    )


def feed_discovery_plan(
    assembler,
    *,
    run_sequence=BREAKAWAY_RUN_SEQUENCE,
    prior_digest=PROBE_DIGEST,
    digest=DISCOVERY_DIGEST,
):
    prior_low, prior_high = prior_digest
    low, high = digest
    assembler.handle_discovery_plan_identity(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "prior_plan_digest_low": prior_low,
            "prior_plan_digest_high": prior_high,
            "family_size": 32,
        }
    )
    assembler.handle_discovery_plan_geometry(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "schema_revision": BREAKAWAY_DISCOVERY_SCHEMA_REVISION,
            "rung_count": 3,
            "observations_per_direction": 8,
            "floor_p_raw": 290,
            "floor_origin": 0,
            "breakaway_p_raw": 320,
            "ceiling_p_raw": 2000,
            "first_additive_step_raw": 40,
            "maximum_workflow_ms": 20_000,
        }
    )


def feed_discovery_terminal(
    assembler,
    *,
    run_sequence=BREAKAWAY_RUN_SEQUENCE,
    prior_digest=PROBE_DIGEST,
    digest=DISCOVERY_DIGEST,
    collected_count=2,
):
    prior_low, prior_high = prior_digest
    low, high = digest
    assembler.handle_discovery_terminal(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 2,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "prior_plan_digest_low": prior_low,
            "prior_plan_digest_high": prior_high,
            "family_size": 32,
            "terminal_cause": 0,
            "collected_count": collected_count,
            "has_safety_fault": 0,
        }
    )


def feed_confirmation_plan(
    assembler,
    *,
    run_sequence=BREAKAWAY_RUN_SEQUENCE,
    prior_digest=DISCOVERY_DIGEST,
    digest=CONFIRMATION_DIGEST,
    candidate_p_raw=400,
):
    prior_low, prior_high = prior_digest
    low, high = digest
    assembler.handle_confirmation_plan(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 3,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "prior_plan_digest_low": prior_low,
            "prior_plan_digest_high": prior_high,
            "family_size": 8,
            "observations_per_direction": 4,
            "candidate_p_raw": candidate_p_raw,
            "band_lower_percent": 70,
            "band_upper_percent": 80,
            "capture_profile": 0,
            "acceptance_rule": 0,
            "nominated_margin_percent_milli": 2_000,
        }
    )


def feed_confirmation_terminal(
    assembler,
    *,
    run_sequence=BREAKAWAY_RUN_SEQUENCE,
    prior_digest=DISCOVERY_DIGEST,
    digest=CONFIRMATION_DIGEST,
    accepted,
):
    prior_low, prior_high = prior_digest
    low, high = digest
    assembler.handle_confirmation_terminal_identity(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 3,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "prior_plan_digest_low": prior_low,
            "prior_plan_digest_high": prior_high,
            "family_size": 8,
            "terminal_cause": 21 if accepted else 15,
        }
    )
    assembler.handle_confirmation_terminal_masks(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 3,
            "forward_collected_mask": 0b1111,
            "forward_eligible_mask": 0b1111,
            "forward_included_mask": 0b1111,
            "reverse_collected_mask": 0b1111,
            "reverse_eligible_mask": 0b1111,
            "reverse_included_mask": 0b1111,
            "accepted": int(accepted),
            "confirmed_p_raw": 400 if accepted else 0,
            "max_relative_se_permille": 500 if accepted else 900,
            "required_relative_se_permille": 667,
            "has_safety_fault": 0,
        }
    )


def feed_campaign_terminal(
    assembler,
    *,
    run_sequence=BREAKAWAY_RUN_SEQUENCE,
    accepted,
    stage_c_digest=STAGE_C_DIGEST,
    terminal_cause=None,
    error_code=0,
):
    low, high = stage_c_digest if accepted else (0, 0)
    assembler.handle_campaign_terminal(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 4,
            "phase": 2,
            "terminal_cause": terminal_cause
            if terminal_cause is not None
            else (21 if accepted else 15),
            "accepted": int(accepted),
            "stage_c_plan_digest_low": low,
            "stage_c_plan_digest_high": high,
            "error_code": error_code,
        }
    )


def test_breakaway_probe_result_relays_firmware_values():
    """No selection happens here: every stored value is the input verbatim."""
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)

    assert assembler.probe_plan["p_start_raw"] == 100
    assert assembler.probe_plan["p_top_raw"] == 2000
    assert assembler.probe_result["rung_index"] == 5
    assert assembler.probe_result["breakaway_p_raw"] == 320
    assert assembler.probe_result["observation_count"] == 14


def test_breakaway_probe_result_rejects_digest_mismatch():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="digest mismatch"):
        assembler.handle_probe_result(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 1,
                "plan_digest_low": 0,
                "plan_digest_high": 0,
                "rung_index": 5,
                "breakaway_p_raw": 320,
                "motion_threshold_counts": 63,
                "observation_count": 14,
            }
        )


def test_breakaway_probe_result_rejects_a_duplicate():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="duplicate probe result"):
        feed_probe_result(assembler)


def test_breakaway_discovery_rejects_a_missing_probe_result():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="resolved probe breakaway"):
        feed_discovery_plan(assembler)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("max_observations", 127),
        ("motion_threshold_counts", 0),
        ("max_capture_interval_us", 2001),
        ("search_count", 0),
    ),
)
def test_breakaway_probe_plan_rejects_an_invalid_upward_contract(field, value):
    assembler = BreakawayCampaignAssembler()
    params = {
        "oid": 0,
        "run_sequence": BREAKAWAY_RUN_SEQUENCE,
        "evidence_sequence": 0,
        "plan_digest_low": PROBE_DIGEST[0],
        "plan_digest_high": PROBE_DIGEST[1],
        "max_observations": 128,
        "search_count": 10,
        "p_start_raw": 100,
        "p_top_raw": 2000,
        "motion_threshold_counts": 63,
        "max_capture_interval_us": 2000,
    }
    params[field] = value

    with pytest.raises(BreakawayCampaignProtocolError):
        assembler.handle_probe_plan(params)


def test_breakaway_probe_terminal_accepts_cause_22():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)

    assembler.handle_probe_terminal(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 1,
            "plan_digest_low": PROBE_DIGEST[0],
            "plan_digest_high": PROBE_DIGEST[1],
            "terminal_cause": 22,
            "has_safety_fault": 0,
        }
    )

    assert assembler.probe_terminal["terminal_cause"] == 22


@pytest.mark.parametrize("cause", (2, 3, 4))
def test_breakaway_probe_terminal_rejects_reserved_causes(cause):
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="invalid probe terminal cause"):
        assembler.handle_probe_terminal(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 1,
                "plan_digest_low": PROBE_DIGEST[0],
                "plan_digest_high": PROBE_DIGEST[1],
                "terminal_cause": cause,
                "has_safety_fault": 0,
            }
        )


def test_breakaway_discovery_plan_must_chain_from_the_probe_digest():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="chain from the probe"):
        assembler.handle_discovery_plan_identity(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "plan_digest_low": DISCOVERY_DIGEST[0],
                "plan_digest_high": DISCOVERY_DIGEST[1],
                "prior_plan_digest_low": 0,
                "prior_plan_digest_high": 0,
                "family_size": 32,
            }
        )


def test_breakaway_discovery_geometry_rejects_gains_out_of_order():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    assembler.handle_discovery_plan_identity(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 2,
            "plan_digest_low": DISCOVERY_DIGEST[0],
            "plan_digest_high": DISCOVERY_DIGEST[1],
            "prior_plan_digest_low": PROBE_DIGEST[0],
            "prior_plan_digest_high": PROBE_DIGEST[1],
            "family_size": 32,
        }
    )

    with pytest.raises(BreakawayCampaignProtocolError, match="floor<=breakaway<=ceiling"):
        assembler.handle_discovery_plan_geometry(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "schema_revision": BREAKAWAY_DISCOVERY_SCHEMA_REVISION,
                "rung_count": 3,
                "observations_per_direction": 8,
                "floor_p_raw": 330,
                "floor_origin": 0,
                "breakaway_p_raw": 320,
                "ceiling_p_raw": 2000,
                "first_additive_step_raw": 40,
                "maximum_workflow_ms": 20_000,
            }
        )


def test_breakaway_discovery_geometry_rejects_unsupported_schema_revision():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    assembler.handle_discovery_plan_identity(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 2,
            "plan_digest_low": DISCOVERY_DIGEST[0],
            "plan_digest_high": DISCOVERY_DIGEST[1],
            "prior_plan_digest_low": PROBE_DIGEST[0],
            "prior_plan_digest_high": PROBE_DIGEST[1],
            "family_size": 32,
        }
    )

    with pytest.raises(BreakawayCampaignProtocolError, match="unsupported"):
        assembler.handle_discovery_plan_geometry(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "schema_revision": BREAKAWAY_DISCOVERY_SCHEMA_REVISION + 1,
                "rung_count": 3,
                "observations_per_direction": 8,
                "floor_p_raw": 290,
                "floor_origin": 0,
                "breakaway_p_raw": 320,
                "ceiling_p_raw": 2000,
                "first_additive_step_raw": 40,
                "maximum_workflow_ms": 20_000,
            }
        )


def test_breakaway_confirmation_masks_reject_included_exceeding_eligible():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    assembler.handle_confirmation_terminal_identity(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 3,
            "plan_digest_low": CONFIRMATION_DIGEST[0],
            "plan_digest_high": CONFIRMATION_DIGEST[1],
            "prior_plan_digest_low": DISCOVERY_DIGEST[0],
            "prior_plan_digest_high": DISCOVERY_DIGEST[1],
            "family_size": 8,
            "terminal_cause": 21,
        }
    )

    with pytest.raises(BreakawayCampaignProtocolError, match="included mask"):
        assembler.handle_confirmation_terminal_masks(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 3,
                "forward_collected_mask": 0b1111,
                "forward_eligible_mask": 0b0011,
                "forward_included_mask": 0b1111,  # exceeds eligible
                "reverse_collected_mask": 0b1111,
                "reverse_eligible_mask": 0b1111,
                "reverse_included_mask": 0b1111,
                "accepted": 1,
                "confirmed_p_raw": 400,
                "max_relative_se_permille": 500,
                "required_relative_se_permille": 667,
                "has_safety_fault": 0,
            }
        )


def test_breakaway_campaign_terminal_requires_agreement_with_confirmation():
    """The campaign closure record must not contradict its own confirmation.

    Firmware only ever routes an `Accepted` confirmation outcome to the
    accepting campaign terminal (`route_confirmed_accept`); this proves the
    host catches a firmware report that disagreed with itself instead of
    silently trusting whichever flag it reads last.
    """
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_terminal(assembler, accepted=False)

    with pytest.raises(BreakawayCampaignProtocolError, match="own acceptance"):
        feed_campaign_terminal(assembler, accepted=True)


def test_breakaway_campaign_terminal_confirmed_refusal_is_not_a_protocol_error():
    """A genuinely confirmed acceptance whose Stage-C plan build was refused
    is a legitimate outcome, not a protocol violation -- only the
    reverse (a Stage-C plan without a confirmed acceptance) remains invalid."""
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_terminal(assembler, accepted=True)

    feed_campaign_terminal(assembler, accepted=False, terminal_cause=26, error_code=11)

    assert assembler.done
    assert assembler.accepted is False
    assert assembler.campaign_terminal["error_code"] == 11


def test_breakaway_campaign_terminal_accepted_requires_a_stage_c_digest():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_terminal(assembler, accepted=True)

    with pytest.raises(BreakawayCampaignProtocolError, match="velocity-integral plan digest"):
        assembler.handle_campaign_terminal(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 4,
                "phase": 2,
                "terminal_cause": 21,
                "accepted": 1,
                "stage_c_plan_digest_low": 0,
                "stage_c_plan_digest_high": 0,
                "error_code": 0,
            }
        )


def test_breakaway_campaign_accepts_and_relays_the_full_report():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_terminal(assembler, accepted=True)
    feed_campaign_terminal(assembler, accepted=True)

    assert assembler.done
    assert assembler.accepted is True
    assert assembler.stage_c_plan_digest == (STAGE_C_DIGEST[0] | (STAGE_C_DIGEST[1] << 32))
    # The confirmed gain is the exact confirmation candidate, never a
    # host-reselected value.
    assert (
        assembler.confirmation_terminal["confirmed_p_raw"]
        == (assembler.confirmation_plan["candidate_p_raw"])
    )


def test_breakaway_campaign_inconclusive_confirmation_preserves_no_candidate():
    """On an inconclusive confirmation the campaign never nominates a gain.

    No Stage-C authority may be derived, so `stage_c_plan_digest` reads as the
    empty identity and a second confirmation plan (a "retry") is refused --
    the assembler exposes no path to keep trying candidates.
    """
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_probe_result(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_terminal(assembler, accepted=False)
    feed_campaign_terminal(assembler, accepted=False)

    assert assembler.done
    assert assembler.accepted is False
    assert assembler.stage_c_plan_digest == 0

    with pytest.raises(BreakawayCampaignProtocolError, match="duplicate confirmation"):
        feed_confirmation_plan(assembler, candidate_p_raw=360)


def test_breakaway_campaign_assembler_exposes_no_decision_making_surface():
    """Dumb-host proof: no method here can choose a rung, family, or retry.

    Every public method on this assembler is named `handle_*` -- it accepts
    and validates one firmware-authored record and stores it unchanged. None
    of the banned decision verbs below (which the acceptance/discovery/probe
    logic in firmware actually uses -- see breakaway_campaign.rs) name any
    method or attribute on this class.
    """
    banned_verbs = (
        "select",
        "choose",
        "pick",
        "nominate",
        "retry",
        "resolve",
        "decide",
        "reselect",
    )
    surface = [name for name in dir(BreakawayCampaignAssembler) if not name.startswith("_")]
    assert surface, "expected a nonempty public surface to scan"
    for name in surface:
        assert name.startswith("handle_") or name in (
            "probe_plan",
            "probe_result",
            "probe_terminal",
            "discovery_plan",
            "discovery_ceiling_source",
            "discovery_rung_zero",
            "discovery_terminal",
            "confirmation_plan",
            "confirmation_terminal",
            "campaign_terminal",
            "accepted",
            "stage_c_plan_digest",
            "done",
        ), f"unexpected non-relay method on the assembler: {name}"
        for verb in banned_verbs:
            assert verb not in name.lower(), f"{name} looks like a decision, not a relay"
