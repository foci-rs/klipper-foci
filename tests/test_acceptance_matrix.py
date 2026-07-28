"""Strict relay tests for fixed-I velocity confidence matrices."""

import struct

import pytest

from klipper_foci.acceptance_matrix import (
    AcceptanceMatrixAssembler,
    AcceptanceMatrixProtocolError,
    parse_autotune_action,
)
from klipper_foci.registers import REGISTERS
from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    SAMPLE_ACTIVE_GAINS,
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


def workflow(assembler, shape=4):
    params = {
        "oid": 1,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": 60_541,
        "maximum_workflow_ms": 66_456,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(
        params
    )
    assembler.handle_workflow_plan(params)


def plan_payload(order=1, targets=TARGETS, schema=2, recovery_bounds=RECOVERY_BOUNDS):
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
        60_541,
        66_456,
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
    schema=2,
):
    return struct.pack(
        "<HIBBQQ8sHBH",
        schema,
        RUN_SEQUENCE,
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
        (None, 0),
        ("combined", 0),
        ("matrix_ascending", 1),
        ("matrix_descending", 2),
    ),
)
def test_action_mapping_is_selector_only(value, expected):
    assert parse_autotune_action(value) == expected


def test_unknown_action_is_rejected():
    with pytest.raises(AcceptanceMatrixProtocolError, match="unknown ACTION"):
        parse_autotune_action("pick_p_1024")


def test_unknown_action_rejects_before_any_mcu_command():
    driver = ready_driver()
    with pytest.raises(CommandError, match="unknown ACTION"):
        driver.autotune.autotune(MockGCmd({"ACTION": "pick_p_1024"}))
    assert driver.protocol.commands.tune.last_args is None


def test_only_compact_matrix_replies_are_registered():
    driver = make_driver()
    registrations = {
        name
        for _callback, name, oid in driver.mcu._serial.responses
        if oid == driver.oid and "acceptance_matrix" in name
    }
    assert registrations == {
        "foci_acceptance_matrix_plan",
        "foci_acceptance_matrix_terminal",
    }


@pytest.mark.parametrize(("shape", "order"), ((4, 1), (5, 2)))
def test_exact_plan_and_terminal_close_one_matrix(shape, order):
    assembler = AcceptanceMatrixAssembler()
    workflow(assembler, shape)
    targets = TARGETS if order == 1 else tuple(reversed(TARGETS))
    assembler.handle_plan({"oid": 1, "payload": plan_payload(order, targets)})
    assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})

    assert assembler.done
    assert assembler.outcome == "complete"
    assert assembler.plan["targets_rpm"] == targets
    assert assembler.plan["recovery_lower_rate_q"] == RECOVERY_BOUNDS
    assert assembler.terminal["eligible_masks"] == (0x1F, 0x1F)


def test_historical_schema_one_plan_and_terminal_remain_decodable():
    assembler = AcceptanceMatrixAssembler()
    workflow(assembler)

    assembler.handle_plan({"oid": 1, "payload": plan_payload(schema=1)})
    assembler.handle_terminal({"oid": 1, "payload": terminal_payload(schema=1)})

    assert assembler.done
    assert assembler.plan["schema_revision"] == 1
    assert assembler.plan["recovery_lower_rate_q"] is None


def test_schema_two_requires_exact_nonzero_recovery_bounds_and_matching_terminal():
    invalid_payloads = [
        bytearray(plan_payload(schema=1)),
        plan_payload(recovery_bounds=(0, RECOVERY_BOUNDS[1])),
        plan_payload(recovery_bounds=(RECOVERY_BOUNDS[0], 0)),
    ]
    invalid_payloads[0][0:2] = (2).to_bytes(2, "little")

    for payload in invalid_payloads:
        assembler = AcceptanceMatrixAssembler()
        workflow(assembler)
        with pytest.raises(AcceptanceMatrixProtocolError):
            assembler.handle_plan({"oid": 1, "payload": bytes(payload)})

    assembler = AcceptanceMatrixAssembler()
    workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload()})
    with pytest.raises(AcceptanceMatrixProtocolError, match="schema"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload(schema=1)})


