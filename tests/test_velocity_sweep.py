"""Velocity-sweep stream reassembly and integrity tests."""

import struct

import pytest

from klipper_foci.velocity_sweep import (
    VelocitySweepAssembler,
    VelocitySweepProtocolError,
)


def plan_fragments(rung_count=5):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 0}
    return (
        {
            **common,
            "fragment": 0,
            "requested_velocity_mrev_s": 5000,
            "requested_velocity_source": 1,
            "planned_velocity_mrev_s": 4800,
            "effective_ceiling_mrev_s": 7500,
            "clamp_flags": 1,
            "binding_source": 0,
        },
        {
            **common,
            "fragment": 1,
            "target_velocity_rpm": 3200,
            "p_start": 8,
            "p_top": 128,
            "rung_count": rung_count,
            "observations_per_direction": 2,
            "max_stroke_travel_mrev": 1000,
            "settle_travel_reserve_mrev": 250,
            "negative_position_headroom_mrev": 1250,
            "positive_position_headroom_mrev": 1250,
            "hard_torque_limit": 1000,
            "usable_torque_limit": 900,
        },
        {
            **common,
            "fragment": 2,
            "moving_stroke_us": 256000,
            "zero_settle_us": 200000,
            "nominal_workflow_ms": 9120,
            "maximum_workflow_ms": 10000,
        },
    )


def _fnv1a(values):
    digest = 0xCBF29CE484222325
    for fmt, value in values:
        for byte in struct.pack("<" + fmt, value):
            digest ^= byte
            digest = (digest * 0x100000001B3) & 0xFFFF_FFFF_FFFF_FFFF
    return digest


def plan_digest(rung_count=5):
    limits, geometry, timing = plan_fragments(rung_count)
    return _fnv1a(
        [
            ("B", 1),
            ("I", 7),
            ("H", 0),
            ("I", limits["requested_velocity_mrev_s"]),
            ("B", limits["requested_velocity_source"]),
            ("I", limits["planned_velocity_mrev_s"]),
            ("I", limits["effective_ceiling_mrev_s"]),
            ("H", limits["clamp_flags"]),
            ("B", limits["binding_source"]),
            ("i", geometry["target_velocity_rpm"]),
            ("H", geometry["p_start"]),
            ("H", geometry["p_top"]),
            ("B", geometry["rung_count"]),
            ("H", geometry["observations_per_direction"]),
            ("I", timing["moving_stroke_us"]),
            ("I", timing["zero_settle_us"]),
            ("I", timing["nominal_workflow_ms"]),
            ("I", timing["maximum_workflow_ms"]),
            ("I", geometry["max_stroke_travel_mrev"]),
            ("I", geometry["settle_travel_reserve_mrev"]),
            ("I", geometry["negative_position_headroom_mrev"]),
            ("I", geometry["positive_position_headroom_mrev"]),
            ("H", geometry["hard_torque_limit"]),
            ("H", geometry["usable_torque_limit"]),
        ]
    )


def test_stage_b_plan_canonical_record_matches_firmware_schema():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler)

    encoded = assembler._encode_plan(plan_digest())

    assert len(encoded) == 78
    assert encoded == b"".join(
        struct.pack("<" + fmt, value)
        for fmt, value in (
            ("B", 1),
            ("I", 7),
            ("H", 0),
            ("I", plan_digest() & 0xFFFF_FFFF),
            ("I", plan_digest() >> 32),
            ("I", 5000),
            ("B", 1),
            ("I", 4800),
            ("I", 7500),
            ("H", 1),
            ("B", 0),
            ("i", 3200),
            ("H", 8),
            ("H", 128),
            ("B", 5),
            ("H", 2),
            ("I", 256000),
            ("I", 200000),
            ("I", 9120),
            ("I", 10000),
            ("I", 1000),
            ("I", 250),
            ("I", 1250),
            ("I", 1250),
            ("H", 1000),
            ("H", 900),
        )
    )


def feed_plan(assembler, rung_count=5):
    limits, geometry, timing = plan_fragments(rung_count)
    assembler.handle_plan_limits(limits)
    assembler.handle_plan_geometry(geometry)
    assembler.handle_plan_timing(timing)


