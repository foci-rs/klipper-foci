"""Velocity-integral stream reassembly and integrity tests."""

import pytest

from klipper_foci.velocity_integral import (
    slot_direction_index,
    BREAKAWAY_DISCOVERY_SCHEMA_REVISION,
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
OPAQUE_DIGEST = 0xDEAD_BEEF_0123_4567


def feed_workflow(assembler, shape=2, maximum_ms=70_000, nominal_ms=None):
    if nominal_ms is None:
        nominal_ms = maximum_ms
    params = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": nominal_ms,
        "maximum_workflow_ms": maximum_ms,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(
        params
    )
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
    for direction, interval in enumerate(
        ((15_000_000, 17_000_000), (-19_000_000, -17_000_000))
    ):
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


def feed_observation(assembler, sequence, rung_index, slot, i_raw, slot_order=0):
    direction = slot_direction_index(slot_order, slot)
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": sequence,
    }
    low, high = (100, 110) if direction == 0 else (-110, -100)
    assembler.handle_observation_core(
        {
            **common,
            "fragment": 0,
            "plan_digest_low": PLAN_DIGEST & 0xFFFF_FFFF,
            "plan_digest_high": PLAN_DIGEST >> 32,
            "rung_index": rung_index,
            "slot": slot,
            "i_raw": i_raw,
            "direction": direction,
            "classification": 0,
            "initial_lead_in": int(sequence == 1),
            "peak_torque_target_abs": 1200,
        }
    )
    assembler.handle_observation_rate(
        {
            **common,
            "fragment": 1,
            "settled_low": -20 if direction else 20,
            "settled_mean": -18 if direction else 18,
            "settled_high": -16 if direction else 16,
            "settled_shift": 1,
            "deficit_low_q": low,
            "deficit_high_q": high,
        }
    )
    assembler.handle_observation_quality(
        {
            **common,
            "fragment": 2,
            "suffix_len": 64,
            "level_or_exclusion": 3,
            "selected_blocks": 16,
            "slope_mantissa": -7,
            "slope_shift": 2,
            "slope_half_width_mantissa": 9,
            "slope_half_width_shift": 1,
            "lag_one_q": -12,
            "lag_one_half_width_q": 30,
            "residual_mantissa": 44,
            "residual_shift": 3,
            "tested_suffixes": 3,
        }
    )


def test_stage_c_observation_advances_over_trace_only_current_sequence():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler, schema_revision=3)
    feed_observation(assembler, 1, 0, 0, 0)
    feed_observation(assembler, 3, 0, 1, 1)

    assert (0, 1) in assembler.observations


def test_stage_c_terminal_can_follow_observation_without_current():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler, schema_revision=3)
    feed_observation(assembler, 1, 0, 0, 0)

    assembler.handle_run_summary(
        {
            "oid": 0,
            "run_sequence": RUN_SEQUENCE,
            "evidence_sequence": 2,
            "fragment": 0,
            "forward_eligible_mask": 0,
            "reverse_eligible_mask": 0,
            "opening_available_mask": 0,
            "bookend_available_mask": 0,
            "current_terminus_plus_one": 0,
            "sufficient_direction_mask": 0,
        }
    )

    assert assembler.summary is not None


def test_stage_c_trace_only_current_hole_does_not_hide_larger_gap():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler, schema_revision=3)
    feed_observation(assembler, 1, 0, 0, 0)

    with pytest.raises(VelocityIntegralProtocolError, match="sequence gap"):
        feed_observation(assembler, 4, 0, 1, 1)


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


