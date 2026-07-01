"""MCU command lookup and response binding for klipper-foci."""

from __future__ import annotations

from .bindings import (
    register_active_diagnostic_responses,
    register_commissioning_responses,
    register_dump_responses,
    register_homing_responses,
    register_selftest_responses,
)


class FociMcuCommands:
    """Bound Klipper MCU commands and protocol response handlers."""

    # The perf stats wire schema is shared by OpenFFBoard and Ouroboros.
    # OpenFFBoard reports one unified TIM5 software-scheduler population.
    # Ouroboros reports split-topology TIM5 work units in the same fields:
    # CC2 trsync/endstop scheduler slots plus CC1 due physical step events.
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
        self.resistance_test = None
        self.set_auto_calibrate_on_enable = None

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
        self.calibrate = mcu.lookup_command("foci_calibrate oid=%c", cq=cmd_queue)
        self.dump_registers = mcu.lookup_command("foci_dump_registers oid=%c")
        register_dump_responses(mcu._serial, driver, oid)
        register_homing_responses(mcu._serial, driver, oid)
        self.set_pid_gains = mcu.lookup_command(
            "tmc_set_pid_gains oid=%c flux_p=%hu flux_i=%hu torque_p=%hu torque_i=%hu"
        )
        self.commission = mcu.lookup_command("foci_commission oid=%c profile=%c")
        self.tune = mcu.lookup_command(
            "foci_tune oid=%c profile=%c mode=%c"
            " inner_lambda=%u theta_e=%u current_ringing=%c current_bw=%u"
            " tau_e_us=%u inner_warning_flags=%c"
        )
        register_commissioning_responses(mcu._serial, driver, oid)
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
            "tmc_current_step_test oid=%c axis=%c target=%hi"
            " duration_ms=%hu voltage_limit=%hu"
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
        self.resistance_test = mcu.lookup_command(
            "tmc_resistance_test oid=%c detail=%c"
        )
        register_active_diagnostic_responses(mcu._serial, driver, oid)
        self.set_auto_calibrate_on_enable = mcu.lookup_command(
            "tmc_set_auto_calibrate_on_enable oid=%c enable=%c"
        )
        register_selftest_responses(mcu._serial, driver, oid)
