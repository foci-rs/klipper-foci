"""Tests for no-motion FOCI stepper execution statistics."""

import re
from pathlib import Path

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
            "shutdown_site_count": 3,
            "shutdown_site_max_cycles": 6000,
            "reset_site_count": 2,
            "reset_site_max_cycles": 4200,
            "trigger_stop_site_count": 15,
            "trigger_stop_site_max_cycles": 900,
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
    assert "queue_step_max_cycles=175000" in gcmd.last_info
    assert "queue_step_max_us=1041" in gcmd.last_info
    assert "shutdown_site_count=3" in gcmd.last_info
    assert "reset_site_count=2" in gcmd.last_info
    assert "trigger_stop_site_count=15" in gcmd.last_info
    assert "tim5_irq_max_cycles=2400" in gcmd.last_info
    assert "tim5_irq_max_us=14" in gcmd.last_info
    assert "tim5_dispatch_max_cycles=2100" in gcmd.last_info
    assert "tim5_dispatch_max_cycles_events=5" in gcmd.last_info
    assert "tim5_events_max_per_irq=3" in gcmd.last_info
    assert "tim5_event_count_total=800" in gcmd.last_info
    assert "tim5_defer_count=5" in gcmd.last_info
    assert "tim5_burst_cycles_per_event_max_cycles=2100" in gcmd.last_info
    assert "tim5_burst_cycles_per_event_max_events=3" in gcmd.last_info
    assert "tim5_entry_latency_max_ticks=8400" in gcmd.last_info
    assert "tim5_pop_lateness_max_ticks=41" in gcmd.last_info
    assert "scheduler_cycles_max=555" in gcmd.last_info
    assert "scheduler_cycles_events_at_max=4" in gcmd.last_info
    assert "scheduler_full_count=2" in gcmd.last_info
    assert "stepper_load_lateness_max_ticks=1234" in gcmd.last_info
    assert "build_trace_enabled=0" in gcmd.last_info


def test_dispatch_stats_diagnostic_reports_cumulative_occupancy():
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.protocol.commands.stepper_perf_stats = MockCommand(
        {
            "oid": 10,
            "channel": 0,
            "crit_max_cycles": 0,
            "crit_max_site": 0,
            "crit_over_10us": 0,
            "crit_over_50us": 0,
            "crit_over_100us": 0,
            "crit_over_1000us": 0,
            "queue_step_count": 0,
            "queue_step_max_cycles": 0,
            "shutdown_site_count": 0,
            "shutdown_site_max_cycles": 0,
            "reset_site_count": 0,
            "reset_site_max_cycles": 0,
            "trigger_stop_site_count": 0,
            "trigger_stop_site_max_cycles": 0,
            "tim5_activation_count": 10,
            "tim5_irq_max_cycles": 0,
            "tim5_dispatch_max_cycles": 0,
            "tim5_dispatch_max_cycles_events": 0,
            "tim5_events_max_per_irq": 0,
            "tim5_event_count_total": 100,
            "tim5_defer_count": 0,
            "tim5_burst_cycles_per_event_max_cycles": 0,
            "tim5_burst_cycles_per_event_max_events": 0,
            "tim5_burst_cycles_per_event_floor3_max": 0,
            "tim5_entry_latency_max_ticks": 0,
            "tim5_pop_lateness_max_ticks": 0,
            "scheduler_cycles_max": 0,
            "scheduler_cycles_events_at_max": 0,
            "scheduler_cycles_per_event_max": 0,
            "scheduler_cycles_per_event_floor3_max": 0,
            "scheduler_full_count": 0,
            "stepper_load_lateness_max_ticks": 0,
            "stepper_load_lateness_last_ticks": 0,
            "build_trace_enabled": 0,
            "total_irq_cycles_lo": 1_000,
            "total_irq_cycles_hi": 2,
            "total_dispatch_cycles_lo": 500,
            "total_dispatch_cycles_hi": 1,
            "elapsed_cycles_lo": 2_000,
            "elapsed_cycles_hi": 4,
        }
    )
    gcmd = MockGCmd({"RESET": 0})

    driver.diagnostics.dispatch_stats(gcmd)

    # Non-zero, distinct high words on every pair, so a bit-shift bug (wrong
    # shift amount, swapped lo/hi, or a silently-dropped high word) would
    # fail this test even though it would pass with all-zero high words.
    assert "total_irq_cycles_lo=1000" in gcmd.last_info
    assert "total_irq_cycles_hi=2" in gcmd.last_info
    assert "total_dispatch_cycles_lo=500" in gcmd.last_info
    assert "total_dispatch_cycles_hi=1" in gcmd.last_info
    assert "elapsed_cycles_lo=2000" in gcmd.last_info
    assert "elapsed_cycles_hi=4" in gcmd.last_info
    # Checked as one contiguous ordered substring, not six independent
    # membership checks, so a transcription slip in the Python fields list
    # (wrong order, a dropped field) fails this test even though every field
    # is still present somewhere in the output.
    assert (
        "total_irq_cycles_lo=1000 total_irq_cycles_hi=2"
        " total_dispatch_cycles_lo=500 total_dispatch_cycles_hi=1"
        " elapsed_cycles_lo=2000 elapsed_cycles_hi=4"
    ) in gcmd.last_info
    assert "total_irq_cycles=8589935592" in gcmd.last_info  # (2 << 32) | 1000
    assert "total_dispatch_cycles=4294967796" in gcmd.last_info  # (1 << 32) | 500
    assert "elapsed_cycles=17179871184" in gcmd.last_info  # (4 << 32) | 2000
    assert "tim5_irq_occupancy_pct=50" in gcmd.last_info  # 8589935592 * 100 // 17179871184
    assert "tim5_dispatch_occupancy_pct=25" in gcmd.last_info  # 4294967796 * 100 // 17179871184
    assert "tim5_dispatch_cycles_per_event_avg=42949677" in gcmd.last_info  # 4294967796 // 100


