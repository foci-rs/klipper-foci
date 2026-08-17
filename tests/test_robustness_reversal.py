"""Parse tests for the reversal-standstill robustness terminal reply."""

import struct

import pytest
from klipper_foci.registers import REGISTERS
from klipper_foci.robustness_reversal import (
    ROBUSTNESS_CAUSE_NAMES,
    ROBUSTNESS_OUTCOME_NAMES,
    ROBUSTNESS_SCHEMA_REVISION,
    RobustnessReversalProtocolError,
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

_DIRECTION_DEFAULTS = {
    "reconvergence_time_us": 12_345,
    "settled_residual_q": 250,
    "recovery_iae_qs": 9_000_000,
    "forward_settle_time_us": 8_765,
    "tripped": 0b0000_0101,
    "retry_count": 2,
    "inconclusive": 0,
}


def _direction_bytes(overrides: dict | None = None) -> bytes:
    fields = {**_DIRECTION_DEFAULTS, **(overrides or {})}
    return struct.pack(
        "<IiiIBBB",
        fields["reconvergence_time_us"],
        fields["settled_residual_q"],
        fields["recovery_iae_qs"],
        fields["forward_settle_time_us"],
        fields["tripped"],
        fields["retry_count"],
        fields["inconclusive"],
    )


def build_robustness_payload(
    *,
    schema_revision=ROBUSTNESS_SCHEMA_REVISION,
    run_sequence=RUN_SEQUENCE,
    outcome=0,
    cause=0,
    selected_p=1_024,
    selected_i=512,
    target_velocity_rpm=-1_500,
    forward=None,
    reverse=None,
    **shared_direction_overrides,
) -> bytes:
    """Build a 54-byte robustness-terminal payload for tests.

    `forward`/`reverse` override one direction only; any keyword also present
    in `_DIRECTION_DEFAULTS` (e.g. `reconvergence_time_us`) is applied to
    both directions unless that direction has its own override.
    """
    header = struct.pack(
        "<HIBBHHi",
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
    return header + _direction_bytes(forward_overrides) + _direction_bytes(reverse_overrides)


def handle_and_return(payload: bytes) -> dict:
    return handle_terminal({"oid": 1, "payload": payload})


def test_wire_layout_is_fifty_four_bytes():
    assert len(build_robustness_payload()) == 54


def test_terminal_parse_decodes_header_and_namespace():
    terminal = handle_and_return(build_robustness_payload())

    assert terminal["outcome_namespace"] == "robustness_reversal"
    assert terminal["outcome"] == 0
    assert terminal["outcome_name"] == "complete"
    assert terminal["run_sequence"] == RUN_SEQUENCE
    assert terminal["selected_p"] == 1_024
    assert terminal["selected_i"] == 512
    assert terminal["target_velocity_rpm"] == -1_500


def test_terminal_parse_reports_cause_name_for_cause_one():
    terminal = handle_and_return(build_robustness_payload(outcome=1, cause=1))

    assert terminal["cause"] == 1
    assert terminal["cause_name"] == "reconvergence_time_exceeded"


def test_terminal_parse_decodes_per_direction_metrics():
    terminal = handle_and_return(
        build_robustness_payload(
            forward={
                "reconvergence_time_us": 11_111,
                "settled_residual_q": 250,
                "recovery_iae_qs": 9_000_000,
                "forward_settle_time_us": 8_765,
                "tripped": 0b0000_0101,
                "retry_count": 2,
                "inconclusive": 0,
            },
            reverse={
                "reconvergence_time_us": 22_222,
                "settled_residual_q": -250,
                "recovery_iae_qs": -9_000_000,
                "forward_settle_time_us": 8_765,
                "tripped": 0b0000_0011,
                "retry_count": 1,
                "inconclusive": 1,
            },
        )
    )

    forward, reverse = terminal["directions"]
    assert forward["reconvergence_time_us"] == 11_111
    assert forward["settled_residual_q"] == 250
    assert forward["recovery_iae_qs"] == 9_000_000
    assert forward["forward_settle_time_us"] == 8_765
    assert forward["tripped"] == 0b0000_0101
    assert forward["retry_count"] == 2
    assert forward["inconclusive"] is False

    assert reverse["reconvergence_time_us"] == 22_222
    assert reverse["settled_residual_q"] == -250
    assert reverse["recovery_iae_qs"] == -9_000_000
    assert reverse["tripped"] == 0b0000_0011
    assert reverse["retry_count"] == 1
    assert reverse["inconclusive"] is True


def test_cause_names_cover_firmware_values_zero_through_nine():
    assert set(ROBUSTNESS_CAUSE_NAMES) == set(range(10))
    assert ROBUSTNESS_CAUSE_NAMES[7] == "evidence_integrity"
    assert ROBUSTNESS_CAUSE_NAMES[8] == "internal_fault"
    assert ROBUSTNESS_CAUSE_NAMES[9] == "rest_not_confirmed"


def test_outcome_names_cover_firmware_values_zero_through_three():
    assert set(ROBUSTNESS_OUTCOME_NAMES) == set(range(4))
    assert ROBUSTNESS_OUTCOME_NAMES[3] == "failed"


def test_formatted_result_exposes_derived_reconvergence_ratio():
    # reconvergence_ratio_ppm is NOT on the wire; the host derives it per
    # direction as reconvergence_time_us * 1_000_000 // forward_settle_time_us.
    terminal = handle_and_return(
        build_robustness_payload(
            reconvergence_time_us=90_000,
            forward_settle_time_us=30_000,
        )
    )
    assert terminal["directions"][0]["reconvergence_ratio_ppm"] == 3_000_000
    assert terminal["directions"][1]["reconvergence_ratio_ppm"] == 3_000_000


def test_reconvergence_ratio_guards_divide_by_zero():
    terminal = handle_and_return(build_robustness_payload(forward={"forward_settle_time_us": 0}))
    assert terminal["directions"][0]["reconvergence_ratio_ppm"] == 0


def test_terminal_rejects_wrong_size_payload():
    with pytest.raises(RobustnessReversalProtocolError, match="expected"):
        handle_terminal({"oid": 1, "payload": build_robustness_payload()[:-1]})


def test_terminal_rejects_missing_payload():
    with pytest.raises(RobustnessReversalProtocolError, match="missing"):
        handle_terminal({"oid": 1})


def test_terminal_rejects_invalid_outcome():
    with pytest.raises(RobustnessReversalProtocolError, match="taxonomy"):
        handle_and_return(build_robustness_payload(outcome=4))


def test_terminal_rejects_invalid_cause():
    with pytest.raises(RobustnessReversalProtocolError, match="taxonomy"):
        handle_and_return(build_robustness_payload(cause=10))


def test_terminal_rejects_unsupported_schema():
    with pytest.raises(RobustnessReversalProtocolError, match="schema"):
        handle_and_return(build_robustness_payload(schema_revision=99))


def test_robustness_reversal_terminal_is_registered():
    driver = make_driver()
    registrations = {
        name
        for _callback, name, oid in driver.mcu._serial.responses
        if oid == driver.oid and "robustness_reversal" in name
    }
    assert registrations == {"foci_robustness_reversal_terminal"}


def test_autotune_router_stores_the_parsed_terminal():
    driver = make_driver()
    payload = build_robustness_payload(outcome=1, cause=1)

    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    terminal = driver.autotune.robustness_reversal_terminal
    assert terminal is not None
    assert terminal["outcome_name"] == "rejected"
    assert terminal["cause_name"] == "reconvergence_time_exceeded"
    assert driver.autotune.robustness_reversal_error is None


def test_autotune_router_rejects_a_duplicate_terminal():
    driver = make_driver()
    payload = build_robustness_payload()

    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})
    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    assert isinstance(driver.autotune.robustness_reversal_error, RobustnessReversalProtocolError)
    assert "duplicate" in str(driver.autotune.robustness_reversal_error)


