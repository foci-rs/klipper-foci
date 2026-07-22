"""Velocity-integral stream reassembly and integrity tests."""

import pytest

from klipper_foci.velocity_integral import (
    VelocityIntegralAssembler,
    VelocityIntegralProtocolError,
    _fnv1a,
)


PLAN_DIGEST = 0x0123_4567_89AB_CDEF
STAGE_B_DIGEST = 0xFEDC_BA98_7654_3210
RUN_SEQUENCE = 9
POSITIVE_I = (5, 10, 20)


def feed_workflow(assembler, shape=2, maximum_ms=70_000):
    params = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": maximum_ms,
        "maximum_workflow_ms": maximum_ms,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(
        params
    )
    assembler.handle_workflow_plan(params)


def feed_plan(assembler):
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
            "schema_revision": 2,
            "channel": 0,
            "final_p": 1448,
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
            "i_start": 5,
            "positive_rung_count": len(POSITIVE_I),
            "family_size": 4 * (len(POSITIVE_I) + 2),
            "total_rung_count": len(POSITIVE_I) + 2,
            "expected_observations": 8 * (len(POSITIVE_I) + 2),
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
                "joint_membership": 0x0038_0000,
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
            "nominal_workflow_ms": 49_920,
            "maximum_workflow_ms": 49_920,
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
    assembler.handle_plan_recovery(
        {
            **common,
            "origin_band_counts": 1000,
            "nominal_slot_us": 1_816_958,
            "maximum_slot_us": 3_000_000,
            "slot_count": len(POSITIVE_I) + 2,
        }
    )
    for rung_index, i_raw in enumerate(POSITIVE_I):
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


def feed_recovery(assembler, sequence, rung_index):
    common = {
        "oid": 0,
        "run_sequence": RUN_SEQUENCE,
        "evidence_sequence": sequence,
    }
    assembler.handle_recovery_core(
        {
            **common,
            "stage": 1,
            "rung_index": rung_index,
            "p_raw": 1448,
            "binding_source": 0,
            "outcome": 0,
        }
    )
    assembler.handle_recovery_position(
        {
            **common,
            "start_offset_counts": 8458,
            "closest_offset_counts": 999,
            "final_offset_counts": 500,
            "origin_band_counts": 1000,
        }
    )
    assembler.handle_recovery_timing(
        {
            **common,
            "moving_duration_us": 600000,
            "settle_duration_us": 500000,
            "total_duration_us": 1100000,
        }
    )
    assembler.handle_recovery_limits(
        {
            **common,
            "planned_velocity_mrev_s": 4394,
            "lower_rate_low": 0x89ABCDEF,
            "lower_rate_high": 0x01234567,
            "peak_torque_target_abs": 2533,
        }
    )


def feed_full_evidence(assembler):
    sequence = 1
    rung_values = (0, *POSITIVE_I, 0)
    for rung_index, i_raw in enumerate(rung_values):
        for slot in range(8):
            feed_observation(assembler, sequence, rung_index, slot, i_raw)
            sequence += 1
        feed_rung(
            assembler,
            sequence,
            rung_index,
            i_raw,
            0 if rung_index == 0 else 2 if rung_index == len(rung_values) - 1 else 1,
        )
        sequence += 1
        feed_recovery(assembler, sequence, rung_index)
        sequence += 1
    return sequence


def feed_terminal(assembler, sequence, *, reproduction=True):
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
            "bookend_available_mask": 0b11,
            "current_terminus_plus_one": 0,
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
    assembler.handle_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": 1 if reproduction else 0,
            "cause": 0,
            "recovery_unavailable": 0,
            "expected_observations": 40,
            "emitted_observations": 40,
            "expected_rungs": 5,
            "emitted_rungs": 5,
        }
    )
    assembler.handle_terminal_identity(
        {
            **common,
            "fragment": 1,
            "plan_digest_low": PLAN_DIGEST & 0xFFFF_FFFF,
            "plan_digest_high": PLAN_DIGEST >> 32,
            "digest_low": assembler.evidence_digest & 0xFFFF_FFFF,
            "digest_high": assembler.evidence_digest >> 32,
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


@pytest.mark.parametrize("shape", [0, 1, 2])
def test_workflow_shapes_preserve_exact_digest_and_duration(shape):
    assembler = VelocityIntegralAssembler()

    feed_workflow(assembler, shape=shape, maximum_ms=300_000 + shape)

    assert assembler.workflow_plan["shape"] == shape
    assert assembler.workflow_plan["digest"] > 0xFFFF_FFFF
    assert assembler.maximum_duration_s == (300_000 + shape) / 1000


def test_workflow_timeout_uses_firmware_composite_maximum_verbatim():
    assembler = VelocityIntegralAssembler()

    feed_workflow(assembler, shape=1, maximum_ms=389_520)

    assert assembler.maximum_duration_s == 389.52


def test_plan_marker_digest_matches_firmware_fixture():
    plan = {
        "run_sequence": 7,
        "plan_digest": PLAN_DIGEST,
        "final_p": 1448,
        "planned_velocity_mrev_s": 4394,
        "target_velocity_rpm": 264,
        "pwm_hz": 25_000,
        "i_start": 5,
        "positive_rung_count": 5,
        "family_size": 28,
        "moving_stroke_us": 512_000,
        "zero_settle_us": 500_000,
        "analysis_budget_us": 236_000,
        "maximum_workflow_ms": 69_888,
        "origin_band_counts": 1000,
        "nominal_slot_us": 1_816_958,
        "maximum_slot_us": 3_000_000,
        "slot_count": 7,
        "hard_torque_limit": 2816,
        "usable_torque_limit": 2534,
    }

    digest = _fnv1a(VelocityIntegralAssembler._encode_plan_marker(plan))

    assert digest == 0xABBE_8F32_FAA4_A140


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
    assert assembler.curves[1]["eligible_mask"] == 0b101
    assert set(assembler.curves[1]["positive"]) == {0, 2}
    assert assembler.reproduction["divergent"][0][1]["signed_gap_q"] == 7
    assert assembler.reproduction["previous_digest"] == 0x0123_4567_89AB_CDEF
    assert assembler.reproduction["current_digest"] == 0xFEDC_BA98_7654_3210
    assert assembler.terminal["run_started_us"] == 0x0000_0001_FFFF_FFFE
    assert assembler.terminal["run_completed_us"] == 0x0000_0002_0000_0004
    assert len(assembler.recoveries) == 5
    assert assembler.recoveries[0]["lower_rate_q"] == 0x0123_4567_89AB_CDEF
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


def test_wrong_terminal_digest_is_rejected():
    assembler = VelocityIntegralAssembler()
    feed_workflow(assembler)
    feed_plan(assembler)
    sequence = feed_full_evidence(assembler)

    original = assembler.evidence_digest
    feed_terminal(assembler, sequence, reproduction=False)
    assembler.terminal["digest"] = original ^ 1

    with pytest.raises(VelocityIntegralProtocolError, match="digest mismatch"):
        assembler.validate_complete()