@pytest.mark.parametrize(
    ("shape", "nominal", "maximum"),
    (
        (3, 60_541, 66_456),
        (4, 60_540, 66_456),
        (4, 60_541, 66_455),
        (5, 60_541, 496_528),
    ),
)
def test_matrix_workflow_rejects_wrong_shapes_and_mixed_durations(
    shape, nominal, maximum
):
    assembler = AcceptanceMatrixAssembler()
    params = {
        "oid": 1,
        "run_sequence": RUN_SEQUENCE,
        "shape": shape,
        "nominal_workflow_ms": nominal,
        "maximum_workflow_ms": maximum,
    }
    params["digest_low"], params["digest_high"] = assembler.workflow_digest_halves(
        params
    )
    with pytest.raises(AcceptanceMatrixProtocolError):
        assembler.handle_workflow_plan(params)


def test_plan_rejects_wrong_order_target_geometry_and_counts():
    cases = (
        plan_payload(order=2),
        plan_payload(targets=(16, 33, 66, 132, 132)),
        bytearray(plan_payload()),
    )
    cases[2][40:42] = (19).to_bytes(2, "little")
    for payload in cases:
        assembler = AcceptanceMatrixAssembler()
        workflow(assembler)
        with pytest.raises(AcceptanceMatrixProtocolError):
            assembler.handle_plan({"oid": 1, "payload": bytes(payload)})


def test_terminal_rejects_duplicates_digest_mismatch_and_invalid_masks():
    assembler = AcceptanceMatrixAssembler()
    workflow(assembler)
    assembler.handle_plan({"oid": 1, "payload": plan_payload()})
    assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})
    with pytest.raises(AcceptanceMatrixProtocolError, match="duplicate terminal"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})

    for payload in (
        terminal_payload(plan_digest=PLAN_DIGEST + 1),
        terminal_payload(eligible=(0x20, 0)),
        terminal_payload(outcome=3, cause=0),
    ):
        candidate = AcceptanceMatrixAssembler()
        workflow(candidate)
        candidate.handle_plan({"oid": 1, "payload": plan_payload()})
        with pytest.raises(AcceptanceMatrixProtocolError):
            candidate.handle_terminal({"oid": 1, "payload": payload})


def test_terminal_requires_complete_plan():
    assembler = AcceptanceMatrixAssembler()
    workflow(assembler)
    with pytest.raises(AcceptanceMatrixProtocolError, match="before plan"):
        assembler.handle_terminal({"oid": 1, "payload": terminal_payload()})


@pytest.mark.parametrize("cause", (3, 4, 5))
def test_pre_motion_failed_terminal_is_complete_without_plan(cause):
    assembler = AcceptanceMatrixAssembler()
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
            ),
        }
    )
    assert assembler.done
    assert assembler.outcome == "failed"


def test_autotune_relays_one_complete_matrix_without_host_decisions():
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def finish_matrix(deadline):
        reactor._time = deadline
        params = {
            "oid": driver.oid,
            "run_sequence": RUN_SEQUENCE,
            "shape": 4,
            "nominal_workflow_ms": 60_541,
            "maximum_workflow_ms": 66_456,
        }
        params["digest_low"], params["digest_high"] = (
            driver.autotune.acceptance_matrix.workflow_digest_halves(params)
        )
        driver.autotune.handle_commissioning_workflow_plan(params)
        driver.autotune.handle_acceptance_matrix_plan(
            {"oid": driver.oid, "payload": plan_payload()}
        )
        driver.autotune.handle_acceptance_matrix_terminal(
            {"oid": driver.oid, "payload": terminal_payload()}
        )
        return reactor._time

    reactor.pause = finish_matrix
    gcmd = MockGCmd({"ACTION": "matrix_ascending"})
    driver.autotune.autotune(gcmd)

    assert driver.protocol.commands.tune.last_args[1] == 1
    assert "velocity confidence matrix: complete" in gcmd.last_info