def test_schema_eight_assembles_the_combined_response_plan():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=449_173, maximum_ms=494_128)
    feed_plan(
        assembler,
        schema_revision=8,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=177_751,
        maximum_workflow_ms=195_496,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["positive_i"] == list(COMBINED_Q4_12_POSITIVE_I)
    assert assembler.plan["family_size"] == 60
    assert assembler.plan["expected_observations"] == 120
    assert assembler.plan["slot_count"] == 15
    assert assembler.maximum_duration_s == 494.128


def test_schema_nine_accepts_the_corrected_combined_duration_envelope():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=451_573, maximum_ms=496_528)
    feed_plan(
        assembler,
        schema_revision=9,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=180_151,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["schema_revision"] == 9
    assert assembler.plan["nominal_workflow_ms"] == 180_151
    assert assembler.plan["maximum_workflow_ms"] == 197_896
    assert assembler.maximum_duration_s == 496.528


def test_schema_ten_preserves_the_corrected_combined_duration_envelope():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=451_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(10)
    feed_plan(
        assembler,
        schema_revision=10,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=180_151,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["schema_revision"] == 10
    assert assembler.maximum_duration_s == 496.528


def test_schema_ten_accepts_the_selected_recovery_combined_duration_envelope():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=452_073, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(11)
    feed_plan(
        assembler,
        schema_revision=10,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=180_151,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["schema_revision"] == 10
    assert assembler.maximum_duration_s == 496.528


def test_schema_eleven_accepts_recovery_wide_combined_duration_envelope():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(12)
    feed_plan(
        assembler,
        schema_revision=11,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["schema_revision"] == 11
    assert assembler.maximum_duration_s == 496.528


def test_schema_thirteen_pairs_with_stage_b_fourteen():
    """Each schema gate fails closed and silently, so this asserts acceptance
    of the current firmware revision pair rather than the absence of a
    crash."""
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(14)
    feed_plan(
        assembler,
        schema_revision=13,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["schema_revision"] == 13


@pytest.mark.parametrize(
    ("stage_b_schema", "schema_revision"),
    [
        (11, 11),  # Stage-C 11 pairs with Stage-B 12
        (12, 12),  # Stage-C 12 pairs with Stage-B 13
        (11, 12),
    ],
)
def test_combined_schema_rejects_mismatched_stage_b_pairing(
    stage_b_schema, schema_revision
):
    """Stage-B and Stage-C revisions must be a matching pair.

    This is a compatibility check on the protocol, not a re-derivation of
    firmware's workflow arithmetic. Durations are firmware-authored and the host
    consumes them; it no longer asserts them.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(stage_b_schema)

    with pytest.raises(VelocityIntegralProtocolError, match="matching pair"):
        feed_plan(
            assembler,
            schema_revision=schema_revision,
            positive_i=COMBINED_Q4_12_POSITIVE_I,
            nominal_workflow_ms=187_651,
            maximum_workflow_ms=197_896,
            final_p=1024,
            joint_membership=0,
        )


def test_firmware_authored_durations_are_consumed_not_asserted():
    """A schedule change must not require a host edit.

    Durations are derived by firmware from stroke, settle, and rung counts. The
    host previously memorised the answers per schema, so any timing change broke
    it, and duration was even used to infer the Stage-B revision, which aborted a
    run in session 3 when two schemas deliberately shared a duration.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(13)
    feed_plan(
        assembler,
        schema_revision=12,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=999_999,
        maximum_workflow_ms=1_000_000,
        final_p=1024,
        joint_membership=0,
    )

    assert assembler.plan["nominal_workflow_ms"] == 999_999
    assert assembler.plan["maximum_workflow_ms"] == 1_000_000


def feed_rung(assembler, sequence, rung_index, i_raw, kind):
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": sequence,
        "rung_index": rung_index,
        "i_raw": i_raw,
    }
    for direction in range(2):
        low, high = (100, 110) if direction == 0 else (-110, -100)
        assembler.handle_rung_core(
            {
                **common,
                "fragment": direction,
                "direction": direction,
                "kind": kind,
                "classification": 0,
                "component_count": 1,
                "usable_mask": 0x0F,
                "included_mask": 0x07,
                "observation_classes": 0,
            }
        )
        assembler.handle_rung_component(
            {
                **common,
                "direction": direction,
                "component": 0,
                "low_q": low,
                "high_q": high,
            }
        )


def feed_recovery(assembler, sequence, rung_index, outcome=0):
    assembler.handle_recovery_summary(
        {
            "oid": 0,
            "run_sequence": RUN_SEQUENCE,
            "evidence_sequence": sequence,
            "stage": 1,
            "rung_index": rung_index,
            "p_raw": assembler.plan["final_p"],
            "binding_source": 0,
            "outcome": outcome,
        }
    )


def stage_c_recovery_assembler():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    for slot in range(8):
        feed_observation(assembler, 2 * slot + 1, 0, slot, 0)
    feed_rung(assembler, 17, 0, 0, 0)
    return assembler


def stage_c_11_recovery_assembler():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(12)
    feed_plan(
        assembler,
        schema_revision=11,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )
    for slot in range(8):
        feed_observation(assembler, 2 * slot + 1, 0, slot, 0)
    feed_rung(assembler, 17, 0, 0, 0)
    return assembler


def stage_c_12_recovery_assembler():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(13)
    feed_plan(
        assembler,
        schema_revision=12,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )
    for slot in range(8):
        feed_observation(assembler, 3 * slot + 1, 0, slot, 0)
    feed_rung(assembler, 25, 0, 0, 0)
    return assembler


@pytest.mark.parametrize(
    ("second_sequence", "error"),
    (
        (4, None),
        (2, "sequence gap"),
        (3, "sequence gap"),
        (5, "sequence gap"),
    ),
)
def test_stage_c_12_ordinary_rest_uses_exact_two_hidden_positions(
    second_sequence, error
):
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    assembler.bind_combined_stage_b_schema(13)
    feed_plan(
        assembler,
        schema_revision=12,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )
    feed_observation(assembler, 1, 0, 0, 0)

    def action():
        feed_observation(assembler, second_sequence, 0, 1, 0)

    if error is None:
        action()
    else:
        with pytest.raises(VelocityIntegralProtocolError, match=error):
            action()


def test_stage_c_recovery_summary_is_causal_and_compact():
    assembler = stage_c_recovery_assembler()

    feed_recovery(assembler, 18, 0)

    assert assembler.recoveries[0] == {
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": 18,
        "stage": 1,
        "rung_index": 0,
        "p_raw": 1448,
        "binding_source": 0,
        "outcome": 0,
    }
    with pytest.raises(VelocityIntegralProtocolError, match="duplicate"):
        feed_recovery(assembler, 18, 0)


@pytest.mark.parametrize(
    ("sequence", "outcome", "error"),
    (
        (19, 1, None),
        (18, 1, "hidden recovery-rest"),
        (18, 0, None),
        (20, 1, "sequence gap"),
    ),
)
def test_stage_c_11_recovery_uses_one_causal_hidden_rest_position(
    sequence, outcome, error
):
    assembler = stage_c_11_recovery_assembler()
    if error is not None:
        with pytest.raises(VelocityIntegralProtocolError, match=error):
            feed_recovery(assembler, sequence, 0, outcome=outcome)
    else:
        feed_recovery(assembler, sequence, 0, outcome=outcome)
        assert assembler.recoveries[0]["outcome"] == outcome


@pytest.mark.parametrize(
    ("sequence", "outcome", "error"),
    (
        (28, 1, None),
        (26, 1, "hidden recovery-rest"),
        (26, 0, None),
        (27, 1, "sequence gap"),
        (29, 1, "sequence gap"),
    ),
)
def test_stage_c_12_recovery_uses_two_causal_hidden_positions(sequence, outcome, error):
    assembler = stage_c_12_recovery_assembler()
    if error is not None:
        with pytest.raises(VelocityIntegralProtocolError, match=error):
            feed_recovery(assembler, sequence, 0, outcome=outcome)
    else:
        feed_recovery(assembler, sequence, 0, outcome=outcome)
        assert assembler.recoveries[0]["outcome"] == outcome


def feed_stage_c_terminal_start(assembler, sequence, cause, outcome=3):
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": sequence,
    }
    assembler.handle_run_summary(
        {
            **common,
            "fragment": 0,
            "forward_eligible_mask": 0,
            "reverse_eligible_mask": 0,
            "opening_available_mask": 0,
            "bookend_available_mask": 0,
            "current_terminus_plus_one": 0,
            "sufficient_direction_mask": 0,
        }
    )
    assembler.handle_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": outcome,
            "cause": cause,
            "rest_boundary_rung_plus_one": 0,
            "rest_boundary_slot_plus_one": 0,
            "expected_observations": 120,
            "emitted_observations": 8,
            "expected_rungs": 15,
            "emitted_rungs": 1,
            "recovery_flags": 0x80,
        }
    )


def test_stage_c_11_accepts_hidden_rest_before_completed_rest_terminal():
    assembler = stage_c_11_recovery_assembler()

    feed_stage_c_terminal_start(assembler, 19, cause=53)

    assert len(assembler._terminal_parts) == 1


def test_stage_c_11_rejects_completed_rest_terminal_without_hidden_sequence():
    assembler = stage_c_11_recovery_assembler()

    with pytest.raises(VelocityIntegralProtocolError, match="omitted hidden"):
        feed_stage_c_terminal_start(assembler, 18, cause=53)


def test_stage_c_11_rejects_hidden_rest_before_unrelated_fault():
    assembler = stage_c_11_recovery_assembler()

    with pytest.raises(VelocityIntegralProtocolError, match="completed-rest"):
        feed_stage_c_terminal_start(assembler, 19, cause=11)


def test_stage_c_12_rest_terminal_requires_exact_hidden_positions():
    accepted = VelocityIntegralAssembler()
    feed_workflow(accepted, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    accepted.bind_combined_stage_b_schema(13)
    feed_plan(
        accepted,
        schema_revision=12,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )
    feed_observation(accepted, 1, 0, 0, 0)
    feed_stage_c_terminal_start(accepted, 4, cause=53, outcome=2)

    omitted = VelocityIntegralAssembler()
    feed_workflow(omitted, shape=3, nominal_ms=470_573, maximum_ms=496_528)
    omitted.bind_combined_stage_b_schema(13)
    feed_plan(
        omitted,
        schema_revision=12,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=187_651,
        maximum_workflow_ms=197_896,
        final_p=1024,
        joint_membership=0,
    )
    feed_observation(omitted, 1, 0, 0, 0)
    with pytest.raises(VelocityIntegralProtocolError, match="omitted hidden"):
        feed_stage_c_terminal_start(omitted, 2, cause=53, outcome=2)


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ({"stage": 0}, "wrong stage"),
        ({"run_sequence": RUN_SEQUENCE + 1}, "run sequence"),
        ({"evidence_sequence": 19}, "sequence gap"),
        ({"rung_index": 1}, "immediately follow"),
        ({"p_raw": 1449}, "fixed P"),
    ),
)
def test_stage_c_recovery_summary_rejects_changed_identity(replacement, message):
    assembler = stage_c_recovery_assembler()
    params = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": 18,
        "stage": 1,
        "rung_index": 0,
        "p_raw": 1448,
        "binding_source": 5,
        "outcome": 1,
        **replacement,
    }

    with pytest.raises(VelocityIntegralProtocolError, match=message):
        assembler.handle_recovery_summary(params)


