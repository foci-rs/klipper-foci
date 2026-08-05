"""Passive FOCI diagnostic commands and response handlers."""

from __future__ import annotations

import logging

from .formatting import (
    OPENFFBOARD_CPU_CYCLES_PER_US,
    format_stepper_event,
    format_stepper_perf_event,
    stepper_dir_inverted,
)

log = logging.getLogger(__name__)


class PassiveDiagnostics:
    """Own read-only FOCI diagnostic commands and events."""

    def __init__(self, driver) -> None:
        self.driver = driver

    def handle_stepper_event(self, params: dict) -> None:
        """Handle bounded firmware stepper diagnostics."""
        message = format_stepper_event(self.driver.stepper_name, params)
        log.info(message)
        gcode = self.driver.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def handle_stepper_perf_event(self, params: dict) -> None:
        """Handle fatal firmware step-dispatch performance snapshots."""
        message = format_stepper_perf_event(self.driver.stepper_name, params)
        log.info(message)
        gcode = self.driver.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def step_position(self, gcmd) -> None:
        """Query raw MCU step position without updating Klipper state."""
        stepper = self.driver._find_linked_stepper()
        if stepper is None:
            raise gcmd.error(
                f"FOCI_STEP_POSITION could not find linked stepper {self.driver.stepper_name}"
            )

        params = self.driver.protocol.get_step_position()
        raw_position = int(params["pos"])
        invert_dir = stepper_dir_inverted(stepper)
        host_position = -raw_position if invert_dir else raw_position

        get_mcu_position = getattr(stepper, "get_mcu_position", None)
        klipper_position = None
        delta = None
        if get_mcu_position is not None:
            klipper_position = int(get_mcu_position())
            delta = host_position - klipper_position

        parts = [
            f"FOCI_STEP_POSITION {self.driver.stepper_name}:",
            f"raw={int(raw_position)}",
            f"host={int(host_position)}",
            f"klipper={klipper_position if klipper_position is not None else '?'}",
            f"delta={delta if delta is not None else '?'}",
            f"invert_dir={(1 if invert_dir else 0)}",
        ]

        get_step_dist = getattr(stepper, "get_step_dist", None)
        if get_step_dist is not None:
            step_dist = float(get_step_dist())
            parts.append(f"step_dist={step_dist:.6f}")
            if delta is not None:
                parts.append(f"delta_mm={delta * step_dist:.3f}")

        gcmd.respond_info(" ".join(parts))

    def stepper_stats(self, gcmd) -> None:
        """Query MCU step queue and execution counters."""
        params = {}
        for response in self.driver.protocol.get_stepper_stats():
            params.update(response)

        fields = [
            "channel",
            "position",
            "queued_segments",
            "queued_steps",
            "loaded_segments",
            "loaded_steps",
            "executed_pos_steps",
            "executed_neg_steps",
            "physical_pos_pulses",
            "physical_neg_pulses",
            "planner_steps_per_rev",
            "encoder_ppr",
            "encoder_counts_per_rev",
            "tmc_grid",
            "physical_step_width",
            "motion_scale_configured",
            "step_half_period_ticks",
            "dir_setup_ticks",
            "waveform_worst_case_ticks",
            "fatal_lateness_ticks",
            "activation_count",
            "last_activation_clock",
            "first_load_now",
            "first_load_scheduled",
            "first_load_compare",
            "first_load_lead_ticks",
            "first_load_compare_delay_ticks",
            "first_step_clock",
            "first_step_delay_ticks",
            "discarded_segments",
            "discarded_steps",
            "queue_empty_count",
            "missed_deadline_count",
            "stop_count",
            "stop_drained_segments",
            "stop_drained_steps",
            "reset_count",
            "reset_drained_segments",
            "reset_drained_steps",
            "last_stop_reason",
            "last_stop_remaining_events",
            "last_stop_queue_len",
            "last_stop_drained_segments",
            "last_stop_drained_steps",
            "timer_active",
            "queue_len",
        ]
        parts = [f"FOCI_STEPPER_STATS {self.driver.stepper_name}:"]
        for field in fields:
            parts.append(f"{field}={params.get(field, '?')}")
        gcmd.respond_info(" ".join(parts))

    def dispatch_stats(self, gcmd) -> None:
        """Query MCU step-dispatch cycle counters."""
        clear = gcmd.get_int("RESET", 0, minval=0, maxval=1)
        response = self.driver.protocol.get_stepper_perf_stats(clear=clear != 0)

        def cycles_to_us(field: str) -> int | str:
            value = response.get(field)
            if value is None:
                return "?"
            return int(value) // OPENFFBOARD_CPU_CYCLES_PER_US

        fields = [
            "channel",
            "crit_max_cycles",
            "crit_max_site",
            "crit_over_10us",
            "crit_over_50us",
            "crit_over_100us",
            "crit_over_1000us",
            "queue_step_count",
            "queue_step_max_cycles",
            "tim5_activation_count",
            "tim5_irq_max_cycles",
            "tim5_dispatch_max_cycles",
            "tim5_dispatch_max_cycles_events",
            "tim5_events_max_per_irq",
            "tim5_event_count_total",
            "tim5_defer_count",
            "tim5_burst_cycles_per_event_max_cycles",
            "tim5_burst_cycles_per_event_max_events",
            "tim5_burst_cycles_per_event_floor3_max",
            "tim5_entry_latency_max_ticks",
            "tim5_pop_lateness_max_ticks",
            "scheduler_cycles_max",
            "scheduler_cycles_events_at_max",
            "scheduler_cycles_per_event_max",
            "scheduler_cycles_per_event_floor3_max",
            "scheduler_full_count",
            "stepper_load_lateness_max_ticks",
            "stepper_load_lateness_last_ticks",
            "build_trace_enabled",
        ]
        parts = [f"FOCI_DISPATCH_STATS {self.driver.stepper_name}:"]
        for field in fields:
            parts.append(f"{field}={response.get(field, '?')}")
        parts.append(f"crit_max_us={cycles_to_us('crit_max_cycles')}")
        parts.append(f"queue_step_max_us={cycles_to_us('queue_step_max_cycles')}")
        parts.append(f"tim5_irq_max_us={cycles_to_us('tim5_irq_max_cycles')}")
        parts.append(f"tim5_dispatch_max_us={cycles_to_us('tim5_dispatch_max_cycles')}")
        gcmd.respond_info(" ".join(parts))

    def tmc_read_register(self, gcmd) -> None:
        """Read a raw TMC4671 register through dev firmware."""
        addr = gcmd.get_int("ADDR", minval=0, maxval=0xFF)
        response = self.driver.protocol.dev_tmc_read_register(addr=addr)
        value = int(response["value"])
        gcmd.respond_info(
            f"FOCI_TMC_READ_REGISTER {self.driver.stepper_name}: addr=0x{addr:02x} value=0x"
            f"{value:08x} value={int(value)}"
        )
