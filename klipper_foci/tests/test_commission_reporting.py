"""Tests for commissioning progress and operator failure reporting."""

from klipper_foci.commissioning import (
    COMMISSION_REASON_NAMES,
)
from tests.mocks import (
    make_driver,
)


def test_phase_progress_says_setup_during_foci_setup():
    d = make_driver()
    d.state.active_label = "setup"
    d.commissioning.handle_commission_phase({"phase": 2, "status": 0})
    gcode = d.printer.lookup_object("gcode")
    assert gcode._responses[-1] == "FOCI manual_stepper stepper_x setup: Coil check"


def test_phase_progress_is_debug_only_during_homing(caplog):
    d = make_driver()
    d.global_config.debug = True
    d.state.active_label = "homing"
    with caplog.at_level("INFO", logger="klipper_foci.commissioning"):
        d.commissioning.handle_commission_phase({"phase": 2, "status": 0})
    gcode = d.printer.lookup_object("gcode")
    assert gcode._responses == []
    assert any("Coil check" in record.message for record in caplog.records)


def test_phase_progress_stays_on_console_for_setup():
    d = make_driver()
    d.state.active_label = "setup"
    d.commissioning.handle_commission_phase({"phase": 2, "status": 0})
    gcode = d.printer.lookup_object("gcode")
    assert gcode._responses == ["FOCI manual_stepper stepper_x setup: Coil check"]


def test_phase_progress_is_debug_only_during_selftest(caplog):
    d = make_driver()
    d.global_config.debug = True
    d.state.active_label = "selftest"
    with caplog.at_level("INFO", logger="klipper_foci.commissioning"):
        for phase_id in (1, 2, 3, 4, 5, 9):
            d.commissioning.handle_commission_phase({"phase": phase_id, "status": 0})
    gcode = d.printer.lookup_object("gcode")
    assert gcode._responses == []
    assert len(caplog.records) == 6
    assert any("Encoder alignment" in record.message for record in caplog.records)


def test_operator_failure_phrase_has_no_doc_links_raw_symbols_or_gaps():
    from klipper_foci.commissioning import operator_failure_phrase

    for code in COMMISSION_REASON_NAMES:
        phrase = operator_failure_phrase(code)
        assert "(" not in phrase, code
        assert "_" not in phrase, code
        assert "troubleshooting" not in phrase.lower(), code


def test_encoder_direction_helper_ignores_other_phase_4_diagnostics():
    from klipper_foci.commissioning import _encoder_direction_sweep_failed

    details = [
        {"phase": 4, "code": 1, "status": 1, "value0": 0, "value1": 0, "value2": 0},
    ]
    assert _encoder_direction_sweep_failed(details) is False


def test_encoder_direction_no_code_40_is_generic_fault_wording():
    d = make_driver()
    d.commissioning.clear_details()
    d.commissioning.handle_commission_detail(
        {"phase": 4, "code": 2, "status": 1, "value0": 3977, "value1": 3939, "value2": 38}
    )
    from klipper_foci.commissioning import format_encoder_direction_failure

    message = format_encoder_direction_failure(d.commissioning.details)
    assert "encoder_direction" not in message
    assert "didn't move as expected" in message


def test_encoder_direction_opposite_sign_reports_config_inversion():
    d = make_driver()
    d.commissioning.clear_details()
    d.commissioning.handle_commission_detail(
        {"phase": 4, "code": 2, "status": 1, "value0": 3977, "value1": 3939, "value2": 38}
    )
    d.commissioning.handle_commission_detail(
        {
            "phase": 4,
            "code": 40,
            "status": 1,
            "value0": 16384,
            "value1": 4096,
            "value2": (2**32 - 100),  # negative when re-decoded signed
        }
    )
    from klipper_foci.commissioning import format_encoder_direction_failure

    message = format_encoder_direction_failure(d.commissioning.details)
    assert "encoder_direction looks inverted" in message


def test_encoder_direction_same_sign_out_of_window_is_generic_fault_wording():
    d = make_driver()
    d.commissioning.clear_details()
    d.commissioning.handle_commission_detail(
        {"phase": 4, "code": 2, "status": 1, "value0": 3977, "value1": 3939, "value2": 38}
    )
    d.commissioning.handle_commission_detail(
        {"phase": 4, "code": 40, "status": 1, "value0": 16384, "value1": 4096, "value2": 100}
    )
    from klipper_foci.commissioning import format_encoder_direction_failure

    message = format_encoder_direction_failure(d.commissioning.details)
    assert "encoder_direction" not in message
    assert "didn't move as expected" in message