def test_ineligible_opening_anchor_may_terminate_without_recovery():
    assembler = stage_c_recovery_assembler()

    feed_terminal(
        assembler,
        18,
        reproduction=False,
        outcome=2,
        emitted_observations=8,
        emitted_rungs=1,
        cause=1,
    )

    assert assembler.done
    assert assembler.outcome == "inconclusive"
    assert assembler.recoveries == {}


def feed_full_evidence(assembler, recovery_outcomes=None, *, rung_count=None):
    sequence = 1
    rung_values = (0, *assembler.plan["positive_i"], 0)
    if rung_count is not None:
        rung_values = rung_values[:rung_count]
    recovery_outcomes = recovery_outcomes or {}
    for rung_index, i_raw in enumerate(rung_values):
        for slot in range(8):
            feed_observation(assembler, sequence, rung_index, slot, i_raw)
            sequence += 2
        feed_rung(
            assembler,
            sequence,
            rung_index,
            i_raw,
            0 if rung_index == 0 else 2 if rung_index == len(rung_values) - 1 else 1,
        )
        sequence += 1
        feed_recovery(
            assembler,
            sequence,
            rung_index,
            outcome=recovery_outcomes.get(rung_index, 0),
        )
        sequence += 1
    return sequence


def feed_terminal(
    assembler,
    sequence,
    *,
    reproduction=True,
    outcome=None,
    emitted_observations=None,
    emitted_rungs=None,
    digest=None,
    cause=0,
    rest_boundary=(0, 0),
    recovery_flags=None,
    current_terminus_plus_one=0,
):
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": sequence,
    }
    assembler.handle_run_summary(
        {
            **common,
            "fragment": 0,
            "forward_eligible_mask": 0b111,
            "reverse_eligible_mask": 0b101,
            "opening_available_mask": 0b11,
            "bookend_available_mask": 0b11,
            "current_terminus_plus_one": current_terminus_plus_one,
            "sufficient_direction_mask": 0b01,
        }
    )
    for direction in range(2):
        assembler.handle_curve_interval(
            {
                **common,
                "kind": 0,
                "direction": direction,
                "rung_index": 0,
                "low_q": -10,
                "high_q": 10,
            }
        )
        mask = (0b111, 0b101)[direction]
        for rung in range(3):
            if mask & (1 << rung):
                assembler.handle_curve_interval(
                    {
                        **common,
                        "kind": 1,
                        "direction": direction,
                        "rung_index": rung,
                        "low_q": -30 + rung,
                        "high_q": 40 + rung,
                    }
                )
        assembler.handle_curve_interval(
            {
                **common,
                "kind": 2,
                "direction": direction,
                "rung_index": 0,
                "low_q": -12,
                "high_q": 12,
            }
        )
        assembler.handle_drift(
            {
                **common,
                "direction": direction,
                "available": 1,
                "opening_low_q": -10,
                "opening_high_q": 10,
                "closing_low_q": -12,
                "closing_high_q": 12,
            }
        )
        assembler.handle_stage_b_comparison(
            {
                **common,
                "direction": direction,
                "available": 1 if direction == 0 else 0,
                "stage_b_low_q16": -200,
                "stage_b_high_q16": 200,
                "expected_low_q": -20,
                "expected_high_q": 20,
                "opening_low_q": -10,
                "opening_high_q": 10,
            }
        )
    if reproduction:
        assembler.handle_reproduction_core(
            {**common, "outcome": 1, "direction_mask": 0b11}
        )
        for direction in range(2):
            assembler.handle_reproduction_mask(
                {
                    **common,
                    "direction": direction,
                    "previous_mask": 0b111,
                    "current_mask": 0b111,
                    "shared_mask": 0b111,
                    "reproduced_mask": 0b101,
                    "divergent_mask": 0b010,
                    "previous_only_mask": 0,
                    "current_only_mask": 0,
                }
            )
            for rung, kind in ((0, 1), (1, 2), (2, 1)):
                assembler.handle_reproduction_interval(
                    {
                        **common,
                        "direction": direction,
                        "rung_index": rung,
                        "kind": kind,
                        "previous_low_q": -30,
                        "previous_high_q": 40,
                        "current_low_q": -20,
                        "current_high_q": 50,
                        "result_low_or_gap_q": -20 if kind == 1 else 7,
                        "result_high_q": 40 if kind == 1 else 0,
                    }
                )
        assembler.handle_reproduction_digest(
            {
                **common,
                "previous_digest_low": 0x89AB_CDEF,
                "previous_digest_high": 0x0123_4567,
                "current_digest_low": 0x7654_3210,
                "current_digest_high": 0xFEDC_BA98,
            }
        )
    total_rungs = int(assembler.plan["total_rung_count"])
    emitted_rungs = total_rungs if emitted_rungs is None else emitted_rungs
    emitted_observations = (
        8 * emitted_rungs if emitted_observations is None else emitted_observations
    )
    terminal_outcome = (1 if reproduction else 0) if outcome is None else outcome
    terminal_core = {
        **common,
        "fragment": 0,
        "outcome": terminal_outcome,
        "cause": cause,
        "rest_boundary_rung_plus_one": rest_boundary[0],
        "rest_boundary_slot_plus_one": rest_boundary[1],
        "expected_observations": 8 * total_rungs,
        "emitted_observations": emitted_observations,
        "expected_rungs": total_rungs,
        "emitted_rungs": emitted_rungs,
    }
    if int(assembler.plan["schema_revision"]) >= 6:
        if recovery_flags is None:
            recovery_flags = 4 if assembler.plan["recovery_quantization_exposed"] else 0
        terminal_core["recovery_flags"] = recovery_flags
    else:
        terminal_core["recovery_unavailable"] = 0
    assembler.handle_terminal_core(terminal_core)
    terminal_digest = OPAQUE_DIGEST if digest is None else digest
    assembler.handle_terminal_identity(
        {
            **common,
            "fragment": 1,
            "plan_digest_low": PLAN_DIGEST & 0xFFFF_FFFF,
            "plan_digest_high": PLAN_DIGEST >> 32,
            "digest_low": terminal_digest & 0xFFFF_FFFF,
            "digest_high": terminal_digest >> 32,
        }
    )
    assembler.handle_terminal_timing(
        {
            **common,
            "fragment": 2,
            "started_low": 0xFFFF_FFFE,
            "started_high": 0x0000_0001,
            "completed_low": 0x0000_0004,
            "completed_high": 0x0000_0002,
        }
    )


