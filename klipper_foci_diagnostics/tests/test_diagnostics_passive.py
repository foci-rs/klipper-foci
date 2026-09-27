"""Tests for the FOCI read-only diagnostic stats commands."""

import pytest
from mocks import (
    CommandError,
    MockCartesianKinematics,
    MockCommand,
    MockGCmd,
    MockStepper,
    make_driver,
)

from klipper_foci_diagnostics.passive import DiagnosticsPassive


def make_watermark_driver(response):
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.protocol.commands.stack_watermark = MockCommand(response)
    return driver


def test_step_position_diagnostic_reports_raw_host_and_klipper_delta():
    stepper = MockStepper(
        "stepper_x",
        oid=10,
        mcu_position=15000,
        dir_inverted=True,
        step_dist=0.01,
    )
    kin = MockCartesianKinematics([[stepper]])
    driver = make_driver(stepper_name="stepper_x", kinematics=kin)
    driver.oid = 10
    driver.protocol.commands.stepper_get_position = MockCommand({"pos": -19176})
    gcmd = MockGCmd()
    passive = DiagnosticsPassive(driver)

    passive.step_position(gcmd)

    assert driver.protocol.commands.stepper_get_position.last_args == [10]
    assert "FOCI_STEP_POSITION stepper_x:" in gcmd.last_info
    assert "raw=-19176" in gcmd.last_info
    assert "host=19176" in gcmd.last_info
    assert "klipper=15000" in gcmd.last_info
    assert "delta=4176" in gcmd.last_info
    assert "invert_dir=1" in gcmd.last_info
    assert "step_dist=0.010000" in gcmd.last_info
    assert "delta_mm=41.760" in gcmd.last_info


def test_step_position_diagnostic_leaves_non_inverted_raw_position_unchanged():
    stepper = MockStepper(
        "stepper_y",
        oid=12,
        mcu_position=8000,
        dir_inverted=False,
        step_dist=0.01,
    )
    kin = MockCartesianKinematics([[stepper]])
    driver = make_driver(stepper_name="stepper_y", kinematics=kin)
    driver.oid = 12
    driver.protocol.commands.stepper_get_position = MockCommand({"pos": 8125})
    gcmd = MockGCmd()
    passive = DiagnosticsPassive(driver)

    passive.step_position(gcmd)

    assert driver.protocol.commands.stepper_get_position.last_args == [12]
    assert "raw=8125" in gcmd.last_info
    assert "host=8125" in gcmd.last_info
    assert "klipper=8000" in gcmd.last_info
    assert "delta=125" in gcmd.last_info
    assert "invert_dir=0" in gcmd.last_info
    assert "delta_mm=1.250" in gcmd.last_info


def test_stepper_stats_keeps_derived_keys():
    """Derived fields dropped from the wire must still be printed.

    The exec-stats reply keeps only the fields the firmware cannot derive
    host-side; `stepper_stats()` must still print every key the
    FOCI_STEPPER_STATS line printed before the trim, computed from
    `planner_steps_per_rev`/`encoder_ppr` and the MCU's `CLOCK_FREQ`
    (84 MHz here, from `mocks.py::make_driver`'s default constants).
    It must also print the `oversize_frame_drops` counter.
    """
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.protocol.commands.stepper_stats = MockCommand(
        {
            "oid": 10,
            "channel": 0,
            "position": -26360,
            "queued_segments": 196,
            "queued_steps": 45150,
            "loaded_segments": 151,
            "loaded_steps": 39538,
            "discarded_segments": 2,
            "discarded_steps": 500,
            "timer_active": 0,
            "queue_len": 0,
            "oversize_frame_drops": 0,
        }
    )
    driver.protocol.commands.stepper_exec_stats = MockCommand(
        {
            "executed_pos_steps": 39538,
            "executed_neg_steps": 0,
            "physical_pos_pulses": 50609,
            "physical_neg_pulses": 3,
            "planner_steps_per_rev": 3200,
            "encoder_ppr": 1000,
            "queue_empty_count": 0,
            "missed_deadline_count": 0,
        }
    )
    driver.protocol.commands.stepper_timing_stats = MockCommand(
        {
            "activation_count": 2,
            "last_activation_clock": 123456,
            "first_load_now": 123584,
            "first_load_scheduled": 124000,
            "first_load_compare": 124000,
            "first_load_lead_ticks": 416,
            "first_load_compare_delay_ticks": 416,
            "first_step_clock": 124002,
            "first_step_delay_ticks": 546,
        }
    )
    driver.protocol.commands.stepper_stop_stats = MockCommand(
        {
            "stop_count": 1,
            "stop_drained_segments": 44,
            "stop_drained_steps": 11128,
            "reset_count": 1,
            "reset_drained_segments": 3,
            "reset_drained_steps": 750,
            "last_stop_reason": 4,
            "last_stop_remaining_events": 22448,
            "last_stop_queue_len": 44,
            "last_stop_drained_segments": 44,
            "last_stop_drained_steps": 11128,
        }
    )
    gcmd = MockGCmd()
    passive = DiagnosticsPassive(driver)

    passive.stepper_stats(gcmd)

    assert driver.protocol.commands.stepper_stats.last_args == [10]
    assert driver.protocol.commands.stepper_exec_stats.last_args == [10]
    assert driver.protocol.commands.stepper_timing_stats.last_args == [10]
    assert driver.protocol.commands.stepper_stop_stats.last_args == [10]
    assert "FOCI_STEPPER_STATS stepper_x:" in gcmd.last_info
    assert "channel=0" in gcmd.last_info
    assert "position=-26360" in gcmd.last_info
    assert "queued_segments=196" in gcmd.last_info
    assert "queued_steps=45150" in gcmd.last_info
    assert "loaded_segments=151" in gcmd.last_info
    assert "loaded_steps=39538" in gcmd.last_info
    assert "executed_pos_steps=39538" in gcmd.last_info
    assert "executed_neg_steps=0" in gcmd.last_info
    assert "physical_pos_pulses=50609" in gcmd.last_info
    assert "physical_neg_pulses=3" in gcmd.last_info
    assert "planner_steps_per_rev=3200" in gcmd.last_info
    assert "encoder_ppr=1000" in gcmd.last_info
    assert "encoder_counts_per_rev=4000" in gcmd.last_info
    assert "tmc_grid=4096" in gcmd.last_info
    assert "physical_step_width=16" in gcmd.last_info
    assert "motion_scale_configured=1" in gcmd.last_info
    assert "step_half_period_ticks=4" in gcmd.last_info
    assert "dir_setup_ticks=8" in gcmd.last_info
    assert "waveform_worst_case_ticks=24" in gcmd.last_info
    assert "fatal_lateness_ticks=84000" in gcmd.last_info
    assert "activation_count=2" in gcmd.last_info
    assert "last_activation_clock=123456" in gcmd.last_info
    assert "first_load_now=123584" in gcmd.last_info
    assert "first_load_scheduled=124000" in gcmd.last_info
    assert "first_load_compare=124000" in gcmd.last_info
    assert "first_load_lead_ticks=416" in gcmd.last_info
    assert "first_load_compare_delay_ticks=416" in gcmd.last_info
    assert "first_step_clock=124002" in gcmd.last_info
    assert "first_step_delay_ticks=546" in gcmd.last_info
    assert "discarded_segments=2" in gcmd.last_info
    assert "discarded_steps=500" in gcmd.last_info
    assert "queue_empty_count=0" in gcmd.last_info
    assert "missed_deadline_count=0" in gcmd.last_info
    assert "stop_count=1" in gcmd.last_info
    assert "stop_drained_segments=44" in gcmd.last_info
    assert "stop_drained_steps=11128" in gcmd.last_info
    assert "reset_count=1" in gcmd.last_info
    assert "reset_drained_segments=3" in gcmd.last_info
    assert "reset_drained_steps=750" in gcmd.last_info
    assert "last_stop_reason=4" in gcmd.last_info
    assert "last_stop_remaining_events=22448" in gcmd.last_info
    assert "last_stop_queue_len=44" in gcmd.last_info
    assert "last_stop_drained_segments=44" in gcmd.last_info
    assert "last_stop_drained_steps=11128" in gcmd.last_info
    assert "timer_active=0" in gcmd.last_info
    assert "queue_len=0" in gcmd.last_info
    assert "oversize_frame_drops=0" in gcmd.last_info


