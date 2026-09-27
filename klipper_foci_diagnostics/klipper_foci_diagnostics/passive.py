"""Read-only FOCI stats G-code commands."""

from __future__ import annotations

import logging

from klipper_foci.diagnostics.formatting import stepper_dir_inverted
from klipper_foci.diagnostics.stepper_scale import derived_exec_stats

log = logging.getLogger(__name__)

STACK_WATERMARK_MEASURED = 0
STACK_WATERMARK_NOT_PAINTED = 1
STACK_WATERMARK_LOWER_BOUND = 2
STACK_WATERMARK_MOTION_ACTIVE = 3


class DiagnosticsPassive:
    """Read-only FOCI diagnostic stats commands."""

    def __init__(self, driver) -> None:
        self.driver = driver

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

        get_constants = getattr(self.driver.mcu, "get_constants", None)
        constants = get_constants() if get_constants is not None else {}
        clock_freq = int(constants.get("CLOCK_FREQ", 0))
        params.update(
            derived_exec_stats(
                planner_steps_per_rev=int(params.get("planner_steps_per_rev", 0)),
                encoder_ppr=int(params.get("encoder_ppr", 0)),
                clock_freq=clock_freq,
            )
        )

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
            "oversize_frame_drops",
        ]
        parts = [f"FOCI_STEPPER_STATS {self.driver.stepper_name}:"]
        for field in fields:
            parts.append(f"{field}={params.get(field, '?')}")
        gcmd.respond_info(" ".join(parts))

    def stack_watermark(self, gcmd) -> None:
        """Query how much of the boot-painted MCU stack was never used.

        The firmware measures the deepest point the stack has reached since
        boot, so run the workload under test first and do not reset the MCU
        between that workload and this query. The firmware masks interrupts for
        the scan and refuses the query outright while motion is active.
        """
        response = self.driver.protocol.get_stack_watermark()
        status = int(response["status"])
        if status == STACK_WATERMARK_NOT_PAINTED:
            raise gcmd.error(
                f"FOCI_STACK_WATERMARK {self.driver.stepper_name}: the board did not "
                "paint its stack at startup"
            )
        if status == STACK_WATERMARK_MOTION_ACTIVE:
            raise gcmd.error(
                f"FOCI_STACK_WATERMARK {self.driver.stepper_name}: refused while motion "
                "is active. The scan masks interrupts, so run it with the motor "
                "disabled and the step queue drained"
            )
        if status not in (STACK_WATERMARK_MEASURED, STACK_WATERMARK_LOWER_BOUND):
            raise gcmd.error(
                f"FOCI_STACK_WATERMARK {self.driver.stepper_name}: firmware reported "
                f"unknown status={status}"
            )
        unused_bytes = int(response["stack_unused_bytes"])
        painted_bytes = int(response["painted_bytes"])
        parts = [
            f"FOCI_STACK_WATERMARK {self.driver.stepper_name}:",
            f"stack_unused_bytes={unused_bytes}",
            f"painted_bytes={painted_bytes}",
        ]
        if status == STACK_WATERMARK_LOWER_BOUND:
            parts.append("(lower bound: the scan found no used word in its window)")
        message = " ".join(parts)
        log.info(message)
        gcmd.respond_info(message)
