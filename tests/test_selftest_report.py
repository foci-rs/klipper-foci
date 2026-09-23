"""Tests for FOCI_SELFTEST streaming result handling and report formatting."""

import logging

import pytest
from klipper_foci.commissioning import format_commission_detail
from klipper_foci.selftest import SELFTEST_STAGES, format_selftest_value

from tests.mocks import CommandError, MockCommand, MockGCmd, make_driver


def test_selftest_result_handler_appends_to_results():
    d = make_driver()
    d.selftest.results = []
    d.selftest.handle_selftest_result({"stage": 2, "status": 0, "value": 312})
    assert d.selftest.results == [{"stage": 2, "status": 0, "value": 312}]


def test_selftest_result_handler_does_not_print_live():
    d = make_driver()
    d.selftest.results = []
    d.selftest.handle_selftest_result({"stage": 2, "status": 0, "value": 312})
    gcode = d.printer.lookup_object("gcode")
    assert gcode._responses == []


def test_selftest_done_handler_marks_complete():
    d = make_driver()
    d.selftest.complete = False
    d.selftest.status = 0
    d.selftest.handle_selftest_done({"status": 0})
    assert d.selftest.complete is True
    assert d.selftest.status == 0


def test_selftest_survives_expanded_electrical_id_duration():
    d = make_driver()
    reactor = d.printer.get_reactor()
    real_pause = reactor.pause

    def pause_and_maybe_finish(deadline):
        result = real_pause(deadline)
        if reactor.monotonic() >= 20.0:
            d.selftest.complete = True
            d.selftest.status = 0
        return result

    reactor.pause = pause_and_maybe_finish

    d.selftest.selftest(MockGCmd())


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
    assert "legacy inductance fit rejected" in line
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


def test_format_commission_detail_inductance_capture_rejected():
    phi = format_commission_detail(
        {
            "phase": 5,
            "code": 33,
            "status": 1,
            "value0": 2,
            "value1": 0,
            "value2": (1000 << 16) | 1000,
        }
    )
    current = format_commission_detail(
        {
            "phase": 5,
            "code": 33,
            "status": 1,
            "value0": 4,
            "value1": 0,
            "value2": (20 << 16) | 0xFFAC,
        }
    )

    assert "inductance AC capture rejected" in phi
    assert "reason=zero phi delta" in phi
    assert "samples=0" in phi
    assert "previous_phi=1000" in phi
    assert "current_phi=1000" in phi
    assert "reason=saliency accumulator" in current
    assert "id=20" in current
    assert "iq=-84" in current


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
    assert "voltage_count=512" in excitation
    assert "legacy_didt_cycles=5000" in excitation
    assert "coil A resistance" in resistance
    assert "avg_current=300 counts" in resistance
    assert "r_count_milli=1706" in resistance
    assert "mOhm" not in resistance


def test_format_commission_detail_resistance_capture_timing_summary():
    # Real values captured from a passing FOCI_SELFTEST run.
    line = format_commission_detail(
        {
            "phase": 5,
            "code": 34,
            "status": 0,
            "value0": 136713096,
            "value1": 16777216,
            "value2": 291,
        }
    )

    assert "resistance capture timing" in line
    assert "status=accepted" in line
    assert "period_us=5000" in line
    assert "valid=2086" in line
    assert "missed=0" in line
    assert "max_consecutive_misses=0" in line
    assert "max_lateness_us=291" in line
    assert "diagnostic" not in line


def test_format_commission_detail_resistance_capture_timing_continuation():
    line = format_commission_detail(
        {
            "phase": 5,
            "code": 35,
            "status": 0,
            "value0": 5097,
            "value1": 45,
            "value2": 39,
        }
    )

    assert "resistance capture timing" in line
    assert "max_interval_us=5097" in line
    assert "max_poll_wall_us=45" in line
    assert "max_spi_wall_us=39" in line
    assert "diagnostic" not in line


def test_format_commission_detail_inductance_capture_timing_summary():
    line = format_commission_detail(
        {
            "phase": 5,
            "code": 36,
            "status": 0,
            "value0": 6553800,
            "value1": 16777216,
            "value2": 11,
        }
    )

    assert "inductance capture timing" in line
    assert "status=accepted" in line
    assert "period_us=200" in line
    assert "valid=100" in line
    assert "max_lateness_us=11" in line


def test_format_commission_detail_capture_timing_rejected_status():
    line = format_commission_detail(
        {
            "phase": 5,
            "code": 34,
            "status": 1,
            "value0": 0,
            "value1": 2 << 24,
            "value2": 0,
        }
    )

    assert "status=rejected" in line


def test_format_commission_detail_capture_timing_overflowed():
    line = format_commission_detail(
        {
            "phase": 5,
            "code": 34,
            "status": 0,
            "value0": 0,
            "value1": 1 << 31,
            "value2": 0,
        }
    )

    assert "overflowed" in line


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


