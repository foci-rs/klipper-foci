"""Pure formatting helpers for FOCI diagnostics."""

from __future__ import annotations

CPU_CYCLES_PER_US_BY_MCU: dict[str, int] = {
    "stm32f407xx": 168,
    "stm32h723xx": 520,
}
DEFAULT_CPU_CYCLES_PER_US = CPU_CYCLES_PER_US_BY_MCU["stm32f407xx"]


def cpu_cycles_per_us(mcu) -> int:
    """Return this board's CPU-cycle counter frequency in cycles/us.

    Resolved from the `MCU` constant Klipper's MCU protocol object reports
    (e.g. "stm32f407xx", "stm32h723xx" — the literal `MCU` constant each
    board's firmware publishes). Falls back to the OpenFFBoard value when
    the constant is missing or unrecognized, so diagnostics degrade to the
    historical behavior rather than crashing.
    """
    get_constants = getattr(mcu, "get_constants", None)
    constants = get_constants() if get_constants is not None else {}
    return CPU_CYCLES_PER_US_BY_MCU.get(constants.get("MCU"), DEFAULT_CPU_CYCLES_PER_US)


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
        f"FOCI_STEPPER_EVENT {stepper_name} reason={reason_name}({int(reason_code)}) channel="
        f"{int(params.get('channel', 255))} pos={int(params.get('position', 0))} clock="
        f"{int(params.get('clock', 0))} timer_active={int(params.get('timer_active', 0))} "
        f"queue_len={int(params.get('queue_len', 65535))} dir={int(params.get('direction', 0))} "
        f"data0={int(params.get('data0', 0))} data1={int(params.get('data1', 0))}"
    )


def format_stepper_perf_event(stepper_name: str, params: dict, cycles_per_us: int) -> str:
    """Format one fatal firmware step-dispatch performance snapshot."""
    reason_code = params.get("reason", 0)
    reason_name = STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")

    def cycles_to_us(field: str) -> int | str:
        value = params.get(field)
        if value is None:
            return "?"
        return int(value) // cycles_per_us

    return (
        f"FOCI_STEPPER_PERF_EVENT {stepper_name} reason={reason_name}({int(reason_code)}) channel="
        f"{int(params.get('channel', 255))} clock={int(params.get('clock', 0))} sample_count="
        f"{int(params.get('sample_count', 0))} crit_count={int(params.get('crit_count', 0))} "
        f"crit_max_cycles={int(params.get('crit_max_cycles', 0))} crit_max_site="
        f"{int(params.get('crit_max_site', 0))} crit_max_us={cycles_to_us('crit_max_cycles')} "
        f"crit_over_10us={int(params.get('crit_over_10us', 0))} crit_over_50us="
        f"{int(params.get('crit_over_50us', 0))} crit_over_100us="
        f"{int(params.get('crit_over_100us', 0))} crit_over_1000us="
        f"{int(params.get('crit_over_1000us', 0))} queue_step_count="
        f"{int(params.get('queue_step_count', 0))} queue_step_max_cycles="
        f"{int(params.get('queue_step_max_cycles', 0))} queue_step_max_us="
        f"{cycles_to_us('queue_step_max_cycles')} shutdown_site_count="
        f"{int(params.get('shutdown_site_count', 0))} shutdown_site_max_cycles="
        f"{int(params.get('shutdown_site_max_cycles', 0))} reset_site_count="
        f"{int(params.get('reset_site_count', 0))} reset_site_max_cycles="
        f"{int(params.get('reset_site_max_cycles', 0))} trigger_stop_site_count="
        f"{int(params.get('trigger_stop_site_count', 0))} trigger_stop_site_max_cycles="
        f"{int(params.get('trigger_stop_site_max_cycles', 0))} tim5_activation_count="
        f"{int(params.get('tim5_activation_count', 0))} tim5_irq_max_cycles="
        f"{int(params.get('tim5_irq_max_cycles', 0))} tim5_irq_max_us="
        f"{cycles_to_us('tim5_irq_max_cycles')} tim5_dispatch_max_cycles="
        f"{int(params.get('tim5_dispatch_max_cycles', 0))} tim5_dispatch_max_us="
        f"{cycles_to_us('tim5_dispatch_max_cycles')} tim5_dispatch_max_cycles_events="
        f"{int(params.get('tim5_dispatch_max_cycles_events', 0))} tim5_events_max_per_irq="
        f"{int(params.get('tim5_events_max_per_irq', 0))} tim5_event_count_total="
        f"{int(params.get('tim5_event_count_total', 0))} tim5_defer_count="
        f"{int(params.get('tim5_defer_count', 0))} tim5_empty_count="
        f"{int(params.get('tim5_empty_count', 0))} tim5_events_last_activation="
        f"{int(params.get('tim5_events_last_activation', 0))} tim5_burst_cycles_per_event_max="
        f"{int(params.get('tim5_burst_cycles_per_event_max', 0))} "
        f"tim5_burst_cycles_per_event_max_cycles="
        f"{int(params.get('tim5_burst_cycles_per_event_max_cycles', 0))} "
        f"tim5_burst_cycles_per_event_max_events="
        f"{int(params.get('tim5_burst_cycles_per_event_max_events', 0))} "
        f"tim5_burst_cycles_per_event_floor3_max="
        f"{int(params.get('tim5_burst_cycles_per_event_floor3_max', 0))} "
        f"tim5_entry_latency_max_ticks={int(params.get('tim5_entry_latency_max_ticks', 0))} "
        f"tim5_pop_lateness_max_ticks={int(params.get('tim5_pop_lateness_max_ticks', 0))} "
        f"scheduler_cycles_max={int(params.get('scheduler_cycles_max', 0))} "
        f"scheduler_cycles_events_at_max={int(params.get('scheduler_cycles_events_at_max', 0))} "
        f"scheduler_cycles_per_event_max={int(params.get('scheduler_cycles_per_event_max', 0))} "
        f"scheduler_cycles_per_event_max_cycles="
        f"{int(params.get('scheduler_cycles_per_event_max_cycles', 0))} "
        f"scheduler_cycles_per_event_max_events="
        f"{int(params.get('scheduler_cycles_per_event_max_events', 0))} "
        f"scheduler_cycles_per_event_floor3_max="
        f"{int(params.get('scheduler_cycles_per_event_floor3_max', 0))} scheduler_full_count="
        f"{int(params.get('scheduler_full_count', 0))} stepper_load_lateness_max_ticks="
        f"{int(params.get('stepper_load_lateness_max_ticks', 0))} stepper_load_lateness_last_ticks="
        f"{int(params.get('stepper_load_lateness_last_ticks', 0))} build_trace_enabled="
        f"{int(params.get('build_trace_enabled', 0))}"
    )
