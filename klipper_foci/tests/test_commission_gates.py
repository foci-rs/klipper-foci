"""Tests for commissioning gates and operator summaries."""

import contextlib
import unittest

import pytest

from tests.mocks import (
    SAMPLE_COMMISSION_RESULT,
    CommandError,
    MockConfigFile,
    MockGCmd,
    MockReactor,
    complete_commission_result,
    make_config_driver,
    make_config_printer,
    make_driver,
    timing_reply,
)


class TestCommissionGates(unittest.TestCase):
    def test_raises_if_lock_held(self):
        d = make_driver()
        d.state.operation_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced"})
        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_rejects_invalid_profile(self):
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "turbo"})
        with self.assertRaises(CommandError) as ctx:
            d.commissioning.commission(gcmd)
        self.assertIn("unknown profile", str(ctx.exception).lower())

    def test_does_not_require_homed_state(self):
        """Commission should not check homing, it works from cold boot."""
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "balanced"})
        d.commissioning.done = True
        d.commissioning.result = SAMPLE_COMMISSION_RESULT
        d.printer._objects["reactor"] = MockReactor()
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.commissioning.commission(gcmd)

    def test_waits_for_disable_to_flush_before_requesting_commission(self):
        """A pending motor_disable must be flushed before run_commission is sent.

        motor_disable() only schedules the MCU command at the toolhead's last
        move time; nothing flushes it. Without a second wait_moves() after
        disabling, run_commission can reach the firmware first, which still
        sees the motor enabled and rejects the commission.
        """
        d = make_driver()
        d.printer._objects["configfile"] = MockConfigFile()
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
        enable_line._enabled = True
        gcmd = MockGCmd({"PROFILE": "balanced"})

        calls = []
        toolhead = d.printer.lookup_object("toolhead")
        original_wait_moves = toolhead.wait_moves
        original_motor_disable = enable_line.motor_disable

        def recording_wait_moves():
            calls.append("wait_moves")
            original_wait_moves()

        def recording_motor_disable(print_time):
            calls.append("motor_disable")
            original_motor_disable(print_time)

        def recording_run_commission(_args):
            calls.append("run_commission")
            d.commissioning.result = complete_commission_result()
            d.commissioning.done = True

        toolhead.wait_moves = recording_wait_moves
        enable_line.motor_disable = recording_motor_disable
        d.protocol.commands.commission.send = recording_run_commission

        d.commissioning.commission(gcmd)

        disable_index = calls.index("motor_disable")
        commission_index = calls.index("run_commission")
        assert any(call == "wait_moves" for call in calls[disable_index + 1 : commission_index]), (
            f"expected a wait_moves() flush between motor_disable and run_commission, got {calls}"
        )

    def test_does_not_require_prior_commissioning(self):
        """Commission works on virgin hardware (no prior gains)."""
        d = make_driver()
        d.state.active_gains = None
        d.state.runtime_status = "uncommissioned"
        gcmd = MockGCmd({"PROFILE": "balanced"})
        d.commissioning.done = True
        d.commissioning.result = SAMPLE_COMMISSION_RESULT
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.commissioning.commission(gcmd)

    def test_commission_failure_reports_diagnostics(self):
        d = make_driver()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        def drive_failure(_args):
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
            d.commissioning.handle_commission_phase({"phase": 0, "status": 8})

        d.protocol.commands.commission.send = drive_failure

        with self.assertRaises(CommandError):
            d.commissioning.commission(gcmd)

        self.assertNotIn("commissioning diagnostics", gcmd.last_info)
        self.assertNotIn("legacy inductance fit rejected", gcmd.last_info)
        self.assertNotIn("usable_points=0", gcmd.last_info)
        self.assertNotIn("selected_mask=0x0000", gcmd.last_info)
        self.assertTrue(gcmd.last_info.startswith("FOCI_SETUP manual_stepper stepper_x: FAILED"))
        self.assertIn("electrical identification failed", gcmd.last_info)


def test_commission_timeout_prints_failed_summary():
    d = make_driver()
    d.printer._objects["reactor"] = MockReactor()
    gcmd = MockGCmd({"PROFILE": "balanced"})

    def never_finish(_args):
        pass

    d.protocol.commands.commission.send = never_finish
    with pytest.raises(CommandError, match="timed out"):
        d.commissioning.commission(gcmd)
    assert gcmd.last_info.startswith("FOCI_SETUP manual_stepper stepper_x: FAILED")
    assert "timed out" in gcmd.last_info


def test_commission_success_prints_succeeded_summary():
    d = make_driver()
    d.printer._objects["configfile"] = MockConfigFile()

    def drive_success(_args):
        d.commissioning.result = complete_commission_result()
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_success
    gcmd = MockGCmd({"PROFILE": "balanced"})
    d.commissioning.commission(gcmd)

    assert gcmd._responses[0].startswith("FOCI_SETUP manual_stepper stepper_x: SUCCEEDED")
    assert "r_count_milli" not in gcmd._responses[0]
    assert "bandwidth_hz" not in gcmd._responses[0]


def test_commission_succeeds_with_no_diagnostics_package_installed(monkeypatch):
    monkeypatch.setattr("klipper_foci.registry.entry_points", lambda *, group: [])
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()
    printer._objects["configfile"] = MockConfigFile()

    def drive_success(_args):
        driver.commissioning.result = complete_commission_result()
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_success
    gcmd = MockGCmd({"PROFILE": "balanced"})

    driver.commissioning.commission(gcmd)

    assert gcmd._responses[0].startswith("FOCI_SETUP stepper_x: SUCCEEDED")


def test_commission_skipped_gain_floor_warns_the_operator_without_debug():
    d = make_driver()
    d.printer._objects["configfile"] = MockConfigFile()
    d.global_config.debug = False

    def drive_success(_args):
        result = complete_commission_result()
        result["inner_warning_flags"] = 1 << 7
        d.commissioning.result = result
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_success
    gcmd = MockGCmd({"PROFILE": "balanced"})
    d.commissioning.commission(gcmd)

    assert gcmd._responses[0].startswith("FOCI_SETUP manual_stepper stepper_x: SUCCEEDED")
    assert any("gain floor skipped" in r for r in gcmd._responses[1:])


def test_commission_timing_evidence_rejected_prints_failed_summary():
    d = make_driver()
    result = complete_commission_result()
    result["timing_summary"] = 2 << 4 | 1 << 6

    def drive_rejected_timing(_args):
        d.commissioning.handle_commission_timing(
            timing_reply(method=2, status=2, requested_period_us=160)
        )
        d.commissioning.result = result
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_rejected_timing
    gcmd = MockGCmd({"PROFILE": "balanced"})

    with pytest.raises(CommandError, match="timing evidence rejected"):
        d.commissioning.commission(gcmd)

    assert gcmd.last_info == (
        "FOCI_SETUP manual_stepper stepper_x: FAILED, timing evidence was rejected."
    )


def test_commission_terminal_status_failure_prints_failed_summary():
    d = make_driver()
    result = complete_commission_result()
    result["status"] = 7  # "encoder fault" in COMMISSION_REASON_NAMES

    def drive_terminal_failure(_args):
        d.commissioning.result = result
        d.commissioning.done = True

    d.protocol.commands.commission.send = drive_terminal_failure
    gcmd = MockGCmd({"PROFILE": "balanced"})

    with pytest.raises(CommandError, match="encoder fault"):
        d.commissioning.commission(gcmd)

    assert gcmd.last_info == ("FOCI_SETUP manual_stepper stepper_x: FAILED, encoder fault.")