def test_dispatch_stats_diagnostic_guards_zero_elapsed_and_zero_events():
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.protocol.commands.stepper_perf_stats = MockCommand(
        {
            "oid": 10,
            "channel": 0,
            "crit_max_cycles": 0,
            "crit_max_site": 0,
            "crit_over_10us": 0,
            "crit_over_50us": 0,
            "crit_over_100us": 0,
            "crit_over_1000us": 0,
            "queue_step_count": 0,
            "queue_step_max_cycles": 0,
            "shutdown_site_count": 0,
            "shutdown_site_max_cycles": 0,
            "reset_site_count": 0,
            "reset_site_max_cycles": 0,
            "trigger_stop_site_count": 0,
            "trigger_stop_site_max_cycles": 0,
            "tim5_activation_count": 0,
            "tim5_irq_max_cycles": 0,
            "tim5_dispatch_max_cycles": 0,
            "tim5_dispatch_max_cycles_events": 0,
            "tim5_events_max_per_irq": 0,
            "tim5_event_count_total": 0,
            "tim5_defer_count": 0,
            "tim5_burst_cycles_per_event_max_cycles": 0,
            "tim5_burst_cycles_per_event_max_events": 0,
            "tim5_burst_cycles_per_event_floor3_max": 0,
            "tim5_entry_latency_max_ticks": 0,
            "tim5_pop_lateness_max_ticks": 0,
            "scheduler_cycles_max": 0,
            "scheduler_cycles_events_at_max": 0,
            "scheduler_cycles_per_event_max": 0,
            "scheduler_cycles_per_event_floor3_max": 0,
            "scheduler_full_count": 0,
            "stepper_load_lateness_max_ticks": 0,
            "stepper_load_lateness_last_ticks": 0,
            "build_trace_enabled": 0,
            "total_irq_cycles_lo": 0,
            "total_irq_cycles_hi": 0,
            "total_dispatch_cycles_lo": 0,
            "total_dispatch_cycles_hi": 0,
            "elapsed_cycles_lo": 0,
            "elapsed_cycles_hi": 0,
        }
    )
    gcmd = MockGCmd({"RESET": 1})

    driver.diagnostics.dispatch_stats(gcmd)

    assert "tim5_irq_occupancy_pct=?" in gcmd.last_info
    assert "tim5_dispatch_occupancy_pct=?" in gcmd.last_info
    assert "tim5_dispatch_cycles_per_event_avg=?" in gcmd.last_info


def test_dispatch_stats_diagnostic_uses_ouroboros_cpu_clock():
    driver = make_driver(stepper_name="stepper_x")
    driver.oid = 10
    driver.mcu.constants["MCU"] = "stm32h723xx"
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
            "shutdown_site_count": 3,
            "shutdown_site_max_cycles": 6000,
            "reset_site_count": 2,
            "reset_site_max_cycles": 4200,
            "trigger_stop_site_count": 15,
            "trigger_stop_site_max_cycles": 900,
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

    assert "crit_max_us=365" in gcmd.last_info
    assert "queue_step_max_us=336" in gcmd.last_info
    assert "tim5_irq_max_us=4" in gcmd.last_info
    assert "tim5_dispatch_max_us=4" in gcmd.last_info


def _rust_reply_field_order(struct_name: str) -> list[str]:
    replies_path = (
        Path(__file__).resolve().parents[3]
        / "shared"
        / "foci-firmware"
        / "src"
        / "ankyra"
        / "replies.rs"
    )
    text = replies_path.read_text()
    match = re.search(rf"pub struct {struct_name} \{{(.*?)\n\}}", text, re.DOTALL)
    assert match, f"{struct_name} not found in {replies_path}"
    fields = re.findall(r"pub (\w+):", match.group(1))
    assert fields, f"no fields parsed from {struct_name} in {replies_path}"
    return fields


def _python_response_field_order() -> list[str]:
    commands_path = Path(__file__).resolve().parents[1] / "protocol" / "commands.py"
    text = commands_path.read_text()
    match = re.search(r"STEPPER_PERF_STATS_RESPONSE = \((.*?)\n    \)", text, re.DOTALL)
    assert match, f"STEPPER_PERF_STATS_RESPONSE not found in {commands_path}"
    literal = "".join(re.findall(r'"([^"]*)"', match.group(1)))
    fields = re.findall(r"(\w+)=%", literal)
    assert fields, f"no fields parsed from STEPPER_PERF_STATS_RESPONSE in {commands_path}"
    return fields


def test_perf_stats_reply_field_order_matches_wire_response():
    rust_fields = _rust_reply_field_order("FociStepperPerfStatsResult")
    python_fields = _python_response_field_order()
    assert rust_fields == python_fields
