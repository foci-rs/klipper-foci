"""Pure formatting helpers for FOCI diagnostics."""

from __future__ import annotations

OPENFFBOARD_CPU_CYCLES_PER_US = 168

STEPPER_EVENT_REASON_NAMES: dict[int, str] = {
    1: "queue_empty",
    2: "missed_deadline_load",
    3: "missed_deadline_step",
    4: "trsync_stop",
    5: "p1_stop",
    6: "reset_step_clock",
    7: "tmc_disable_signal",
}


def stepper_dir_inverted(stepper) -> bool:
    """Return whether a Klipper stepper's direction is inverted."""
    get_dir_inverted = getattr(stepper, "get_dir_inverted", None)
    if get_dir_inverted is None:
        return False
    dir_info = get_dir_inverted()
    if isinstance(dir_info, (list, tuple)):
        return bool(dir_info[0])
    return bool(dir_info)


def format_stepper_event(stepper_name: str, params: dict) -> str:
    """Format one firmware stepper diagnostic event."""
    reason_code = params.get("reason", 0)
    reason_name = STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")
    return (
        "FOCI_STEPPER_EVENT %s reason=%s(%d) channel=%d pos=%d"
        " clock=%d timer_active=%d queue_len=%d dir=%d data0=%d data1=%d"
        % (
            stepper_name,
            reason_name,
            reason_code,
            params.get("channel", 255),
            params.get("position", 0),
            params.get("clock", 0),
            params.get("timer_active", 0),
            params.get("queue_len", 65535),
            params.get("direction", 0),
            params.get("data0", 0),
            params.get("data1", 0),
        )
    )


def format_stepper_perf_event(stepper_name: str, params: dict) -> str:
    """Format one fatal firmware step-dispatch performance snapshot."""
    reason_code = params.get("reason", 0)
    reason_name = STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")

    def cycles_to_us(field: str) -> int | str:
        value = params.get(field)
        if value is None:
            return "?"
        return int(value) // OPENFFBOARD_CPU_CYCLES_PER_US

    return (
        "FOCI_STEPPER_PERF_EVENT %s reason=%s(%d) channel=%d clock=%d"
        " sample_count=%d crit_count=%d crit_max_cycles=%d crit_max_site=%d"
        " crit_max_us=%s crit_over_10us=%d crit_over_50us=%d"
        " crit_over_100us=%d crit_over_1000us=%d queue_step_count=%d"
        " queue_step_max_cycles=%d queue_step_max_us=%s"
        " tim5_activation_count=%d"
        " tim5_irq_max_cycles=%d tim5_irq_max_us=%s"
        " tim5_dispatch_max_cycles=%d tim5_dispatch_max_us=%s"
        " tim5_dispatch_max_cycles_events=%d"
        " tim5_events_max_per_irq=%d"
        " tim5_event_count_total=%d tim5_defer_count=%d"
        " tim5_empty_count=%d tim5_events_last_activation=%d"
        " tim5_burst_cycles_per_event_max=%d"
        " tim5_burst_cycles_per_event_max_cycles=%d"
        " tim5_burst_cycles_per_event_max_events=%d"
        " tim5_burst_cycles_per_event_floor3_max=%d"
        " tim5_entry_latency_max_ticks=%d tim5_pop_lateness_max_ticks=%d"
        " scheduler_cycles_max=%d scheduler_cycles_events_at_max=%d"
        " scheduler_cycles_per_event_max=%d"
        " scheduler_cycles_per_event_max_cycles=%d"
        " scheduler_cycles_per_event_max_events=%d"
        " scheduler_cycles_per_event_floor3_max=%d scheduler_full_count=%d"
        " stepper_load_lateness_max_ticks=%d"
        " stepper_load_lateness_last_ticks=%d build_trace_enabled=%d"
        % (
            stepper_name,
            reason_name,
            reason_code,
            params.get("channel", 255),
            params.get("clock", 0),
            params.get("sample_count", 0),
            params.get("crit_count", 0),
            params.get("crit_max_cycles", 0),
            params.get("crit_max_site", 0),
            cycles_to_us("crit_max_cycles"),
            params.get("crit_over_10us", 0),
            params.get("crit_over_50us", 0),
            params.get("crit_over_100us", 0),
            params.get("crit_over_1000us", 0),
            params.get("queue_step_count", 0),
            params.get("queue_step_max_cycles", 0),
            cycles_to_us("queue_step_max_cycles"),
            params.get("tim5_activation_count", 0),
            params.get("tim5_irq_max_cycles", 0),
            cycles_to_us("tim5_irq_max_cycles"),
            params.get("tim5_dispatch_max_cycles", 0),
            cycles_to_us("tim5_dispatch_max_cycles"),
            params.get("tim5_dispatch_max_cycles_events", 0),
            params.get("tim5_events_max_per_irq", 0),
            params.get("tim5_event_count_total", 0),
            params.get("tim5_defer_count", 0),
            params.get("tim5_empty_count", 0),
            params.get("tim5_events_last_activation", 0),
            params.get("tim5_burst_cycles_per_event_max", 0),
            params.get("tim5_burst_cycles_per_event_max_cycles", 0),
            params.get("tim5_burst_cycles_per_event_max_events", 0),
            params.get("tim5_burst_cycles_per_event_floor3_max", 0),
            params.get("tim5_entry_latency_max_ticks", 0),
            params.get("tim5_pop_lateness_max_ticks", 0),
            params.get("scheduler_cycles_max", 0),
            params.get("scheduler_cycles_events_at_max", 0),
            params.get("scheduler_cycles_per_event_max", 0),
            params.get("scheduler_cycles_per_event_max_cycles", 0),
            params.get("scheduler_cycles_per_event_max_events", 0),
            params.get("scheduler_cycles_per_event_floor3_max", 0),
            params.get("scheduler_full_count", 0),
            params.get("stepper_load_lateness_max_ticks", 0),
            params.get("stepper_load_lateness_last_ticks", 0),
            params.get("build_trace_enabled", 0),
        )
    )
