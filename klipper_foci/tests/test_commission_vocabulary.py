"""Tests for commissioning error and reason vocabulary."""

import pytest

from klipper_foci import commissioning
from klipper_foci._vocabulary_generated import HARD_FAULT_CODES
from klipper_foci.commissioning import (
    COMMISSION_REASON_NAMES,
    ELECTRICAL_ID_DETAIL_NAMES,
    RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES,
    TIMING_REJECTION_ERROR_CODES,
    TROUBLESHOOTING_DOC_LINKS,
    format_commission_error_name,
    format_current_loop_failure_summary,
)


def test_hand_written_code_groups_only_name_codes_the_vocabulary_defines():
    groups = {
        "TROUBLESHOOTING_DOC_LINKS": set(TROUBLESHOOTING_DOC_LINKS),
        "RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES": set(RESISTANCE_MEASUREMENT_UNSUPPORTED_CODES),
        "HARD_FAULT_CODES": set(HARD_FAULT_CODES),
        "TIMING_REJECTION_ERROR_CODES": set(TIMING_REJECTION_ERROR_CODES.values()),
    }
    for name, codes in groups.items():
        assert codes <= set(COMMISSION_REASON_NAMES), f"{name} names an undefined code"


def test_sustained_hold_failure_has_operator_label_and_is_hard_fault():
    assert COMMISSION_REASON_NAMES.get(42) == "sustained hold validation failed"
    assert format_commission_error_name(42) == "sustained hold validation failed"
    assert 42 in HARD_FAULT_CODES


def test_timing_error_names_match_firmware_wire_codes():
    expected = {
        47: "invalid_schedule",
        48: "resistance_timing",
        49: "resistance_timeout",
        50: "inductance_timing",
        51: "delay_timing",
    }
    assert {code: COMMISSION_REASON_NAMES[code] for code in expected} == expected
    assert {code: ELECTRICAL_ID_DETAIL_NAMES[code] for code in expected} == expected


def test_analysis_overrun_has_a_dedicated_operator_label():
    assert COMMISSION_REASON_NAMES[52] == "velocity sweep analysis overrun"
    assert format_commission_error_name(52) == "velocity sweep analysis overrun"


def test_unconfirmed_velocity_rest_has_a_dedicated_operator_label():
    assert COMMISSION_REASON_NAMES[53] == "velocity rest not confirmed"
    assert format_commission_error_name(53) == "velocity rest not confirmed"


def test_inductance_current_envelope_code_has_a_name():
    assert COMMISSION_REASON_NAMES.get(76) == "inductance current envelope exceeded"


def test_electrical_id_status_reject_is_decoded_not_raw():
    from klipper_foci.commissioning import format_commission_detail

    detail = {
        "phase": 5,
        "code": 41,
        "status": 1,
        "value0": 0x0000_0021,
        "value1": 0x03,
        "value2": 0,
    }
    formatted = format_commission_detail(detail)
    assert "value0=" not in formatted
    assert "value1=" not in formatted
    assert "status_flags_or=0x00000021" in formatted
    assert "entry_mask=0x03" in formatted


def test_pid_gain_invalid_reason_present():
    assert COMMISSION_REASON_NAMES.get(79) == "pid gain invalid"


def test_malformed_interval_reason_present():
    assert COMMISSION_REASON_NAMES[80] == "malformed interval"


def test_missing_rate_table_entry_reason_present():
    assert COMMISSION_REASON_NAMES[81] == "missing rate table entry"


def test_mismatched_observation_reason_present():
    assert COMMISSION_REASON_NAMES[82] == "mismatched observation"


def test_elapsed_time_conversion_invalid_reason_present():
    assert COMMISSION_REASON_NAMES[83] == "elapsed time conversion invalid"


def test_velocity_envelope_ceiling_zero_reason_present():
    assert COMMISSION_REASON_NAMES[84] == "velocity envelope ceiling zero"


def test_velocity_envelope_exceeds_ceiling_reason_present():
    assert COMMISSION_REASON_NAMES[85] == "velocity envelope exceeds ceiling"


def test_safety_timing_gap_invalid_reason_present():
    assert COMMISSION_REASON_NAMES[86] == "safety timing gap invalid"


def test_net_displacement_overflow_reason_present():
    assert COMMISSION_REASON_NAMES[87] == "net displacement overflow"


def test_saliency_bracket_codes_are_unassigned():
    assert 41 not in commissioning.COMMISSION_REASON_NAMES
    assert not {8, 9, 10} & set(commissioning.INDUCTANCE_CAPTURE_REJECT_REASON_NAMES)