@pytest.mark.parametrize("shape", [0, 1, 2, 3])
def test_workflow_shapes_preserve_exact_digest_and_duration(shape):
    assembler = VelocityIntegralAssembler()
    maximum_ms = 494_128 if shape == 3 else 300_000 + shape
    nominal_ms = 449_173 if shape == 3 else maximum_ms

    feed_workflow(assembler, shape=shape, nominal_ms=nominal_ms, maximum_ms=maximum_ms)

    assert assembler.workflow_plan["shape"] == shape
    assert assembler.workflow_plan["digest"] > 0xFFFF_FFFF
    assert assembler.maximum_duration_s == maximum_ms / 1000


def test_workflow_timeout_uses_firmware_composite_maximum_verbatim():
    assembler = VelocityIntegralAssembler()

    feed_workflow(assembler, shape=1, maximum_ms=389_520)

    assert assembler.maximum_duration_s == 389.52


def test_combined_complete_reports_target_without_reproduction():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=449_173, maximum_ms=494_128)
    feed_plan(
        assembler,
        schema_revision=8,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=177_751,
        maximum_workflow_ms=195_496,
        final_p=1024,
        joint_membership=0,
    )
    sequence = feed_full_evidence(assembler)

    feed_terminal(
        assembler,
        sequence,
        reproduction=False,
        outcome=1,
        recovery_flags=0xC0,
    )

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.reproduction is None
    assert assembler.terminal["combined_workflow"] is True
    assert assembler.terminal["target_status"] == "target_not_reached_at_cap"
    assert assembler.terminal["target_terminus"] is None


def test_combined_complete_relays_firmware_terminal_without_target_status():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=3, nominal_ms=449_173, maximum_ms=494_128)
    feed_plan(
        assembler,
        schema_revision=8,
        positive_i=COMBINED_Q4_12_POSITIVE_I,
        nominal_workflow_ms=177_751,
        maximum_workflow_ms=195_496,
        final_p=1_024,
        joint_membership=0,
    )
    sequence = feed_full_evidence(assembler)

    feed_terminal(
        assembler,
        sequence,
        reproduction=False,
        outcome=1,
        cause=10,
        rest_boundary=(9, 1),
        recovery_flags=0x80,
    )

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.terminal["target_status"] is None
    assert assembler.terminal["rest_boundary"] == {
        "positive_rung_index": 8,
        "slot": 0,
    }


def test_assembles_exact_curves_sparse_masks_and_divergence_records():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    sequence = feed_full_evidence(assembler)

    feed_terminal(assembler, sequence)

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.plan["plan_digest"] == PLAN_DIGEST
    assert assembler.plan["stage_b_plan_digest"] == STAGE_B_DIGEST
    assert assembler.plan["authorities"][0]["directional_validity"] == 2
    assert assembler.plan["authorities"][1]["directional_validity"] == 1
    assert assembler.plan["authorities"][0]["reduced_margin"] == 1
    assert assembler.curves[1]["eligible_mask"] == 0b101
    assert set(assembler.curves[1]["positive"]) == {0, 2}
    assert assembler.reproduction["divergent"][0][1]["signed_gap_q"] == 7
    assert assembler.reproduction["previous_digest"] == 0x0123_4567_89AB_CDEF
    assert assembler.reproduction["current_digest"] == 0xFEDC_BA98_7654_3210
    assert assembler.summary["opening_available_mask"] == 0b11
    assert assembler.stage_b_comparison[0]["available"] == 1
    assert assembler.stage_b_comparison[1]["available"] == 0
    assert assembler.terminal["run_started_us"] == 0x0000_0001_FFFF_FFFE
    assert assembler.terminal["run_completed_us"] == 0x0000_0002_0000_0004
    assert len(assembler.recoveries) == 5
    assert assembler.recoveries[0]["binding_source"] == 0
    assert assembler.terminal["recovery_unavailable"] == 0
    assert "absolute_curves" in assembler.report
    assert "reproduction" in assembler.report


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


def test_terminal_rejects_missing_reproduction_fragment():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    sequence = feed_full_evidence(assembler)

    feed_terminal(assembler, sequence)
    assembler.done = False
    assembler.reproduction["masks"].pop(1)

    with pytest.raises(VelocityIntegralProtocolError, match="reproduction masks"):
        assembler.validate_complete()


def test_terminal_digest_is_retained_as_opaque_firmware_identity():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    sequence = feed_full_evidence(assembler)
    opaque_digest = 0xDEAD_BEEF_0123_4567

    feed_terminal(
        assembler,
        sequence,
        reproduction=False,
        digest=opaque_digest,
    )

    assembler.validate_complete()
    assert assembler.terminal["digest"] == opaque_digest


def test_terminal_exposes_compact_rest_boundary_without_reconstructing_it():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    sequence = feed_full_evidence(assembler)

    feed_terminal(
        assembler,
        sequence,
        reproduction=False,
        cause=10,
        rest_boundary=(3, 6),
    )

    assert assembler.terminal["rest_boundary"] == {
        "positive_rung_index": 2,
        "slot": 5,
    }


@pytest.mark.parametrize(
    ("cause", "rest_boundary", "current_terminus_plus_one", "accepted"),
    (
        (10, (4, 1), 0, True),
        (3, (0, 0), 4, True),
        (0, (0, 0), 0, False),
    ),
)
def test_partial_rung_recovery_requires_post_sufficiency_terminal(
    cause,
    rest_boundary,
    current_terminus_plus_one,
    accepted,
):
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=7,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
        recovery_flags=2,
    )
    sequence = feed_full_evidence(assembler, rung_count=4)
    boundary_rung = 4
    feed_observation(
        assembler,
        sequence,
        boundary_rung,
        0,
        assembler.plan["positive_i"][boundary_rung - 1],
    )
    sequence += 2
    feed_recovery(assembler, sequence, boundary_rung)
    sequence += 1
    bookend_rung = int(assembler.plan["total_rung_count"]) - 1
    for slot in range(8):
        feed_observation(assembler, sequence, bookend_rung, slot, 0)
        sequence += 2
    feed_rung(assembler, sequence, bookend_rung, 0, 2)
    sequence += 1
    feed_recovery(assembler, sequence, bookend_rung)
    sequence += 1

    terminal = {
        "reproduction": False,
        "emitted_observations": 41,
        "emitted_rungs": 5,
        "cause": cause,
        "rest_boundary": rest_boundary,
        "recovery_flags": 8,
        "current_terminus_plus_one": current_terminus_plus_one,
    }
    if not accepted:
        with pytest.raises(
            VelocityIntegralProtocolError,
            match="recovery records do not match fully acquired rungs",
        ):
            feed_terminal(assembler, sequence, **terminal)
        return

    feed_terminal(assembler, sequence, **terminal)

    assert assembler.outcome == "complete_candidate"
    assert set(assembler.recoveries) == {0, 1, 2, 3, boundary_rung, bookend_rung}