def test_stack_watermark_reports_headroom_and_painted_span():
    driver = make_watermark_driver(
        {
            "oid": 10,
            "stack_unused_bytes": 40960,
            "painted_bytes": 97280,
            "status": 0,
        }
    )
    gcmd = MockGCmd()
    passive = DiagnosticsPassive(driver)

    passive.stack_watermark(gcmd)

    assert driver.protocol.commands.stack_watermark.last_args == [10]
    assert "stack_unused_bytes=40960" in gcmd.last_info
    assert "painted_bytes=97280" in gcmd.last_info
    assert "lower bound" not in gcmd.last_info


def test_stack_watermark_flags_a_truncated_scan_as_a_lower_bound():
    driver = make_watermark_driver(
        {
            "oid": 10,
            "stack_unused_bytes": 32768,
            "painted_bytes": 97280,
            "status": 2,
        }
    )
    gcmd = MockGCmd()
    passive = DiagnosticsPassive(driver)

    passive.stack_watermark(gcmd)

    assert "stack_unused_bytes=32768" in gcmd.last_info
    assert "lower bound" in gcmd.last_info


def test_stack_watermark_rejects_a_board_that_never_painted():
    driver = make_watermark_driver(
        {"oid": 10, "stack_unused_bytes": 0, "painted_bytes": 0, "status": 1}
    )
    passive = DiagnosticsPassive(driver)

    with pytest.raises(CommandError, match="did not paint"):
        passive.stack_watermark(MockGCmd())


def test_stack_watermark_reports_a_firmware_refusal_during_motion():
    driver = make_watermark_driver(
        {"oid": 10, "stack_unused_bytes": 0, "painted_bytes": 0, "status": 3}
    )
    passive = DiagnosticsPassive(driver)

    with pytest.raises(CommandError, match="refused while motion is active"):
        passive.stack_watermark(MockGCmd())


def test_stack_watermark_rejects_an_unknown_status():
    driver = make_watermark_driver(
        {"oid": 10, "stack_unused_bytes": 0, "painted_bytes": 0, "status": 9}
    )
    passive = DiagnosticsPassive(driver)

    with pytest.raises(CommandError, match="unknown status=9"):
        passive.stack_watermark(MockGCmd())


def test_stack_watermark_rejects_an_incomplete_reply():
    driver = make_watermark_driver({"oid": 10, "status": 0})
    passive = DiagnosticsPassive(driver)

    with pytest.raises(CommandError, match="incomplete data"):
        passive.stack_watermark(MockGCmd())


def test_stack_watermark_rejects_a_missing_reply():
    driver = make_watermark_driver(None)
    passive = DiagnosticsPassive(driver)

    with pytest.raises(CommandError, match="returned no data"):
        passive.stack_watermark(MockGCmd())


def test_stack_watermark_requires_mcu_identify():
    driver = make_watermark_driver({"oid": 10})
    driver.oid = None
    passive = DiagnosticsPassive(driver)

    with pytest.raises(CommandError, match="before MCU identify"):
        passive.stack_watermark(MockGCmd())