def test_current_loop_failure_summary_decodes_gate_sample_status():
    run = {
        "failure_reason": 4,
        "candidate_attempt": 0,
        "candidate_flux_p": 3564,
        "candidate_flux_i": 3520,
        "candidate_torque_p": 3564,
        "candidate_torque_i": 3520,
        "retry_budget_exhausted": 0,
    }
    samples = {
        "flux": [
            {
                "status": 4,
                "sample_delay_ms": 100,
                "gate_role": "gate",
                "positive_response_permille": 984,
                "negative_response_permille": 1007,
                "cross_axis_permille": 156,
                "cross_axis_peak_permille": 281,
                "voltage_output_permille": 159,
                "encoder_delta_counts": 1,
                "status_flags_or": 0xF000_0080,
            }
        ],
        "torque": [],
    }

    text = format_current_loop_failure_summary(run, samples)

    assert text is not None
    assert "flux_validation" in text
    assert "cross-axis coupling" in text
    assert "delay=100ms" in text
    assert "cross=156 permille" in text
    assert "candidate_flux=3564/3520" in text


def test_gain_floor_step_overshoot_is_a_named_failure():
    from klipper_foci.commissioning import (
        format_commission_error_name,
        operator_failure_phrase,
    )

    assert "overshoot" in format_commission_error_name(118)
    assert "unknown" not in operator_failure_phrase(118)
    assert "bandwidth" in operator_failure_phrase(118)


def test_current_validation_envelope_unreachable_is_a_named_failure():
    from klipper_foci.commissioning import (
        format_commission_error_name,
        operator_failure_phrase,
    )

    assert "envelope" in format_commission_error_name(120)
    assert "unknown" not in operator_failure_phrase(120)
    assert "run current" in operator_failure_phrase(120)
    assert "profile" in operator_failure_phrase(120)


def test_current_gain_unrepresentable_is_a_named_failure():
    from klipper_foci.commissioning import (
        format_commission_error_name,
        operator_failure_phrase,
    )

    assert "gain" in format_commission_error_name(121)
    assert "unknown" not in operator_failure_phrase(121)
    assert "inductance" in operator_failure_phrase(121)
    assert "profile" in operator_failure_phrase(121)


def test_resistance_bus_voltage_out_of_range_is_a_named_failure():
    from klipper_foci.commissioning import (
        TROUBLESHOOTING_DOC_LINKS,
        format_commission_error_name,
        operator_failure_phrase,
    )

    assert "bus voltage" in format_commission_error_name(122)
    assert "unknown" not in operator_failure_phrase(122)
    assert "supply voltage" in operator_failure_phrase(122)
    assert "18" in operator_failure_phrase(122) and "60" in operator_failure_phrase(122)
    assert TROUBLESHOOTING_DOC_LINKS[122].endswith("resistance-identification.md")


def test_discovery_stops_are_not_reported_as_safety_envelope_violations():
    from klipper_foci.commissioning import (
        format_commission_error_name,
        operator_failure_phrase,
    )

    for code in (123, 124):
        assert code in HARD_FAULT_CODES
        assert "unknown" not in operator_failure_phrase(code)
        assert "safety envelope" not in format_commission_error_name(code)
    assert "run current" in operator_failure_phrase(123)
    assert "tuning velocity" in operator_failure_phrase(123)
    assert "status" in operator_failure_phrase(124)