def schema_six_full_report(*, recovery_outcome=0, terminal_flags=4):
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
    final_rung = int(assembler.plan["total_rung_count"]) - 1
    sequence = feed_full_evidence(
        assembler,
        recovery_outcomes={final_rung: recovery_outcome},
    )
    feed_terminal(assembler, sequence, recovery_flags=terminal_flags)
    return assembler


def schema_six_recovery_fault_prefix(*, outcome=3, missing_recoveries=(6,)):
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
    emitted_rungs = 7
    sequence = feed_full_evidence(assembler, rung_count=emitted_rungs)
    for rung_index in missing_recoveries:
        assembler.recoveries.pop(rung_index)
    final_rung = emitted_rungs - 1
    assembler._last_evidence = (
        ("rung", final_rung)
        if final_rung in missing_recoveries
        else ("recovery", final_rung)
    )
    feed_terminal(
        assembler,
        sequence,
        reproduction=False,
        outcome=outcome,
        emitted_rungs=emitted_rungs,
        cause=11 if outcome == 3 else 0,
        recovery_flags=4,
    )
    return assembler


def test_stage_c_fault_accepts_one_missing_final_recovery():
    assembler = schema_six_recovery_fault_prefix()

    assert assembler.outcome == "fault"
    assert assembler.terminal["cause"] == 11
    assert set(assembler.recoveries) == set(range(6))


def test_stage_c_non_fault_rejects_one_missing_final_recovery():
    with pytest.raises(VelocityIntegralProtocolError, match="fully acquired rungs"):
        schema_six_recovery_fault_prefix(outcome=2)


def test_stage_c_fault_rejects_two_missing_recovery_records():
    with pytest.raises(VelocityIntegralProtocolError, match="fully acquired rungs"):
        schema_six_recovery_fault_prefix(missing_recoveries=(5, 6))


def test_stage_c_fault_rejects_missing_intermediate_recovery():
    with pytest.raises(VelocityIntegralProtocolError, match="fully acquired rungs"):
        schema_six_recovery_fault_prefix(missing_recoveries=(5,))


def test_schema_six_requires_causal_recovery_outcome_for_recovered_flag():
    assembler = schema_six_full_report(recovery_outcome=5, terminal_flags=6)

    assert assembler.terminal["recovery_unavailable"] == 0
    assert assembler.terminal["recovered_with_current_headroom"] is True
    assert assembler.terminal["recovery_quantization_exposed"] is True
    assert assembler.recoveries[13]["outcome"] == 5

    with pytest.raises(VelocityIntegralProtocolError, match="causal recovery"):
        schema_six_full_report(recovery_outcome=0, terminal_flags=6)


def test_schema_six_rejects_reserved_or_inconsistent_terminal_flags():
    with pytest.raises(VelocityIntegralProtocolError, match="terminal recovery flags"):
        schema_six_full_report(terminal_flags=8)

    with pytest.raises(VelocityIntegralProtocolError, match="exposure differ"):
        schema_six_full_report(terminal_flags=0)


def test_schema_six_preserves_recovery_unavailable_as_a_named_flag():
    assembler = schema_six_full_report(terminal_flags=5)

    assert assembler.terminal["recovery_unavailable"] == 1
    assert assembler.terminal["recovered_with_current_headroom"] is False
    assert assembler.terminal["recovery_quantization_exposed"] is True


def test_schema_seven_requires_matching_probe_constrained_terminal_flag():
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
    sequence = feed_full_evidence(assembler)
    feed_terminal(assembler, sequence, recovery_flags=0b1000)

    assert assembler.terminal["probe_constrained_test_point"] is True
    assert assembler.report["plan"]["probe_constrained_test_point"] is True

    with pytest.raises(VelocityIntegralProtocolError, match="probe constraint differ"):
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
        sequence = feed_full_evidence(assembler)
        feed_terminal(assembler, sequence, recovery_flags=0)


def feed_no_transition_terminal(assembler, *, outcome=5, cause=11, flags=0b1000):
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": 0,
    }
    assembler.handle_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": outcome,
            "cause": cause,
            "recovery_flags": flags,
            "rest_boundary_rung_plus_one": 0,
            "rest_boundary_slot_plus_one": 0,
            "expected_observations": 0,
            "emitted_observations": 0,
            "expected_rungs": 0,
            "emitted_rungs": 0,
        }
    )
    assembler.handle_terminal_identity(
        {
            **common,
            "fragment": 1,
            "plan_digest_low": PLAN_DIGEST & 0xFFFF_FFFF,
            "plan_digest_high": PLAN_DIGEST >> 32,
            "digest_low": 0,
            "digest_high": 0,
        }
    )
    assembler.handle_terminal_timing(
        {
            **common,
            "fragment": 2,
            "started_low": 0,
            "started_high": 0,
            "completed_low": 0,
            "completed_high": 0,
        }
    )


def test_no_transition_direct_resume_accepts_exact_zero_motion_terminal():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=2, maximum_ms=182_512)

    feed_no_transition_terminal(assembler)

    assert assembler.plan is None
    assert assembler.summary is None
    assert assembler.done is True
    assert assembler.outcome == "failed"
    assert assembler.terminal["cause"] == 11
    assert assembler.terminal["plan_digest"] == PLAN_DIGEST
    assert assembler.terminal["digest"] == 0
    assert assembler.terminal["probe_constrained_test_point"] is True


@pytest.mark.parametrize(
    ("outcome", "cause", "flags", "message"),
    (
        (4, 11, 0b1000, "terminal preceded exact plan"),
        (5, 10, 0b1000, "terminal preceded exact plan"),
        (5, 11, 0, "terminal preceded exact plan"),
    ),
)
def test_no_transition_rejects_any_other_terminal_only_shape(
    outcome, cause, flags, message
):
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=2, maximum_ms=182_512)

    with pytest.raises(VelocityIntegralProtocolError, match=message):
        feed_no_transition_terminal(
            assembler,
            outcome=outcome,
            cause=cause,
            flags=flags,
        )


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


def test_mirrored_run_accepts_the_inverted_slot_direction():
    """A mirrored run inverts which direction each slot travels.

    The host validated direction against raw slot parity, so every observation of
    a mirrored run was rejected with "invalid observation slot or direction". The
    run aborted at the first observation, before producing any evidence.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=7,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
        recovery_flags=0b100,
    )
    assert assembler.plan["mirrored_slot_order"] is True

    # Slot 0 travels reverse under mirroring, which is the inverse of parity.
    feed_observation(assembler, 1, 0, 0, 1, slot_order=1)
    assert (0, 0) in assembler.observations

    # The unmirrored pairing must now be the one refused.
    with pytest.raises(VelocityIntegralProtocolError, match="slot or direction"):
        feed_observation(assembler, 3, 0, 1, 1, slot_order=0)


def test_unmirrored_run_still_requires_parity_matched_directions():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=7,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
        recovery_flags=0,
    )
    assert assembler.plan["mirrored_slot_order"] is False

    feed_observation(assembler, 1, 0, 0, 1)
    assert (0, 0) in assembler.observations
    with pytest.raises(VelocityIntegralProtocolError, match="slot or direction"):
        feed_observation(assembler, 3, 0, 1, 1, slot_order=1)


def test_paired_slot_order_accepts_its_f_r_r_f_directions():
    """The paired order runs F,R,R,F,F,R,R,F, so direction is not slot parity.

    A boolean mirrored flag cannot express it: slots 0 and 3 both travel forward
    while slots 1 and 2 both travel reverse, which neither parity nor its inverse
    produces.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=7,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
        recovery_flags=0b1000,
    )
    assert assembler.plan["slot_order"] == 2

    expected = [0, 1, 1, 0, 0, 1, 1, 0]
    for slot, direction in enumerate(expected):
        assert slot_direction_index(2, slot) == direction, f"slot {slot}"

    # Slot 0 forward and slot 1 reverse match parity here, but slot 2 must be
    # reverse and slot 3 forward, which is where parity would disagree.
    feed_observation(assembler, 1, 0, 0, 1, slot_order=2)
    assert (0, 0) in assembler.observations
    with pytest.raises(VelocityIntegralProtocolError, match="slot or direction"):
        feed_observation(assembler, 3, 0, 2, 1, slot_order=0)