def test_formatted_message_names_cause_and_reports_derived_ratio():
    driver = make_driver()
    payload = build_robustness_payload(
        outcome=1,
        cause=1,
        forward={"reconvergence_time_us": 90_000, "forward_settle_time_us": 30_000},
    )
    driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})

    message = driver.autotune._format_robustness_reversal_result()

    assert "robustness reversal: rejected" in message
    assert "cause=1 (reconvergence_time_exceeded)" in message
    assert "ratio_ppm=3000000" in message
    assert "forward_settle_time_us=30000" in message


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
        payload = build_robustness_payload(
            outcome=1,
            cause=1,
            forward={"reconvergence_time_us": 90_000, "forward_settle_time_us": 30_000},
        )
        driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})
        return reactor._time

    reactor.pause = finish_robustness
    gcmd = MockGCmd({"ACTION": "robustness_reversal"})
    driver.autotune.autotune(gcmd)

    assert "robustness reversal: rejected" in gcmd.last_info
    assert "cause=1 (reconvergence_time_exceeded)" in gcmd.last_info
    assert "forward_settle_time_us=30000" in gcmd.last_info


def test_robustness_safety_fault_reports_outer_envelope_detail():
    """A cause=6 robustness terminal must surface the outer-envelope detail.

    Regression guard for the reporting gap: the robustness gate's most
    important failure mode (safety_fault) previously reached the host with
    only `cause=6` and no evidence of which envelope check tripped.
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
        payload = build_robustness_payload(outcome=3, cause=6, inconclusive=1)
        driver.autotune.handle_robustness_reversal_terminal({"oid": driver.oid, "payload": payload})
        return reactor._time

    reactor.pause = finish_with_safety_fault
    gcmd = MockGCmd({"ACTION": "robustness_reversal"})
    driver.autotune.autotune(gcmd)

    message = gcmd.last_info
    assert "robustness reversal: failed" in message
    assert "cause=6 (safety_fault)" in message
    assert "outer safety velocity" in message
    assert "window_delta_counts=-125" in message
    assert "velocity_counts_per_ms=-31" in message
    assert "cap_counts_per_ms=24" in message
    assert "budget=750mrev/6000mrev_s/3000ms dir=0x03" in message


def test_autotune_raises_on_robustness_reversal_transport_failure():
    """A parse error must surface as a command error, not hang to timeout."""
    driver = ready_driver()
    reactor = driver.printer.get_reactor()

    def fail_robustness(deadline):
        reactor._time = deadline
        bad_payload = build_robustness_payload()[:-1]
        driver.autotune.handle_robustness_reversal_terminal(
            {"oid": driver.oid, "payload": bad_payload}
        )
        return reactor._time

    reactor.pause = fail_robustness
    gcmd = MockGCmd({"ACTION": "robustness_reversal"})

    with pytest.raises(CommandError, match="robustness reversal transport failure"):
        driver.autotune.autotune(gcmd)
