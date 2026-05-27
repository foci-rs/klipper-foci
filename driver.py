# TMC4671 register definitions and FOCI driver class.
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Register reference: TMC4671-LA datasheet rev 2.08

import logging

from .commissioning import (
    COMMISSION_ERROR_NAMES,
    HARD_FAULT_CODES,
    PROFILE_MAP,
    CommissioningWorkflow,
    format_commission_detail,
    format_inner_warning_flags,
)
from .controls import (
    MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
    MIN_RAW_VOLTAGE_LIMIT,
    ControlsWorkflow,
)
from .dump import RegisterDumpWorkflow
from .homing import HomingWorkflow
from .registers import REGISTERS
from .registry import register_gcode_commands
from .state import FociRuntimeState
from .trace import (
    TRACE_FAST_HEADERS,
    TRACE_FULL_HEADERS,
    TRACE_HOLD_HEADERS,
    TRACE_VELOCITY_HEADERS,
    _format_trace_summary,
)

log = logging.getLogger(__name__)

OPENFFBOARD_CPU_CYCLES_PER_US = 168


######################################################################
# FociDriver - per-axis driver instance
######################################################################

STEP_PINS: dict[str, int] = {"STEP0": 0, "STEP1": 1}
MIN_OPERATIONAL_VOLTAGE_LIMIT = 1024
DEFAULT_OPERATIONAL_VOLTAGE_LIMIT = 16000


