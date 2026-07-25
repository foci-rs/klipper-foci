"""Velocity-sweep stream reassembly and integrity tests."""

import pytest

from klipper_foci.velocity_sweep import (
    VelocitySweepAssembler,
    VelocitySweepProtocolError,
)

OPAQUE_DIGEST = 0xDEAD_BEEF_0123_4567


def plan_fragments(rung_count=5, observations_per_direction=2):
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
            "observations_per_direction": observations_per_direction,
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
        {
            **common,
            "origin_band_counts": 1000,
            "nominal_slot_us": 1_816_958,
            "maximum_slot_us": 3_000_000,
            "slot_count": rung_count,
        },
    )


def feed_plan(assembler, rung_count=5, observations_per_direction=2):
    limits, geometry, timing, recovery = plan_fragments(
        rung_count, observations_per_direction
    )
    assembler.handle_plan_limits(limits)
    assembler.handle_plan_geometry(geometry)
    assembler.handle_plan_timing(timing)
    assembler.handle_plan_recovery(recovery)


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


def feed_stage_b_handoff(
    assembler,
    *,
    sequence=3,
    member_mask=0b11100,
    joint_union_mask=None,
    region_class=1,
):
    if joint_union_mask is None:
        joint_union_mask = member_mask
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    assembler.handle_stage_b_handoff_core(
        {
            **common,
            "nominated_p": 724,
            "joint_member_mask": joint_union_mask,
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
            "selected_joint_mask": member_mask,
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
                "region_class": region_class,
                "coverage": 0,
                "signed_rung_distance": 0,
                "gain_ratio_num": 1,
                "gain_ratio_den": 1,
                "settled_rate_difference_mantissa": 0,
                "settled_rate_difference_shift": 0,
            }
        )


def stage_b_reproduction_v4_fragments(
    *,
    sequence,
    member_mask=0x0038_0000,
    selected_joint_mask=None,
    final_p=1448,
    selected_first_rung=None,
    selected_member_count=None,
    forward_validity=2,
    reverse_validity=3,
    reduced_margin=0,
    previous_digest=0x0102_0304_0506_0708,
    current_digest=0,
):
    if selected_joint_mask is None:
        selected_joint_mask = member_mask
    if selected_first_rung is None:
        selected_first_rung = (
            selected_joint_mask & -selected_joint_mask
        ).bit_length() - 1
    if selected_member_count is None:
        selected_member_count = selected_joint_mask.bit_count()
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    fragments = [
        (
            "handle_stage_b_reproduction_v4_core",
            {
                **common,
                "outcome": 1,
                "reason_mask": 0,
                "previous_provisional_p": 1448,
                "current_provisional_p": 1024,
                "final_p": final_p,
                "selected_joint_mask": selected_joint_mask,
                "selected_first_rung": selected_first_rung,
                "selected_member_count": selected_member_count,
                "forward_validity": forward_validity,
                "reverse_validity": reverse_validity,
                "reduced_margin": reduced_margin,
                "schema_revision": 8,
            },
        )
    ]
    for object_index in range(3):
        current_mask = member_mask | (0x0004_0000 if object_index == 0 else 0)
        fragments.append(
            (
                "handle_stage_b_reproduction_v4_membership",
                {
                    **common,
                    "object": object_index,
                    "previous_mask": member_mask,
                    "current_mask": current_mask,
                    "core_mask": member_mask,
                    "previous_only_mask": 0,
                    "current_only_mask": current_mask & ~member_mask,
                    "low_delta": -1 if object_index == 0 else 0,
                    "high_delta": 0,
                },
            )
        )
    for direction in range(2):
        fragments.append(
            (
                "handle_stage_b_reproduction_v4_pooled",
                {
                    **common,
                    "direction": direction,
                    "previous_low_q16": 104,
                    "previous_high_q16": 116,
                    "current_low_q16": 108,
                    "current_high_q16": 120,
                    "overlap_low_q16": 108,
                    "overlap_high_q16": 116,
                },
            )
        )
    for direction in range(2):
        fragments.append(
            (
                "handle_stage_b_reproduction_v4_common",
                {
                    **common,
                    "direction": direction,
                    "previous_low_q16": 104,
                    "previous_high_q16": 116,
                    "current_low_q16": 108 if direction == 0 else 120,
                    "current_high_q16": 120 if direction == 0 else 130,
                    "conservative_low_q16": 108 if direction == 0 else 120,
                    "conservative_high_q16": 116,
                    "nonempty": 1 if direction == 0 else 0,
                },
            )
        )
    for direction in range(2):
        fragments.append(
            (
                "handle_stage_b_reproduction_v4_coverage",
                {
                    **common,
                    "direction": direction,
                    "coverage": direction,
                    "signed_rung_distance": direction,
                    "gain_ratio_num": 1 if direction == 0 else 1448,
                    "gain_ratio_den": 1 if direction == 0 else 1024,
                },
            )
        )
    fragments.append(
        (
            "handle_stage_b_reproduction_v4_digest",
            {
                **common,
                "previous_digest_low": previous_digest & 0xFFFF_FFFF,
                "previous_digest_high": previous_digest >> 32,
                "current_digest_low": current_digest & 0xFFFF_FFFF,
                "current_digest_high": current_digest >> 32,
            },
        )
    )
    return fragments


