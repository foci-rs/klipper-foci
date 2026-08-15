"""Velocity-sweep stream reassembly and integrity tests."""

import pytest
from klipper_foci.velocity_sweep import (
    VelocitySweepAssembler,
    VelocitySweepProtocolError,
)


def feed_stage_b_terminal(
    assembler,
    *,
    sequence=4,
    outcome=0,
    cause=0,
    member_mask=0b11100,
    joint_member_mask=None,
    nominated_p=724,
    intervals=((104, 116), (104, 116)),
    digest=0,
    plan_digest_value=0,
    recovery_unavailable=0,
    expected_observations=0,
    emitted_observations=0,
    expected_rungs=0,
    emitted_rungs=0,
):
    if joint_member_mask is None:
        joint_member_mask = member_mask
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
            "expected_observations": expected_observations,
            "emitted_observations": emitted_observations,
            "expected_rungs": expected_rungs,
            "emitted_rungs": emitted_rungs,
        }
    )
    assembler.handle_stage_b_terminal_identity(
        {
            **common,
            "fragment": 1,
            "forward_member_mask": member_mask,
            "reverse_member_mask": member_mask,
            "joint_member_mask": joint_member_mask,
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


def test_stage_b_assembler_has_no_host_evidence_authority():
    assembler = VelocitySweepAssembler()

    assert not hasattr(assembler, "segment_regions")
    assert not hasattr(assembler, "choose_p")


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


def test_stage_b_terminal_ignores_klipper_reply_name_metadata():
    """The shared merge strips Klipper reply metadata from the terminal record."""
    assembler = VelocitySweepAssembler()
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 0}
    assembler.handle_stage_b_terminal_core(
        {
            **common,
            "#name": "foci_velocity_stage_b_terminal_core",
            "#receive_time": 1.0,
            "fragment": 0,
            "outcome": 4,
            "cause": 6,
            "recovery_unavailable": 0,
            "model_direction_mask": 0,
            "coverage_mask": 0,
            "forward_region_count": 0,
            "reverse_region_count": 0,
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
            "#name": "foci_velocity_stage_b_terminal_identity",
            "#receive_time": 2.0,
            "fragment": 1,
            "forward_member_mask": 0,
            "reverse_member_mask": 0,
            "joint_member_mask": 0,
            "nominated_p": 0,
            "plan_digest_low": 123,
            "plan_digest_high": 0,
            "digest_low": 0,
            "digest_high": 0,
        }
    )
    for direction in range(2):
        assembler.handle_stage_b_terminal_interval(
            {
                **common,
                "fragment": direction + 2,
                "direction": direction,
                "pooled_low_q16": 0,
                "pooled_high_q16": 0,
                "started_low": 10,
                "started_high": 0,
                "completed_low": 20,
                "completed_high": 0,
            }
        )

    assert assembler.done
    assert assembler.outcome == "rejected_plan_mismatch"
    assert assembler.terminal["plan_digest"] == 123
    assert "#name" not in assembler.terminal
    assert "#receive_time" not in assembler.terminal


def test_reordered_or_duplicate_fragment_is_rejected():
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 0}

    identity_first = VelocitySweepAssembler()
    with pytest.raises(VelocitySweepProtocolError, match="fragment"):
        identity_first.handle_stage_b_terminal_identity({**common, "fragment": 1})

    duplicate_core = VelocitySweepAssembler()
    duplicate_core.handle_stage_b_terminal_core({**common, "fragment": 0})
    with pytest.raises(VelocitySweepProtocolError, match="fragment"):
        duplicate_core.handle_stage_b_terminal_core({**common, "fragment": 0})


def stage_b_recovery_assembler():
    """Assemble the minimal state a Stage-B recovery summary is validated against.

    The recovery summary follows exactly one causal rung; its acquisition path
    (plan, observations, consensus) has been removed from the wire, so the tests
    seed the rung/cursor state directly instead of replaying dead evidence.
    """
    assembler = VelocitySweepAssembler()
    assembler.plan = {"observations_per_direction": 4, "recovery_slot_count": 2}
    assembler.rungs = {0: {"velocity_p": 16}}
    assembler._run_sequence = 7
    assembler._next_evidence_sequence = 18
    assembler._last_evidence = ("rung", 0)
    return assembler


