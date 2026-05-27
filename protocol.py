"""Host-to-firmware protocol boundary for klipper-foci."""

from __future__ import annotations


class FociMcuCommands:
    """Bound Klipper MCU commands and protocol response handlers."""

    STEPPER_PERF_STATS_RESPONSE = (
        "foci_stepper_perf_stats_result oid=%c channel=%c"
        " crit_max_cycles=%u crit_max_site=%c"
        " crit_over_10us=%u crit_over_50us=%u"
        " crit_over_100us=%u crit_over_1000us=%u"
        " queue_step_count=%u queue_step_max_cycles=%u"
        " tim5_activation_count=%u tim5_irq_max_cycles=%u"
        " tim5_dispatch_max_cycles=%u"
        " tim5_dispatch_max_cycles_events=%u"
        " tim5_events_max_per_irq=%u"
        " tim5_event_count_total=%u tim5_defer_count=%u"
        " tim5_burst_cycles_per_event_max_cycles=%u"
        " tim5_burst_cycles_per_event_max_events=%u"
        " tim5_burst_cycles_per_event_floor3_max=%u"
        " tim5_entry_latency_max_ticks=%u"
        " tim5_pop_lateness_max_ticks=%u"
        " scheduler_cycles_max=%u"
        " scheduler_cycles_events_at_max=%u"
        " scheduler_cycles_per_event_max=%u"
        " scheduler_cycles_per_event_floor3_max=%u"
        " scheduler_full_count=%u"
        " stepper_load_lateness_max_ticks=%u"
        " stepper_load_lateness_last_ticks=%i build_trace_enabled=%c"
    )

    def __init__(self) -> None:
        self.stepper_get_position = None
        self.stepper_stats = None
        self.stepper_exec_stats = None
        self.stepper_timing_stats = None
        self.stepper_stop_stats = None
        self.stepper_perf_stats = None
        self.set_current = None
        self.set_encoder = None
        self.set_encoder_dir = None
        self.selftest = None
        self.read_register = None
        self.calibrate = None
        self.dump_registers = None
        self.set_pid_gains = None
        self.commission = None
        self.tune = None
        self.set_velocity_filter = None
        self.set_torque_filter = None
        self.set_position_filter = None
        self.set_flux_filter = None
        self.set_position_gains = None
        self.set_velocity_feedforward = None
        self.set_velocity_transient_feedforward = None
        self.set_accel_feedforward = None
        self.set_decoupling_feedforward = None
        self.set_position_lead = None
        self.set_phase_advance = None
        self.set_velocity_limit = None
        self.set_voltage_limit = None
        self.current_step_test = None
        self.current_vector_step_test = None
        self.current_torque_sample_test = None
        self.position_torque_offset_sample_test = None
        self.voltage_step_test = None
        self.set_auto_calibrate_on_enable = None
        self.trace_info = None
        self.trace_start = None
        self.trace_stop = None
        self.trace_fetch = None

    def bind(self, driver, mcu, oid: int) -> None:
        """Bind MCU command handles and response callbacks for one FOCI OID."""
        cmd_queue = mcu.alloc_command_queue()
        self.stepper_get_position = mcu.lookup_query_command(
            "stepper_get_position oid=%c",
            "stepper_position oid=%c pos=%i",
            oid=oid,
        )
        self.stepper_stats = mcu.lookup_query_command(
            "foci_stepper_stats oid=%c",
            "foci_stepper_stats_result oid=%c channel=%c position=%i"
            " queued_segments=%u queued_steps=%u"
            " loaded_segments=%u loaded_steps=%u"
            " discarded_segments=%u discarded_steps=%u"
            " timer_active=%c queue_len=%hu",
            oid=oid,
        )
        self.stepper_exec_stats = mcu.lookup_query_command(
            "foci_stepper_exec_stats oid=%c",
            "foci_stepper_exec_stats_result oid=%c channel=%c"
            " executed_pos_steps=%u executed_neg_steps=%u"
            " queue_empty_count=%u missed_deadline_count=%u",
            oid=oid,
        )
        self.stepper_timing_stats = mcu.lookup_query_command(
            "foci_stepper_timing_stats oid=%c",
            "foci_stepper_timing_stats_result oid=%c channel=%c"
            " activation_count=%u last_activation_clock=%u"
            " first_load_now=%u first_load_scheduled=%u first_load_compare=%u"
            " first_load_lead_ticks=%i first_load_compare_delay_ticks=%i"
            " first_step_clock=%u first_step_delay_ticks=%i",
            oid=oid,
        )
        self.stepper_stop_stats = mcu.lookup_query_command(
            "foci_stepper_stop_stats oid=%c",
            "foci_stepper_stop_stats_result oid=%c channel=%c"
            " stop_count=%u stop_drained_segments=%u stop_drained_steps=%u"
            " reset_count=%u reset_drained_segments=%u reset_drained_steps=%u"
            " last_stop_reason=%c"
            " last_stop_remaining_events=%u last_stop_queue_len=%hu"
            " last_stop_drained_segments=%u last_stop_drained_steps=%u",
            oid=oid,
        )
        self.stepper_perf_stats = mcu.lookup_query_command(
            "foci_stepper_perf_stats oid=%c clear=%c",
            self.STEPPER_PERF_STATS_RESPONSE,
            oid=oid,
        )
        self.set_current = mcu.lookup_command("tmc_set_current oid=%c run_ma=%u")
        self.set_encoder = mcu.lookup_command(
            "tmc_set_encoder oid=%c channel=%c ppr=%u"
        )
        self.set_encoder_dir = mcu.lookup_command(
            "tmc_set_encoder_dir oid=%c channel=%c invert=%c"
        )
        self.selftest = mcu.lookup_command("foci_selftest oid=%c")
        # Preserve release firmware behavior where the dev-only command is absent.
        try:
            self.read_register = mcu.lookup_query_command(
                "tmc_read_register oid=%c addr=%c",
                "tmc_register_value oid=%c addr=%c value=%u",
                oid=oid,
            )
        except Exception:
            self.read_register = None
        self.calibrate = mcu.lookup_command("foci_calibrate oid=%c", cq=cmd_queue)
        self.dump_registers = mcu.lookup_command("foci_dump_registers oid=%c")
        mcu._serial.register_response(
            driver.dump.handle_dump_value, "foci_dump_value", oid
        )
        mcu._serial.register_response(
            driver.dump.handle_dump_done, "foci_dump_done", oid
        )
        mcu._serial.register_response(
            driver.homing.handle_calibrate_response, "foci_calibrate_result", oid
        )
        self.set_pid_gains = mcu.lookup_command(
            "tmc_set_pid_gains oid=%c flux_p=%hu flux_i=%hu torque_p=%hu torque_i=%hu"
        )
        self.commission = mcu.lookup_command("foci_commission oid=%c profile=%c")
        self.tune = mcu.lookup_command(
            "foci_tune oid=%c profile=%c mode=%c"
            " inner_lambda=%u theta_e=%u current_ringing=%c current_bw=%u"
            " tau_e_us=%u tau_e_crosscheck_us=%u"
            " tau_residual_permille=%hu inner_warning_flags=%c"
        )
        mcu._serial.register_response(
            driver.commissioning.handle_commission_phase,
            "foci_commission_phase",
            oid,
        )
        mcu._serial.register_response(
            driver.commissioning.handle_commission_result,
            "foci_commission_result",
            oid,
        )
        mcu._serial.register_response(
            driver.autotune.handle_tune_result,
            "foci_tune_result",
            oid,
        )
        self.set_velocity_filter = mcu.lookup_command(
            "tmc_set_velocity_filter oid=%c filter_hz=%hu"
        )
        self.set_torque_filter = mcu.lookup_command(
            "tmc_set_torque_filter oid=%c filter_hz=%hu"
        )
        self.set_position_filter = mcu.lookup_command(
            "tmc_set_position_filter oid=%c filter_hz=%hu"
        )
        self.set_flux_filter = mcu.lookup_command(
            "tmc_set_flux_filter oid=%c filter_hz=%hu"
        )
        self.set_position_gains = mcu.lookup_command(
            "tmc_set_position_gains oid=%c position_p=%hu position_i=%hu"
            " velocity_p=%hu velocity_i=%hu"
        )
        self.set_velocity_feedforward = mcu.lookup_command(
            "tmc_set_velocity_feedforward oid=%c enable=%c multiplier=%hu"
        )
        self.set_velocity_transient_feedforward = mcu.lookup_command(
            "tmc_set_velocity_transient_feedforward oid=%c enable=%c"
            " lead_time_us=%hu gain_permille=%hu max_offset=%hu rate_hz=%hu"
        )
        self.set_accel_feedforward = mcu.lookup_command(
            "tmc_set_accel_feedforward oid=%c enable=%c"
            " accel_gain_permille=%hu decel_gain_permille=%hu"
        )
        self.set_decoupling_feedforward = mcu.lookup_command(
            "tmc_set_decoupling_feedforward oid=%c enable=%c"
            " r_int=%u l_int=%u pole_pairs=%hu position_units_per_rev=%u"
            " f_pwm_hz=%u max_offset=%hu"
        )
        self.set_position_lead = mcu.lookup_command(
            "tmc_set_position_lead oid=%c enable=%c gain_permille=%hu max_counts=%hu"
        )
        self.set_phase_advance = mcu.lookup_command(
            "tmc_set_phase_advance oid=%c enable=%c"
            " gain_ppm=%i max_counts=%hu deadband=%hu"
        )
        self.set_velocity_limit = mcu.lookup_command(
            "tmc_set_velocity_limit oid=%c limit=%u"
        )
        self.set_voltage_limit = mcu.lookup_command(
            "tmc_set_voltage_limit oid=%c voltage_limit=%u"
        )
        self.current_step_test = mcu.lookup_command(
            "tmc_current_step_test oid=%c target=%hi duration_ms=%hu voltage_limit=%hu"
        )
        self.current_vector_step_test = mcu.lookup_command(
            "tmc_current_vector_step_test oid=%c torque_target=%hi flux_target=%hi"
            " duration_ms=%hu voltage_limit=%hu"
        )
        self.current_torque_sample_test = mcu.lookup_command(
            "tmc_current_torque_sample_test oid=%c target=%hi flux_target=%hi"
            " sample_delay_ms=%hu voltage_limit=%hu"
        )
        self.position_torque_offset_sample_test = mcu.lookup_command(
            "tmc_position_torque_offset_sample_test oid=%c target=%hi"
            " sample_delay_ms=%hu voltage_limit=%hu"
        )
        self.voltage_step_test = mcu.lookup_command(
            "tmc_voltage_step_test oid=%c uq_ext=%hi ud_ext=%hi sample_delay_ms=%hu"
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_current_step_result,
            "foci_current_step_result",
            oid,
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_current_vector_step_result,
            "foci_current_vector_step_result",
            oid,
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_current_torque_sample_result,
            "foci_current_torque_sample_result",
            oid,
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_current_torque_sample_detail_result,
            "foci_current_torque_sample_detail_result",
            oid,
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_voltage_step_result,
            "foci_voltage_step_result",
            oid,
        )
        self.set_auto_calibrate_on_enable = mcu.lookup_command(
            "tmc_set_auto_calibrate_on_enable oid=%c enable=%c"
        )
        self.trace_info = mcu.lookup_command("foci_trace_info oid=%c")
        self.trace_start = mcu.lookup_command("foci_trace_start oid=%c preset=%c")
        self.trace_stop = mcu.lookup_command("foci_trace_stop oid=%c")
        self.trace_fetch = mcu.lookup_query_command(
            "foci_trace_fetch oid=%c offset=%hu generation=%c",
            "foci_trace_data oid=%c offset=%hu status=%c data=%*s",
            oid=oid,
        )
        mcu._serial.register_response(
            driver.trace.handle_trace_info_result,
            "foci_trace_info_result",
            oid,
        )
        mcu._serial.register_response(
            driver.selftest.handle_selftest_result,
            "foci_selftest_result",
            oid,
        )
        mcu._serial.register_response(
            driver.selftest.handle_selftest_done,
            "foci_selftest_done",
            oid,
        )
        mcu._serial.register_response(
            driver.commissioning.handle_commission_detail,
            "foci_commission_detail",
            oid,
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_stepper_event,
            "foci_stepper_event",
        )
        mcu._serial.register_response(
            driver.diagnostics.handle_stepper_perf_event,
            "foci_stepper_perf_event",
        )