def feed_stage_b_reproduction(assembler, **kwargs):
    for method, params in stage_b_reproduction_v4_fragments(**kwargs):
        getattr(assembler, method)(params)


def feed_stage_b_terminal(
    assembler,
    *,
    sequence=4,
    outcome=0,
    cause=0,
    member_mask=0b11100,
    nominated_p=724,
    intervals=((104, 116), (104, 116)),
    digest=0,
    plan_digest_value=0,
    recovery_unavailable=0,
):
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": sequence}
    assembler.handle_stage_b_terminal_core(
        {
            **common,
            "fragment": 0,
            "outcome": outcome,
            "cause": cause,
            "recovery_unavailable": recovery_unavailable,
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
        pooled_low_q16, pooled_high_q16 = intervals[direction]
        assembler.handle_stage_b_terminal_interval(
            {
                **common,
                "fragment": direction + 2,
                "direction": direction,
                "pooled_low_q16": pooled_low_q16,
                "pooled_high_q16": pooled_high_q16,
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


def feed_current(assembler, *, sequence, slot, capability=0, contact=0):
    assembler.handle_current_evidence(
        {
            "oid": 0,
            "run_sequence": 7,
            "evidence_sequence": sequence,
            "stage": 0,
            "rung_index": 0,
            "slot": slot,
            "clamp_limit": 900,
            "clamp_readback": 900,
            "moving_pid_output_peak": 200,
            "zero_pid_output_peak": 300,
            "moving_status_flags": 0,
            "zero_status_flags": 0,
            "capability": capability,
            "contact": contact,
        }
    )


def test_stage_b_current_evidence_is_retained_after_its_observation():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    feed_observation(assembler, sequence=1, slot=0, low=100, high=110)

    feed_current(assembler, sequence=2, slot=0, capability=0, contact=2)

    assert assembler.current_evidence[(0, 0)]["contact"] == 2


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
    digest = OPAQUE_DIGEST if digest is None else digest
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
    limits, geometry, timing, recovery = plan_fragments()
    limits["#name"] = "foci_velocity_sweep_plan_limits"
    geometry["#name"] = "foci_velocity_sweep_plan_geometry"
    timing["#name"] = "foci_velocity_sweep_plan_timing"
    limits["#receive_time"] = 1.0
    geometry["#receive_time"] = 2.0
    timing["#receive_time"] = 3.0

    assembler.handle_plan_limits(limits)
    assembler.handle_plan_geometry(geometry)
    assembler.handle_plan_timing(timing)
    recovery["#name"] = "foci_velocity_sweep_plan_recovery"
    assembler.handle_plan_recovery(recovery)

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


def test_stage_b_handoff_preserves_union_and_selected_component_separately():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    feed_stage_b_region(assembler, sequence=1, direction=0)
    feed_stage_b_region(assembler, sequence=2, direction=1)
    for sequence, member_mask, bounds in (
        (3, 0b00011, 0 | (1 << 8)),
        (4, 0b11100, 2 | (4 << 8)),
    ):
        assembler.handle_joint_region(
            {
                "oid": 0,
                "run_sequence": 7,
                "evidence_sequence": sequence,
                "member_mask": member_mask,
                "rung_bounds": bounds,
                "member_count": member_mask.bit_count(),
                "p_low": 256,
                "p_high": 1024,
                "closure": 1,
            }
        )
    feed_stage_b_handoff(
        assembler,
        sequence=5,
        member_mask=0b11100,
        joint_union_mask=0b11111,
    )

    assert assembler.handoff["joint_union_mask"] == 0b11111
    assert assembler.handoff["selected_joint_mask"] == 0b11100
    assert assembler.handoff["directions"][0]["region_class"] == 1


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


def test_stage_b_terminal_checks_selected_records_and_retains_digest():
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

    feed_stage_b_terminal(
        assembler,
        sequence=5,
        digest=OPAQUE_DIGEST,
        plan_digest_value=plan_identity,
    )

    assert assembler.done
    assert assembler.outcome == "complete_candidate"
    assert assembler.terminal["nominated_p"] == 724
    assert assembler.terminal["digest"] == OPAQUE_DIGEST


def test_stage_b_terminal_retains_opaque_firmware_digest():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    opaque_digest = OPAQUE_DIGEST

    feed_stage_b_terminal(
        assembler,
        sequence=1,
        outcome=2,
        cause=1,
        member_mask=0,
        nominated_p=0,
        digest=opaque_digest,
        plan_digest_value=123,
    )

    assert assembler.terminal["digest"] == opaque_digest


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
    pre_reproduction_digest = 0x0102_0304_0506_0708
    feed_stage_b_reproduction(
        assembler,
        sequence=5,
        current_digest=pre_reproduction_digest,
    )

    feed_stage_b_terminal(
        assembler,
        sequence=6,
        outcome=1,
        member_mask=0x0038_0000,
        nominated_p=1448,
        intervals=((108, 116), (108, 116)),
        digest=OPAQUE_DIGEST,
        plan_digest_value=plan_identity,
    )

    assert assembler.outcome == "complete"
    assert assembler.reproduction["current_digest"] == pre_reproduction_digest
    assert assembler.reproduction["schema_revision"] == 8
    assert assembler.reproduction["memberships"][0] == {
        "previous": 0x0038_0000,
        "current": 0x003C_0000,
        "core": 0x0038_0000,
        "previous_only": 0,
        "current_only": 0x0004_0000,
        "low_delta": -1,
        "high_delta": 0,
    }
    assert assembler.reproduction["final_p"] == 1448
    assert assembler.reproduction["common"][1]["nonempty"] is False


def test_stage_b_complete_terminal_uses_reproduced_pooled_overlap():
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
    pre_reproduction_digest = 0x0102_0304_0506_0708
    feed_stage_b_reproduction(
        assembler,
        sequence=5,
        member_mask=0b11100,
        final_p=724,
        current_digest=pre_reproduction_digest,
    )
    feed_stage_b_terminal(
        assembler,
        sequence=6,
        outcome=1,
        member_mask=0b11100,
        nominated_p=724,
        intervals=((108, 116), (108, 116)),
        digest=OPAQUE_DIGEST,
        plan_digest_value=plan_identity,
    )

    assert assembler.outcome == "complete"
    assert assembler.terminal["selected_intervals"] == ((108, 116), (108, 116))


def test_stage_b_reproduction_v4_rejects_missing_duplicate_and_reordered_parts():
    fragments = stage_b_reproduction_v4_fragments(sequence=1)

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    getattr(assembler, fragments[0][0])(fragments[0][1])
    with pytest.raises(VelocitySweepProtocolError, match="reordered"):
        getattr(assembler, fragments[-1][0])(fragments[-1][1])

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    for method, params in fragments[:2]:
        getattr(assembler, method)(params)
    with pytest.raises(VelocitySweepProtocolError, match="reordered"):
        getattr(assembler, fragments[1][0])(fragments[1][1])

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    getattr(assembler, fragments[0][0])(fragments[0][1])
    with pytest.raises(VelocitySweepProtocolError, match="reordered"):
        getattr(assembler, fragments[2][0])(fragments[2][1])


def test_stage_b_reproduction_v4_rejects_identity_schema_and_early_terminal():
    fragments = stage_b_reproduction_v4_fragments(sequence=1)

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    getattr(assembler, fragments[0][0])(fragments[0][1])
    changed_identity = dict(fragments[1][1], evidence_sequence=2)
    with pytest.raises(VelocitySweepProtocolError, match="evidence sequence"):
        getattr(assembler, fragments[1][0])(changed_identity)

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    unknown_schema = dict(fragments[0][1], schema_revision=3)
    with pytest.raises(VelocitySweepProtocolError, match="unsupported"):
        getattr(assembler, fragments[0][0])(unknown_schema)

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    for method, params in fragments[:-1]:
        getattr(assembler, method)(params)
    with pytest.raises(VelocitySweepProtocolError, match="interrupted"):
        feed_stage_b_terminal(assembler, sequence=2)


def test_schema_eight_is_required():
    fragments = stage_b_reproduction_v4_fragments(sequence=1)

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    schema_eight = dict(fragments[0][1], schema_revision=8)
    assembler.handle_stage_b_reproduction_v4_core(schema_eight)

    rejected = VelocitySweepAssembler()
    feed_plan(rejected)
    schema_seven = dict(fragments[0][1], schema_revision=7)
    with pytest.raises(VelocitySweepProtocolError, match="unsupported"):
        rejected.handle_stage_b_reproduction_v4_core(schema_seven)


def test_stage_b_reproduction_v4_preserves_firmware_values_without_correction():
    fragments = stage_b_reproduction_v4_fragments(
        sequence=1,
        member_mask=0x003C_0000,
        selected_joint_mask=0x0018_0000,
        final_p=1024,
        selected_first_rung=19,
        selected_member_count=2,
        forward_validity=2,
        reverse_validity=1,
        reduced_margin=1,
    )
    fragments[0][1]["outcome"] = 2
    fragments[1][1]["core_mask"] = 0x0010_0000

    assembler = VelocitySweepAssembler()
    feed_plan(assembler)
    for method, params in fragments:
        getattr(assembler, method)(params)

    assert assembler.reproduction["outcome"] == 2
    assert assembler.reproduction["memberships"][0]["core"] == 0x0010_0000
    assert assembler.reproduction["selected_joint_mask"] == 0x0018_0000
    assert assembler.reproduction["selected_first_rung"] == 19
    assert assembler.reproduction["selected_member_count"] == 2
    assert assembler.reproduction["final_p"] == 1024
    assert assembler.reproduction["forward_validity"] == 2
    assert assembler.reproduction["reverse_validity"] == 1
    assert assembler.reproduction["reduced_margin"] == 1


def test_reordered_or_duplicate_fragment_is_rejected():
    limits, geometry, _timing, _recovery = plan_fragments()
    assembler = VelocitySweepAssembler()

    with pytest.raises(VelocitySweepProtocolError, match="fragment"):
        assembler.handle_plan_geometry(geometry)

    assembler = VelocitySweepAssembler()
    assembler.handle_plan_limits(limits)
    with pytest.raises(VelocitySweepProtocolError, match="fragment"):
        assembler.handle_plan_limits(limits)


def test_complete_terminal_checks_counts_and_retains_digest():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    forward, reverse, integrity = terminal_fragments()

    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)
    assembler.handle_terminal_integrity(integrity)

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.sufficient_direction_mask == 3


def test_legacy_terminal_retains_opaque_firmware_digest():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=0)
    opaque_digest = OPAQUE_DIGEST
    forward, reverse, integrity = terminal_fragments(digest=opaque_digest)
    assembler.handle_terminal_direction(forward)
    assembler.handle_terminal_direction(reverse)

    assembler.handle_terminal_integrity(integrity)

    assert assembler.integrity["digest"] == opaque_digest


def test_compressed_observation_fields_are_retained_exactly():
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

    assert assembler.observations[(0, 0)]["delta_mantissa"] == 2_147_483_649
    assert assembler.observations[(0, 0)]["disturbance_q16"] == 123_456


def consensus_core(*, sequence, forward_class=0, reverse_class=0):
    component_counts = {0: 1, 1: 2, 2: 0, 3: 0}
    return {
        "oid": 0,
        "run_sequence": 7,
        "evidence_sequence": sequence,
        "fragment": 0,
        "rung_index": 0,
        "velocity_p": 16,
        "forward_class": forward_class,
        "reverse_class": reverse_class,
        "forward_collected_mask": 0b1111,
        "reverse_collected_mask": 0b1111,
        "forward_eligible_mask": 0b1111,
        "reverse_eligible_mask": 0b1111,
        "forward_included_mask": 0b0111 if forward_class == 0 else 0,
        "reverse_included_mask": 0b1110 if reverse_class == 0 else 0,
        "forward_component_count": component_counts[forward_class],
        "reverse_component_count": component_counts[reverse_class],
        "forward_operable_count": 4,
        "reverse_operable_count": 3,
        "flags": 0b11,
    }


def consensus_component(*, sequence, direction, component_index, low, high):
    return {
        "oid": 0,
        "run_sequence": 7,
        "evidence_sequence": sequence,
        "fragment": 1 + direction * 2 + component_index,
        "rung_index": 0,
        "direction": direction,
        "component_index": component_index,
        "low_q16": low,
        "high_q16": high,
    }


def consensus_pool(*, sequence, direction):
    return {
        "oid": 0,
        "run_sequence": 7,
        "evidence_sequence": sequence,
        "fragment": 5 + direction,
        "rung_index": 0,
        "direction": direction,
        "pooled_q16": 150 if direction == 0 else -150,
        "pooled_low_q16": 140 if direction == 0 else -160,
        "pooled_high_q16": 160 if direction == 0 else -140,
        "variance_floor_observations": 0,
        "mean_min_mantissa": 1,
        "mean_max_mantissa": 2,
        "envelope_low_mantissa": 0,
        "envelope_high_mantissa": 3,
        "rate_shift": 0,
    }


def feed_eight_observations(assembler):
    for slot in range(8):
        sign = 1 if slot % 2 == 0 else -1
        feed_observation(
            assembler,
            sequence=slot + 1,
            slot=slot,
            low=sign * 100 if sign > 0 else sign * 200,
            high=sign * 200 if sign > 0 else sign * 100,
        )


def test_eight_observations_preserve_firmware_consensus_group():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1, observations_per_direction=4)
    feed_eight_observations(assembler)
    sequence = 9
    assembler.handle_rung_consensus_core(consensus_core(sequence=sequence))
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=sequence, direction=0, component_index=0, low=145, high=155
        )
    )
    assembler.handle_rung_consensus_pool(consensus_pool(sequence=sequence, direction=0))
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=sequence, direction=1, component_index=0, low=-155, high=-145
        )
    )
    assembler.handle_rung_consensus_pool(consensus_pool(sequence=sequence, direction=1))

    assert sorted(assembler.observations) == [(0, slot) for slot in range(8)]
    assert assembler.rungs[0]["forward_included_mask"] == 0b0111
    assert assembler.rungs[0]["reverse_operable_count"] == 3
    assert assembler.rungs[0]["components"][0] == [(145, 155)]


