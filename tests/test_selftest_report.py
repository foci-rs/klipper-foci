"""Tests for FOCI_SELFTEST streaming result handling and report formatting."""

from tmc4671 import FociDriver

from tests.mocks import make_driver


def test_selftest_result_handler_appends_to_results():
    d = make_driver()
    d._selftest_results = []
    d._handle_selftest_result({"stage": 2, "status": 0, "value": 312})
    assert d._selftest_results == [{"stage": 2, "status": 0, "value": 312}]


def test_selftest_done_handler_marks_complete():
    d = make_driver()
    d._selftest_complete = False
    d._selftest_status = 0
    d._handle_selftest_done({"status": 0})
    assert d._selftest_complete is True
    assert d._selftest_status == 0


def test_stage_names_map_contains_all_eight():
    assert FociDriver.SELFTEST_STAGES[1] == "ADC calibration"
    assert FociDriver.SELFTEST_STAGES[2] == "Motor coil A"
    assert FociDriver.SELFTEST_STAGES[3] == "Motor coil B"
    assert FociDriver.SELFTEST_STAGES[4] == "Phase wiring"
    assert FociDriver.SELFTEST_STAGES[5] == "Encoder"
    assert FociDriver.SELFTEST_STAGES[6] == "Encoder direction"
    assert FociDriver.SELFTEST_STAGES[7] == "Resistance"
    assert FociDriver.SELFTEST_STAGES[8] == "Inductance"


def test_format_adc_calibration_unpacks_offsets():
    packed = (0x0ADC << 16) | 0x0CDC
    out = FociDriver._format_selftest_value(1, 0, packed)
    assert "offset_i0=3292" in out
    assert "offset_i1=2780" in out


def test_format_coil_current_positive():
    out = FociDriver._format_selftest_value(2, 0, 300)
    assert "300" in out


def test_format_coil_current_negative_reinterprets_high_bit():
    # i16 -1 bit-reinterpreted = 0xFFFF
    out = FociDriver._format_selftest_value(3, 0, 0xFFFF)
    assert "-1" in out


def test_format_phase_wiring_pass_has_no_detail():
    assert FociDriver._format_selftest_value(4, 0, 0) == ""


def test_format_encoder_delta_shows_count():
    out = FociDriver._format_selftest_value(5, 0, 3)
    assert "delta=3" in out


def test_format_encoder_direction_labels_value():
    assert "increasing" in FociDriver._format_selftest_value(6, 0, 0).lower()
    assert "reversed" in FociDriver._format_selftest_value(6, 0, 1).lower()


def test_format_resistance_uses_ohm_units():
    # 1714 milliohm -> "1.7 ohm"
    out = FociDriver._format_selftest_value(7, 0, 1714)
    assert "1.7" in out and "ohm" in out


def test_format_inductance_uses_mh_units():
    # 3256 microhenry -> "3.3 mH"
    out = FociDriver._format_selftest_value(8, 0, 3256)
    assert "3.3" in out and "mH" in out


def test_format_fail_status_returns_error_marker():
    out = FociDriver._format_selftest_value(7, 1, 0)
    assert "FAIL" in out or "fail" in out.lower()