class FociProtocol:
    """Host protocol facade for low-level FOCI MCU communication."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.commands = FociMcuCommands()

    def bind_mcu(self, mcu, oid: int) -> None:
        """Bind MCU commands and response handlers for one FOCI driver."""
        self.commands.bind(self.driver, mcu, oid)

    def set_current(self, run_ma: int) -> None:
        self.commands.set_current.send([self.driver.oid, run_ma])

    def set_voltage_limit(self, voltage_limit: int) -> None:
        self.commands.set_voltage_limit.send([self.driver.oid, voltage_limit])

    def set_encoder(self, channel: int, encoder_ppr: int) -> None:
        self.commands.set_encoder.send([self.driver.oid, channel, encoder_ppr])

    def set_encoder_direction(self, channel: int, encoder_reversed: bool) -> None:
        self.commands.set_encoder_dir.send(
            [self.driver.oid, channel, int(encoder_reversed)]
        )

    def set_pid_gains(
        self,
        flux_p: int,
        flux_i: int,
        torque_p: int,
        torque_i: int,
    ) -> None:
        self.commands.set_pid_gains.send(
            [self.driver.oid, flux_p, flux_i, torque_p, torque_i]
        )

    def set_velocity_filter(self, filter_hz: int) -> None:
        self.commands.set_velocity_filter.send([self.driver.oid, filter_hz])

    def set_torque_filter(self, filter_hz: int) -> None:
        self.commands.set_torque_filter.send([self.driver.oid, filter_hz])

    def set_position_filter(self, filter_hz: int) -> None:
        self.commands.set_position_filter.send([self.driver.oid, filter_hz])

    def set_flux_filter(self, filter_hz: int) -> None:
        self.commands.set_flux_filter.send([self.driver.oid, filter_hz])

    def set_position_gains(
        self,
        position_p: int,
        position_i: int,
        velocity_p: int,
        velocity_i: int,
    ) -> None:
        self.commands.set_position_gains.send(
            [self.driver.oid, position_p, position_i, velocity_p, velocity_i]
        )

    def set_velocity_feedforward(self, enable: bool, multiplier: int) -> None:
        self.commands.set_velocity_feedforward.send(
            [self.driver.oid, int(enable), multiplier]
        )

    def set_velocity_limit(self, velocity_limit: int) -> None:
        self.commands.set_velocity_limit.send([self.driver.oid, velocity_limit])

    def configure_startup(
        self,
        *,
        current_ma: int,
        voltage_limit: int,
        channel: int,
        encoder_ppr: int,
        encoder_reversed: bool,
        pid_gains: tuple[int, int, int, int] | None,
        filter_hz: dict[str, int],
        position_gains: tuple[int, int, int, int] | None,
        velocity_feedforward: tuple[bool, int],
        velocity_limit: int | None,
    ) -> None:
        """Apply connect-time firmware configuration in the existing order."""
        self.set_current(current_ma)
        self.set_voltage_limit(voltage_limit)
        self.set_encoder(channel, encoder_ppr)
        self.set_encoder_direction(channel, encoder_reversed)
        if pid_gains is not None:
            self.set_pid_gains(*pid_gains)
        if filter_hz.get("velocity", 0) > 0:
            self.set_velocity_filter(filter_hz["velocity"])
        if filter_hz.get("torque", 0) > 0:
            self.set_torque_filter(filter_hz["torque"])
        if filter_hz.get("position", 0) > 0:
            self.set_position_filter(filter_hz["position"])
        if filter_hz.get("flux", 0) > 0:
            self.set_flux_filter(filter_hz["flux"])
        if position_gains is not None:
            self.set_position_gains(*position_gains)
        enable_feedforward, multiplier = velocity_feedforward
        if enable_feedforward:
            self.set_velocity_feedforward(True, multiplier)
        if velocity_limit is not None:
            self.set_velocity_limit(velocity_limit)

    def set_auto_calibrate_on_enable(self, allowed: bool) -> None:
        self.commands.set_auto_calibrate_on_enable.send([self.driver.oid, int(allowed)])

    def preload_active_gains(self, gains: dict[str, int], voltage_limit: int) -> None:
        self.set_voltage_limit(voltage_limit)
        self.set_pid_gains(
            gains["flux_p"],
            gains["flux_i"],
            gains["torque_p"],
            gains["torque_i"],
        )
        if gains.get("velocity_p") is not None:
            self.set_position_gains(
                gains["position_p"],
                gains["position_i"],
                gains["velocity_p"],
                gains["velocity_i"],
            )
        if gains.get("velocity_limit"):
            self.set_velocity_limit(gains["velocity_limit"])
        for filter_name, setter in (
            ("velocity", self.set_velocity_filter),
            ("torque", self.set_torque_filter),
            ("position", self.set_position_filter),
            ("flux", self.set_flux_filter),
        ):
            hz = gains.get("%s_filter_hz" % filter_name, 0)
            if hz > 0:
                setter(hz)

    def run_calibration(self) -> None:
        self.commands.calibrate.send([self.driver.oid])

    def run_commission(self, profile_code: int) -> None:
        self.commands.commission.send([self.driver.oid, profile_code])

    def run_tune(
        self,
        *,
        profile_code: int,
        mode_code: int,
        inner_lambda: int,
        theta_e: int,
        current_ringing: int,
        current_bw: int,
        tau_e_us: int,
        tau_e_crosscheck_us: int,
        tau_residual_permille: int,
        inner_warning_flags: int,
    ) -> None:
        self.commands.tune.send(
            [
                self.driver.oid,
                profile_code,
                mode_code,
                inner_lambda,
                theta_e,
                current_ringing,
                current_bw,
                tau_e_us,
                tau_e_crosscheck_us,
                tau_residual_permille,
                inner_warning_flags,
            ]
        )

    def run_selftest(self) -> None:
        self.commands.selftest.send([self.driver.oid])

    def dump_registers(self) -> None:
        self.commands.dump_registers.send([self.driver.oid])

    def read_register(self, addr: int) -> int:
        """Read one raw TMC4671 register address through dev firmware."""
        if self.commands.read_register is None:
            raise self.driver.printer.command_error(
                "Raw register access requires dev firmware build"
            )
        params = self.commands.read_register.send([self.driver.oid, addr])
        return params["value"]