def stage_b_recovery_assembler():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1, observations_per_direction=4)
    feed_eight_observations(assembler)
    sequence = 9
    assembler.handle_rung_consensus_core(consensus_core(sequence=sequence))
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=sequence, direction=0, component_index=0, low=145, high=155
        )
    )
    assembler.handle_rung_consensus_pool(consensus_pool(sequence=sequence, direction=0))
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=sequence, direction=1, component_index=0, low=-155, high=-145
        )
    )
    assembler.handle_rung_consensus_pool(consensus_pool(sequence=sequence, direction=1))
    return assembler


def test_stage_b_recovery_summary_is_causal_and_compact():
    assembler = stage_b_recovery_assembler()
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 10}
    summary = {
        **common,
        "stage": 0,
        "rung_index": 0,
        "p_raw": 16,
        "binding_source": 5,
        "outcome": 1,
    }
    assembler.handle_recovery_summary(summary)

    assert assembler.recoveries[0] == {
        "run_sequence": 7,
        "evidence_sequence": 10,
        "stage": 0,
        "rung_index": 0,
        "p_raw": 16,
        "binding_source": 5,
        "outcome": 1,
    }
    with pytest.raises(VelocitySweepProtocolError, match="duplicate"):
        assembler.handle_recovery_summary(summary)