@pytest.mark.parametrize(
    ("phase", "code", "status", "value0", "value1", "value2", "expected"),
    [
        pytest.param(
            2,
            2,
            0,
            120,
            65516,
            4293656696,
            (
                "Coil check: coil B sample PASS (expected=120 counts, "
                "other=-20 counts, raw=0xffec0078)"
            ),
            id="coil_b_pass",
        ),
        pytest.param(
            2,
            1,
            1,
            65516,
            20,
            4660,
            (
                "Coil check: coil A sample FAIL (expected=-20 counts, "
                "other=20 counts, raw=0x00001234)"
            ),
            id="coil_a_fail",
        ),
        pytest.param(
            2,
            1,
            0,
            120,
            65516,
            4293656696,
            (
                "Coil check: coil A sample PASS (expected=120 counts, "
                "other=-20 counts, raw=0xffec0078)"
            ),
            id="coil_a_pass",
        ),
        pytest.param(
            4,
            1,
            0,
            1,
            2,
            3,
            ("Encoder check: ABN read unstable (samples=1/2/3)"),
            id="abn_read_unstable",
        ),
        pytest.param(
            4,
            40,
            0,
            100,
            50,
            60,
            (
                "Encoder check: encoder direction FAIL (commanded=100 PHI_E, expected=50 counts, "
                "observed=60 counts)"
            ),
            id="encoder_direction_same_sign",
        ),
        pytest.param(
            4,
            40,
            0,
            100,
            50,
            4294967264,
            (
                "Encoder check: encoder direction FAIL (commanded=100 PHI_E, expected=50 counts, "
                "observed=-32 counts, wrong direction)"
            ),
            id="encoder_direction_wrong_direction",
        ),
        pytest.param(
            4,
            41,
            0,
            4294967280,
            16,
            7,
            ("Encoder check: encoder direction bounds (accepted=-16..16 counts, pole_pairs=7)"),
            id="encoder_direction_bounds_precedes_code41",
        ),
        pytest.param(
            4,
            3,
            0,
            5,
            6,
            7,
            ("Encoder check: coil B resistance (avg_current=5 counts, r_count_milli=6, samples=7)"),
            id="phase4_unlisted_code_uses_code_branch",
        ),
        pytest.param(
            10,
            1,
            2,
            5,
            4294967280,
            7,
            ("Closed-loop entry: runaway FAIL (position_1=5, position_2=-16, drift=7)"),
            id="runaway",
        ),
        pytest.param(
            10,
            1,
            1,
            5,
            4294967280,
            7,
            ("Closed-loop entry: drift FAIL (position_1=5, position_2=-16, drift=7)"),
            id="drift",
        ),
        pytest.param(
            4,
            2,
            0,
            1,
            2,
            3,
            ("Encoder check: direction sweep PASS (start=1, end=2, delta=3)"),
            id="direction_sweep_pass",
        ),
        pytest.param(
            9,
            1,
            0,
            1,
            4,
            0,
            ("Encoder alignment: alignment movement PASS (movement=1, min=4, stability=0)"),
            id="alignment_pass",
        ),
        pytest.param(
            5,
            1,
            0,
            10,
            20,
            30,
            (
                "Electrical ID: excitation (voltage_count=10, "
                "legacy_didt_cycles=20, sample_period=30us)"
            ),
            id="code1",
        ),
        pytest.param(
            5,
            2,
            0,
            10,
            20,
            30,
            (
                "Electrical ID: coil A resistance (avg_current=10 counts, "
                "r_count_milli=20, samples=30)"
            ),
            id="code2",
        ),
        pytest.param(
            5,
            3,
            0,
            10,
            20,
            30,
            (
                "Electrical ID: coil B resistance (avg_current=10 counts, "
                "r_count_milli=20, samples=30)"
            ),
            id="code3",
        ),
        pytest.param(
            5,
            25,
            0,
            10,
            20,
            30,
            ("Electrical ID: coil resistance mismatch (10 permille, limit=20)"),
            id="code25",
        ),
        pytest.param(
            5,
            26,
            0,
            10,
            20,
            30,
            ("Electrical ID: coil control-model tau mismatch (10 permille, limit=20)"),
            id="code26",
        ),
        pytest.param(
            5,
            28,
            0,
            0,
            3,
            171,
            (
                "Electrical ID: legacy inductance fit rejected (coil=A, "
                "usable_points=3, selected_mask=0x00ab)"
            ),
            id="code28_a",
        ),
        pytest.param(
            5,
            28,
            0,
            1,
            3,
            171,
            (
                "Electrical ID: legacy inductance fit rejected (coil=B, "
                "usable_points=3, selected_mask=0x00ab)"
            ),
            id="code28_b",
        ),
        pytest.param(
            5,
            30,
            0,
            19,
            40,
            4294967280,
            (
                "Electrical ID: legacy inductance fit point (coil=B point=3, "
                "ud=40, avg_delta=4294967280 counts)"
            ),
            id="code30",
        ),
        pytest.param(
            5,
            31,
            0,
            2,
            40,
            4294967280,
            (
                "Electrical ID: legacy inductance fit correction (coil=A "
                "point=2, samples=40, effective_ud=-16)"
            ),
            id="code31",
        ),
        pytest.param(
            5,
            32,
            0,
            1000,
            2000,
            300,
            (
                "Electrical ID: inductance frequency out of range "
                "(realized_frequency_millihz=1000, elapsed_us=2000, "
                "samples=300)"
            ),
            id="code32",
        ),
        pytest.param(
            5,
            33,
            0,
            1,
            9,
            6553800,
            (
                "Electrical ID: inductance AC capture rejected (reason=phi "
                "interval invalid, samples=9, previous_phi=100, "
                "current_phi=200)"
            ),
            id="code33_r1",
        ),
        pytest.param(
            5,
            33,
            0,
            2,
            9,
            6553800,
            (
                "Electrical ID: inductance AC capture rejected (reason=zero "
                "phi delta, samples=9, previous_phi=100, current_phi=200)"
            ),
            id="code33_r2",
        ),
        pytest.param(
            5,
            33,
            0,
            3,
            9,
            4294901765,
            (
                "Electrical ID: inductance AC capture rejected (reason=frame "
                "accumulator, samples=9, id=-1, iq=5)"
            ),
            id="code33_r3",
        ),
        pytest.param(
            5,
            33,
            0,
            6,
            9,
            524286,
            (
                "Electrical ID: inductance AC capture rejected "
                "(reason=second-half accumulator, samples=9, id=7, iq=-2)"
            ),
            id="code33_r6",
        ),
        pytest.param(
            5,
            33,
            0,
            7,
            9,
            6553800,
            (
                "Electrical ID: inductance AC capture rejected "
                "(reason=elapsed interpolation, samples=9, "
                "previous_elapsed_us=100, current_elapsed_us=200)"
            ),
            id="code33_r7",
        ),
        pytest.param(
            5,
            33,
            0,
            9,
            9,
            77,
            ("Electrical ID: inductance AC capture rejected (reason=reason 9, samples=9, aux=77)"),
            id="code33_other",
        ),
        pytest.param(
            5,
            41,
            0,
            43981,
            5,
            0,
            (
                "Electrical ID: inductance status rejected "
                "(status_flags_or=0x0000abcd, entry_mask=0x05)"
            ),
            id="code41",
        ),
        pytest.param(
            5,
            34,
            0,
            3276900,
            16973828,
            900,
            (
                "Electrical ID: resistance capture timing: status=accepted "
                "period_us=100 valid=50 missed=4 max_consecutive_misses=3 "
                "max_lateness_us=900"
            ),
            id="t34",
        ),
        pytest.param(
            5,
            36,
            0,
            3276900,
            2181234692,
            900,
            (
                "Electrical ID: inductance capture timing: status=rejected "
                "period_us=100 valid=50 missed=4 max_consecutive_misses=3 "
                "max_lateness_us=900, overflowed"
            ),
            id="t36",
        ),
        pytest.param(
            5,
            38,
            0,
            3276900,
            2130706436,
            900,
            (
                "Electrical ID: delay capture timing: status=unknown(127) "
                "period_us=100 valid=50 missed=4 max_consecutive_misses=0 "
                "max_lateness_us=900"
            ),
            id="t38",
        ),
        pytest.param(
            5,
            35,
            0,
            1,
            2,
            3,
            (
                "Electrical ID: resistance capture timing (cont.): "
                "max_interval_us=1 max_poll_wall_us=2 max_spi_wall_us=3"
            ),
            id="t35",
        ),
        pytest.param(
            5,
            37,
            0,
            1,
            2,
            3,
            (
                "Electrical ID: inductance capture timing (cont.): "
                "max_interval_us=1 max_poll_wall_us=2 max_spi_wall_us=3"
            ),
            id="t37",
        ),
        pytest.param(
            5,
            39,
            0,
            1,
            2,
            3,
            (
                "Electrical ID: delay capture timing (cont.): "
                "max_interval_us=1 max_poll_wall_us=2 max_spi_wall_us=3"
            ),
            id="t39",
        ),
        pytest.param(
            5,
            22,
            0,
            10,
            0,
            0,
            ("Electrical ID: model scale rounded to zero (l_count_micro=10)"),
            id="code22",
        ),
        pytest.param(
            5,
            23,
            0,
            10,
            20,
            0,
            ("Electrical ID: resistance below short threshold (r_count_milli=10, limit=20)"),
            id="code23",
        ),
        pytest.param(
            5,
            24,
            0,
            10,
            20,
            0,
            ("Electrical ID: resistance above open threshold (r_count_milli=10, limit=20)"),
            id="code24",
        ),
        pytest.param(
            5,
            29,
            0,
            10,
            20,
            0,
            ("Electrical ID: transport delay too large (theta_us=10, tau_us=20)"),
            id="code29",
        ),
        pytest.param(
            5,
            99,
            0,
            1,
            2,
            3,
            ("Electrical ID: diagnostic 99 (value0=1, value1=2, value2=3)"),
            id="generic_vals",
        ),
        pytest.param(5, 99, 0, 0, 0, 0, ("Electrical ID: diagnostic 99"), id="generic_none"),
    ],
)
def test_format_commission_detail_output_shape(
    phase, code, status, value0, value1, value2, expected
):
    from klipper_foci.commissioning import format_commission_detail

    detail = {
        "phase": phase,
        "code": code,
        "status": status,
        "value0": value0,
        "value1": value1,
        "value2": value2,
    }

    assert format_commission_detail(detail) == expected