def test_format_commission_detail_encoder_read_unstable():
    line = format_commission_detail(
        {
            "phase": 4,
            "code": 1,
            "status": 1,
            "value0": 500,
            "value1": 600,
            "value2": 500,
        }
    )

    assert "Encoder check" in line
    assert "ABN read unstable" in line
    assert "samples=500/600/500" in line


def test_format_commission_detail_encoder_direction_result():
    line = format_commission_detail(
        {
            "phase": 4,
            "code": 2,
            "status": 1,
            "value0": 1234,
            "value1": 1234,
            "value2": 0,
        }
    )

    assert "Encoder check" in line
    assert "direction sweep" in line
    assert "FAIL" in line
    assert "start=1234" in line
    assert "end=1234" in line
    assert "delta=0" in line


def test_format_commission_detail_encoder_alignment_result():
    line = format_commission_detail(
        {
            "phase": 16,
            "code": 1,
            "status": 1,
            "value0": 1,
            "value1": 4,
            "value2": 0,
        }
    )

    assert "Encoder alignment" in line
    assert "alignment movement" in line
    assert "FAIL" in line
    assert "movement=1" in line
    assert "min=4" in line
    assert "stability=0" in line


def test_format_commission_detail_encoder_direction_expected():
    line = format_commission_detail(
        {
            "phase": 4,
            "code": 40,
            "status": 1,
            "value0": 32768,
            "value1": 40,
            "value2": 4294967258,
        }
    )

    assert "Encoder check" in line
    assert "commanded=32768" in line
    assert "expected=40 counts" in line
    assert "observed=-38 counts" in line
    assert "wrong direction" in line


def test_format_commission_detail_encoder_direction_expected_same_sign_omits_wrong_direction():
    line = format_commission_detail(
        {
            "phase": 4,
            "code": 40,
            "status": 1,
            "value0": 32768,
            "value1": 40,
            "value2": 25,
        }
    )

    assert "observed=25 counts" in line
    assert "wrong direction" not in line


def test_format_commission_detail_encoder_direction_bounds():
    line = format_commission_detail(
        {
            "phase": 4,
            "code": 41,
            "status": 1,
            "value0": 30,
            "value1": 50,
            "value2": 50,
        }
    )

    assert "Encoder check" in line
    assert "accepted=30..50 counts" in line
    assert "pole_pairs=50" in line


def test_stage_names_map_contains_all_eight():
    assert SELFTEST_STAGES[1] == "ADC calibration"
    assert SELFTEST_STAGES[2] == "Motor coil A"
    assert SELFTEST_STAGES[3] == "Motor coil B"
    assert SELFTEST_STAGES[4] == "Phase wiring"
    assert SELFTEST_STAGES[5] == "Encoder"
    assert SELFTEST_STAGES[6] == "Encoder direction"
    assert SELFTEST_STAGES[7] == "R-model evidence"
    assert SELFTEST_STAGES[8] == "L control-model evidence"


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


def test_format_resistance_uses_diagnostic_count_units():
    out = format_selftest_value(7, 0, 1714)
    assert "r_count_milli=1714" in out
    assert "ohm" not in out


def test_format_inductance_uses_diagnostic_count_units():
    out = format_selftest_value(8, 0, 3256)
    assert "control_l_count_micro=3256" in out
    assert "mH" not in out


def test_format_fail_status_decodes_stage_value_instead_of_raw_dump():
    out = format_selftest_value(7, 1, 1714)
    assert "r_count_milli=1714" in out
    assert "raw" not in out


def test_format_fail_status_falls_back_to_raw_when_stage_has_no_decode():
    out = format_selftest_value(4, 1, 99)
    assert "raw=99" in out
    assert "FAIL" not in out


def test_cmd_selftest_builds_multiline_report(caplog):
    d = make_driver()
    d.global_config.debug = True
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
    with caplog.at_level(logging.INFO, logger="klipper_foci.selftest"):
        d.selftest.selftest(gcmd)

    out = caplog.text
    assert "ADC calibration" in out
    assert "Motor coil A" in out
    assert "Motor coil B" in out
    assert "Phase wiring" in out
    assert "Encoder " in out  # trailing space distinguishes from "Encoder direction"
    assert "Encoder direction" in out
    assert "R-model evidence" in out
    assert "L control-model evidence" in out
    assert "8/8 stages" not in out
    assert "PASS" in out


def test_cmd_selftest_duplicate_stage_updates_without_inflating_report(caplog):
    d = make_driver()
    d.global_config.debug = True
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
    with caplog.at_level(logging.INFO, logger="klipper_foci.selftest"):
        d.selftest.selftest(gcmd)

    out = caplog.text
    assert out.count("Encoder direction") == 1
    assert "reversed" in out
    assert "7/7 stages" not in out
    assert "6/6 stages" not in out
    assert gcmd._responses[-1] == (
        "FOCI_SELFTEST manual_stepper stepper_x: SUCCEEDED — all 6 stages passed."
    )


