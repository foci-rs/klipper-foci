"""Tests for no-motion FOCI stepper execution statistics."""

from tests.mocks import MockCommand, MockGCmd, make_driver


def test_stepper_stats_diagnostic_formats_firmware_counters():
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
            "encoder_counts_per_rev": 4000,
            "tmc_grid": 4096,
            "physical_step_width": 16,
            "motion_scale_configured": 1,
            "step_half_period_ticks": 4,
            "dir_setup_ticks": 8,
            "waveform_worst_case_ticks": 24,
            "fatal_lateness_ticks": 84000,
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

    driver.diagnostics.stepper_stats(gcmd)

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