class FociDriver:
    """Klipper extras driver for a single TMC4671 FOC channel."""

    cmd_FOCI_TRACE_START_help = "Start FOCI per-tick trace capture"
    cmd_FOCI_TRACE_STOP_help = "Stop FOCI per-tick trace capture"
    cmd_FOCI_TRACE_help = "Fetch and display trace capture buffer"
    cmd_FOCI_STEP_POSITION_help = (
        "Query raw FOCI MCU step position without syncing Klipper"
    )
    cmd_FOCI_STEPPER_STATS_help = (
        "Query FOCI MCU step queue/execution counters without motion"
    )
    cmd_FOCI_DISPATCH_STATS_help = (
        "Query FOCI MCU step-dispatch cycle counters without motion"
    )
    cmd_FOCI_SELFTEST_help = "Run TMC4671 self-test for a FOCI stepper"
    cmd_FOCI_AUTOTUNE_help = (
        "Tune installed FOCI stepper (Stage 2: requires commissioning + homing)"
    )
    cmd_FOCI_CURRENT_STEP_TEST_help = "Run a bounded FOCI current-loop step diagnostic"
    cmd_FOCI_CURRENT_VECTOR_STEP_TEST_help = (
        "Run a bounded FOCI current-vector step diagnostic"
    )
    cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST_help = (
        "Run a bounded FOCI torque pulse and sample it early"
    )
    cmd_FOCI_POSITION_TORQUE_OFFSET_TEST_help = (
        "Run a bounded FOCI position-mode torque-offset sample"
    )
    cmd_FOCI_VOLTAGE_STEP_TEST_help = (
        "Run a bounded FOCI open-loop voltage-vector diagnostic"
    )

    def __init__(self, config) -> None:
        # Parse section name: [foci stepper_x]
        self.stepper_name: str = " ".join(config.get_name().split()[1:])
        self.name: str = config.get_name()
        self._current_torque_sample_details: dict[tuple[int, int, int, int], dict] = {}
        self._current_torque_sample_labels: dict[tuple[int, int, int, int], str] = {}

        self.printer = config.get_printer()
        self.global_config = self.printer.load_object(config, "foci")
        self.foci_mode: str = self.global_config.mode

        # Required motor config
        self.run_current: float = config.getfloat("run_current", above=0.0)
        self.encoder_ppr: int = config.getint("encoder_ppr", minval=1)
        self.voltage_limit: int = config.getint(
            "voltage_limit",
            DEFAULT_OPERATIONAL_VOLTAGE_LIMIT,
            minval=MIN_RAW_VOLTAGE_LIMIT,
            maxval=MAX_DIAGNOSTIC_VOLTAGE_LIMIT,
        )
        # Encoder count direction relative to motor rotation.
        # "default" = encoder counts up when motor drives forward.
        # "reversed" = encoder counts down when motor drives forward
        #              (swap A/B wiring or mount orientation).
        dir_choice: str = config.getchoice(
            "encoder_direction",
            {"default": False, "reversed": True},
            default="default",
        )
        self.encoder_reversed: bool = dir_choice

        # Optional PID gains (from FOCI_AUTOTUNE + SAVE_CONFIG or manual).
        # All four must be set together or not at all.
        self.pid_flux_p: int | None = config.getint(
            "pid_flux_p", None, minval=0, maxval=65535
        )
        self.pid_flux_i: int | None = config.getint(
            "pid_flux_i", None, minval=0, maxval=65535
        )
        self.pid_torque_p: int | None = config.getint(
            "pid_torque_p", None, minval=0, maxval=65535
        )
        self.pid_torque_i: int | None = config.getint(
            "pid_torque_i", None, minval=0, maxval=65535
        )
        pid_gains = [
            self.pid_flux_p,
            self.pid_flux_i,
            self.pid_torque_p,
            self.pid_torque_i,
        ]
        pid_set = [v for v in pid_gains if v is not None]
        if pid_set and len(pid_set) != 4:
            raise config.error(
                "PID gains must be set as a complete group"
                " (pid_flux_p, pid_flux_i, pid_torque_p, pid_torque_i)."
                " Found %d of 4 in [%s]" % (len(pid_set), self.name)
            )

        # Optional biquad low-pass filters (0 = disabled, 10..1000 Hz)
        self.velocity_filter_hz: int = config.getint(
            "velocity_filter_hz", 0, minval=0, maxval=1000
        )
        if self.velocity_filter_hz != 0 and self.velocity_filter_hz < 10:
            raise config.error(
                "velocity_filter_hz must be 0 (disabled) or 10..1000 in [%s]"
                % self.name
            )
        self.torque_filter_hz: int = config.getint(
            "torque_filter_hz", 0, minval=0, maxval=1000
        )
        if self.torque_filter_hz != 0 and self.torque_filter_hz < 10:
            raise config.error(
                "torque_filter_hz must be 0 (disabled) or 10..1000 in [%s]" % self.name
            )
        self.position_filter_hz: int = config.getint(
            "position_filter_hz", 0, minval=0, maxval=1000
        )
        if self.position_filter_hz != 0 and self.position_filter_hz < 10:
            raise config.error(
                "position_filter_hz must be 0 (disabled) or 10..1000 in [%s]"
                % self.name
            )
        self.flux_filter_hz: int = config.getint(
            "flux_filter_hz", 0, minval=0, maxval=1000
        )
        if self.flux_filter_hz != 0 and self.flux_filter_hz < 10:
            raise config.error(
                "flux_filter_hz must be 0 (disabled) or 10..1000 in [%s]" % self.name
            )

        # Optional position/velocity PID gains (Q8.8 raw register values)
        self.pid_position_p: int | None = config.getint(
            "pid_position_p", None, minval=0, maxval=32767
        )
        self.pid_position_i: int | None = config.getint(
            "pid_position_i", None, minval=0, maxval=32767
        )
        self.pid_velocity_p: int | None = config.getint(
            "pid_velocity_p", None, minval=0, maxval=32767
        )
        self.pid_velocity_i: int | None = config.getint(
            "pid_velocity_i", None, minval=0, maxval=32767
        )
        pos_gains = [
            self.pid_position_p,
            self.pid_position_i,
            self.pid_velocity_p,
            self.pid_velocity_i,
        ]
        pos_set = [v for v in pos_gains if v is not None]
        if pos_set and len(pos_set) != 4:
            raise config.error(
                "pid_position_p/i and pid_velocity_p/i must be set together"
                " (pid_position_p, pid_position_i, pid_velocity_p, pid_velocity_i)."
                " Found %d of 4 in [%s]" % (len(pos_set), self.name)
            )

        # Velocity feedforward (boolean, default disabled)
        self.velocity_feedforward: bool = config.getboolean(
            "velocity_feedforward", False
        )
        self.velocity_feedforward_multiplier: int = config.getint(
            "velocity_feedforward_multiplier", 1, minval=0, maxval=65535
        )
        self.velocity_transient_feedforward: bool = False
        self.velocity_transient_lead_time_us: int = 0
        self.velocity_transient_gain: int = 0
        self.velocity_transient_max_offset: int = 0
        self.velocity_transient_rate_hz: int = 1000
        self.accel_feedforward: bool = False
        self.accel_feedforward_accel_gain: int = 1000
        self.accel_feedforward_decel_gain: int = 1000
        self.decoupling_feedforward: bool = False
        self.decoupling_r_int: int = 3000
        self.decoupling_l_int: int = 4095
        self.decoupling_pole_pairs: int = 50
        self.decoupling_position_units_per_rev: int = 65536
        self.decoupling_f_pwm_hz: int = 25000
        self.decoupling_max_offset: int = 500
        self.position_lead: bool = False
        self.position_lead_gain: int = 0
        self.position_lead_max_counts: int = 0
        self.phase_advance: bool = False
        self.phase_advance_gain_ppm: int = 0
        self.phase_advance_max_counts: int = 0
        self.phase_advance_deadband: int = 16

        # PID velocity limit (caps position PID output, anti-windup).
        # 0 or unset = unconstrained (0x7FFFFFFF). Units: TMC4671 internal
        # velocity. Appropriate value depends on motor/encoder config.
        self.pid_velocity_limit: int | None = config.getint(
            "pid_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
        )

        # Commissioned fallback gains (from Stage 1, separate from tuned gains)
        self.commissioned_velocity_p: int | None = config.getint(
            "commissioned_velocity_p", None, minval=0, maxval=32767
        )
        self.commissioned_velocity_i: int | None = config.getint(
            "commissioned_velocity_i", None, minval=0, maxval=32767
        )
        self.commissioned_position_p: int | None = config.getint(
            "commissioned_position_p", None, minval=0, maxval=32767
        )
        self.commissioned_position_i: int | None = config.getint(
            "commissioned_position_i", None, minval=0, maxval=32767
        )
        self.commissioned_velocity_limit: int | None = config.getint(
            "commissioned_velocity_limit", None, minval=1, maxval=0x7FFFFFFF
        )

        # Inner-tuning parameters (persisted by Stage 1 for Stage 2 restart)
        self.identified_r_int: int | None = config.getint(
            "identified_r_int", None, minval=0
        )
        self.identified_l_int: int | None = config.getint(
            "identified_l_int", None, minval=0
        )
        self.identified_r_count_milli: int | None = config.getint(
            "identified_r_count_milli", None, minval=0
        )
        self.identified_l_count_micro: int | None = config.getint(
            "identified_l_count_micro", None, minval=0
        )
        self.identified_lambda_us: int | None = config.getint(
            "identified_lambda_us", None, minval=0
        )
        self.identified_theta_e_us: int | None = config.getint(
            "identified_theta_e_us", None, minval=0
        )
        self.identified_ringing_count: int | None = config.getint(
            "identified_ringing_count", None, minval=0, maxval=255
        )
        self.identified_bandwidth_hz: int | None = config.getint(
            "identified_bandwidth_hz", None, minval=0
        )

        # Phase 1 inner-confidence fields (added 2026-04-30). Optional in
        # the persisted config: old configs that never ran the new firmware
        # leave these unset and `_resolve_inner_confidence` substitutes
        # documented defaults (bit 6 = host-default confidence).
        self.identified_tau_e_us: int | None = config.getint(
            "identified_tau_e_us", None, minval=0
        )
        self.identified_tau_e_crosscheck_us: int | None = config.getint(
            "identified_tau_e_crosscheck_us", None, minval=0
        )
        self.identified_tau_residual_permille: int | None = config.getint(
            "identified_tau_residual_permille", None, minval=0, maxval=1000
        )
        self.identified_inner_warning_flags: int | None = config.getint(
            "identified_inner_warning_flags", None, minval=0, maxval=255
        )

        # Stage 2 model parameters persisted for traceability.
        self.identified_j_eff: int | None = config.getint(
            "identified_j_eff", None, minval=0
        )
        self.identified_b_eff: int | None = config.getint(
            "identified_b_eff", None, minval=0
        )

        # Persisted profile/mode labels from SAVE_CONFIG.
        self.autotune_profile: str | None = config.get("autotune_profile", None)
        self.autotune_mode: str | None = config.get("autotune_mode", None)

        # Autotune status (commissioned / tuned / tuned_conservative)
        self.autotune_status: str | None = config.get("autotune_status", None)

        # Find stepper config section. The stepper may be defined as
        # [manual_stepper stepper_x], [stepper stepper_x], or [stepper_x]
        # depending on kinematics. The foci section always uses the short
        # name: [foci stepper_x].
        if not config.has_section(self.stepper_name):
            raise config.error(
                "[%s] cannot find stepper section for '%s'"
                % (self.name, self.stepper_name)
            )
        stepper_config = config.getsection(self.stepper_name)

        self.microsteps: int = stepper_config.getint("microsteps")
        self.full_steps: int = stepper_config.getint("full_steps_per_rotation", 200)

        # Resolve MCU and channel from step_pin
        step_pin: str = stepper_config.get("step_pin")
        ppins = self.printer.lookup_object("pins")
        pin_params = ppins.parse_pin(step_pin, can_invert=True)
        pin_name: str = pin_params["pin"]
        if pin_name not in STEP_PINS:
            raise config.error(
                "[%s] step_pin '%s' is not a FOCI STEP pin (expected one"
                " of: %s)" % (self.name, pin_name, ", ".join(sorted(STEP_PINS)))
            )
        self.mcu = pin_params["chip"]
        self.channel: int = STEP_PINS[pin_name]

        # Runtime FOCI commands use the Klipper stepper OID. It is resolved
        # after MCU identification, when Klipper has loaded all steppers.
        self.oid: int | None = None
        self.stepper_oid: int | None = None

        # Command handles — resolved in _handle_mcu_identify after
        # the MCU data dictionary is loaded.
        self.set_current_cmd = None
        self.set_encoder_cmd = None
        self.set_encoder_dir_cmd = None
        self.selftest_cmd = None
        self.read_reg_cmd = None
        self.calibrate_cmd = None
        self.dump_cmd = None
        self.set_pid_gains_cmd = None
        self.commission_cmd = None
        self.tune_cmd = None
        self.set_velocity_filter_cmd = None
        self.set_position_gains_cmd = None
        self.set_velocity_feedforward_cmd = None
        self.set_velocity_transient_feedforward_cmd = None
        self.set_accel_feedforward_cmd = None
        self.set_decoupling_feedforward_cmd = None
        self.set_position_lead_cmd = None
        self.set_phase_advance_cmd = None
        self.set_velocity_limit_cmd = None
        self.set_voltage_limit_cmd = None
        self.set_auto_calibrate_on_enable_cmd = None
        self.trace_info_cmd = None
        self.trace_fetch_cmd = None
        self.trace_start_cmd = None
        self.trace_stop_cmd = None
        self.stepper_get_position_cmd = None
        self.stepper_stats_cmd = None
        self.stepper_exec_stats_cmd = None
        self.stepper_timing_stats_cmd = None
        self.stepper_stop_stats_cmd = None
        self.stepper_perf_stats_cmd = None

        # Trace capture state
        self.state = FociRuntimeState()
        self._trace_info: dict | None = None
        self._trace_info_received: bool = False
        self.dump = RegisterDumpWorkflow(self)
        self.controls = ControlsWorkflow(self)
        self.homing = HomingWorkflow(self)
        self.commissioning = CommissioningWorkflow(self)

        # Selftest streaming state (populated by foci_selftest_result / foci_selftest_done).
        self._selftest_results: list[dict] = []
        self._selftest_complete: bool = False
        self._selftest_status: int = 0

        # Two-stage commissioning volatile state (per-session, not persisted)
        # See spec: docs/specs/2026-04-11-two-stage-foci-commissioning-design.md
        # Commissioning phase tracking (used by commission/tune progress callbacks)
        # Register GCode commands
        gcode = self.printer.lookup_object("gcode")
        register_gcode_commands(self, gcode, self.foci_mode)

        # Lifecycle events
        self.printer.register_event_handler(
            "klippy:mcu_identify", self._handle_mcu_identify
        )
        self.printer.register_event_handler("klippy:connect", self._handle_connect)
        self.printer.register_event_handler(
            "homing:home_rails_begin", self.homing.handle_home_rails_begin
        )
        self.printer.register_event_handler(
            "homing:homing_move_begin", self.homing.handle_homing_move_begin
        )
        self.printer.register_event_handler(
            "homing:homing_move_end", self.homing.handle_homing_move_end
        )

    def _find_linked_stepper(self):
        toolhead = self.printer.lookup_object("toolhead", None)
        if toolhead is not None:
            kin = toolhead.get_kinematics()
            rails = getattr(kin, "rails", None)
            if rails is None and hasattr(kin, "get_rails"):
                rails = kin.get_rails()
            if rails is not None:
                for rail in rails:
                    for stepper in rail.get_steppers():
                        if stepper.get_name() == self.stepper_name:
                            return stepper
            get_steppers = getattr(kin, "get_steppers", None)
            if get_steppers is not None:
                for stepper in get_steppers():
                    if stepper.get_name() == self.stepper_name:
                        return stepper
        for _name, manual_stepper in self.printer.lookup_objects("manual_stepper"):
            steppers = getattr(manual_stepper, "steppers", [])
            for stepper in steppers:
                if stepper.get_name() == self.stepper_name:
                    return stepper
        return None

    def _resolve_stepper_oid(self) -> int:
        force_move = self.printer.lookup_object("force_move", None)
        if force_move is not None and hasattr(force_move, "lookup_stepper"):
            stepper = force_move.lookup_stepper(self.stepper_name)
        else:
            stepper = self._find_linked_stepper()
        if stepper is None or not hasattr(stepper, "get_oid"):
            raise self.printer.config_error(
                "[%s] could not resolve MCU stepper OID for %s"
                % (self.name, self.stepper_name)
            )
        oid = stepper.get_oid()
        if oid is None:
            raise self.printer.config_error(
                "[%s] could not resolve MCU stepper OID for %s"
                % (self.name, self.stepper_name)
            )
        return oid

    def _handle_mcu_identify(self) -> None:
        """Look up MCU commands after data dictionary is loaded."""
        self.stepper_oid = self._resolve_stepper_oid()
        self.oid = self.stepper_oid
        cmd_queue = self.mcu.alloc_command_queue()
        self.stepper_get_position_cmd = self.mcu.lookup_query_command(
            "stepper_get_position oid=%c",
            "stepper_position oid=%c pos=%i",
            oid=self.oid,
        )
        self.stepper_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_stats oid=%c",
            "foci_stepper_stats_result oid=%c channel=%c position=%i"
            " queued_segments=%u queued_steps=%u"
            " loaded_segments=%u loaded_steps=%u"
            " discarded_segments=%u discarded_steps=%u"
            " timer_active=%c queue_len=%hu",
            oid=self.oid,
        )
        self.stepper_exec_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_exec_stats oid=%c",
            "foci_stepper_exec_stats_result oid=%c channel=%c"
            " executed_pos_steps=%u executed_neg_steps=%u"
            " queue_empty_count=%u missed_deadline_count=%u",
            oid=self.oid,
        )
        self.stepper_timing_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_timing_stats oid=%c",
            "foci_stepper_timing_stats_result oid=%c channel=%c"
            " activation_count=%u last_activation_clock=%u"
            " first_load_now=%u first_load_scheduled=%u first_load_compare=%u"
            " first_load_lead_ticks=%i first_load_compare_delay_ticks=%i"
            " first_step_clock=%u first_step_delay_ticks=%i",
            oid=self.oid,
        )
        self.stepper_stop_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_stop_stats oid=%c",
            "foci_stepper_stop_stats_result oid=%c channel=%c"
            " stop_count=%u stop_drained_segments=%u stop_drained_steps=%u"
            " reset_count=%u reset_drained_segments=%u reset_drained_steps=%u"
            " last_stop_reason=%c"
            " last_stop_remaining_events=%u last_stop_queue_len=%hu"
            " last_stop_drained_segments=%u last_stop_drained_steps=%u",
            oid=self.oid,
        )
        self.stepper_perf_stats_cmd = self.mcu.lookup_query_command(
            "foci_stepper_perf_stats oid=%c clear=%c",
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
            " stepper_load_lateness_last_ticks=%i build_trace_enabled=%c",
            oid=self.oid,
        )
        self.set_current_cmd = self.mcu.lookup_command(
            "tmc_set_current oid=%c run_ma=%u"
        )
        self.set_encoder_cmd = self.mcu.lookup_command(
            "tmc_set_encoder oid=%c channel=%c ppr=%u"
        )
        self.set_encoder_dir_cmd = self.mcu.lookup_command(
            "tmc_set_encoder_dir oid=%c channel=%c invert=%c"
        )
        self.selftest_cmd = self.mcu.lookup_command("foci_selftest oid=%c")
        # tmc_read_register is only available in dev firmware builds
        # (#[cfg(feature = "dev")]). Gracefully degrade on release builds.
        try:
            self.read_reg_cmd = self.mcu.lookup_query_command(
                "tmc_read_register oid=%c addr=%c",
                "tmc_register_value oid=%c addr=%c value=%u",
                oid=self.oid,
            )
        except Exception:
            self.read_reg_cmd = None
        self.calibrate_cmd = self.mcu.lookup_command(
            "foci_calibrate oid=%c", cq=cmd_queue
        )
        self.dump_cmd = self.mcu.lookup_command("foci_dump_registers oid=%c")
        self.mcu._serial.register_response(
            self.dump.handle_dump_value, "foci_dump_value", self.oid
        )
        self.mcu._serial.register_response(
            self.dump.handle_dump_done, "foci_dump_done", self.oid
        )
        self.mcu._serial.register_response(
            self.homing.handle_calibrate_response, "foci_calibrate_result", self.oid
        )
        self.set_pid_gains_cmd = self.mcu.lookup_command(
            "tmc_set_pid_gains oid=%c flux_p=%hu flux_i=%hu torque_p=%hu torque_i=%hu"
        )
        self.commission_cmd = self.mcu.lookup_command(
            "foci_commission oid=%c profile=%c"
        )
        self.tune_cmd = self.mcu.lookup_command(
            "foci_tune oid=%c profile=%c mode=%c"
            " inner_lambda=%u theta_e=%u current_ringing=%c current_bw=%u"
            " tau_e_us=%u tau_e_crosscheck_us=%u"
            " tau_residual_permille=%hu inner_warning_flags=%c"
        )
        self.mcu._serial.register_response(
            self.commissioning.handle_commission_phase,
            "foci_commission_phase",
            self.oid,
        )
        self.mcu._serial.register_response(
            self.commissioning.handle_commission_result,
            "foci_commission_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_tune_result,
            "foci_tune_result",
            self.oid,
        )
        self.set_velocity_filter_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_filter oid=%c filter_hz=%hu"
        )
        self.set_torque_filter_cmd = self.mcu.lookup_command(
            "tmc_set_torque_filter oid=%c filter_hz=%hu"
        )
        self.set_position_filter_cmd = self.mcu.lookup_command(
            "tmc_set_position_filter oid=%c filter_hz=%hu"
        )
        self.set_flux_filter_cmd = self.mcu.lookup_command(
            "tmc_set_flux_filter oid=%c filter_hz=%hu"
        )
        self.set_position_gains_cmd = self.mcu.lookup_command(
            "tmc_set_position_gains oid=%c position_p=%hu position_i=%hu"
            " velocity_p=%hu velocity_i=%hu"
        )
        self.set_velocity_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_feedforward oid=%c enable=%c multiplier=%hu"
        )
        self.set_velocity_transient_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_transient_feedforward oid=%c enable=%c"
            " lead_time_us=%hu gain_permille=%hu max_offset=%hu rate_hz=%hu"
        )
        self.set_accel_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_accel_feedforward oid=%c enable=%c"
            " accel_gain_permille=%hu decel_gain_permille=%hu"
        )
        self.set_decoupling_feedforward_cmd = self.mcu.lookup_command(
            "tmc_set_decoupling_feedforward oid=%c enable=%c"
            " r_int=%u l_int=%u pole_pairs=%hu position_units_per_rev=%u"
            " f_pwm_hz=%u max_offset=%hu"
        )
        self.set_position_lead_cmd = self.mcu.lookup_command(
            "tmc_set_position_lead oid=%c enable=%c gain_permille=%hu max_counts=%hu"
        )
        self.set_phase_advance_cmd = self.mcu.lookup_command(
            "tmc_set_phase_advance oid=%c enable=%c"
            " gain_ppm=%i max_counts=%hu deadband=%hu"
        )
        self.set_velocity_limit_cmd = self.mcu.lookup_command(
            "tmc_set_velocity_limit oid=%c limit=%u"
        )
        self.set_voltage_limit_cmd = self.mcu.lookup_command(
            "tmc_set_voltage_limit oid=%c voltage_limit=%u"
        )
        self.current_step_test_cmd = self.mcu.lookup_command(
            "tmc_current_step_test oid=%c target=%hi duration_ms=%hu voltage_limit=%hu"
        )
        self.current_vector_step_test_cmd = self.mcu.lookup_command(
            "tmc_current_vector_step_test oid=%c torque_target=%hi flux_target=%hi"
            " duration_ms=%hu voltage_limit=%hu"
        )
        self.current_torque_sample_test_cmd = self.mcu.lookup_command(
            "tmc_current_torque_sample_test oid=%c target=%hi flux_target=%hi"
            " sample_delay_ms=%hu voltage_limit=%hu"
        )
        self.position_torque_offset_sample_test_cmd = self.mcu.lookup_command(
            "tmc_position_torque_offset_sample_test oid=%c target=%hi"
            " sample_delay_ms=%hu voltage_limit=%hu"
        )
        self.voltage_step_test_cmd = self.mcu.lookup_command(
            "tmc_voltage_step_test oid=%c uq_ext=%hi ud_ext=%hi sample_delay_ms=%hu"
        )
        self.mcu._serial.register_response(
            self._handle_current_step_result,
            "foci_current_step_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_current_vector_step_result,
            "foci_current_vector_step_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_current_torque_sample_result,
            "foci_current_torque_sample_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_current_torque_sample_detail_result,
            "foci_current_torque_sample_detail_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_voltage_step_result,
            "foci_voltage_step_result",
            self.oid,
        )
        self.set_auto_calibrate_on_enable_cmd = self.mcu.lookup_command(
            "tmc_set_auto_calibrate_on_enable oid=%c enable=%c"
        )
        self.trace_info_cmd = self.mcu.lookup_command("foci_trace_info oid=%c")
        self.trace_start_cmd = self.mcu.lookup_command(
            "foci_trace_start oid=%c preset=%c"
        )
        self.trace_stop_cmd = self.mcu.lookup_command("foci_trace_stop oid=%c")
        self.trace_fetch_cmd = self.mcu.lookup_query_command(
            "foci_trace_fetch oid=%c offset=%hu generation=%c",
            "foci_trace_data oid=%c offset=%hu status=%c data=%*s",
            oid=self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_trace_info_result,
            "foci_trace_info_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_selftest_result,
            "foci_selftest_result",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_selftest_done,
            "foci_selftest_done",
            self.oid,
        )
        self.mcu._serial.register_response(
            self.commissioning.handle_commission_detail,
            "foci_commission_detail",
            self.oid,
        )
        self.mcu._serial.register_response(
            self._handle_stepper_event,
            "foci_stepper_event",
        )
        self.mcu._serial.register_response(
            self._handle_stepper_perf_event,
            "foci_stepper_perf_event",
        )

    def _read_register(self, reg_name: str) -> int:
        """Read a single TMC4671 register via the firmware.

        Args:
            reg_name: Name of the register to read (must be in REGISTERS).

        Returns:
            The 32-bit register value returned by the firmware.

        Raises:
            command_error: If raw register access is not available in this
                firmware build.
        """
        if self.read_reg_cmd is None:
            raise self.printer.command_error(
                "Raw register access requires dev firmware build"
            )
        addr = REGISTERS[reg_name]
        params = self.read_reg_cmd.send([self.oid, addr])
        return params["value"]

    @staticmethod
    def _stepper_dir_inverted(stepper) -> bool:
        get_dir_inverted = getattr(stepper, "get_dir_inverted", None)
        if get_dir_inverted is None:
            return False
        dir_info = get_dir_inverted()
        if isinstance(dir_info, (list, tuple)):
            return bool(dir_info[0])
        return bool(dir_info)

    # -----------------------------------------------------------------
    # Commissioning phase/error/profile/mode maps
    # -----------------------------------------------------------------

    STEPPER_EVENT_REASON_NAMES: dict[int, str] = {
        1: "queue_empty",
        2: "missed_deadline_load",
        3: "missed_deadline_step",
        4: "trsync_stop",
        5: "p1_stop",
        6: "reset_step_clock",
        7: "tmc_disable_signal",
    }

    MODE_MAP: dict[str, int] = {
        "unloaded": 0,
        "nominal": 1,
        "high_inertia": 2,
    }

    SELFTEST_STAGES: dict[int, str] = {
        1: "ADC calibration",
        2: "Motor coil A",
        3: "Motor coil B",
        4: "Phase wiring",
        5: "Encoder",
        6: "Encoder direction",
        7: "Resistance",
        8: "Inductance",
    }

    @staticmethod
    def _format_selftest_value(stage: int, status: int, value: int) -> str:
        """Return a stage-specific detail string (empty string for bare PASS).

        ``value`` is decoded per the firmware-side encoding in foci-core:

        - stage 1 (ADC calibration): low 16 bits = offset_i0, high 16 bits = offset_i1
        - stages 2, 3 (coil currents): i16 bit-reinterpreted as u16, then zero-extended
        - stage 4 (phase wiring): value is always 0
        - stage 5 (encoder delta): unsigned magnitude (sign in stage 6)
        - stage 6 (encoder direction): 0 = increasing, 1 = reversed
        - stage 7 (resistance): milliohms
        - stage 8 (inductance): microhenries

        Args:
            stage: Stage number (1–8) as reported by the firmware.
            status: 0 = pass, non-zero = fail.
            value: Stage-specific encoded value from the firmware.

        Returns:
            A parenthesised detail string, or an empty string when no
            per-stage detail is applicable (e.g. bare phase-wiring pass).
        """
        if status != 0:
            return " (FAIL, raw=%d)" % value
        if stage == 1:
            offset_i0 = value & 0xFFFF
            offset_i1 = (value >> 16) & 0xFFFF
            return " (offset_i0=%d, offset_i1=%d)" % (offset_i0, offset_i1)
        if stage in (2, 3):
            # Value is an i16 whose two's-complement bit pattern was stored
            # in the low 16 bits of a u32. Reinterpret bit 15 as sign.
            low16 = value & 0xFFFF
            signed = low16 if low16 < 0x8000 else low16 - 0x10000
            return " (current=%d)" % signed
        if stage == 4:
            return ""
        if stage == 5:
            return " (delta=%d)" % value
        if stage == 6:
            return " (reversed)" if value == 1 else " (increasing)"
        if stage == 7:
            return " (%.1f ohm)" % (value / 1000.0)
        if stage == 8:
            return " (%.1f mH)" % (value / 1000.0)
        return ""

    def _handle_tune_result(self, params: dict) -> None:
        """Handle foci_tune_result from firmware (Stage 2 completion)."""
        self.commissioning.result = params
        self.commissioning.done = True

    def _handle_current_step_result(self, params: dict) -> None:
        """Handle foci_current_step_result from firmware."""
        msg = (
            "FOCI %s current step: status=%d target=%d actual=%d"
            " before=%d after=%d flux=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.name,
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
        self.printer.lookup_object("gcode").respond_info(msg)

    def _handle_current_vector_step_result(self, params: dict) -> None:
        """Handle foci_current_vector_step_result from firmware."""
        msg = (
            "FOCI %s current vector step: status=%d"
            " torque_target=%d flux_target=%d"
            " actual_torque=%d actual_flux=%d"
            " before=%d after=%d iq=%d id=%d"
            " uq_limited=%d ud_limited=%d"
            " enc_before=%d enc_after=%d enc_delta=%d adc_vm_raw=%d"
            % (
                self.name,
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
        self.printer.lookup_object("gcode").respond_info(msg)

    def _handle_current_torque_sample_result(self, params: dict) -> None:
        """Handle foci_current_torque_sample_result from firmware."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        detail = self._current_torque_sample_details.pop(detail_key, {})
        label = self._current_torque_sample_labels.pop(
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
                self.name,
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
        self.printer.lookup_object("gcode").respond_info(msg)

    def _handle_current_torque_sample_detail_result(self, params: dict) -> None:
        """Cache split current torque sample details until the base reply arrives."""
        detail_key = (
            params["target"],
            params.get("flux_target", 0),
            params["sample_delay_ms"],
            params["voltage_limit"],
        )
        self._current_torque_sample_details[detail_key] = params

    def _handle_voltage_step_result(self, params: dict) -> None:
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
                self.name,
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
        self.printer.lookup_object("gcode").respond_info(msg)

    def _format_stepper_event(self, params: dict) -> str:
        """Format one firmware stepper diagnostic event."""
        reason_code = params.get("reason", 0)
        reason_name = self.STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")
        return (
            "FOCI_STEPPER_EVENT %s reason=%s(%d) channel=%d pos=%d"
            " clock=%d timer_active=%d queue_len=%d dir=%d data0=%d data1=%d"
            % (
                self.stepper_name,
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

    def _handle_stepper_event(self, params: dict) -> None:
        """Handle bounded firmware stepper diagnostics."""
        message = self._format_stepper_event(params)
        log.info(message)
        gcode = self.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def _format_stepper_perf_event(self, params: dict) -> str:
        """Format one fatal firmware step-dispatch performance snapshot."""
        reason_code = params.get("reason", 0)
        reason_name = self.STEPPER_EVENT_REASON_NAMES.get(reason_code, "unknown")

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
                self.stepper_name,
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

    def _handle_stepper_perf_event(self, params: dict) -> None:
        """Handle fatal firmware step-dispatch performance snapshots."""
        message = self._format_stepper_perf_event(params)
        log.info(message)
        gcode = self.printer.lookup_object("gcode", None)
        if gcode is not None:
            gcode.respond_info(message)

    def _handle_selftest_result(self, params: dict) -> None:
        """Collect one stage result streamed during FOCI_SELFTEST."""
        result = {
            "stage": params["stage"],
            "status": params["status"],
            "value": params["value"],
        }
        for idx, existing in enumerate(self._selftest_results):
            if existing["stage"] == result["stage"]:
                self._selftest_results[idx] = result
                return
        self._selftest_results.append(result)

    def _handle_selftest_done(self, params: dict) -> None:
        """Terminal signal for FOCI_SELFTEST."""
        self._selftest_complete = True
        self._selftest_status = params["status"]

    def cmd_FOCI_STEP_POSITION(self, gcmd) -> None:
        """Query raw MCU step position without updating Klipper state."""
        if self.stepper_get_position_cmd is None or self.oid is None:
            raise gcmd.error("FOCI_STEP_POSITION is not available before MCU identify")

        stepper = self._find_linked_stepper()
        if stepper is None:
            raise gcmd.error(
                "FOCI_STEP_POSITION could not find linked stepper %s"
                % self.stepper_name
            )

        params = self.stepper_get_position_cmd.send([self.oid])
        if params is None or "pos" not in params:
            raise gcmd.error("FOCI_STEP_POSITION query returned no position")

        raw_position = int(params["pos"])
        invert_dir = self._stepper_dir_inverted(stepper)
        host_position = -raw_position if invert_dir else raw_position

        get_mcu_position = getattr(stepper, "get_mcu_position", None)
        klipper_position = None
        delta = None
        if get_mcu_position is not None:
            klipper_position = int(get_mcu_position())
            delta = host_position - klipper_position

        parts = [
            "FOCI_STEP_POSITION %s:" % self.stepper_name,
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

    def cmd_FOCI_STEPPER_STATS(self, gcmd) -> None:
        """Query MCU step queue and execution counters."""
        query_cmds = (
            ("stats", self.stepper_stats_cmd),
            ("exec_stats", self.stepper_exec_stats_cmd),
            ("timing_stats", self.stepper_timing_stats_cmd),
            ("stop_stats", self.stepper_stop_stats_cmd),
        )
        if self.oid is None or any(cmd is None for _, cmd in query_cmds):
            raise gcmd.error("FOCI_STEPPER_STATS is not available before MCU identify")

        params = {}
        for name, cmd in query_cmds:
            response = cmd.send([self.oid])
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
        parts = ["FOCI_STEPPER_STATS %s:" % self.stepper_name]
        for field in fields:
            parts.append("%s=%s" % (field, params.get(field, "?")))
        gcmd.respond_info(" ".join(parts))

    def cmd_FOCI_DISPATCH_STATS(self, gcmd) -> None:
        """Query MCU step-dispatch cycle counters."""
        if self.oid is None or self.stepper_perf_stats_cmd is None:
            raise gcmd.error("FOCI_DISPATCH_STATS is not available before MCU identify")

        clear = gcmd.get_int("RESET", 0, minval=0, maxval=1)
        response = self.stepper_perf_stats_cmd.send([self.oid, clear])
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
        parts = ["FOCI_DISPATCH_STATS %s:" % self.stepper_name]
        for field in fields:
            parts.append("%s=%s" % (field, response.get(field, "?")))
        parts.append("crit_max_us=%s" % cycles_to_us("crit_max_cycles"))
        parts.append("queue_step_max_us=%s" % cycles_to_us("queue_step_max_cycles"))
        parts.append("tim5_irq_max_us=%s" % cycles_to_us("tim5_irq_max_cycles"))
        parts.append(
            "tim5_dispatch_max_us=%s" % cycles_to_us("tim5_dispatch_max_cycles")
        )
        gcmd.respond_info(" ".join(parts))

    def _validate_and_load_config(self) -> None:
        """Validate persisted config and populate _active_gains/_runtime_status.

        Called from _handle_connect. Checks that all mandatory fields for the
        claimed autotune_status are present. If any are missing, logs a warning
        and leaves _active_gains and _runtime_status as None (motor cannot be
        enabled until FOCI_COMMISSION is run).
        """
        status = self.autotune_status
        if status is None:
            # No prior commissioning -- virgin hardware
            self.state.runtime_status = "uncommissioned"
            self.state.active_gains = None
            return

        valid_statuses = ("commissioned", "tuned", "tuned_conservative")
        if status not in valid_statuses:
            logging.warning(
                "FOCI %s: unknown autotune_status='%s' (expected one of: %s). "
                "Motor cannot be enabled until FOCI_COMMISSION is run.",
                self.name,
                status,
                ", ".join(valid_statuses),
            )
            self.state.runtime_status = "uncommissioned"
            self.state.active_gains = None
            return

        # Mandatory for all statuses: current-loop gains + inner-tuning params
        required_base = [
            ("pid_flux_p", self.pid_flux_p),
            ("pid_flux_i", self.pid_flux_i),
            ("pid_torque_p", self.pid_torque_p),
            ("pid_torque_i", self.pid_torque_i),
            ("identified_lambda_us", self.identified_lambda_us),
            ("identified_theta_e_us", self.identified_theta_e_us),
            ("identified_ringing_count", self.identified_ringing_count),
            ("identified_bandwidth_hz", self.identified_bandwidth_hz),
        ]
        missing = [name for name, val in required_base if val is None]

        # Status-specific outer gain requirements
        if status == "commissioned":
            commissioned_fields = [
                ("commissioned_velocity_p", self.commissioned_velocity_p),
                ("commissioned_velocity_i", self.commissioned_velocity_i),
                ("commissioned_position_p", self.commissioned_position_p),
                ("commissioned_position_i", self.commissioned_position_i),
                ("commissioned_velocity_limit", self.commissioned_velocity_limit),
            ]
            missing.extend(name for name, val in commissioned_fields if val is None)
        elif status in ("tuned", "tuned_conservative"):
            tuned_fields = [
                ("pid_velocity_p", self.pid_velocity_p),
                ("pid_velocity_i", self.pid_velocity_i),
                ("pid_velocity_limit", self.pid_velocity_limit),
                ("pid_position_p", self.pid_position_p),
                ("pid_position_i", self.pid_position_i),
            ]
            missing.extend(name for name, val in tuned_fields if val is None)

        if missing:
            logging.warning(
                "FOCI %s: autotune_status='%s' but missing required fields: %s. "
                "Motor cannot be enabled until FOCI_COMMISSION is run.",
                self.name,
                status,
                ", ".join(missing),
            )
            self.state.runtime_status = "uncommissioned"
            self.state.active_gains = None
            return

        # All required fields present -- build _active_gains
        if status == "commissioned":
            self.state.active_gains = {
                "flux_p": self.pid_flux_p,
                "flux_i": self.pid_flux_i,
                "torque_p": self.pid_torque_p,
                "torque_i": self.pid_torque_i,
                "velocity_p": self.commissioned_velocity_p,
                "velocity_i": self.commissioned_velocity_i,
                "position_p": self.commissioned_position_p,
                "position_i": self.commissioned_position_i,
                "velocity_limit": self.commissioned_velocity_limit,
                "velocity_filter_hz": self.velocity_filter_hz,
                "torque_filter_hz": self.torque_filter_hz,
                "position_filter_hz": self.position_filter_hz,
                "flux_filter_hz": self.flux_filter_hz,
            }
        else:  # tuned or tuned_conservative
            self.state.active_gains = {
                "flux_p": self.pid_flux_p,
                "flux_i": self.pid_flux_i,
                "torque_p": self.pid_torque_p,
                "torque_i": self.pid_torque_i,
                "velocity_p": self.pid_velocity_p,
                "velocity_i": self.pid_velocity_i,
                "position_p": self.pid_position_p,
                "position_i": self.pid_position_i,
                "velocity_limit": self.pid_velocity_limit,
                "velocity_filter_hz": self.velocity_filter_hz,
                "torque_filter_hz": self.torque_filter_hz,
                "position_filter_hz": self.position_filter_hz,
                "flux_filter_hz": self.flux_filter_hz,
            }
        self.state.runtime_status = status
        logging.info(
            "FOCI %s: loaded config, status=%s, active gains ready",
            self.name,
            status,
        )

    def _handle_connect(self) -> None:
        """Send configuration to firmware and check microstep alignment.

        Converts run_current to milliamps and sends it with the encoder
        PPR to the firmware. Warns if the configured microstep resolution
        does not match the encoder's natural resolution.
        """
        run_ma: int = int(self.run_current * 1000.0)
        self.set_current_cmd.send([self.oid, run_ma])
        self.set_voltage_limit_cmd.send([self.oid, self.voltage_limit])
        self.set_encoder_cmd.send([self.oid, self.channel, self.encoder_ppr])
        self.set_encoder_dir_cmd.send(
            [self.oid, self.channel, int(self.encoder_reversed)]
        )
        # Send saved PID gains if present (all-or-none validated at config time).
        # Otherwise firmware uses conservative defaults.
        if self.pid_flux_p is not None:
            self.set_pid_gains_cmd.send(
                [
                    self.oid,
                    self.pid_flux_p,
                    self.pid_flux_i,
                    self.pid_torque_p,
                    self.pid_torque_i,
                ]
            )
        if self.velocity_filter_hz > 0:
            self.set_velocity_filter_cmd.send([self.oid, self.velocity_filter_hz])
        if self.torque_filter_hz > 0:
            self.set_torque_filter_cmd.send([self.oid, self.torque_filter_hz])
        if self.position_filter_hz > 0:
            self.set_position_filter_cmd.send([self.oid, self.position_filter_hz])
        if self.flux_filter_hz > 0:
            self.set_flux_filter_cmd.send([self.oid, self.flux_filter_hz])
        if self.pid_position_p is not None:
            self.set_position_gains_cmd.send(
                [
                    self.oid,
                    self.pid_position_p,
                    self.pid_position_i,
                    self.pid_velocity_p,
                    self.pid_velocity_i,
                ]
            )
        if self.velocity_feedforward:
            self.set_velocity_feedforward_cmd.send(
                [self.oid, 1, self.velocity_feedforward_multiplier]
            )
        if self.pid_velocity_limit is not None:
            self.set_velocity_limit_cmd.send([self.oid, self.pid_velocity_limit])
        encoder_steps: int = self.encoder_ppr * 4
        configured_steps: int = self.microsteps * self.full_steps
        if configured_steps != encoder_steps:
            optimal: int = encoder_steps // self.full_steps
            gcode = self.printer.lookup_object("gcode")
            gcode.respond_info(
                "[foci %s] Note: microsteps=%d gives %d steps/rev,"
                " encoder resolves %d. Consider microsteps=%d"
                % (
                    self.stepper_name,
                    self.microsteps,
                    configured_steps,
                    encoder_steps,
                    optimal,
                )
            )
        self._validate_and_load_config()
        if self.state.active_gains is not None and not self.state.inhibited:
            self.homing.apply_active_gains_to_firmware()
        self.homing.set_auto_calibrate_on_enable_allowed(
            self.state.active_gains is not None and not self.state.inhibited
        )
        self.homing.install_enable_hooks()

    def cmd_FOCI_SELFTEST(self, gcmd) -> None:
        """Run TMC4671 self-test and emit a per-stage report.

        Sends foci_selftest; firmware streams foci_selftest_result for
        each completed stage and a terminal foci_selftest_done. This
        handler collects the stream and formats the GCode console report.

        Selftest includes encoder alignment, so homing is invalidated at
        command-accepted time.
        """
        if not self.state.try_acquire():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.name
            )
        try:
            self.homing.invalidate_homing()

            reactor = self.printer.get_reactor()
            self._selftest_results = []
            self._selftest_complete = False
            self._selftest_status = 0
            self.commissioning.clear_details()

            self.selftest_cmd.send([self.oid])

            # Wait for the terminal foci_selftest_done message (15 s timeout).
            deadline = reactor.monotonic() + 15.0
            while not self._selftest_complete:
                if reactor.monotonic() > deadline:
                    raise self.printer.command_error(
                        "FOCI %s: selftest timed out" % self.stepper_name
                    )
                reactor.pause(reactor.monotonic() + 0.05)
        finally:
            self.state.release()

        status_names = {0: "PASS", 1: "FAIL", 2: "SKIP"}
        lines = ["Self-Test: %s" % self.stepper_name]
        passed = 0
        total = len(self._selftest_results)
        for result in self._selftest_results:
            stage_id = result["stage"]
            stage_status = result["status"]
            stage_value = result["value"]
            name = self.SELFTEST_STAGES.get(stage_id, "Stage %d" % stage_id)
            status_str = status_names.get(stage_status, "?")
            detail = self._format_selftest_value(stage_id, stage_status, stage_value)
            dots = "." * max(1, 35 - len(name))
            lines.append("  %s %s %s%s" % (name, dots, status_str, detail))
            if stage_status == 0:
                passed += 1

        if self.commissioning.details:
            lines.append("Diagnostics:")
            for detail in self.commissioning.details:
                lines.append("  %s" % format_commission_detail(detail))

        if self._selftest_status == 0:
            overall = "PASS"
        else:
            err = COMMISSION_ERROR_NAMES.get(
                self._selftest_status, "unknown error %d" % self._selftest_status
            )
            self.commissioning.maybe_clear_calibration_for_chip_reset(
                self._selftest_status
            )
            overall = "FAIL (%s)" % err
        lines.append("Result: %s (%d/%d stages)" % (overall, passed, total))
        gcmd.respond_info("\n".join(lines))

        if self._selftest_status != 0:
            err = COMMISSION_ERROR_NAMES.get(
                self._selftest_status, "unknown error %d" % self._selftest_status
            )
            self.commissioning.maybe_clear_calibration_for_chip_reset(
                self._selftest_status
            )
            raise self.printer.command_error(
                "FOCI %s: selftest failed: %s" % (self.stepper_name, err)
            )

    def _resolve_inner_confidence(self) -> tuple[int, int, int, int]:
        """Resolve the four Phase 1 inner-confidence fields for Stage 2.

        Returns ``(tau_e_us, tau_e_crosscheck_us, tau_residual_permille,
        inner_warning_flags)``. Fresh Stage 1 results from
        ``_commissioned_result`` win over persisted values; persisted
        values fall back to documented defaults when absent (used only
        for old configs that pre-date this field set).
        """
        if self.state.commissioned_result is not None:
            r = self.state.commissioned_result
            return (
                r.get("tau_e_us", 0),
                r.get("tau_e_crosscheck_us", 0),
                r.get("tau_residual_permille", 1000),
                r.get("inner_warning_flags", 0),
            )

        tau_e_us = self.identified_tau_e_us
        if tau_e_us is None:
            # Spec wording: "when `identified_lambda_us` is available,
            # otherwise 1000". Treat only `None` as missing — a genuine
            # zero (implausible but legal) maps to the 1000us floor.
            if self.identified_lambda_us is None:
                tau_e_us = 1000
            else:
                tau_e_us = max(self.identified_lambda_us, 1000)

        tau_e_crosscheck_us = self.identified_tau_e_crosscheck_us
        if tau_e_crosscheck_us is None:
            tau_e_crosscheck_us = 0

        tau_residual_permille = self.identified_tau_residual_permille
        if tau_residual_permille is None:
            tau_residual_permille = 1000

        inner_warning_flags = self.identified_inner_warning_flags
        if inner_warning_flags is None:
            # Bit 6: host-defaulted confidence data (no fresh measurement).
            inner_warning_flags = 0x40

        return (
            tau_e_us,
            tau_e_crosscheck_us,
            tau_residual_permille,
            inner_warning_flags,
        )

    def cmd_FOCI_AUTOTUNE(self, gcmd) -> None:
        """Stage 2: installed tuning after commissioning and homing.

        Runs mechanical ID, velocity/position tuning, filter selection,
        and commit. Requires motor calibrated, enabled, in closed-loop
        position mode, and printer fully homed.
        """
        profile_name = gcmd.get("PROFILE", "balanced").lower()
        mode_name = gcmd.get("MODE", "nominal").lower()
        if profile_name not in PROFILE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown profile '%s' (expected: %s)"
                % (self.name, profile_name, ", ".join(sorted(PROFILE_MAP)))
            )
        if mode_name not in self.MODE_MAP:
            raise gcmd.error(
                "FOCI %s: unknown mode '%s' (expected: %s)"
                % (self.name, mode_name, ", ".join(sorted(self.MODE_MAP)))
            )

        # Hard gates -- before any side effects
        if not self.state.try_acquire():
            raise gcmd.error(
                "FOCI %s: another FOCI operation is in progress" % self.name
            )

        try:
            if self.state.inhibited:
                raise gcmd.error(
                    "FOCI %s: inhibited after failed FOCI_COMMISSION" % self.name
                )
            if self.state.runtime_status == "uncommissioned":
                raise gcmd.error(
                    "FOCI %s: not commissioned. Run FOCI_COMMISSION first." % self.name
                )
            if not self.state.is_calibrated:
                raise gcmd.error(
                    "FOCI %s: not calibrated. Enable motor, re-home, then retry."
                    % self.name
                )

            # Check homing — skip for NoneKinematics (manual_stepper has
            # no kinematic axes and never reports homed_axes).
            toolhead = self.printer.lookup_object("toolhead")
            kinematics = toolhead.get_kinematics()
            if hasattr(kinematics, "rails"):
                kin_status = toolhead.get_status(toolhead.get_last_move_time())
                homed = set(kin_status.get("homed_axes", ""))
                expected = set("xyz")  # full homing required
                if not expected.issubset(homed):
                    missing = expected - homed
                    raise gcmd.error(
                        "FOCI %s: printer not fully homed (missing: %s). "
                        "Home first." % (self.name, "".join(sorted(missing)))
                    )

            # Setup sequence (lock held)
            toolhead.wait_moves()

            # Post-wait revalidation
            if not self.state.is_calibrated:
                raise gcmd.error("FOCI %s: calibration lost during wait" % self.name)
            if hasattr(kinematics, "rails"):
                kin_status = toolhead.get_status(toolhead.get_last_move_time())
                if not expected.issubset(set(kin_status.get("homed_axes", ""))):
                    raise gcmd.error("FOCI %s: homing lost during wait" % self.name)

            self.homing.invalidate_homing()

            # Get inner-tuning params from cache or config
            if self.state.commissioned_result is not None:
                inner_lambda = self.state.commissioned_result["lambda_us"]
                theta_e = self.state.commissioned_result["theta_e_us"]
                ringing = self.state.commissioned_result["ringing_count"]
                bandwidth = self.state.commissioned_result["bandwidth_hz"]
            else:
                inner_lambda = self.identified_lambda_us
                theta_e = self.identified_theta_e_us
                ringing = self.identified_ringing_count
                bandwidth = self.identified_bandwidth_hz

            (
                tau_e_us,
                tau_e_crosscheck_us,
                tau_residual_permille,
                inner_warning_flags,
            ) = self._resolve_inner_confidence()

            # Send tune command
            self.commissioning.done = False
            self.commissioning.result = None
            self.commissioning.error_code = 0

            self.tune_cmd.send(
                [
                    self.oid,
                    PROFILE_MAP[profile_name],
                    self.MODE_MAP[mode_name],
                    inner_lambda,
                    theta_e,
                    ringing,
                    bandwidth,
                    tau_e_us,
                    tau_e_crosscheck_us,
                    tau_residual_permille,
                    inner_warning_flags,
                ]
            )

            # Wait for result (up to 30 seconds).
            # foci_tune_result is emitted for all outcomes: success, soft failure,
            # and safety fault (OuterFailed always sends foci_tune_result).
            reactor = self.printer.get_reactor()
            eventtime = reactor.monotonic()
            timeout = eventtime + 30.0
            while not self.commissioning.done:
                eventtime = reactor.pause(eventtime + 0.1)
                if eventtime > timeout:
                    raise gcmd.error("FOCI %s: FOCI_AUTOTUNE timed out" % self.name)
                if self.commissioning.error_code != 0:
                    error_name = COMMISSION_ERROR_NAMES.get(
                        self.commissioning.error_code,
                        "UNKNOWN(%d)" % self.commissioning.error_code,
                    )
                    self.commissioning.maybe_clear_calibration_for_chip_reset(
                        self.commissioning.error_code
                    )
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE failed: %s" % (self.name, error_name)
                    )

            result = self.commissioning.result
            status = result.get("status", 255)
            if status > 1:
                error_name = COMMISSION_ERROR_NAMES.get(status, "UNKNOWN(%d)" % status)
                if status == 18:
                    self.commissioning.handle_chip_reset_detected()
                    stepper_enable = self.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE chip reset: %s "
                        "(motor disabled by firmware)" % (self.name, error_name)
                    )
                elif status in HARD_FAULT_CODES:
                    # Hard fault: firmware disabled motor, cleared state.
                    # Sync host-side state and block raw-enable auto-calibration
                    # until a fresh Stage 1 commission succeeds.
                    self.commissioning.on_commission_failure()
                    stepper_enable = self.printer.lookup_object("stepper_enable")
                    enable_line = stepper_enable.lookup_enable(self.stepper_name)
                    enable_line.motor_disable(toolhead.get_last_move_time())
                    raise gcmd.error(
                        "FOCI %s: FOCI_AUTOTUNE safety fault: %s "
                        "(motor disabled by firmware)" % (self.name, error_name)
                    )
                # Soft failure -- firmware restored entry gains
                gcmd.respond_info(
                    "FOCI %s: FOCI_AUTOTUNE failed: %s "
                    "(motor holding with entry gains)" % (self.name, error_name)
                )
                return  # _runtime_status unchanged, gains preserved

            # Determine tuned vs tuned_conservative
            warning_code = result.get("warning_code", 0)
            if status == 1 or warning_code != 0:
                tune_status = "tuned_conservative"
            else:
                tune_status = "tuned"

            # Update _active_gains with tuned outer gains + existing current-loop
            self.state.active_gains = {
                "flux_p": self.state.active_gains["flux_p"],
                "flux_i": self.state.active_gains["flux_i"],
                "torque_p": self.state.active_gains["torque_p"],
                "torque_i": self.state.active_gains["torque_i"],
                "velocity_p": result["velocity_p"],
                "velocity_i": result["velocity_i"],
                "position_p": result["position_p"],
                "position_i": result["position_i"],
                "velocity_limit": result["velocity_limit"],
                "velocity_filter_hz": result["velocity_filter_hz"],
                "torque_filter_hz": result["torque_filter_hz"],
                "position_filter_hz": result["position_filter_hz"],
                "flux_filter_hz": result["flux_filter_hz"],
            }
            self.state.runtime_status = tune_status

            # Persist tuned gains
            self._persist_tune_results(result, mode_name, tune_status)

            gcmd.respond_info(
                "FOCI %s tuned (%s): vel_p=%d pos_p=%d"
                % (
                    self.name,
                    tune_status,
                    result["velocity_p"],
                    result["position_p"],
                )
            )
            # Reuse the inner_warning_flags resolved earlier in this command —
            # they were sent to the firmware along with the tune request and
            # have not changed since.
            if inner_warning_flags:
                gcmd.respond_info(
                    "FOCI %s inner confidence: %s"
                    % (
                        self.name,
                        format_inner_warning_flags(inner_warning_flags),
                    )
                )
        finally:
            self.state.release()

    def cmd_FOCI_CURRENT_STEP_TEST(self, gcmd) -> None:
        """Run a bounded current-loop step diagnostic.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, and outside a homing move.
        """
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.current_step_test_cmd.send([self.oid, target, duration_ms, voltage_limit])

        gcmd.respond_info(
            "FOCI %s current-step requested: target=%d"
            " duration_ms=%d voltage_limit=%d"
            % (self.name, target, duration_ms, voltage_limit)
        )

    def cmd_FOCI_CURRENT_VECTOR_STEP_TEST(self, gcmd) -> None:
        """Run a bounded current-vector step diagnostic.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, and outside a homing move.
        """
        torque_target = gcmd.get_int("TORQUE_TARGET", 0, minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        duration_ms = gcmd.get_int("DURATION_MS", 80, minval=20, maxval=200)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )

        self.current_vector_step_test_cmd.send(
            [self.oid, torque_target, flux_target, duration_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s current-vector-step requested:"
            " torque_target=%d flux_target=%d duration_ms=%d voltage_limit=%d"
            % (self.name, torque_target, flux_target, duration_ms, voltage_limit)
        )

    def cmd_FOCI_CURRENT_TORQUE_SAMPLE_TEST(self, gcmd) -> None:
        """Run a bounded torque pulse and sample it before the 20 ms dwell floor.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, and outside a homing move.
        """
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        flux_target = gcmd.get_int("FLUX_TARGET", 0, minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 5, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        self._current_torque_sample_details.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )
        self._current_torque_sample_labels.pop(
            (target, flux_target, sample_delay_ms, voltage_limit),
            None,
        )

        self.current_torque_sample_test_cmd.send(
            [self.oid, target, flux_target, sample_delay_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s current-torque-sample requested:"
            " target=%d flux_target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.name, target, flux_target, sample_delay_ms, voltage_limit)
        )

    def cmd_FOCI_POSITION_TORQUE_OFFSET_TEST(self, gcmd) -> None:
        """Run a bounded torque-offset sample while staying in position mode.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, outside a homing move, and in production position mode.
        """
        target = gcmd.get_int("TARGET", minval=-1000, maxval=1000)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)
        voltage_limit = gcmd.get_int(
            "VOLTAGE_LIMIT",
            12000,
            minval=MIN_OPERATIONAL_VOLTAGE_LIMIT,
            maxval=29000,
        )
        detail_key = (target, 0, sample_delay_ms, voltage_limit)
        self._current_torque_sample_details.pop(detail_key, None)
        self._current_torque_sample_labels[detail_key] = "position torque offset sample"

        self.position_torque_offset_sample_test_cmd.send(
            [self.oid, target, sample_delay_ms, voltage_limit]
        )

        gcmd.respond_info(
            "FOCI %s position-torque-offset requested:"
            " target=%d sample_delay_ms=%d voltage_limit=%d"
            % (self.name, target, sample_delay_ms, voltage_limit)
        )

    def cmd_FOCI_VOLTAGE_STEP_TEST(self, gcmd) -> None:
        """Run a bounded open-loop voltage-vector pulse and sample it.

        The firmware rejects this command unless the motor is already enabled,
        calibrated, idle, outside a homing move, and in production position mode.
        """
        uq_ext = gcmd.get_int("UQ", minval=-1024, maxval=1024)
        ud_ext = gcmd.get_int("UD", 0, minval=-1024, maxval=1024)
        sample_delay_ms = gcmd.get_int("SAMPLE_DELAY_MS", 2, minval=1, maxval=20)

        self.voltage_step_test_cmd.send([self.oid, uq_ext, ud_ext, sample_delay_ms])

        gcmd.respond_info(
            "FOCI %s voltage-step requested:"
            " uq_ext=%d ud_ext=%d sample_delay_ms=%d"
            % (self.name, uq_ext, ud_ext, sample_delay_ms)
        )

    def _persist_tune_results(self, result: dict, mode_name: str, status: str) -> None:
        """Persist Stage 2 results to printer.cfg (pending SAVE_CONFIG)."""
        configfile = self.printer.lookup_object("configfile")
        configfile.set(self.name, "pid_velocity_p", "%d" % result["velocity_p"])
        configfile.set(self.name, "pid_velocity_i", "%d" % result["velocity_i"])
        configfile.set(self.name, "pid_velocity_limit", "%d" % result["velocity_limit"])
        configfile.set(self.name, "pid_position_p", "%d" % result["position_p"])
        configfile.set(self.name, "pid_position_i", "%d" % result["position_i"])
        configfile.set(
            self.name,
            "velocity_filter_hz",
            "%d" % result["velocity_filter_hz"],
        )
        configfile.set(
            self.name,
            "position_filter_hz",
            "%d" % result["position_filter_hz"],
        )
        configfile.set(self.name, "flux_filter_hz", "%d" % result["flux_filter_hz"])
        configfile.set(self.name, "torque_filter_hz", "%d" % result["torque_filter_hz"])
        configfile.set(self.name, "identified_j_eff", "%d" % result["j_eff"])
        configfile.set(self.name, "identified_b_eff", "%d" % result["b_eff"])
        configfile.set(self.name, "autotune_mode", mode_name)
        configfile.set(self.name, "autotune_status", status)

    def _handle_trace_info_result(self, params: dict) -> None:
        """Handle foci_trace_info_result response from firmware."""
        self._trace_info = params
        self._trace_info_received = True

    def cmd_FOCI_TRACE_START(self, gcmd) -> None:
        """Start per-tick trace capture for the selected stepper."""
        preset_name = gcmd.get("PRESET", "full").lower()
        presets = {"fast": 0, "full": 1, "velocity": 2, "hold": 3}
        if preset_name not in presets:
            raise gcmd.error(
                "FOCI %s: unknown trace preset '%s' "
                "(expected fast, full, velocity, or hold)" % (self.name, preset_name)
            )
        self.trace_start_cmd.send([self.oid, presets[preset_name]])
        gcmd.respond_info(
            "FOCI %s trace capture started (%s preset)" % (self.name, preset_name)
        )

    def cmd_FOCI_TRACE_STOP(self, gcmd) -> None:
        """Stop per-tick trace capture for the selected stepper."""
        self.trace_stop_cmd.send([self.oid])
        gcmd.respond_info("FOCI %s trace capture stopped" % self.name)

    def cmd_FOCI_TRACE(self, gcmd) -> None:
        """Fetch and display the trace capture buffer."""
        import struct

        format_name = gcmd.get("FORMAT", "table").lower()
        phase_filter = gcmd.get_int("PHASE", None)

        # Query trace buffer metadata
        self._trace_info = None
        self._trace_info_received = False
        self.trace_info_cmd.send([self.oid])

        reactor = self.printer.get_reactor()
        deadline = reactor.monotonic() + 5.0
        while not self._trace_info_received:
            if reactor.monotonic() > deadline:
                raise gcmd.error("FOCI %s: trace info timed out" % self.name)
            reactor.pause(reactor.monotonic() + 0.05)

        info = self._trace_info
        state = info.get("state", 0)
        count = info.get("count", 0)
        generation = info.get("generation", 0)

        if state != 2 or count == 0:
            gcmd.respond_info("FOCI %s: no trace data available" % self.name)
            return

        preset = info.get("preset", 0)
        dropped = info.get("dropped", 0)
        sample_period = info.get("sample_period_us", 1000)

        if preset == 1:  # Full
            sample_size = 48
            fmt = "<HBBiiIiIiIiiii"
            headers = TRACE_FULL_HEADERS
        elif preset == 2:  # Velocity
            sample_size = 52
            fmt = "<HBBiiIiIiiiiiii"
            headers = TRACE_VELOCITY_HEADERS
        elif preset == 3:  # Hold
            sample_size = 52
            fmt = "<HBBiiIiIiiiIIii"
            headers = TRACE_HOLD_HEADERS
        else:  # Fast
            sample_size = 28
            fmt = "<HBBiiIiIi"
            headers = TRACE_FAST_HEADERS

        def _i16(val: int) -> int:
            """Convert unsigned 16-bit half to signed i16."""
            return val - 0x10000 if val >= 0x8000 else val

        # Fetch samples
        samples = []
        for i in range(count):
            params = self.trace_fetch_cmd.send([self.oid, i, generation])
            status = params.get("status", 2)
            if status != 0:
                status_names = {1: "capture still active", 2: "invalid"}
                gcmd.respond_info(
                    "FOCI %s: trace fetch aborted at offset %d: %s"
                    % (self.name, i, status_names.get(status, "unknown"))
                )
                return
            data = params.get("data", b"")
            if len(data) != sample_size:
                gcmd.respond_info(
                    "FOCI %s: unexpected sample size %d (expected %d)"
                    % (self.name, len(data), sample_size)
                )
                return
            fields = struct.unpack(fmt, data)

            # Split torque/flux packed fields (halves are signed i16)
            if preset == 1:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:9]))  # pidout_vel, status, abn
                tf_tgt = fields[9]
                row.append(_i16((tf_tgt >> 16) & 0xFFFF))  # torque_target
                row.append(_i16(tf_tgt & 0xFFFF))  # flux_target
                row.extend(list(fields[10:]))  # vel_ofs, esum_pos/vel/trq
            elif preset == 2:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:9]))  # pidout_vel, status, abn
                row.extend(
                    list(fields[9:])
                )  # pos_err, pidout_trq/flx, pidin_vel, vel_actual, vel_ofs
            elif preset == 3:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:9]))  # pidout_vel, status, abn
                row.extend(list(fields[9:11]))  # pidout_trq, pidout_flx
                foc_uq_ud = fields[11]
                row.append(_i16((foc_uq_ud >> 16) & 0xFFFF))  # foc_uq
                row.append(_i16(foc_uq_ud & 0xFFFF))  # foc_ud
                foc_uq_ud_limited = fields[12]
                row.append(_i16((foc_uq_ud_limited >> 16) & 0xFFFF))  # foc_uq_lim
                row.append(_i16(foc_uq_ud_limited & 0xFFFF))  # foc_ud_lim
                row.extend(list(fields[13:]))  # esum_trq, esum_flx
            else:
                row = list(fields[:3])  # tick, phase, flags
                row.extend(list(fields[3:5]))  # pos_tgt, pos_act
                tf_act = fields[5]
                row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
                row.append(_i16(tf_act & 0xFFFF))  # flux_actual
                row.extend(list(fields[6:]))  # pidout_vel, status, abn
            samples.append(row)

        # Apply phase filter
        if phase_filter is not None:
            phase_col = 1  # phase is second column
            samples = [s for s in samples if s[phase_col] == phase_filter]

        if not samples:
            gcmd.respond_info("FOCI %s: no samples match filter" % self.name)
            return

        # Format output
        preset_names = {1: "full", 2: "velocity", 3: "hold"}
        preset_name = preset_names.get(preset, "fast")
        expected_tick_step = {1: 2, 2: 2, 3: 10}.get(preset, 1)
        header = "FOCI %s trace: %d samples" % (self.name, len(samples))
        if dropped > 0:
            header += " (%d dropped)" % dropped
        header += ", %s preset, %dus period" % (preset_name, sample_period)

        if format_name == "summary":
            lines = _format_trace_summary(
                self.name,
                samples,
                headers,
                preset_name,
                sample_period,
                dropped,
                expected_tick_step,
            )
        elif format_name == "csv":
            lines = [header, ",".join(headers)]
            for row in samples:
                lines.append(",".join(str(v) for v in row))
        else:
            lines = [header]
            col_widths = [max(len(h), 8) for h in headers]
            lines.append("  ".join(h.rjust(w) for h, w in zip(headers, col_widths)))
            for row in samples:
                lines.append(
                    "  ".join(str(v).rjust(w) for v, w in zip(row, col_widths))
                )

        gcmd.respond_info("\n".join(lines))