def stage_b_region_fragments(*, sequence=1, direction=0, member_mask=0b11100):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    return (
        {
            **common,
            "direction_kind_closure": direction | (4 << 2),
            "member_mask": member_mask,
            "rung_bounds": 2 | (4 << 8),
            "p_low": 512,
            "p_high": 1024,
            "member_count": 3,
            "boundary_rung_plus_one": 0,
        },
        {
            **common,
            "member_mask": member_mask,
            "common_low_q16": 100,
            "common_high_q16": 120,
            "pooled_q16": 110,
            "pooled_low_q16": 104,
            "pooled_high_q16": 116,
            "variance_floor_observations": 0,
        },
        {
            **common,
            "member_mask": member_mask,
            "mean_min_mantissa": 10,
            "mean_max_mantissa": 12,
            "envelope_low_mantissa": 9,
            "envelope_high_mantissa": 13,
            "rate_shift": 0,
        },
        {
            **common,
            "member_mask": member_mask,
            "tested_low_q16": 121,
            "tested_high_q16": 130,
        },
    )


def feed_stage_b_region(assembler, **kwargs):
    core, model, rates, boundary = stage_b_region_fragments(**kwargs)
    assembler.handle_directional_region_core(core)
    assembler.handle_directional_region_model(model)
    assembler.handle_directional_region_rates(rates)
    assembler.handle_directional_region_boundary(boundary)


def feed_stage_b_handoff(assembler, *, sequence=3, member_mask=0b11100):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    assembler.handle_stage_b_handoff_core(
        {
            **common,
            "nominated_p": 724,
            "joint_member_mask": member_mask,
            "forward_member_mask": member_mask,
            "reverse_member_mask": member_mask,
            "flags": 0b11,
        }
    )
    assembler.handle_stage_b_nomination(
        {
            **common,
            "nominated_rung": 3,
            "nominated_p": 724,
            "distance_to_start_q16": 4 << 16,
            "distance_to_top_q16": 2 << 16,
            "flags": 0,
        }
    )
    for direction in range(2):
        assembler.handle_stage_b_directional_handoff(
            {
                **common,
                "direction": direction,
                "member_mask": member_mask,
                "coverage": 0,
                "signed_rung_distance": 0,
                "gain_ratio_num": 1,
                "gain_ratio_den": 1,
                "settled_rate_difference_mantissa": 0,
                "settled_rate_difference_shift": 0,
            }
        )


def feed_stage_b_reproduction(
    assembler,
    *,
    sequence,
    member_mask=0b11100,
    previous_digest=0x0102_0304_0506_0708,
    current_digest=0,
):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    assembler.handle_stage_b_reproduction_core(
        {
            **common,
            "outcome": 1,
            "previous_nominated_p": 724,
            "current_nominated_p": 724,
        }
    )
    assembler.handle_stage_b_reproduction_membership(
        {
            **common,
            "previous_forward_mask": member_mask,
            "previous_reverse_mask": member_mask,
            "previous_joint_mask": member_mask,
            "current_forward_mask": member_mask,
            "current_reverse_mask": member_mask,
            "current_joint_mask": member_mask,
        }
    )
    for direction in range(2):
        assembler.handle_stage_b_reproduction_interval(
            {
                **common,
                "direction": direction,
                "previous_low_q16": 104,
                "previous_high_q16": 116,
                "current_low_q16": 104,
                "current_high_q16": 116,
            }
        )
    assembler.handle_stage_b_reproduction_digest(
        {
            **common,
            "previous_digest_low": previous_digest & 0xFFFF_FFFF,
            "previous_digest_high": previous_digest >> 32,
            "current_digest_low": current_digest & 0xFFFF_FFFF,
            "current_digest_high": current_digest >> 32,
        }
    )


