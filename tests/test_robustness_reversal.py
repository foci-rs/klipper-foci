"""Parse tests for the reversal-standstill robustness terminal reply."""

import struct

import pytest
from klipper_foci.robustness_reversal import (
    ROBUSTNESS_CAUSE_NAMES,
    ROBUSTNESS_OUTCOME_NAMES,
    ROBUSTNESS_SCHEMA_REVISION,
    RobustnessReversalProtocolError,
    handle_terminal,
)

from tests.mocks import make_driver

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


def test_cause_names_cover_firmware_values_zero_through_seven():
    assert set(ROBUSTNESS_CAUSE_NAMES) == set(range(8))
    assert ROBUSTNESS_CAUSE_NAMES[7] == "evidence_integrity"


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
        handle_and_return(build_robustness_payload(cause=8))


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
