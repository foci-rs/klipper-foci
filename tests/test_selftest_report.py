"""Tests for FOCI_SELFTEST streaming result handling and report formatting."""

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