def test_slot_direction_index_covers_all_three_orders():
    for slot in range(8):
        assert slot_direction_index(0, slot) == slot & 1
        assert slot_direction_index(1, slot) == (slot & 1) ^ 1
    assert [slot_direction_index(2, s) for s in range(8)] == [0, 1, 1, 0, 0, 1, 1, 0]


def test_slot_range_follows_the_plan_not_a_hardcoded_eight():
    """Slots per rung is firmware geometry, not a host constant.

    A schedule with a different slot count would otherwise be rejected here even
    though the plan declares it, which is the same shape of defect as the
    hardcoded workflow durations.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, maximum_ms=182_512)
    feed_plan(
        assembler,
        schema_revision=7,
        positive_i=NATIVE_Q4_12_POSITIVE_I,
        nominal_workflow_ms=165_950,
        maximum_workflow_ms=182_512,
    )
    rungs = int(assembler.plan["total_rung_count"])
    observations = int(assembler.plan["expected_observations"])

    assert observations % rungs == 0
    assert assembler.slots_per_rung == observations // rungs


# ============================================================================
# Breakaway-seeded campaign: schema-14 Stage-C continuation
# ============================================================================


def test_schema_fourteen_assembles_the_breakaway_stage_c_plan():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=6, nominal_ms=20_000, maximum_ms=20_000)
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
    feed_workflow(assembler, shape=3, nominal_ms=20_000, maximum_ms=20_000)

    with pytest.raises(VelocityIntegralProtocolError, match="breakaway workflow"):
        feed_plan(
            assembler, schema_revision=14, positive_i=POSITIVE_I, joint_membership=0
        )


def test_shape_six_stage_c_plan_rejects_a_non_breakaway_schema():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=6, nominal_ms=20_000, maximum_ms=20_000)

    with pytest.raises(VelocityIntegralProtocolError, match="combined workflow"):
        feed_plan(
            assembler, schema_revision=13, positive_i=POSITIVE_I, joint_membership=0
        )


def test_schema_fourteen_terminal_core_does_not_require_a_combined_marker():
    """Firmware never sets TERMINAL_COMBINED_WORKFLOW for a breakaway plan.

    `data.plan.combined_workflow` (and therefore the wire marker) is only
    `true` when `combined_selected_response` was built, which
    StageCAuthority::new_breakaway never does. Before this fix, the old
    unconditional `schema_revision >= 8` gate rejected every schema-14
    terminal outright.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=6, nominal_ms=49_920, maximum_ms=49_920)
    feed_plan(assembler, schema_revision=14, positive_i=POSITIVE_I, joint_membership=0)
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": 1,
    }
    assembler.handle_run_summary(
        {
            **common,
            "fragment": 0,
            "forward_eligible_mask": 0,
            "reverse_eligible_mask": 0,
            "opening_available_mask": 0,
            "bookend_available_mask": 0,
            "current_terminus_plus_one": 0,
            "sufficient_direction_mask": 0,
        }
    )

    assembler.handle_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": 3,
            "cause": 17,
            "rest_boundary_rung_plus_one": 0,
            "rest_boundary_slot_plus_one": 0,
            "expected_observations": 0,
            "emitted_observations": 0,
            "expected_rungs": 0,
            "emitted_rungs": 0,
            "recovery_flags": 0,
        }
    )

    assert len(assembler._terminal_parts) == 1


def test_schema_fourteen_complete_outcome_does_not_require_reproduction():
    """Neither shape 3 nor shape 6 ever has a reproduced Stage-B model.

    This targets the `combined_or_breakaway` exemption in `validate_complete`
    directly: the completeness state is synthesized rather than streamed
    through the full observation/rung/terminal handler sequence (already
    exercised by the schema<12 combined-flow tests above and unaffected by
    this change), because schema >= 12's two-hidden-position sequencing is
    orthogonal to what this test targets.
    """
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler, shape=6, nominal_ms=49_920, maximum_ms=49_920)
    feed_plan(assembler, schema_revision=14, positive_i=(5,), joint_membership=0)

    assembler.outcome = "complete"
    assembler._summary = {"bookend_available_mask": 0b11}
    assembler.curves = [
        {"eligible_mask": 0, "opening": (0, 0), "positive": {}, "bookend": (0, 0)},
        {"eligible_mask": 0, "opening": (0, 0), "positive": {}, "bookend": (0, 0)},
    ]
    assembler.drift = [{}, {}]
    assembler.stage_b_comparison = [{}, {}]
    assembler.terminal = {
        "plan_digest": assembler.plan["plan_digest"],
        "expected_observations": assembler.plan["expected_observations"],
        "emitted_observations": 0,
        "expected_rungs": assembler.plan["total_rung_count"],
        "emitted_rungs": 0,
        "cause": 0,
        "rest_boundary": None,
        "recovery_quantization_exposed": False,
        "recovered_with_current_headroom": False,
        "probe_constrained_test_point": False,
    }
    assembler.observations = {}
    assembler.rungs = {}
    assembler.recoveries = {}

    assembler.validate_complete()  # must not raise despite reproduction is None


# ============================================================================
# Breakaway-seeded campaign: BreakawayCampaignAssembler
# ============================================================================

BREAKAWAY_RUN_SEQUENCE = 21
PROBE_DIGEST = (0x1111_1111, 0x2222_2222)
DISCOVERY_DIGEST = (0x3333_3333, 0x4444_4444)
CONFIRMATION_DIGEST = (0x5555_5555, 0x6666_6666)
STAGE_C_DIGEST = (0x7777_7777, 0x8888_8888)


def feed_probe_plan(
    assembler, *, run_sequence=BREAKAWAY_RUN_SEQUENCE, digest=PROBE_DIGEST
):
    low, high = digest
    assembler.handle_probe_plan(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 0,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "family_size": 16,
            "max_observations": 8,
            "search_count": 10,
            "p_start_raw": 100,
            "p_top_raw": 2000,
        }
    )