def feed_stage_b_terminal(
    assembler,
    *,
    sequence=4,
    outcome=0,
    cause=0,
    member_mask=0b11100,
    nominated_p=724,
    digest=0,
    plan_digest_value=0,
):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    assembler.handle_stage_b_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": outcome,
            "cause": cause,
            "model_direction_mask": 3 if member_mask else 0,
            "coverage_mask": 3 if member_mask else 0,
            "forward_region_count": 1 if member_mask else 0,
            "reverse_region_count": 1 if member_mask else 0,
            "forward_fragment_count": 0,
            "reverse_fragment_count": 0,
            "expected_observations": 0,
            "emitted_observations": 0,
            "expected_rungs": 0,
            "emitted_rungs": 0,
        }
    )
    assembler.handle_stage_b_terminal_identity(
        {
            **common,
            "fragment": 1,
            "forward_member_mask": member_mask,
            "reverse_member_mask": member_mask,
            "joint_member_mask": member_mask,
            "nominated_p": nominated_p,
            "plan_digest_low": plan_digest_value & 0xFFFF_FFFF,
            "plan_digest_high": plan_digest_value >> 32,
            "digest_low": digest & 0xFFFF_FFFF,
            "digest_high": digest >> 32,
        }
    )
    for direction in range(2):
        assembler.handle_stage_b_terminal_interval(
            {
                **common,
                "fragment": direction + 2,
                "direction": direction,
                "pooled_low_q16": 104,
                "pooled_high_q16": 116,
                "started_low": 10,
                "started_high": 0,
                "completed_low": 20,
                "completed_high": 0,
            }
        )


def feed_observation(
    assembler,
    *,
    sequence,
    slot,
    low,
    high,
    velocity_p=16,
    classification=0,
    flags=0,
):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    assembler.handle_observation_core(
        {
            **common,
            "fragment": 0,
            "rung_index": 0,
            "slot": slot,
            "classification": classification,
            "flags": flags,
            "delta_sign": slot & 1,
            "delta_mantissa": 1,
            "delta_shift": 0,
            "elapsed_mantissa": 1000,
            "elapsed_shift": 0,
        }
    )
    assembler.handle_observation_rate(
        {
            **common,
            "fragment": 1,
            "rate_low": 1,
            "rate_mean": 2,
            "rate_high": 3,
            "deficit_low": 4,
            "deficit_high": 5,
            "rate_shift": 0,
            "suffix_len": 64,
            "selected_level": 1,
            "selected_blocks": 16,
            "variance_mantissa": 1,
            "variance_shift": 0,
        }
    )
    assembler.handle_observation_stationarity(
        {
            **common,
            "fragment": 2,
            "slope_mantissa": 0,
            "slope_shift": 0,
            "slope_half_width_mantissa": 1,
            "slope_half_width_shift": 0,
            "lag_one_q": 0,
            "lag_one_half_width_q": 1,
            "residual_mantissa": 1,
            "residual_shift": 0,
            "tested_suffixes": 3,
        }
    )
    assembler.handle_observation_disturbance(
        {
            **common,
            "fragment": 3,
            "velocity_p": velocity_p,
            "target_velocity_rpm": 3200 if not slot & 1 else -3200,
            "disturbance_q16": (low + high) // 2,
            "disturbance_low_q16": low,
            "disturbance_high_q16": high,
            "variance_mantissa": 1,
            "variance_shift": 0,
            "predicted_torque_target_abs": 200,
        }
    )


def terminal_fragments(
    *,
    outcome=0,
    mask=3,
    digest=None,
    cause=None,
    sequence=1,
    expected_observations=0,
    emitted_observations=0,
    expected_rungs=0,
    emitted_rungs=0,
):
    digest = plan_digest(0) if digest is None else digest
    if cause is None:
        cause = 1 if outcome == 1 and mask in (1, 2) else 2 if outcome == 1 else 0
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    direction = {
        "direction_closure": 0,
        "first_moving": 8,
        "p_low": 8,
        "p_high": 32,
        "common_low_q16": 100,
        "common_high_q16": 200,
        "pooled_q16": 150,
        "pooled_low_q16": 120,
        "pooled_high_q16": 180,
        "eligible_rungs": 3,
        "eligible_observations": 6,
        "flags": 0x0D,
    }
    return (
        {**common, **direction, "fragment": 0, "flags": 0x0C | (mask & 1)},
        {
            **common,
            **direction,
            "fragment": 1,
            "direction_closure": 1,
            "flags": 0x0C | ((mask >> 1) & 1),
        },
        {
            **common,
            "fragment": 2,
            "expected_observations": expected_observations,
            "emitted_observations": emitted_observations,
            "expected_rungs": expected_rungs,
            "emitted_rungs": emitted_rungs,
            "digest_low": digest & 0xFFFF_FFFF,
            "digest_high": digest >> 32,
            "outcome": outcome,
            "cause": cause,
            "sufficient_direction_mask": mask,
        },
    )


