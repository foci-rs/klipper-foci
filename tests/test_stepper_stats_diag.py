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


def test_dispatch_stats_diagnostic_formats_perf_counters_and_reset_flag():
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.protocol.commands.stepper_perf_stats = MockCommand(
        {
            "oid": 10,
            "channel": 0,
            "crit_max_cycles": 190000,
            "crit_max_site": 1,
            "crit_over_10us": 9,
            "crit_over_50us": 4,
            "crit_over_100us": 2,
            "crit_over_1000us": 1,
            "queue_step_count": 23,
            "queue_step_max_cycles": 175000,
            "tim5_activation_count": 400,
            "tim5_irq_max_cycles": 2400,
            "tim5_dispatch_max_cycles": 2100,
            "tim5_dispatch_max_cycles_events": 5,
            "tim5_events_max_per_irq": 3,
            "tim5_event_count_total": 800,
            "tim5_defer_count": 5,
            "tim5_burst_cycles_per_event_max_cycles": 2100,
            "tim5_burst_cycles_per_event_max_events": 3,
            "tim5_burst_cycles_per_event_floor3_max": 700,
            "tim5_entry_latency_max_ticks": 8400,
            "tim5_pop_lateness_max_ticks": 41,
            "scheduler_cycles_max": 555,
            "scheduler_cycles_events_at_max": 4,
            "scheduler_cycles_per_event_max": 111,
            "scheduler_cycles_per_event_floor3_max": 111,
            "scheduler_full_count": 2,
            "stepper_load_lateness_max_ticks": 1234,
            "stepper_load_lateness_last_ticks": -20,
            "build_trace_enabled": 0,
        }
    )
    gcmd = MockGCmd({"RESET": 1})

    driver.diagnostics.dispatch_stats(gcmd)

    assert driver.protocol.commands.stepper_perf_stats.last_args == [10, 1]
    assert "FOCI_DISPATCH_STATS stepper_x:" in gcmd.last_info
    assert "channel=0" in gcmd.last_info
    assert "crit_max_cycles=190000" in gcmd.last_info
    assert "crit_max_site=1" in gcmd.last_info
    assert "crit_max_us=1130" in gcmd.last_info
    assert "crit_over_1000us=1" in gcmd.last_info
    assert "queue_step_max_cycles=175000" in gcmd.last_info
    assert "queue_step_max_us=1041" in gcmd.last_info
    assert "tim5_irq_max_cycles=2400" in gcmd.last_info
    assert "tim5_irq_max_us=14" in gcmd.last_info
    assert "tim5_dispatch_max_cycles=2100" in gcmd.last_info
    assert "tim5_dispatch_max_cycles_events=5" in gcmd.last_info
    assert "tim5_events_max_per_irq=3" in gcmd.last_info
    assert "tim5_event_count_total=800" in gcmd.last_info
    assert "tim5_defer_count=5" in gcmd.last_info
    assert "tim5_burst_cycles_per_event_max_cycles=2100" in gcmd.last_info
    assert "tim5_burst_cycles_per_event_max_events=3" in gcmd.last_info
    assert "tim5_burst_cycles_per_event_floor3_max=700" in gcmd.last_info
    assert "tim5_entry_latency_max_ticks=8400" in gcmd.last_info
    assert "tim5_pop_lateness_max_ticks=41" in gcmd.last_info
    assert "scheduler_cycles_max=555" in gcmd.last_info
    assert "scheduler_cycles_events_at_max=4" in gcmd.last_info
    assert "scheduler_cycles_per_event_max=111" in gcmd.last_info
    assert "scheduler_cycles_per_event_floor3_max=111" in gcmd.last_info
    assert "scheduler_full_count=2" in gcmd.last_info
    assert "stepper_load_lateness_max_ticks=1234" in gcmd.last_info
    assert "stepper_load_lateness_last_ticks=-20" in gcmd.last_info
    assert "build_trace_enabled=0" in gcmd.last_info