def test_cmd_selftest_failure_raises_and_still_emits_report(caplog):
    d = make_driver()
    d.global_config.debug = True
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
    with (
        caplog.at_level(logging.INFO, logger="klipper_foci.selftest"),
        pytest.raises(CommandError),
    ):
        d.selftest.selftest(gcmd)

    # report_summary was called before the raise — the console line is still available.
    assert gcmd._responses[-1] == (
        "FOCI_SELFTEST manual_stepper stepper_x: FAILED — ADC calibration fault."
    )

    out = caplog.text
    assert "FAIL" in out
    assert "legacy inductance fit rejected" in out
    assert "1/1 stages" not in out  # stage 1 failed, so passed count is 0
    assert "0/1 stages" not in out


def test_cmd_selftest_pass_does_not_raise(caplog):
    d = make_driver()
    d.global_config.debug = True
    d.protocol.commands.selftest = MockCommand()

    def drive_stream(_args):
        d.selftest.handle_selftest_result({"stage": 4, "status": 0, "value": 0})
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream

    gcmd = MockGCmd()
    with caplog.at_level(logging.INFO, logger="klipper_foci.selftest"):
        d.selftest.selftest(gcmd)  # must not raise

    assert gcmd.last_info == (
        "FOCI_SELFTEST manual_stepper stepper_x: SUCCEEDED — all 1 stages passed."
    )


def test_cmd_selftest_pass_prints_succeeded_summary():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    def drive_stream(_args):
        d.selftest.handle_selftest_result({"stage": 4, "status": 0, "value": 0})
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream
    gcmd = MockGCmd()

    d.selftest.selftest(gcmd)

    assert (
        gcmd._responses[-1]
        == "FOCI_SELFTEST manual_stepper stepper_x: SUCCEEDED — all 1 stages passed."
    )


def test_cmd_selftest_diagnostics_add_no_console_lines():
    def run(push_detail: bool):
        d = make_driver()
        d.protocol.commands.selftest = MockCommand()

        def drive_stream(_args):
            if push_detail:
                d.commissioning.handle_commission_detail(
                    {
                        "phase": 5,
                        "code": 999,
                        "status": 0,
                        "value0": 1,
                        "value1": 2,
                        "value2": 3,
                    }
                )
            d.selftest.handle_selftest_result({"stage": 4, "status": 0, "value": 0})
            d.selftest.handle_selftest_done({"status": 0})

        d.protocol.commands.selftest.send = drive_stream
        gcmd = MockGCmd()
        d.selftest.selftest(gcmd)
        return d, gcmd

    d_without, gcmd_without = run(push_detail=False)
    d_with, gcmd_with = run(push_detail=True)

    assert d_without.commissioning.details == []
    assert len(d_with.commissioning.details) == 1
    assert len(gcmd_with._responses) == len(gcmd_without._responses)


def test_cmd_selftest_per_stage_breakdown_reaches_the_console():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    def drive_stream(_args):
        for result in [
            {"stage": 1, "status": 0, "value": 0},
            {"stage": 2, "status": 0, "value": 0},
            {"stage": 3, "status": 0, "value": 0},
        ]:
            d.selftest.handle_selftest_result(result)
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream
    gcmd = MockGCmd()

    d.selftest.selftest(gcmd)

    # notice + 3 stage lines (no header) + verdict -- the breakdown's line
    # count reaches the console, not just the debug log.
    assert len(gcmd._responses) == 1 + len(d.selftest.results) + 1


def test_cmd_selftest_prints_running_message_before_dispatching_command():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()
    seen_before_dispatch = []

    def drive_stream(_args):
        seen_before_dispatch.extend(gcmd._responses)
        d.selftest.handle_selftest_result({"stage": 4, "status": 0, "value": 0})
        d.selftest.handle_selftest_done({"status": 0})

    d.protocol.commands.selftest.send = drive_stream
    gcmd = MockGCmd()

    d.selftest.selftest(gcmd)

    assert len(seen_before_dispatch) == 1
    assert seen_before_dispatch[0] == gcmd._responses[0]


def test_cmd_selftest_failure_prints_failed_summary_and_still_raises():
    d = make_driver()
    d.protocol.commands.selftest = MockCommand()

    def drive_stream(_args):
        d.selftest.handle_selftest_result({"stage": 1, "status": 1, "value": 0})
        d.selftest.handle_selftest_done({"status": 4})  # "ADC calibration fault"

    d.protocol.commands.selftest.send = drive_stream
    gcmd = MockGCmd()

    with pytest.raises(CommandError):
        d.selftest.selftest(gcmd)

    assert gcmd._responses[-1] == (
        "FOCI_SELFTEST manual_stepper stepper_x: FAILED — ADC calibration fault."
    )