def test_plan_is_timeout_authority_before_terminal():
    assembler = VelocitySweepAssembler()

    feed_plan(assembler)

    assert assembler.plan_ready
    assert assembler.maximum_duration_s == 10.0
    assert assembler.plan["rung_count"] == 5


def test_plan_ignores_klipper_reply_name_metadata():
    assembler = VelocitySweepAssembler()
    limits, geometry, timing = plan_fragments()
    limits["#name"] = "foci_velocity_sweep_plan_limits"
    geometry["#name"] = "foci_velocity_sweep_plan_geometry"
    timing["#name"] = "foci_velocity_sweep_plan_timing"
    limits["#receive_time"] = 1.0
    geometry["#receive_time"] = 2.0
    timing["#receive_time"] = 3.0

    assembler.handle_plan_limits(limits)
    assembler.handle_plan_geometry(geometry)
    assembler.handle_plan_timing(timing)

    assert assembler.plan_ready
    assert "#name" not in assembler.plan
    assert "#receive_time" not in assembler.plan


def test_stage_b_assembler_has_no_host_evidence_authority():
    assembler = VelocitySweepAssembler()

    assert not hasattr(assembler, "segment_regions")
    assert not hasattr(assembler, "choose_p")


def test_directional_region_joins_fragments_by_exact_membership():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)

    feed_stage_b_region(assembler, sequence=1)

    assert assembler.directional_regions[0]["member_mask"] == 0b11100
    assert assembler.directional_regions[0]["common_interval_q16"] == (100, 120)
    assert assembler.directional_regions[0]["pooled_interval_q16"] == (104, 116)


def test_directional_region_rejects_reordered_fragments():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    _core, model, _rates, _boundary = stage_b_region_fragments()

    with pytest.raises(VelocitySweepProtocolError, match="directional region"):
        assembler.handle_directional_region_model(model)


def test_stage_b_handoff_uses_firmware_nomination_and_annotates_membership():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    feed_stage_b_region(assembler, sequence=1, direction=0)
    feed_stage_b_region(assembler, sequence=2, direction=1)
    assembler.handle_joint_region(
        {
            "oid": 0,
            "run_sequence": 7,
            "evidence_sequence": 3,
            "member_mask": 0b11100,
            "rung_bounds": 2 | (4 << 8),
            "member_count": 3,
            "p_low": 512,
            "p_high": 1024,
            "closure": 1,
        }
    )
    feed_stage_b_handoff(assembler, sequence=4)

    assert assembler.handoff["nominated_p"] == 724
    assert assembler.directional_regions[0]["covers_nominated_p"] is True
    assert assembler.directional_regions[1]["covers_nominated_p"] is True


def test_preflight_plan_mismatch_terminal_is_accepted_without_motion_plan():
    assembler = VelocitySweepAssembler()

    feed_stage_b_terminal(
        assembler,
        sequence=0,
        outcome=4,
        cause=6,
        member_mask=0,
        nominated_p=0,
        digest=0,
        plan_digest_value=123,
    )

    assert assembler.done
    assert assembler.outcome == "rejected_plan_mismatch"
    assert assembler.terminal["plan_digest"] == 123


def test_stage_b_terminal_checks_selected_records_and_exact_digest():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    feed_stage_b_region(assembler, sequence=1, direction=0)
    feed_stage_b_region(assembler, sequence=2, direction=1)
    assembler.handle_joint_region(
        {
            "oid": 0,
            "run_sequence": 7,
            "evidence_sequence": 3,
            "member_mask": 0b11100,
            "rung_bounds": 2 | (4 << 8),
            "member_count": 3,
            "p_low": 512,
            "p_high": 1024,
            "closure": 1,
        }
    )
    feed_stage_b_handoff(assembler, sequence=4)
    plan_identity = 0x1111_2222_3333_4444
    digest = assembler._stage_b_digest(plan_identity)

    feed_stage_b_terminal(
        assembler,
        sequence=5,
        digest=digest,
        plan_digest_value=plan_identity,
    )

    assert assembler.done
    assert assembler.outcome == "complete_candidate"
    assert assembler.terminal["nominated_p"] == 724


