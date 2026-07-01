"""Tests for FOCI_SELFTEST streaming result handling and report formatting."""

import pytest

from klipper_foci.commissioning import format_commission_detail
from klipper_foci.selftest import SELFTEST_STAGES, format_selftest_value

from tests.mocks import CommandError, make_driver, MockCommand, MockGCmd


def test_selftest_result_handler_appends_to_results():
    d = make_driver()
    d.selftest.results = []
    d.selftest.handle_selftest_result({"stage": 2, "status": 0, "value": 312})
    assert d.selftest.results == [{"stage": 2, "status": 0, "value": 312}]


def test_selftest_done_handler_marks_complete():
    d = make_driver()
    d.selftest.complete = False
    d.selftest.status = 0
    d.selftest.handle_selftest_done({"status": 0})
    assert d.selftest.complete is True
    assert d.selftest.status == 0


def test_commission_detail_handler_appends_to_details():
    d = make_driver()
    d.commissioning.details = []
    d.commissioning.handle_commission_detail(
        {
            "phase": 5,
            "code": 28,
            "status": 1,
            "value0": 820,
            "value1": 500,
            "value2": 0,
        }
    )
    assert d.commissioning.details == [
        {
            "phase": 5,
            "code": 28,
            "status": 1,
            "value0": 820,
            "value1": 500,
            "value2": 0,
        }
    ]


def test_format_commission_detail_rejected_inductance_fit():
    line = format_commission_detail(
        {
            "phase": 5,
            "code": 28,
            "status": 1,
            "value0": 1,
            "value1": 2,
            "value2": 0b0101,
        }
    )
    assert "Electrical ID" in line
    assert "corrected inductance fit rejected" in line
    assert "coil=B" in line
    assert "usable_points=2" in line
    assert "selected_mask=0x0005" in line


def test_format_commission_detail_inductance_fit_points():
    point = format_commission_detail(
        {
            "phase": 5,
            "code": 30,
            "status": 0,
            "value0": 0x12,
            "value1": 768,
            "value2": 39,
        }
    )
    correction = format_commission_detail(
        {
            "phase": 5,
            "code": 31,
            "status": 0,
            "value0": 0x12,
            "value1": 4750,
            "value2": 0xFFFFFE9A,
        }
    )

    assert "coil=B point=2" in point
    assert "ud=768" in point
    assert "avg_delta=39 counts" in point
    assert "samples=4750" in correction
    assert "effective_ud=-358" in correction


def test_format_commission_detail_measurements():
    excitation = format_commission_detail(
        {
            "phase": 5,
            "code": 1,
            "status": 0,
            "value0": 512,
            "value1": 5000,
            "value2": 160,
        }
    )
    resistance = format_commission_detail(
        {
            "phase": 5,
            "code": 2,
            "status": 0,
            "value0": 300,
            "value1": 1706,
            "value2": 1000,
        }
    )
    inductance = format_commission_detail(
        {
            "phase": 5,
            "code": 4,
            "status": 0,
            "value0": 40,
            "value1": 730,
            "value2": 5000,
        }
    )
    transient = format_commission_detail(
        {
            "phase": 5,
            "code": 6,
            "status": 0,
            "value0": 1000,
            "value1": 160,
            "value2": 1328,
        }
    )

    assert "voltage_count=512" in excitation
    assert "didt_cycles=5000" in excitation
    assert "coil A resistance" in resistance
    assert "avg_current=300 counts" in resistance
    assert "r=1706 mOhm" in resistance
    assert "coil A inductance" in inductance
    assert "avg_delta=40 counts" in inductance
    assert "tau=730us" in inductance
    assert "transient" in transient
    assert "steady_state=1000 counts" in transient
    assert "crosscheck=1328us" in transient


def test_format_commission_detail_coil_check_sample():
    line = format_commission_detail(
        {
            "phase": 2,
            "code": 1,
            "status": 1,
            "value0": 120,
            "value1": 0xFFEC,
            "value2": 0xFFEC0078,
        }
    )

    assert "Coil check" in line
    assert "coil A sample" in line
    assert "FAIL" in line
    assert "expected=120 counts" in line
    assert "other=-20 counts" in line
    assert "raw=0xffec0078" in line


def test_stage_names_map_contains_all_eight():
    assert SELFTEST_STAGES[1] == "ADC calibration"
    assert SELFTEST_STAGES[2] == "Motor coil A"
    assert SELFTEST_STAGES[3] == "Motor coil B"
    assert SELFTEST_STAGES[4] == "Phase wiring"
    assert SELFTEST_STAGES[5] == "Encoder"
    assert SELFTEST_STAGES[6] == "Encoder direction"
    assert SELFTEST_STAGES[7] == "Resistance"
    assert SELFTEST_STAGES[8] == "Inductance"


def test_format_adc_calibration_unpacks_offsets():
    packed = (0x0ADC << 16) | 0x0CDC
    out = format_selftest_value(1, 0, packed)
    assert "offset_i0=3292" in out
    assert "offset_i1=2780" in out


