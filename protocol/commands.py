"""MCU command lookup and response binding for klipper-foci."""

from __future__ import annotations

from .bindings import (
    register_active_diagnostic_responses,
    register_commissioning_responses,
    register_dump_responses,
    register_homing_responses,
    register_last_boot_diagnostic_response,
    register_motion_scale_responses,
    register_selftest_responses,
    register_stepper_event_response,
)


class FociMcuCommands:
    """Bound Klipper MCU commands and protocol response handlers."""

    def __init__(self) -> None:
        self.stepper_get_position = None
        self.stepper_stats = None
        self.stepper_exec_stats = None
        self.stepper_timing_stats = None
        self.stepper_stop_stats = None
        self.stack_watermark = None
        self.query_adc_vm_offset = None
        self.set_current = None
        self.set_motion_scale = None
        self.set_encoder_dir = None
        self.selftest = None
        self.calibrate = None
        self.dump_registers = None
        self.set_pid_gains = None
        self.commission = None
        self.commission_cancel = None
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
        self.dev_tmc_write_register = None
        self.dev_tmc_read_register = None
        self.config_homing = None
        self.query_stall = None

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
            " timer_active=%c queue_len=%hu"
            " oversize_frame_drops=%u",
            oid=oid,
        )
        self.stepper_exec_stats = mcu.lookup_query_command(
            "foci_stepper_exec_stats oid=%c",
            "foci_stepper_exec_stats_result oid=%c"
            " executed_pos_steps=%u executed_neg_steps=%u"
            " physical_pos_pulses=%u physical_neg_pulses=%u"
            " planner_steps_per_rev=%u encoder_ppr=%u"
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
        self.query_adc_vm_offset = mcu.lookup_query_command(
            "foci_adc_vm_offset oid=%c",
            "foci_adc_vm_offset_result oid=%c offset_raw=%hu sample_count=%c status=%c",
            oid=oid,
        )
        self.stack_watermark = mcu.lookup_query_command(
            "foci_stack_watermark oid=%c",
            "foci_stack_watermark_result oid=%c stack_unused_bytes=%u painted_bytes=%u status=%c",
            oid=oid,
        )
        self.set_current = mcu.lookup_command("tmc_set_current oid=%c run_ma=%u")
        self.set_motion_scale = mcu.lookup_command(
            "tmc_set_motion_scale oid=%c channel=%c encoder_ppr=%u planner_steps_per_rev=%u"
        )
        register_motion_scale_responses(mcu._serial, driver, oid)
        self.set_encoder_dir = mcu.lookup_command("tmc_set_encoder_dir oid=%c channel=%c invert=%c")
        self.selftest = mcu.lookup_command("foci_selftest oid=%c")
        self.calibrate = mcu.lookup_command("foci_calibrate oid=%c", cq=cmd_queue)
        self.dump_registers = mcu.lookup_command("foci_dump_registers oid=%c")
        register_dump_responses(mcu._serial, driver, oid)
        register_last_boot_diagnostic_response(mcu._serial, driver, oid)
        register_homing_responses(mcu._serial, driver, oid)
        self.set_pid_gains = mcu.lookup_command(
            "tmc_set_pid_gains oid=%c flux_p=%hu flux_i=%hu torque_p=%hu torque_i=%hu"
        )
        self.commission = mcu.lookup_command("foci_commission oid=%c profile=%c")
        self.commission_cancel = mcu.lookup_command("foci_commission_cancel oid=%c")
        self.tune = mcu.lookup_command(
            "foci_tune oid=%c action=%c profile=%c mode=%c"
            " inner_lambda=%u theta_e=%u current_bw=%u"
            " inner_warning_flags=%c requested_velocity_mrev_s=%u"
            " machine_velocity_ceiling_mrev_s=%u requested_velocity_source=%c"
            " max_stroke_travel_mrev=%u settle_travel_reserve_mrev=%u"
            " negative_position_headroom_mrev=%u positive_position_headroom_mrev=%u"
            " max_duration_ms=%hu homing_speed_mrev_s=%u max_accel_mrev_s2=%u"
        )
        register_commissioning_responses(mcu._serial, driver, oid)
        self.set_velocity_filter = mcu.lookup_command(
            "tmc_set_velocity_filter oid=%c filter_hz=%hu"
        )
        self.set_torque_filter = mcu.lookup_command("tmc_set_torque_filter oid=%c filter_hz=%hu")
        self.set_position_filter = mcu.lookup_command(
            "tmc_set_position_filter oid=%c filter_hz=%hu"
        )
        self.set_flux_filter = mcu.lookup_command("tmc_set_flux_filter oid=%c filter_hz=%hu")
        self.set_position_gains = mcu.lookup_command(
            "tmc_set_position_gains oid=%c position_p=%hu position_i=%hu"
            " velocity_p=%hu velocity_i=%hu"
        )
        self.set_velocity_feedforward = mcu.lookup_command(
            "tmc_set_velocity_feedforward_rpm oid=%c enable=%c gain_permille=%hu"
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
            "tmc_set_phase_advance oid=%c enable=%c gain_ppm=%i max_counts=%hu deadband=%hu"
        )
        self.set_velocity_limit = mcu.lookup_command("tmc_set_velocity_limit oid=%c limit=%u")
        self.set_voltage_limit = mcu.lookup_command("tmc_set_voltage_limit oid=%c voltage_limit=%u")
        self.current_step_test = mcu.lookup_command(
            "tmc_current_step_test oid=%c axis=%c target=%hi duration_ms=%hu voltage_limit=%hu"
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
        self.resistance_test = mcu.lookup_command("tmc_resistance_test oid=%c detail=%c")
        register_active_diagnostic_responses(mcu._serial, driver, oid)
        register_stepper_event_response(mcu, driver)
        self.set_auto_calibrate_on_enable = mcu.lookup_command(
            "tmc_set_auto_calibrate_on_enable oid=%c enable=%c"
        )
        register_selftest_responses(mcu._serial, driver, oid)
        self.dev_tmc_write_register = self._optional_lookup_command(
            mcu,
            "tmc_write_register oid=%c addr=%c value=%u",
        )
        self.dev_tmc_read_register = self._optional_lookup_query_command(
            mcu,
            "tmc_read_register oid=%c addr=%c",
            "tmc_register_value oid=%c addr=%c value=%u",
            oid=oid,
        )
        self.config_homing = mcu.lookup_command(
            "foci_config_homing oid=%c homing_ma=%u stall_units=%u margin_units=%u persistence=%c"
        )
        self.query_stall = mcu.lookup_query_command(
            "foci_stall_query oid=%c",
            "foci_stall_result oid=%c latched=%c peak_error_units=%u"
            " trigger_tick=%u clamp_active=%c trigger_path=%c"
            " peak_margin_delta_units=%u",
            oid=oid,
        )

    @staticmethod
    def _optional_lookup_command(mcu, fmt: str):
        """Return a command handle when a dev-gated MCU command exists."""
        try:
            return mcu.lookup_command(fmt)
        except Exception:
            return None

    @staticmethod
    def _optional_lookup_query_command(mcu, send_fmt: str, recv_fmt: str, *, oid: int):
        """Return a query handle when a dev-gated MCU command exists."""
        try:
            return mcu.lookup_query_command(send_fmt, recv_fmt, oid=oid)
        except Exception:
            return None