def test_stage_b_terminal_rejects_digest_mismatch():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)

    with pytest.raises(VelocitySweepProtocolError, match="digest"):
        feed_stage_b_terminal(
            assembler,
            sequence=1,
            outcome=2,
            cause=1,
            member_mask=0,
            nominated_p=0,
            digest=1,
            plan_digest_value=123,
        )


def test_stage_b_reproduction_precedes_matching_complete_terminal():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    feed_stage_b_region(assembler, sequence=1, direction=0)
    feed_stage_b_region(assembler, sequence=2, direction=1)
    assembler.handle_joint_region(
        {
            "oid": 0,
            "run_sequence": 7,
            "evidence_sequence": 3,
            "member_mask": 0b11100,
            "rung_bounds": 2 | (4 << 8),
            "member_count": 3,
            "p_low": 512,
            "p_high": 1024,
            "closure": 1,
        }
    )
    feed_stage_b_handoff(assembler, sequence=4)
    plan_identity = 0x1111_2222_3333_4444
    pre_reproduction_digest = assembler._stage_b_digest(plan_identity)
    feed_stage_b_reproduction(
        assembler,
        sequence=5,
        current_digest=pre_reproduction_digest,
    )
    final_digest = assembler._stage_b_digest(plan_identity)

    feed_stage_b_terminal(
        assembler,
        sequence=6,
        outcome=1,
        digest=final_digest,
        plan_digest_value=plan_identity,
    )

    assert assembler.outcome == "complete"
    assert assembler.reproduction["current_digest"] == pre_reproduction_digest


def test_reordered_or_duplicate_fragment_is_rejected():
    limits, geometry, _timing = plan_fragments()
    assembler = VelocitySweepAssembler()

    with pytest.raises(VelocitySweepProtocolError, match="fragment"):
        assembler.handle_plan_geometry(geometry)

    assembler = VelocitySweepAssembler()
    assembler.handle_plan_limits(limits)
    with pytest.raises(VelocitySweepProtocolError, match="fragment"):
        assembler.handle_plan_limits(limits)


def test_complete_terminal_checks_counts_and_exact_digest():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    forward, reverse, integrity = terminal_fragments()

    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)
    assembler.handle_terminal_integrity(integrity)

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.sufficient_direction_mask == 3


def test_digest_mismatch_is_transport_failure():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    forward, reverse, integrity = terminal_fragments(digest=1)
    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)

    with pytest.raises(VelocitySweepProtocolError, match="digest"):
        assembler.handle_terminal_integrity(integrity)


def test_compressed_observation_digest_matches_firmware_fixture():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    common = {
        "oid": 0,
        "run_sequence": 7,
        "evidence_sequence": 1,
    }
    assembler.handle_observation_core(
        {
            **common,
            "fragment": 0,
            "rung_index": 0,
            "slot": 0,
            "classification": 0,
            "flags": 1,
            "delta_sign": 0,
            "delta_mantissa": 2_147_483_649,
            "delta_shift": 1,
            "elapsed_mantissa": 2_500_000_001,
            "elapsed_shift": 1,
        }
    )
    assembler.handle_observation_rate(
        {
            **common,
            "fragment": 1,
            "rate_low": -1_250_000_001,
            "rate_mean": 1,
            "rate_high": 1_250_000_001,
            "deficit_low": -1_500_000_001,
            "deficit_high": 1_500_000_001,
            "rate_shift": 2,
            "suffix_len": 0,
            "selected_level": 3,
            "selected_blocks": 16,
            "variance_mantissa": 2_147_483_648,
            "variance_shift": 49,
        }
    )
    assembler.handle_observation_stationarity(
        {
            **common,
            "fragment": 2,
            "slope_mantissa": 0,
            "slope_shift": 0,
            "slope_half_width_mantissa": 0,
            "slope_half_width_shift": 0,
            "lag_one_q": 0,
            "lag_one_half_width_q": 0,
            "residual_mantissa": 0,
            "residual_shift": 0,
            "tested_suffixes": 0,
        }
    )
    assembler.handle_observation_disturbance(
        {
            **common,
            "fragment": 3,
            "velocity_p": 350,
            "target_velocity_rpm": 3200,
            "disturbance_q16": 123_456,
            "disturbance_low_q16": 120_000,
            "disturbance_high_q16": 130_000,
            "variance_mantissa": 2_147_483_648,
            "variance_shift": 9,
            "predicted_torque_target_abs": 500,
        }
    )

    assert assembler._digest == 0xA4D1_29E7_0765_6385


