"""Velocity-integral stream reassembly and integrity tests."""

import pytest

from klipper_foci.velocity_integral import (
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


def feed_observation(assembler, sequence, rung_index, slot, i_raw):
    direction = slot & 1
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


@pytest.mark.parametrize(
    (
        "workflow_nominal",
        "workflow_maximum",
        "schema_revision",
        "stage_nominal",
        "stage_maximum",
    ),
    [
        (449_173, 494_128, 9, 180_151, 197_896),
        (451_573, 496_528, 8, 177_751, 195_496),
    ],
)
def test_combined_schema_rejects_mixed_duration_envelopes(
    workflow_nominal,
    workflow_maximum,
    schema_revision,
    stage_nominal,
    stage_maximum,
):
    assembler = VelocityIntegralAssembler()
    feed_workflow(
        assembler,
        shape=3,
        nominal_ms=workflow_nominal,
        maximum_ms=workflow_maximum,
    )

    with pytest.raises(
        VelocityIntegralProtocolError, match="does not match Stage-C schema"
    ):
        feed_plan(
            assembler,
            schema_revision=schema_revision,
            positive_i=COMBINED_Q4_12_POSITIVE_I,
            nominal_workflow_ms=stage_nominal,
            maximum_workflow_ms=stage_maximum,
            final_p=1024,
            joint_membership=0,
        )


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
