"""Tests for FOCI autotune workflow behavior."""

import unittest

from klipper_foci.commissioning import format_inner_warning_flags
from klipper_foci.registers import REGISTERS

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockGCmd,
    MockNoneKinematics,
    MockPrintStats,
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    make_driver,
)


class MockConfigFile:
    def __init__(self):
        self.values = {}

    def set(self, section, key, value):
        self.values[(section, key)] = value


def install_live_dump(driver, dump_values=None):
    values = {
        REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 26,
        REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 26,
    }
    if dump_values is not None:
        values.update(dump_values)

    def dump_registers():
        for addr, value in values.items():
            driver.dump.handle_dump_value({"addr": addr, "value": value})
        driver.dump.handle_dump_done({})

    driver.protocol.dump_registers = dump_registers


class TestAutotuneGates(unittest.TestCase):
    def _commissioned_driver(self, kinematics=None, homed_axes="xyz"):
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kinematics
            or MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
            homed_axes=homed_axes,
        )
        d.state.is_calibrated = True
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.runtime_status = "commissioned"
        d.state.commissioned_result = SAMPLE_COMMISSION_RESULT.copy()
        d.state.commissioned_result.update(
            {
                "tau_e_us": 730,
                "inner_warning_flags": 0,
                "bandwidth_hz": 1600,
                "current_gains_source": 1,
                "current_gains_tier": 1,
                "current_retry_budget_exhausted": 0,
                "current_failure_reason": 0,
                "inductance_source": 1,
                "inductance_reactance_count_ratio_milli": 8600,
                "inductance_saliency_status": 1,
                "resistance_selected_count_slope_milli": 1042,
            }
        )
        install_live_dump(d)
        return d

    def test_raises_if_lock_held(self):
        d = self._commissioned_driver()
        d.state.operation_lock = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = self._commissioned_driver()
        d.state.inhibited = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_not_commissioned(self):
        d = self._commissioned_driver()
        d.state.runtime_status = "uncommissioned"
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("not commissioned", str(ctx.exception))

    def test_raises_if_not_calibrated(self):
        d = self._commissioned_driver()
        d.state.is_calibrated = False
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("not calibrated", str(ctx.exception))

    def test_raises_if_not_homed_with_kinematics(self):
        kin = MockCartesianKinematics()
        d = self._commissioned_driver(kinematics=kin, homed_axes="x")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("not homed for X/Y", str(ctx.exception))

    def test_refuses_none_kinematics_for_production_autotune(self):
        d = self._commissioned_driver(kinematics=MockNoneKinematics(), homed_axes="")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("unsupported kinematics", str(ctx.exception))

    def test_refuses_autotune_when_printer_is_not_idle(self):
        d = self._commissioned_driver()
        d.printer._objects["print_stats"] = MockPrintStats("printing")
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("printer is not idle", str(ctx.exception))
        self.assertEqual(d.printer.lookup_object("gcode")._scripts, [])
        self.assertIsNone(d.protocol.commands.tune.last_args)

    def test_rejects_invalid_profile(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "turbo", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("unknown profile", str(ctx.exception).lower())

    def test_rejects_invalid_mode(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "extreme"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("unknown mode", str(ctx.exception))

    def test_accepts_tuned_conservative_as_commissioned(self):
        """A motor with tuned_conservative status can be re-tuned."""
        d = self._commissioned_driver()
        d.state.runtime_status = "tuned_conservative"
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        # Should get past the "not commissioned" gate
        try:
            d.autotune.autotune(gcmd)
        except (CommandError, AttributeError, TypeError) as e:
            self.assertNotIn("not commissioned", str(e))

    def test_admission_failure_reports_error_instead_of_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_admission_failure(deadline):
            reactor._time = deadline
            d.commissioning.handle_commission_phase({"phase": 0, "status": 15})
            return reactor._time

        reactor.pause = pause_and_report_admission_failure

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("commissioning already running", str(ctx.exception))
        self.assertNotIn("timed out", str(ctx.exception))

    def test_missing_velocity_sweep_plan_uses_short_setup_timeout(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("timed out waiting for plan", str(ctx.exception))

    def test_firmware_plan_replaces_short_timeout_with_reported_maximum(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_with_plan(deadline):
            reactor._time = deadline
            if d.autotune.velocity_sweep.plan is None:
                d.autotune.velocity_sweep.plan = {"maximum_workflow_ms": 10_000}
            if reactor._time >= 6.0:
                d.autotune.handle_tune_result({"status": 2})
            return reactor._time

        reactor.pause = pause_with_plan

        d.autotune.autotune(gcmd)

        self.assertGreaterEqual(reactor._time, 6.0)

    def test_hard_fault_inhibits_future_raw_enable(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(
            d.stepper_name
        )
        enable_line.motor_enable(0.0)

        def pause_and_report_hard_fault(deadline):
            reactor._time = deadline
            d.autotune.handle_tune_result({"status": 17})
            return reactor._time

        reactor.pause = pause_and_report_hard_fault

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("safety fault", str(ctx.exception))
        self.assertFalse(enable_line.is_motor_enabled())
        self.assertFalse(d.state.is_calibrated)
        self.assertTrue(d.state.inhibited)
        self.assertEqual(
            d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0]
        )

    def test_safety_fault_reports_outer_envelope_detail(self):
        d = self._commissioned_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()

        def pause_and_report_safety_fault(deadline):
            reactor._time = deadline
            d.autotune.handle_outer_safety_fault(
                {
                    "reason": 4,
                    "max_travel_mrev": 750,
                    "max_velocity_mrev_s": 6000,
                    "max_duration_ms": 3000,
                    "direction_mask": 3,
                    "delta_counts": -125,
                    "dt_us": 4000,
                    "velocity_counts_per_ms": -31,
                    "velocity_cap_counts_per_ms": 24,
                    "position_counts": -373,
                    "position_window_counts": 3000,
                    "elapsed_us": 120000,
                    "duration_cap_us": 3000000,
                }
            )
            d.autotune.handle_tune_result({"status": 17})
            return reactor._time

        reactor.pause = pause_and_report_safety_fault

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        message = str(ctx.exception)
        self.assertIn("safety fault: safety envelope violation", message)
        self.assertIn("outer safety velocity", message)
        self.assertIn("delta_counts=-125", message)
        self.assertIn("dt_us=4000", message)
        self.assertIn("velocity_counts_per_ms=-31", message)
        self.assertIn("cap_counts_per_ms=24", message)
        self.assertIn("position_counts=-373/3000", message)
        self.assertIn("elapsed_us=120000/3000000", message)
        self.assertIn("budget=750mrev/6000mrev_s/3000ms dir=0x03", message)


class TestAutotuneStateTransitions(unittest.TestCase):
    def test_inhibited_blocks_autotune(self):
        d = make_driver()
        d.state.inhibited = True
        d.state.runtime_status = "commissioned"
        d.state.is_calibrated = True
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)
        self.assertIn("inhibited", str(ctx.exception))


class InnerWarningFlagFormattingTests(unittest.TestCase):
    """Phase 1 inner-warning flag formatting."""

    def test_format_inner_warning_flags_lists_active_bits(self):
        text = format_inner_warning_flags((1 << 0) | (1 << 5))
        self.assertIn("coil R mismatch", text)
        self.assertIn("current gains fell back to defaults", text)

    def test_format_inner_warning_flags_empty_when_clean(self):
        self.assertEqual(format_inner_warning_flags(0), "none")

    def test_format_inner_warning_flags_ignores_tau_residual_telemetry(self):
        self.assertEqual(format_inner_warning_flags(1 << 2), "none")

    def test_format_inner_warning_flags_ignores_deprecated_bit4(self):
        self.assertEqual(format_inner_warning_flags(1 << 4), "none")


class TestAutotuneReadinessAdmission(unittest.TestCase):
    def _ready_driver(self):
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=MockCartesianKinematics([["stepper_x"], ["stepper_y"]]),
            homed_axes="xyz",
        )
        d.state.is_calibrated = True
        d.state.runtime_status = "commissioned"
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.config.identified_lambda_us = 700
        d.config.identified_tau_e_us = 730
        d.config.identified_theta_e_us = 160
        d.config.identified_ringing_count = 7
        d.config.identified_bandwidth_hz = 1600
        d.config.identified_inner_warning_flags = 0
        d.config.identified_current_gains_source = 1
        d.config.identified_current_gains_tier = 1
        d.config.identified_current_retry_budget_exhausted = 0
        d.config.identified_current_failure_reason = 0
        d.config.identified_l_source = 1
        d.config.identified_l_reactance_count_ratio_milli = 8600
        d.config.identified_l_saliency_status = 1
        d.config.identified_r_count_slope_milli = 1042
        install_live_dump(d)
        return d

    def _finish_tune_on_next_pause(self, driver, result_fields=None):
        reactor = driver.printer.get_reactor()
        result = {
            "status": 0,
            "warning_code": 0,
            "velocity_p": 1152,
            "velocity_i": 0,
            "position_p": 640,
            "position_i": 0,
            "velocity_limit": 500000,
            "velocity_filter_hz": 0,
            "torque_filter_hz": 0,
            "position_filter_hz": 0,
            "flux_filter_hz": 0,
            "j_eff": 42,
            "b_eff": 11,
        }
        result.update(result_fields or {})

        def finish_tune(deadline):
            reactor._time = deadline
            driver.autotune.handle_tune_result(result)
            return reactor._time

        reactor.pause = finish_tune

    def _install_live_dump(self, driver, dump_values):
        calls = []

        def dump_registers():
            calls.append("dump_registers")
            for addr, value in dump_values.items():
                driver.dump.handle_dump_value({"addr": addr, "value": value})
            driver.dump.handle_dump_done({})

        driver.protocol.dump_registers = dump_registers
        return calls

    def test_blocks_before_tune_when_current_loop_failed(self):
        d = self._ready_driver()
        d.config.identified_current_failure_reason = 6
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        calls = []
        d.homing.invalidate_homing = lambda: calls.append("invalidate_homing")

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("FOCI_AUTOTUNE blocked", str(ctx.exception))
        self.assertIn("current-loop failure reason=6", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(calls, [])

    def test_resolver_preserves_host_default_confidence_bit6(self):
        d = self._ready_driver()
        d.config.identified_inner_warning_flags = None
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        self._finish_tune_on_next_pause(d)

        d.autotune.autotune(gcmd)

        args = d.protocol.commands.tune.last_args
        self.assertIsNotNone(args)
        self.assertEqual(args[7], 0x40)
        self.assertIn("inner confidence", gcmd.last_info)

    def test_autotune_moves_to_safe_pose_and_sends_budget(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockCartesianKinematics([["stepper_x"], ["stepper_y"]])
        toolhead._kinematics.rails[0].get_steppers()[0]._step_dist = 0.01
        toolhead._homed_axes = "xy"
        toolhead.set_bounds(x_min=0.0, x_max=120.0, y_min=0.0, y_max=120.0)
        toolhead.set_position(x=10.0, y=20.0)
        d.printer._objects["configfile"] = MockConfigFile()
        self._finish_tune_on_next_pause(
            d,
            {
                "outer_evidence_flags": 0,
                "stiffness_timebase_ms": 50,
                "velocity_search_stop_reason": 1,
                "motion_budget_mrev": 750,
            },
        )

        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        d.autotune.autotune(gcmd)

        gcode = d.printer.lookup_object("gcode")
        self.assertEqual(gcode._scripts, ["G0 X60.000 Y60.000"])
        self.assertEqual(
            d.protocol.commands.tune.last_args[-8:],
            [5000, 7500, 1, 1000, 250, 1250, 1250, 3000],
        )
        self.assertIn(
            "FOCI foci stepper_x autotune evidence: budget=750mrev "
            "stiffness_timebase=50ms search_stop=1 flags=0x00",
            gcmd._responses,
        )

    def test_autotune_refuses_unsupported_kinematics_before_tune(self):
        d = self._ready_driver()
        toolhead = d.printer.lookup_object("toolhead")
        toolhead._kinematics = MockNoneKinematics()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("unsupported kinematics", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)

    def test_blocks_before_tune_when_live_current_gains_mismatch(self):
        d = self._ready_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        invalidate_calls = []
        d.homing.invalidate_homing = lambda: invalidate_calls.append(
            "invalidate_homing"
        )
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (257 << 16) | 26,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 26,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("live current-loop gain flux_p mismatch", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(invalidate_calls, [])

    def test_blocks_before_tune_when_live_current_gain_readback_is_missing(self):
        d = self._ready_driver()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        invalidate_calls = []
        d.homing.invalidate_homing = lambda: invalidate_calls.append(
            "invalidate_homing"
        )
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 26,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn("live current-loop gain torque_p unavailable", str(ctx.exception))
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(invalidate_calls, [])

    def test_unavailable_stage2_inputs_refuse_before_homing_invalidation_and_tune(self):
        d = self._ready_driver()
        d.config.identified_l_source = 0
        d.config.identified_l_reactance_count_ratio_milli = None
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        invalidate_calls = []
        d.homing.invalidate_homing = lambda: invalidate_calls.append(
            "invalidate_homing"
        )
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 26,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 26,
            },
        )

        with self.assertRaises(CommandError) as ctx:
            d.autotune.autotune(gcmd)

        self.assertIn(
            "stage 2 unavailable inputs: average_inductance", str(ctx.exception)
        )
        self.assertIsNone(d.protocol.commands.tune.last_args)
        self.assertEqual(invalidate_calls, [])

    def test_default_current_gain_evidence_sets_inner_warning_bit5_for_tune(self):
        d = self._ready_driver()
        d.config.identified_current_gains_source = 2
        d.config.identified_current_gains_tier = 3
        d.printer._objects["configfile"] = MockConfigFile()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        reactor = d.printer.get_reactor()
        self._install_live_dump(
            d,
            {
                REGISTERS["PID_FLUX_P_FLUX_I"]: (256 << 16) | 26,
                REGISTERS["PID_TORQUE_P_TORQUE_I"]: (256 << 16) | 26,
            },
        )

        def finish_tune(deadline):
            reactor._time = deadline
            d.autotune.handle_tune_result(
                {
                    "status": 0,
                    "warning_code": 0,
                    "velocity_p": 1152,
                    "velocity_i": 0,
                    "position_p": 640,
                    "position_i": 0,
                    "velocity_limit": 500000,
                    "velocity_filter_hz": 0,
                    "torque_filter_hz": 0,
                    "position_filter_hz": 0,
                    "flux_filter_hz": 0,
                    "j_eff": 42,
                    "b_eff": 11,
                }
            )
            return reactor._time

        reactor.pause = finish_tune

        d.autotune.autotune(gcmd)

        args = d.protocol.commands.tune.last_args
        self.assertIsNotNone(args)
        self.assertEqual(args[7], 1 << 5)