@pytest.mark.parametrize(
    ("replacement", "message"),
    (
        ({"stage": 1}, "wrong stage"),
        ({"run_sequence": 8}, "run sequence"),
        ({"evidence_sequence": 11}, "sequence gap"),
        ({"rung_index": 1}, "immediately follow"),
        ({"p_raw": 17}, "rung gain"),
    ),
)
def test_stage_b_recovery_summary_rejects_changed_identity(replacement, message):
    assembler = stage_b_recovery_assembler()
    params = {
        "oid": 0,
        "run_sequence": 7,
        "evidence_sequence": 10,
        "stage": 0,
        "rung_index": 0,
        "p_raw": 16,
        "binding_source": 0,
        "outcome": 0,
        **replacement,
    }

    with pytest.raises(VelocitySweepProtocolError, match=message):
        assembler.handle_recovery_summary(params)


def recovery_cardinality_assembler(recovered_rungs):
    assembler = VelocitySweepAssembler()
    assembler.plan = {
        "observations_per_direction": 4,
        "recovery_slot_count": 2,
    }
    assembler.rungs = {0: {}, 1: {}}
    assembler.observations = {
        (rung_index, slot): {} for rung_index in range(2) for slot in range(8)
    }
    assembler.recoveries = {rung_index: {} for rung_index in recovered_rungs}
    assembler._last_evidence = ("rung", 1)
    return assembler


