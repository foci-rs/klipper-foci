"""Diagnostic FOCI host workflows."""

from __future__ import annotations

import logging

from .constants import MIN_OPERATIONAL_VOLTAGE_LIMIT

OPENFFBOARD_CPU_CYCLES_PER_US = 168

log = logging.getLogger(__name__)

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


class DiagnosticsWorkflow:
    """Own advanced and expert FOCI diagnostic commands and responses."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.current_torque_sample_details: dict[tuple[int, int, int, int], dict] = {}
        self.current_torque_sample_labels: dict[tuple[int, int, int, int], str] = {}

    def handle_current_step_result(self, params: dict) -> None:
        """Handle foci_current_step_result from firmware."""
        msg = (
            "FOCI %s current step: status=%d target=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.driver.name,
                params["status"],
                params["target"],
                params["torque_during"],
                params["torque_before"],
                params["torque_after"],
                params["flux_during"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_vector_step_result(self, params: dict) -> None:
        """Handle foci_current_vector_step_result from firmware."""
        msg = (
            "FOCI %s current vector step: status=%d"
            " torque_target=%d flux_target=%d"
            " actual_torque=%d actual_flux=%d"
            " before=%d after=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.driver.name,
                params["status"],
                params["torque_target"],
                params["flux_target"],
                params["torque_during"],
                params["flux_during"],
                params["torque_before"],
                params["torque_after"],
                params["iq_during"],
                params["id_during"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_after"],
                params["encoder_delta"],
                params["adc_vm_raw"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_torque_sample_result(self, params: dict) -> None:
        """Handle foci_current_torque_sample_result from firmware."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        detail = self.current_torque_sample_details.pop(detail_key, {})
        label = self.current_torque_sample_labels.pop(
            detail_key, "current torque sample"
        )
        msg = (
            "FOCI %s %s: status=%d"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " pidin_target_torque=%d pidin_target_flux=%d"
            " pidout_target_torque=%d pidout_target_flux=%d"
            " pid_torque_target_monitor=%d"
            " torque_error=%d flux_error=%d"
            " torque_error_sum=%d flux_error_sum=%d"
            " uq_prelimit=%d ud_prelimit=%d"
            " ff_velocity=%d ff_torque=%d"
            " status_flags=0x%08x"
            % (
                self.driver.name,
                label,
                params["status"],
                params["target"],
                params.get("flux_target", 0),
                params["sample_delay_ms"],
                params["voltage_limit"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params.get("pidin_target_torque", 0),
                params.get("pidin_target_flux", 0),
                params.get("pidout_target_torque", 0),
                params.get("pidout_target_flux", 0),
                params.get("pid_torque_target_monitor", 0),
                detail.get("torque_error", 0),
                detail.get("flux_error", 0),
                detail.get("torque_error_sum", 0),
                detail.get("flux_error_sum", 0),
                detail.get("uq_prelimit", 0),
                detail.get("ud_prelimit", 0),
                detail.get("ff_velocity", 0),
                detail.get("ff_torque", 0),
                params.get("status_flags", 0),
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def handle_current_torque_sample_detail_result(self, params: dict) -> None:
        """Cache split current torque sample details until the base reply arrives."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        self.current_torque_sample_details[detail_key] = params

    def handle_voltage_step_result(self, params: dict) -> None:
        """Handle foci_voltage_step_result from firmware."""
        msg = (
            "FOCI %s voltage step: status=%d"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " uux_sample=%d uwy_sample=%d"
            " pwm_ux_sample=%d pwm_wy_sample=%d"
            " pwm_sv_chop=0x%08x pwm_bbm=0x%08x pwm_maxcnt=%d"
            " phi_e_sample=%d phi_m_sample=%d"
            " enc_before=%d enc_sample=%d enc_after=%d"
            " enc_delta_sample=%d enc_delta_after=%d adc_vm_raw=%d"
            " status_flags=0x%08x"
            % (
                self.driver.name,
                params["status"],
                params["uq_ext"],
                params["ud_ext"],
                params["sample_delay_ms"],
                params["torque_sample"],
                params["torque_before"],
                params["torque_after"],
                params["flux_sample"],
                params["iq_sample"],
                params["id_sample"],
                params["uq_limited"],
                params["ud_limited"],
                params["uux_sample"],
                params["uwy_sample"],
                params["pwm_ux_sample"],
                params["pwm_wy_sample"],
                params["pwm_sv_chop"],
                params["pwm_bbm"],
                params["pwm_maxcnt"],
                params["phi_e_sample"],
                params["phi_m_sample"],
                params["encoder_before"],
                params["encoder_sample"],
                params["encoder_after"],
                params["encoder_delta_sample"],
                params["encoder_delta_after"],
                params["adc_vm_raw"],
                params["status_flags"],
            )
        )
        self.driver.printer.lookup_object("gcode").respond_info(msg)

    def format_stepper_event(self, params: dict) -> str:
        """Format one firmware stepper diagnostic event."""
        reason_code = params.get("reason", 0)
        reason_name = STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")
        return (
            "FOCI_STEPPER_EVENT %s reason=%s(%d) channel=%d pos=%d"
            " clock=%d timer_active=%d queue_len=%d dir=%d data0=%d data1=%d"
            % (
                self.driver.stepper_name,
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

    def handle_stepper_event(self, params: dict) -> None:
        """Handle bounded firmware stepper diagnostics."""
        message = self.format_stepper_event(params)
        log.info(message)
        gcode = self.driver.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def format_stepper_perf_event(self, params: dict) -> str:
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
                self.driver.stepper_name,
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

    def handle_stepper_perf_event(self, params: dict) -> None:
        """Handle fatal firmware step-dispatch performance snapshots."""
        message = self.format_stepper_perf_event(params)
        log.info(message)
        gcode = self.driver.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def step_position(self, gcmd) -> None:
        """Query raw MCU step position without updating Klipper state."""
        if self.driver.stepper_get_position_cmd is None or self.driver.oid is None:
            raise gcmd.error("FOCI_STEP_POSITION is not available before MCU identify")

        stepper = self.driver._find_linked_stepper()
        if stepper is None:
            raise gcmd.error(
                "FOCI_STEP_POSITION could not find linked stepper %s"
                % self.driver.stepper_name
            )

        params = self.driver.stepper_get_position_cmd.send([self.driver.oid])
        if params is None or "pos" not in params:
            raise gcmd.error("FOCI_STEP_POSITION query returned no position")

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
            "FOCI_STEP_POSITION %s:" % self.driver.stepper_name,
            "raw=%d" % raw_position,
            "host=%d" % host_position,
            "klipper=%s" % (klipper_position if klipper_position is not None else "?"),
            "delta=%s" % (delta if delta is not None else "?"),
            "invert_dir=%d" % (1 if invert_dir else 0),
        ]

        get_step_dist = getattr(stepper, "get_step_dist", None)
        if get_step_dist is not None:
            step_dist = float(get_step_dist())
            parts.append("step_dist=%.6f" % step_dist)
            if delta is not None:
                parts.append("delta_mm=%.3f" % (delta * step_dist))

        gcmd.respond_info(" ".join(parts))

    def stepper_stats(self, gcmd) -> None:
        """Query MCU step queue and execution counters."""
        query_cmds = (
            ("stats", self.driver.stepper_stats_cmd),
            ("exec_stats", self.driver.stepper_exec_stats_cmd),
            ("timing_stats", self.driver.stepper_timing_stats_cmd),
            ("stop_stats", self.driver.stepper_stop_stats_cmd),
        )
        if self.driver.oid is None or any(cmd is None for _, cmd in query_cmds):
            raise gcmd.error("FOCI_STEPPER_STATS is not available before MCU identify")

        params = {}
        for name, cmd in query_cmds:
            response = cmd.send([self.driver.oid])
            if response is None:
                raise gcmd.error("FOCI_STEPPER_STATS %s query returned no data" % name)
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
        parts = ["FOCI_STEPPER_STATS %s:" % self.driver.stepper_name]
        for field in fields:
            parts.append("%s=%s" % (field, params.get(field, "?")))
        gcmd.respond_info(" ".join(parts))

    def dispatch_stats(self, gcmd) -> None:
        """Query MCU step-dispatch cycle counters."""
        if self.driver.oid is None or self.driver.stepper_perf_stats_cmd is None:
            raise gcmd.error("FOCI_DISPATCH_STATS is not available before MCU identify")

        clear = gcmd.get_int("RESET", 0, minval=0, maxval=1)
        response = self.driver.stepper_perf_stats_cmd.send([self.driver.oid, clear])
        if response is None:
            raise gcmd.error("FOCI_DISPATCH_STATS query returned no data")

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
        parts = ["FOCI_DISPATCH_STATS %s:" % self.driver.stepper_name]
        for field in fields:
            parts.append("%s=%s" % (field, response.get(field, "?")))
        parts.append("crit_max_us=%s" % cycles_to_us("crit_max_cycles"))
        parts.append("queue_step_max_us=%s" % cycles_to_us("queue_step_max_cycles"))
        parts.append("tim5_irq_max_us=%s" % cycles_to_us("tim5_irq_max_cycles"))
        parts.append(
            "tim5_dispatch_max_us=%s" % cycles_to_us("tim5_dispatch_max_cycles")
        )
        gcmd.respond_info(" ".join(parts))

    def current_step_test(self, gcmd) -> None:
        """Run a bounded current-loop step diagnostic."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.current_step_test_cmd.send(
            [self.driver.oid, target, duration_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s current-step requested: target=%d"
            " duration_ms=%d voltage_limit=%d"
            % (self.driver.name, target, duration_ms, voltage_limit)
        )

    def current_vector_step_test(self, gcmd) -> None:
        """Run a bounded current-vector step diagnostic."""
        torque_target = gcmd.get_int("TORQUE_TARGET", 0, minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.driver.current_vector_step_test_cmd.send(
            [
                self.driver.oid,
                torque_target,
                flux_target,
                duration_ms,
                voltage_limit,
            ]
        )

        gcmd.respond_info(
            "FOCI %s current-vector-step requested:"
            " torque_target=%d flux_target=%d duration_ms=%d voltage_limit=%d"
            % (
                self.driver.name,
                torque_target,
                flux_target,
                duration_ms,
                voltage_limit,
            )
        )

    def current_torque_sample_test(self, gcmd) -> None:
        """Run a bounded torque pulse and sample it before the dwell floor."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 5, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self.current_torque_sample_details.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )
        self.current_torque_sample_labels.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )

        self.driver.current_torque_sample_test_cmd.send(
            [
                self.driver.oid,
                target,
                flux_target,
                sample_delay_ms,
                voltage_limit,
            ]
        )

        gcmd.respond_info(
            "FOCI %s current-torque-sample requested:"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d"
            % (
                self.driver.name,
                target,
                flux_target,
                sample_delay_ms,
                voltage_limit,
            )
        )

    def position_torque_offset_test(self, gcmd) -> None:
        """Run a bounded torque-offset sample while staying in position mode."""
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        detail_key = (target, 0, sample_delay_ms, voltage_limit)
        self.current_torque_sample_details.pop(detail_key, None)
        self.current_torque_sample_labels[detail_key] = "position torque offset sample"

        self.driver.position_torque_offset_sample_test_cmd.send(
            [self.driver.oid, target, sample_delay_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s position-torque-offset requested:"
            " target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.driver.name, target, sample_delay_ms, voltage_limit)
        )

    def voltage_step_test(self, gcmd) -> None:
        """Run a bounded open-loop voltage-vector pulse and sample it."""
        uq_ext = gcmd.get_int("UQ", minval=-1024, maxval=1024)
        ud_ext = gcmd.get_int("UD", 0, minval=-1024, maxval=1024)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)

        self.driver.voltage_step_test_cmd.send(
            [self.driver.oid, uq_ext, ud_ext, sample_delay_ms]
        )

        gcmd.respond_info(
            "FOCI %s voltage-step requested:"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d"
            % (self.driver.name, uq_ext, ud_ext, sample_delay_ms)
        )