def test_four_observations_reconstruct_and_check_firmware_rung_verdict():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1)
    feed_observation(assembler, sequence=1, slot=0, low=100, high=200)
    feed_observation(assembler, sequence=2, slot=1, low=-200, high=-100)
    feed_observation(assembler, sequence=3, slot=2, low=120, high=220)
    feed_observation(assembler, sequence=4, slot=3, low=-220, high=-120)
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 5}
    assembler.handle_rung_band(
        {
            **common,
            "fragment": 0,
            "rung_index": 0,
            "velocity_p": 16,
            "forward_low_q16": 120,
            "forward_high_q16": 200,
            "reverse_low_q16": -200,
            "reverse_high_q16": -120,
            "forward_p_low": 16,
            "forward_p_high": 16,
            "reverse_p_low": 16,
            "reverse_p_high": 16,
        }
    )
    assembler.handle_rung_quality(
        {
            **common,
            "fragment": 1,
            "rung_index": 0,
            "forward_class": 0,
            "reverse_class": 0,
            "forward_closure": 0,
            "reverse_closure": 0,
            "flags": 3,
            "forward_eligible_rungs": 1,
            "reverse_eligible_rungs": 1,
            "forward_eligible_observations": 2,
            "reverse_eligible_observations": 2,
        }
    )

    assert assembler.rungs[0]["forward_low_q16"] == 120


@pytest.mark.parametrize(
    (
        "first_class",
        "second_class",
        "first_interval",
        "second_interval",
        "rung_class",
        "forward_moving",
    ),
    [
        (0, 0, (100, 150), (200, 250), 4, True),
        (0, 1, (100, 200), (0, 0), 5, False),
        (4, 5, (0, 0), (0, 0), 6, False),
        (3, 3, (0, 0), (0, 0), 3, True),
        (9, 0, (0, 0), (100, 200), 7, False),
    ],
)
def test_noneligible_rung_verdicts_do_not_require_interval_intersection(
    first_class,
    second_class,
    first_interval,
    second_interval,
    rung_class,
    forward_moving,
):
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1)
    feed_observation(
        assembler,
        sequence=1,
        slot=0,
        low=first_interval[0],
        high=first_interval[1],
        classification=first_class,
    )
    feed_observation(assembler, sequence=2, slot=1, low=-200, high=-100)
    feed_observation(
        assembler,
        sequence=3,
        slot=2,
        low=second_interval[0],
        high=second_interval[1],
        classification=second_class,
    )
    feed_observation(assembler, sequence=4, slot=3, low=-220, high=-120)
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 5}
    assembler.handle_rung_band(
        {
            **common,
            "fragment": 0,
            "rung_index": 0,
            "velocity_p": 16,
            "forward_low_q16": 0,
            "forward_high_q16": 0,
            "reverse_low_q16": -200,
            "reverse_high_q16": -120,
            "forward_p_low": 0,
            "forward_p_high": 0,
            "reverse_p_low": 16,
            "reverse_p_high": 16,
        }
    )
    assembler.handle_rung_quality(
        {
            **common,
            "fragment": 1,
            "rung_index": 0,
            "forward_class": rung_class,
            "reverse_class": 0,
            "forward_closure": 0,
            "reverse_closure": 0,
            "flags": 2 | int(forward_moving),
            "forward_eligible_rungs": 0,
            "reverse_eligible_rungs": 1,
            "forward_eligible_observations": 0,
            "reverse_eligible_observations": 2,
        }
    )

    assert assembler.rungs[0]["forward_class"] == rung_class