def test_schema_six_current_headroom_allows_only_missing_final_recovery():
    assembler = recovery_cardinality_assembler({0})

    assembler._validate_recovery_completeness({"cause": 4, "recovery_unavailable": 1})


def test_reproduced_current_headroom_allows_only_missing_final_recovery():
    assembler = recovery_cardinality_assembler({0})

    assembler._validate_recovery_completeness({"cause": 0, "recovery_unavailable": 1})


def test_schema_six_ordinary_end_requires_every_complete_rung_recovery():
    assembler = recovery_cardinality_assembler({0})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired"):
        assembler._validate_recovery_completeness(
            {"cause": 0, "recovery_unavailable": 0}
        )


def test_schema_six_current_headroom_rejects_missing_nonterminal_recovery():
    assembler = recovery_cardinality_assembler({1})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired"):
        assembler._validate_recovery_completeness(
            {"cause": 4, "recovery_unavailable": 1}
        )


def test_schema_six_missing_final_recovery_requires_terminal_annotation():
    assembler = recovery_cardinality_assembler({0})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired"):
        assembler._validate_recovery_completeness(
            {"cause": 4, "recovery_unavailable": 0}
        )


def test_structured_recovery_source_is_preserved():
    assembler = stage_b_recovery_assembler()
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 10}
    assembler.handle_recovery_summary(
        {
            **common,
            "stage": 0,
            "rung_index": 0,
            "p_raw": 16,
            "binding_source": 5,
            "outcome": 0,
        }
    )

    assert assembler.recoveries[0]["binding_source"] == 5


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
        digest=OPAQUE_DIGEST,
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
        digest=OPAQUE_DIGEST,
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