def feed_directional_breakaways(
    assembler, *, run_sequence=BREAKAWAY_RUN_SEQUENCE, digest=PROBE_DIGEST
):
    low, high = digest
    for direction, (inert, moving, observations) in enumerate(
        ((300, 320, 5), (310, 330, 6))
    ):
        assembler.handle_directional_breakaway(
            {
                "oid": 0,
                "run_sequence": run_sequence,
                "evidence_sequence": 1,
                "plan_digest_low": low,
                "plan_digest_high": high,
                "direction": direction,
                "inert_present": 1,
                "inert_p_raw": inert,
                "moving_p_raw": moving,
                "observations": observations,
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


def feed_confirmation_observations(
    assembler, *, run_sequence=BREAKAWAY_RUN_SEQUENCE, digest=CONFIRMATION_DIGEST
):
    low, high = digest
    for slot_index in range(8):
        assembler.handle_confirmation_observation(
            {
                "oid": 0,
                "run_sequence": run_sequence,
                "evidence_sequence": 3,
                "plan_digest_low": low,
                "plan_digest_high": high,
                "slot_index": slot_index,
                "direction": 0 if slot_index < 4 else 1,
                "response_lower_percent_milli": 72_000,
                "response_upper_percent_milli": 78_000,
                "relative_standard_error_permille": 500,
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
):
    low, high = stage_c_digest if accepted else (0, 0)
    assembler.handle_campaign_terminal(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": 4,
            "phase": 2,
            "terminal_cause": 21 if accepted else 15,
            "accepted": int(accepted),
            "stage_c_plan_digest_low": low,
            "stage_c_plan_digest_high": high,
        }
    )


def feed_raw_observation(
    assembler,
    *,
    run_sequence=BREAKAWAY_RUN_SEQUENCE,
    evidence_sequence,
    digest,
    phase,
    rung_index=0,
    slot_index=0,
    direction=0,
    mean_rate_q_low=1_000,
    mean_rate_q_high=0,
    target_rate_q_low=2_000,
    target_rate_q_high=0,
):
    low, high = digest
    assembler.handle_raw_observation_identity(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": evidence_sequence,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "phase": phase,
            "rung_index": rung_index,
            "slot_index": slot_index,
            "direction": direction,
        }
    )
    assembler.handle_raw_observation_measurement(
        {
            "oid": 0,
            "run_sequence": run_sequence,
            "evidence_sequence": evidence_sequence,
            "mean_rate_q_low": mean_rate_q_low,
            "mean_rate_q_high": mean_rate_q_high,
            "variance_word0": 1,
            "variance_word1": 0,
            "variance_word2": 0,
            "variance_word3": 0,
            "target_rate_q_low": target_rate_q_low,
            "target_rate_q_high": target_rate_q_high,
        }
    )


def test_breakaway_probe_and_directional_breakaway_relay_firmware_values():
    """No selection happens here: every stored value is the input verbatim."""
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)

    assert assembler.probe_plan["p_start_raw"] == 100
    assert assembler.probe_plan["p_top_raw"] == 2000
    assert assembler.directional_breakaways[0]["moving_p_raw"] == 320
    assert assembler.directional_breakaways[1]["moving_p_raw"] == 330
    assert assembler.directional_breakaways[0]["observations"] == 5
    assert assembler.directional_breakaways[1]["observations"] == 6


def test_breakaway_directional_breakaway_rejects_digest_mismatch():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="digest mismatch"):
        assembler.handle_directional_breakaway(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 1,
                "plan_digest_low": 0,
                "plan_digest_high": 0,
                "direction": 0,
                "inert_present": 1,
                "inert_p_raw": 300,
                "moving_p_raw": 320,
                "observations": 5,
            }
        )


def test_breakaway_discovery_plan_must_chain_from_the_probe_digest():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)

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
    feed_directional_breakaways(assembler)
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

    with pytest.raises(
        BreakawayCampaignProtocolError, match="floor<=breakaway<=ceiling"
    ):
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
    feed_directional_breakaways(assembler)
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


def _feed_partial_confirmation(assembler, stroke_count):
    """Feed a confirmation plan, `stroke_count` forward strokes, and a
    non-accepted terminal whose masks match the partial block."""
    feed_confirmation_plan(assembler)
    low, high = CONFIRMATION_DIGEST
    for slot_index in range(stroke_count):
        assembler.handle_confirmation_observation(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 3,
                "plan_digest_low": low,
                "plan_digest_high": high,
                "slot_index": slot_index,
                "direction": 0,
                "response_lower_percent_milli": 72_000,
                "response_upper_percent_milli": 78_000,
                "relative_standard_error_permille": 500,
            }
        )
    partial_mask = (1 << min(stroke_count, 4)) - 1
    assembler.handle_confirmation_terminal_identity(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 3,
            "plan_digest_low": low,
            "plan_digest_high": high,
            "prior_plan_digest_low": DISCOVERY_DIGEST[0],
            "prior_plan_digest_high": DISCOVERY_DIGEST[1],
            "family_size": 8,
            "terminal_cause": 15,  # a non-accepted cause
        }
    )
    assembler.handle_confirmation_terminal_masks(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 3,
            "forward_collected_mask": partial_mask,
            "forward_eligible_mask": partial_mask,
            "forward_included_mask": 0,
            "reverse_collected_mask": 0,
            "reverse_eligible_mask": 0,
            "reverse_included_mask": 0,
            "accepted": 0,
            "confirmed_p_raw": 0,
            "max_relative_se_permille": 900,
            "required_relative_se_permille": 667,
            "has_safety_fault": 0,
        }
    )


def test_breakaway_confirmation_allows_a_partial_non_accepted_block():
    """A mid-block SafetyFault or ConfirmationEvidenceExcluded preserves the
    1-7 strokes that ran. A non-accepted terminal carrying a partial block is
    legitimate; only an accepted terminal must carry the full eight."""
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    _feed_partial_confirmation(assembler, stroke_count=2)

    feed_campaign_terminal(assembler, accepted=False)  # closes confirmation
    assert assembler._confirmation_closed is True


def test_breakaway_accepted_confirmation_still_requires_all_eight_strokes():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    # Only two strokes, but an accepted terminal.
    low, high = CONFIRMATION_DIGEST
    for slot_index in range(2):
        assembler.handle_confirmation_observation(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 3,
                "plan_digest_low": low,
                "plan_digest_high": high,
                "slot_index": slot_index,
                "direction": 0,
                "response_lower_percent_milli": 72_000,
                "response_upper_percent_milli": 78_000,
                "relative_standard_error_permille": 500,
            }
        )
    feed_confirmation_terminal(assembler, accepted=True)

    with pytest.raises(
        BreakawayCampaignProtocolError, match="missing its eight-stroke"
    ):
        feed_campaign_terminal(assembler, accepted=True)


def test_breakaway_confirmation_observation_follows_the_fixed_capture_schedule():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="capture schedule"):
        assembler.handle_confirmation_observation(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 3,
                "plan_digest_low": CONFIRMATION_DIGEST[0],
                "plan_digest_high": CONFIRMATION_DIGEST[1],
                "slot_index": 0,
                "direction": 1,  # slot 0 must be forward (direction 0)
                "response_lower_percent_milli": 72_000,
                "response_upper_percent_milli": 78_000,
                "relative_standard_error_permille": 500,
            }
        )