def test_stage_b_recovery_summary_is_causal_and_compact():
    assembler = stage_b_recovery_assembler()
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 18}
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
        "evidence_sequence": 18,
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
        ({"evidence_sequence": 19}, "sequence gap"),
        ({"rung_index": 1}, "immediately follow"),
        ({"p_raw": 17}, "rung gain"),
    ),
)
def test_stage_b_recovery_summary_rejects_changed_identity(replacement, message):
    assembler = stage_b_recovery_assembler()
    params = {
        "oid": 0,
        "run_sequence": 7,
        "evidence_sequence": 18,
        "stage": 0,
        "rung_index": 0,
        "p_raw": 16,
        "binding_source": 0,
        "outcome": 0,
        **replacement,
    }

    with pytest.raises(VelocitySweepProtocolError, match=message):
        assembler.handle_recovery_summary(params)


def test_structured_recovery_source_is_preserved():
    assembler = stage_b_recovery_assembler()
    common = {"oid": 0, "run_sequence": 7, "evidence_sequence": 18}
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


def recovery_cardinality_assembler(recovered_rungs, *, last_evidence=("rung", 1)):
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
    assembler._last_evidence = last_evidence
    return assembler


def test_stage_b_fault_accepts_one_missing_final_recovery():
    assembler = recovery_cardinality_assembler({0})

    assembler._validate_recovery_completeness({"outcome": 3})


def test_stage_b_non_fault_rejects_one_missing_final_recovery():
    assembler = recovery_cardinality_assembler({0})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired rungs"):
        assembler._validate_recovery_completeness({"outcome": 2})


def test_stage_b_fault_rejects_two_missing_recovery_records():
    assembler = recovery_cardinality_assembler(set())

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired rungs"):
        assembler._validate_recovery_completeness({"outcome": 3})


def test_stage_b_fault_rejects_missing_intermediate_recovery():
    assembler = recovery_cardinality_assembler({1}, last_evidence=("recovery", 1))

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired rungs"):
        assembler._validate_recovery_completeness({"outcome": 3})


def test_schema_six_current_headroom_allows_only_missing_final_recovery():
    assembler = recovery_cardinality_assembler({0})

    assembler._validate_recovery_completeness({"cause": 4, "recovery_unavailable": 1})


def test_reproduced_current_headroom_allows_only_missing_final_recovery():
    assembler = recovery_cardinality_assembler({0})

    assembler._validate_recovery_completeness({"cause": 0, "recovery_unavailable": 1})


def test_schema_six_ordinary_end_requires_every_complete_rung_recovery():
    assembler = recovery_cardinality_assembler({0})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired"):
        assembler._validate_recovery_completeness({"cause": 0, "recovery_unavailable": 0})


def test_schema_six_current_headroom_rejects_missing_nonterminal_recovery():
    assembler = recovery_cardinality_assembler({1})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired"):
        assembler._validate_recovery_completeness({"cause": 4, "recovery_unavailable": 1})


def test_schema_six_missing_final_recovery_requires_terminal_annotation():
    assembler = recovery_cardinality_assembler({0})

    with pytest.raises(VelocitySweepProtocolError, match="fully acquired"):
        assembler._validate_recovery_completeness({"cause": 4, "recovery_unavailable": 0})


def test_breakaway_workflow_shape_is_accepted_but_stays_inert():
    """Shape 6 (the breakaway campaign) never emits Stage-B sweep evidence.

    BreakawayCampaignAssembler (velocity_integral.py) relays the campaign's
    own probe/discovery/confirmation evidence; this assembler only needs to
    accept the shared command-level workflow shape without raising, exactly
    as it already does for shape 2 (Stage-C resume).
    """
    assembler = VelocitySweepAssembler()

    assembler.configure_workflow_shape(6, 400_000, 400_000)

    assert assembler.plan is None
    assert assembler.done is False