def test_host_does_not_recompute_a_structurally_valid_firmware_consensus():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1, observations_per_direction=4)
    feed_eight_observations(assembler)
    sequence = 9
    assembler.handle_rung_consensus_core(consensus_core(sequence=sequence))
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=sequence, direction=0, component_index=0, low=300, high=400
        )
    )
    assembler.handle_rung_consensus_pool(consensus_pool(sequence=sequence, direction=0))
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=sequence, direction=1, component_index=0, low=-400, high=-300
        )
    )
    assembler.handle_rung_consensus_pool(consensus_pool(sequence=sequence, direction=1))

    assert assembler.rungs[0]["components"] == [[(300, 400)], [(-400, -300)]]


def test_ambiguous_and_incomplete_groups_preserve_firmware_classes():
    ambiguous = VelocitySweepAssembler()
    feed_plan(ambiguous, rung_count=1, observations_per_direction=4)
    feed_eight_observations(ambiguous)
    core = consensus_core(sequence=9, forward_class=1, reverse_class=3)
    ambiguous.handle_rung_consensus_core(core)
    for component_index, bounds in enumerate(((100, 120), (200, 220))):
        ambiguous.handle_rung_consensus_component(
            consensus_component(
                sequence=9,
                direction=0,
                component_index=component_index,
                low=bounds[0],
                high=bounds[1],
            )
        )
    assert ambiguous.rungs[0]["forward_class"] == 1
    assert ambiguous.rungs[0]["components"][0] == [(100, 120), (200, 220)]

    incomplete = VelocitySweepAssembler()
    feed_plan(incomplete, rung_count=1, observations_per_direction=4)
    feed_eight_observations(incomplete)
    core = consensus_core(sequence=9, forward_class=3, reverse_class=3)
    core["forward_collected_mask"] = 0b0111
    core["reverse_collected_mask"] = 0b0111
    core["forward_eligible_mask"] = 0b0111
    core["reverse_eligible_mask"] = 0b0111
    incomplete.observations.pop((0, 6))
    incomplete.observations.pop((0, 7))
    incomplete.handle_rung_consensus_core(core)
    assert incomplete.rungs[0]["forward_class"] == 3
    assert incomplete.rungs[0]["components"] == [[], []]