@pytest.mark.parametrize(("outcome", "cause"), [(2, 9), (1, 4), (0, 4)])
def test_terminal_accepts_digest_verified_evidence_prefix(outcome, cause):
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1)
    feed_observation(
        assembler,
        sequence=1,
        slot=0,
        low=0,
        high=0,
        classification=9 if outcome == 2 else 3,
    )
    forward, reverse, integrity = terminal_fragments(
        outcome=outcome,
        mask=0,
        digest=assembler._digest,
        cause=cause,
        sequence=2,
        expected_observations=4,
        emitted_observations=1,
        expected_rungs=1,
        emitted_rungs=0,
    )

    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)
    assembler.handle_terminal_integrity(integrity)

    assert not assembler.full_plan_executed
    expected_outcome = {0: "complete", 1: "inconclusive", 2: "fault"}[outcome]
    assert assembler.outcome == expected_outcome
    if outcome == 1:
        assert "current headroom" in assembler.remediation
    else:
        assert assembler.done


@pytest.mark.parametrize(("outcome", "cause"), [(0, 0), (1, 1), (1, 2), (1, 3)])
def test_terminal_rejects_unexplained_incomplete_evidence(outcome, cause):
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1)
    feed_observation(
        assembler,
        sequence=1,
        slot=0,
        low=0,
        high=0,
        classification=1,
    )
    forward, reverse, integrity = terminal_fragments(
        outcome=outcome,
        mask=0,
        digest=assembler._digest,
        cause=cause,
        sequence=2,
        expected_observations=4,
        emitted_observations=1,
        expected_rungs=1,
        emitted_rungs=0,
    )
    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)

    with pytest.raises(VelocitySweepProtocolError, match="incomplete"):
        assembler.handle_terminal_integrity(integrity)


def test_rung_verdict_disagreement_is_transport_failure():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1)
    feed_observation(assembler, sequence=1, slot=0, low=100, high=200)
    feed_observation(assembler, sequence=2, slot=1, low=-200, high=-100)
    feed_observation(assembler, sequence=3, slot=2, low=120, high=220)
    feed_observation(assembler, sequence=4, slot=3, low=-220, high=-120)
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 5}
    assembler.handle_rung_band(
        {
            **common,
            "fragment": 0,
            "rung_index": 0,
            "velocity_p": 16,
            "forward_low_q16": 121,
            "forward_high_q16": 200,
            "reverse_low_q16": -200,
            "reverse_high_q16": -120,
            "forward_p_low": 16,
            "forward_p_high": 16,
            "reverse_p_low": 16,
            "reverse_p_high": 16,
        }
    )

    with pytest.raises(VelocitySweepProtocolError, match="verdict"):
        assembler.handle_rung_quality(
            {
                **common,
                "fragment": 1,
                "rung_index": 0,
                "forward_class": 0,
                "reverse_class": 0,
                "forward_closure": 0,
                "reverse_closure": 0,
                "flags": 3,
                "forward_eligible_rungs": 1,
                "reverse_eligible_rungs": 1,
                "forward_eligible_observations": 2,
                "reverse_eligible_observations": 2,
            }
        )


def test_inconclusive_requires_matching_generic_terminal():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    forward, reverse, integrity = terminal_fragments(outcome=1, mask=1)
    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)
    assembler.handle_terminal_integrity(integrity)

    assert not assembler.done

    assembler.handle_outer_inconclusive(
        {
            "oid": 0,
            "run_sequence": 7,
            "evidence_sequence": 1,
            "fragment": 3,
            "phase": 10,
            "sufficient_direction_mask": 1,
            "cause": 1,
            "digest_low": plan_digest(0) & 0xFFFF_FFFF,
            "digest_high": plan_digest(0) >> 32,
        }
    )

    assert assembler.done
    assert assembler.outcome == "inconclusive"
    assert "one direction" in assembler.remediation
