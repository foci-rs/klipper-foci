"""Tests for the shared console/log report emitter."""

import logging

from klipper_foci.report import humanize, report_detail, report_summary
from tests.mocks import MockGCode


def test_report_summary_calls_respond_info_with_the_message():
    gcode = MockGCode()
    report_summary(gcode, "FOCI_SETUP stepper_x: SUCCEEDED — done.")
    assert gcode._responses == ["FOCI_SETUP stepper_x: SUCCEEDED — done."]


def test_report_detail_logs_at_info_when_debug_enabled(caplog):
    logger = logging.getLogger("klipper_foci.test_report_detail")
    with caplog.at_level(logging.INFO, logger=logger.name):
        report_detail(logger, True, "raw evidence line")
    assert "raw evidence line" in caplog.text


def test_report_detail_is_silent_when_debug_disabled(caplog):
    logger = logging.getLogger("klipper_foci.test_report_detail_off")
    with caplog.at_level(logging.INFO, logger=logger.name):
        report_detail(logger, False, "raw evidence line")
    assert "raw evidence line" not in caplog.text


def test_humanize_replaces_underscores_with_spaces():
    assert humanize("torque_validation") == "torque validation"
    assert humanize("hold_sample_error") == "hold sample error"


def test_humanize_leaves_already_plain_text_unchanged():
    assert humanize("coil connectivity fault") == "coil connectivity fault"