def test_breakaway_confirmation_masks_reject_included_exceeding_eligible():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_observations(assembler)
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
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_observations(assembler)
    feed_confirmation_terminal(assembler, accepted=False)

    with pytest.raises(BreakawayCampaignProtocolError, match="own acceptance"):
        feed_campaign_terminal(assembler, accepted=True)


def test_breakaway_campaign_terminal_accepted_requires_a_stage_c_digest():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_observations(assembler)
    feed_confirmation_terminal(assembler, accepted=True)

    with pytest.raises(BreakawayCampaignProtocolError, match="Stage-C plan digest"):
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
            }
        )


def test_breakaway_campaign_accepts_and_relays_the_full_report():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_observations(assembler)
    feed_confirmation_terminal(assembler, accepted=True)
    feed_campaign_terminal(assembler, accepted=True)

    assert assembler.done
    assert assembler.accepted is True
    assert assembler.stage_c_plan_digest == (
        STAGE_C_DIGEST[0] | (STAGE_C_DIGEST[1] << 32)
    )
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
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_confirmation_observations(assembler)
    feed_confirmation_terminal(assembler, accepted=False)
    feed_campaign_terminal(assembler, accepted=False)

    assert assembler.done
    assert assembler.accepted is False
    assert assembler.stage_c_plan_digest == 0

    with pytest.raises(BreakawayCampaignProtocolError, match="duplicate confirmation"):
        feed_confirmation_plan(assembler, candidate_p_raw=360)


def test_breakaway_raw_observation_relays_discovery_and_confirmation_evidence():
    """No r/SE/nomination math happens here -- the merged fragment is stored

    exactly as firmware sent it, for foci-trace's independent offline replay.
    """
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_raw_observation(
        assembler,
        evidence_sequence=2,
        digest=DISCOVERY_DIGEST,
        phase=1,
        rung_index=1,
        slot_index=3,
        direction=1,
        mean_rate_q_low=4_242,
        target_rate_q_low=6_000,
    )
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    feed_raw_observation(
        assembler,
        evidence_sequence=3,
        digest=CONFIRMATION_DIGEST,
        phase=2,
        slot_index=5,
        direction=1,
    )
    feed_confirmation_observations(assembler)
    feed_confirmation_terminal(assembler, accepted=True)
    feed_campaign_terminal(assembler, accepted=True)

    assert len(assembler.raw_observations) == 2
    discovery_observation, confirmation_observation = assembler.raw_observations
    assert discovery_observation["phase"] == 1
    assert discovery_observation["rung_index"] == 1
    assert discovery_observation["slot_index"] == 3
    assert discovery_observation["mean_rate_q_low"] == 4_242
    assert discovery_observation["target_rate_q_low"] == 6_000
    assert confirmation_observation["phase"] == 2
    assert confirmation_observation["slot_index"] == 5
    # No reduced statistic (r, SE, nomination interval) is ever computed or
    # stored here -- only the raw firmware-authored inputs.
    for observation in assembler.raw_observations:
        assert "r" not in observation
        assert "relative_standard_error_permille" not in observation
        assert "nominated_margin_percent_milli" not in observation


def test_breakaway_raw_observation_identity_rejects_plan_digest_mismatch():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="plan digest mismatch"):
        assembler.handle_raw_observation_identity(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "plan_digest_low": 0,
                "plan_digest_high": 0,
                "phase": 1,
                "rung_index": 0,
                "slot_index": 0,
                "direction": 0,
            }
        )


def test_breakaway_raw_observation_identity_rejects_probe_phase():
    """Firmware never streams raw observations for the probe phase (0)."""
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)

    with pytest.raises(
        BreakawayCampaignProtocolError, match="invalid raw observation phase"
    ):
        assembler.handle_raw_observation_identity(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "plan_digest_low": DISCOVERY_DIGEST[0],
                "plan_digest_high": DISCOVERY_DIGEST[1],
                "phase": 0,
                "rung_index": 0,
                "slot_index": 0,
                "direction": 0,
            }
        )


def test_breakaway_raw_observation_measurement_requires_prior_identity():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)

    with pytest.raises(BreakawayCampaignProtocolError, match="preceded its identity"):
        assembler.handle_raw_observation_measurement(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "mean_rate_q_low": 0,
                "mean_rate_q_high": 0,
                "variance_word0": 0,
                "variance_word1": 0,
                "variance_word2": 0,
                "variance_word3": 0,
                "target_rate_q_low": 0,
                "target_rate_q_high": 0,
            }
        )


def test_breakaway_raw_observation_identity_rejects_a_dangling_predecessor():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    assembler.handle_raw_observation_identity(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 2,
            "plan_digest_low": DISCOVERY_DIGEST[0],
            "plan_digest_high": DISCOVERY_DIGEST[1],
            "phase": 1,
            "rung_index": 0,
            "slot_index": 0,
            "direction": 0,
        }
    )

    with pytest.raises(
        BreakawayCampaignProtocolError, match="before its prior measurement"
    ):
        assembler.handle_raw_observation_identity(
            {
                "oid": 0,
                "run_sequence": BREAKAWAY_RUN_SEQUENCE,
                "evidence_sequence": 2,
                "plan_digest_low": DISCOVERY_DIGEST[0],
                "plan_digest_high": DISCOVERY_DIGEST[1],
                "phase": 1,
                "rung_index": 0,
                "slot_index": 1,
                "direction": 1,
            }
        )


def test_breakaway_campaign_terminal_rejects_a_dangling_raw_observation():
    assembler = BreakawayCampaignAssembler()
    feed_probe_plan(assembler)
    feed_directional_breakaways(assembler)
    feed_discovery_plan(assembler)
    feed_discovery_terminal(assembler)
    feed_confirmation_plan(assembler)
    assembler.handle_raw_observation_identity(
        {
            "oid": 0,
            "run_sequence": BREAKAWAY_RUN_SEQUENCE,
            "evidence_sequence": 3,
            "plan_digest_low": CONFIRMATION_DIGEST[0],
            "plan_digest_high": CONFIRMATION_DIGEST[1],
            "phase": 2,
            "rung_index": 0,
            "slot_index": 0,
            "direction": 0,
        }
    )
    feed_confirmation_observations(assembler)
    feed_confirmation_terminal(assembler, accepted=True)

    with pytest.raises(BreakawayCampaignProtocolError, match="no matching measurement"):
        feed_campaign_terminal(assembler, accepted=True)


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
    surface = [
        name for name in dir(BreakawayCampaignAssembler) if not name.startswith("_")
    ]
    assert surface, "expected a nonempty public surface to scan"
    for name in surface:
        assert name.startswith("handle_") or name in (
            "probe_plan",
            "directional_breakaways",
            "probe_terminal",
            "discovery_plan",
            "discovery_ceiling_source",
            "discovery_rung_zero",
            "discovery_terminal",
            "confirmation_plan",
            "confirmation_observations",
            "confirmation_terminal",
            "campaign_terminal",
            "raw_observations",
            "accepted",
            "stage_c_plan_digest",
            "done",
        ), f"unexpected non-relay method on the assembler: {name}"
        for verb in banned_verbs:
            assert verb not in name.lower(), (
                f"{name} looks like a decision, not a relay"
            )