def test_format_coil_current_positive():
    out = format_selftest_value(2, 0, 300)
    assert "300" in out


def test_format_coil_current_negative_reinterprets_high_bit():
    # i16 -1 bit-reinterpreted = 0xFFFF
    out = format_selftest_value(3, 0, 0xFFFF)
    assert "-1" in out


def test_format_phase_wiring_pass_has_no_detail():
    assert format_selftest_value(4, 0, 0) == ""


def test_format_encoder_delta_shows_count():
    out = format_selftest_value(5, 0, 3)
    assert "delta=3" in out


def test_format_encoder_direction_labels_value():
    assert "increasing" in format_selftest_value(6, 0, 0).lower()
    assert "reversed" in format_selftest_value(6, 0, 1).lower()


def test_format_resistance_uses_ohm_units():
    # 1714 milliohm -> "1.7 ohm"
    out = format_selftest_value(7, 0, 1714)
    assert "1.7" in out and "ohm" in out


def test_format_inductance_uses_mh_units():
    # 3256 microhenry -> "3.3 mH"
    out = format_selftest_value(8, 0, 3256)
    assert "3.3" in out and "mH" in out


def test_format_fail_status_returns_error_marker():
    out = format_selftest_value(7, 1, 0)
    assert "FAIL" in out or "fail" in out.lower()


def test_cmd_selftest_builds_multiline_report():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    # Drive the response stream synchronously when the self-test command is sent.
    def drive_stream(_args):
        for result in [
            {"stage": 1, "status": 0, "value": (0x0ADC << 16) | 0x0CDC},
            {"stage": 2, "status": 0, "value": 300},
            {"stage": 3, "status": 0, "value": 312},
            {"stage": 4, "status": 0, "value": 0},
            {"stage": 5, "status": 0, "value": 3},
            {"stage": 6, "status": 0, "value": 0},
            {"stage": 7, "status": 0, "value": 1714},
            {"stage": 8, "status": 0, "value": 3256},
        ]:
            d.selftest.handle_selftest_result(result)
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream

    gcmd = MockGCmd()
    d.selftest.selftest(gcmd)

    out = gcmd.last_info
    assert "Self-Test" in out
    assert "ADC calibration" in out
    assert "Motor coil A" in out
    assert "Motor coil B" in out
    assert "Phase wiring" in out
    assert "Encoder " in out  # trailing space distinguishes from "Encoder direction"
    assert "Encoder direction" in out
    assert "Resistance" in out
    assert "Inductance" in out
    assert "8/8 stages" in out
    assert "PASS" in out


def test_cmd_selftest_duplicate_stage_updates_without_inflating_report():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    def drive_stream(_args):
        for result in [
            {"stage": 1, "status": 0, "value": (0x0ADC << 16) | 0x0CDC},
            {"stage": 2, "status": 0, "value": 300},
            {"stage": 3, "status": 0, "value": 312},
            {"stage": 4, "status": 0, "value": 0},
            {"stage": 5, "status": 0, "value": 3},
            {"stage": 6, "status": 0, "value": 0},
            {"stage": 6, "status": 0, "value": 1},
        ]:
            d.selftest.handle_selftest_result(result)
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream

    gcmd = MockGCmd()
    d.selftest.selftest(gcmd)

    out = gcmd.last_info
    assert out.count("Encoder direction") == 1
    assert "reversed" in out
    assert "7/7 stages" not in out
    assert "6/6 stages" in out


def test_cmd_selftest_failure_raises_and_still_emits_report():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    # Stage 1 fails; firmware emits a foci_selftest_result then foci_selftest_done
    # with the ADC calibration fault code (4 = "ADC calibration fault").
    def drive_stream(_args):
        d.commissioning.handle_commission_detail(
            {
                "phase": 5,
                "code": 28,
                "status": 1,
                "value0": 0,
                "value1": 0,
                "value2": 0,
            }
        )
        d.selftest.handle_selftest_result({"stage": 1, "status": 1, "value": 0})
        d.selftest.handle_selftest_done({"status": 4})

    d.protocol.commands.selftest.send = drive_stream

    gcmd = MockGCmd()
    with pytest.raises(CommandError):
        d.selftest.selftest(gcmd)

    # respond_info was called before the raise — report is still available.
    out = gcmd.last_info
    assert "FAIL" in out
    assert "ADC calibration fault" in out
    assert "corrected inductance fit rejected" in out
    assert "1/1 stages" not in out  # stage 1 failed, so passed count is 0
    assert "0/1 stages" in out


def test_cmd_selftest_pass_does_not_raise():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    def drive_stream(_args):
        d.selftest.handle_selftest_result({"stage": 4, "status": 0, "value": 0})
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream

    gcmd = MockGCmd()
    d.selftest.selftest(gcmd)  # must not raise

    assert "PASS" in gcmd.last_info