def test_consensus_group_rejects_missing_duplicate_and_misidentified_parts():
    assembler = VelocitySweepAssembler()
    feed_plan(assembler, rung_count=1, observations_per_direction=4)
    feed_eight_observations(assembler)
    assembler.handle_rung_consensus_core(consensus_core(sequence=9))
    forward = consensus_component(
        sequence=9, direction=0, component_index=0, low=100, high=200
    )
    assembler.handle_rung_consensus_component(forward)
    with pytest.raises(VelocitySweepProtocolError, match="duplicate"):
        assembler.handle_rung_consensus_component(forward)
    forward_pool = consensus_pool(sequence=9, direction=0)
    assembler.handle_rung_consensus_pool(forward_pool)
    with pytest.raises(VelocitySweepProtocolError, match="duplicate"):
        assembler.handle_rung_consensus_pool(forward_pool)
    assembler.handle_rung_consensus_component(
        consensus_component(
            sequence=9, direction=1, component_index=0, low=-200, high=-100
        )
    )

    wrong = VelocitySweepAssembler()
    feed_plan(wrong, rung_count=1, observations_per_direction=4)
    feed_eight_observations(wrong)
    wrong.handle_rung_consensus_core(consensus_core(sequence=9))
    component = consensus_component(
        sequence=9, direction=0, component_index=0, low=100, high=200
    )
    component["fragment"] = 2
    with pytest.raises(VelocitySweepProtocolError, match="identity"):
        wrong.handle_rung_consensus_component(component)

    missing = VelocitySweepAssembler()
    feed_plan(missing, rung_count=1, observations_per_direction=4)
    feed_eight_observations(missing)
    missing.handle_rung_consensus_core(consensus_core(sequence=9))
    with pytest.raises(VelocitySweepProtocolError, match="fragment|interrupted"):
        missing.handle_plan_limits(plan_fragments(1, 4)[0])


def test_consensus_core_rejects_invalid_masks_gain_and_observation_order():
    masks = VelocitySweepAssembler()
    feed_plan(masks, rung_count=1, observations_per_direction=4)
    feed_eight_observations(masks)
    core = consensus_core(sequence=9)
    core["forward_included_mask"] = 0b1_0000
    with pytest.raises(VelocitySweepProtocolError, match="mask"):
        masks.handle_rung_consensus_core(core)

    gain = VelocitySweepAssembler()
    feed_plan(gain, rung_count=1, observations_per_direction=4)
    feed_eight_observations(gain)
    core = consensus_core(sequence=9)
    core["velocity_p"] = 17
    with pytest.raises(VelocitySweepProtocolError, match="gain"):
        gain.handle_rung_consensus_core(core)

    early = VelocitySweepAssembler()
    feed_plan(early, rung_count=1, observations_per_direction=4)
    core = consensus_core(sequence=1)
    with pytest.raises(VelocitySweepProtocolError, match="before"):
        early.handle_rung_consensus_core(core)


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
            "digest_low": OPAQUE_DIGEST & 0xFFFF_FFFF,
            "digest_high": OPAQUE_DIGEST >> 32,
        }
    )

    assert assembler.done
    assert assembler.outcome == "inconclusive"
    assert "one direction" in assembler.remediation
