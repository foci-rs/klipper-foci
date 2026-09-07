"""Tests for FOCI homing and calibration workflow behavior."""

import contextlib
import unittest

from klipper_foci.registers import REGISTERS

from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    SAMPLE_COMMISSION_RESULT,
    CommandError,
    MockCartesianKinematics,
    MockCoreXYKinematics,
    MockGCmd,
    MockNoneKinematics,
    make_driver,
)


class TestEnsureCalibratedGates(unittest.TestCase):
    def test_returns_immediately_if_already_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        # Should return without error or side effects
        d.homing.ensure_calibrated()

    def test_inhibited_raises_even_if_already_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_inhibited(self):
        d = make_driver()
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_raises_if_no_active_gains(self):
        d = make_driver()
        d.state.active_gains = None
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("no commissioned gains", str(ctx.exception))

    def test_raises_if_lock_held(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS
        d.state.operation_lock = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("another FOCI operation", str(ctx.exception))

    def test_does_not_recalibrate_if_already_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.ensure_calibrated()
        # Calibration should not have been requested.
        self.assertIsNone(d.protocol.commands.calibrate.last_args)

    def test_calibration_failure_reports_encoder_check_diagnostics(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        reactor = d.printer.get_reactor()
        reactor.completion_result = {
            "oid": d.oid,
            "status": 8,
            "adc_i0": 0,
            "adc_i1": 0,
            "encoder_count": 0,
        }

        def send_calibrate(_args):
            d.commissioning.handle_commission_detail(
                {
                    "phase": 4,
                    "code": 2,
                    "status": 1,
                    "value0": 123,
                    "value1": 123,
                    "value2": 0,
                }
            )

        d.protocol.commands.calibrate.send = send_calibrate

        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()

        self.assertIn("ENCODER_FAULT", str(ctx.exception))
        gcode = d.printer.lookup_object("gcode")
        self.assertEqual(len(gcode._responses), 1)
        self.assertIn("calibration diagnostics", gcode._responses[0])
        self.assertIn("Encoder check: direction sweep FAIL", gcode._responses[0])
        self.assertIn("start=123", gcode._responses[0])
        self.assertIn("delta=0", gcode._responses[0])

    def test_calibration_failure_reports_closed_loop_activation_diagnostics(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        reactor = d.printer.get_reactor()
        reactor.completion_result = {
            "oid": d.oid,
            "status": 9,
            "adc_i0": 0,
            "adc_i1": 0,
            "encoder_count": 0,
        }

        def send_calibrate(_args):
            d.commissioning.handle_commission_detail(
                {
                    "phase": 17,
                    "code": 1,
                    "status": 3,
                    "value0": 0,
                    "value1": 65,
                    "value2": 65,
                }
            )

        d.protocol.commands.calibrate.send = send_calibrate

        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()

        self.assertIn("CLOSED_LOOP_ACTIVATION_UNSTABLE", str(ctx.exception))
        gcode = d.printer.lookup_object("gcode")
        self.assertEqual(len(gcode._responses), 1)
        self.assertIn("calibration diagnostics", gcode._responses[0])
        self.assertIn("Closed-loop entry: drift FAIL", gcode._responses[0])
        self.assertIn("position_1=0", gcode._responses[0])
        self.assertIn("position_2=65", gcode._responses[0])
        self.assertIn("drift=65", gcode._responses[0])

    def test_calibration_success_reports_retained_diagnostics(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        reactor = d.printer.get_reactor()
        reactor.completion_result = {
            "oid": d.oid,
            "status": 0,
            "adc_i0": 0,
            "adc_i1": 0,
            "encoder_count": 123,
        }

        def send_calibrate(_args):
            # Simulates a bounded direction-sweep retry: the first attempt
            # found no movement but a later attempt recovered, so the
            # calibrate call still succeeds overall.
            d.commissioning.handle_commission_detail(
                {
                    "phase": 4,
                    "code": 2,
                    "status": 1,
                    "value0": 123,
                    "value1": 123,
                    "value2": 0,
                }
            )

        d.protocol.commands.calibrate.send = send_calibrate

        d.homing.ensure_calibrated()

        self.assertTrue(d.state.is_calibrated)
        gcode = d.printer.lookup_object("gcode")
        self.assertEqual(len(gcode._responses), 1)
        self.assertIn("calibration diagnostics", gcode._responses[0])
        self.assertIn("Encoder check: direction sweep FAIL", gcode._responses[0])
        self.assertIn("start=123", gcode._responses[0])
        self.assertIn("delta=0", gcode._responses[0])

    def test_calibration_success_reports_nothing_when_no_diagnostics(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        reactor = d.printer.get_reactor()
        reactor.completion_result = {
            "oid": d.oid,
            "status": 0,
            "adc_i0": 0,
            "adc_i1": 0,
            "encoder_count": 123,
        }

        d.homing.ensure_calibrated()

        self.assertTrue(d.state.is_calibrated)
        gcode = d.printer.lookup_object("gcode")
        self.assertEqual(gcode._responses, [])


class TestHomingStateTransitions(unittest.TestCase):
    def test_connect_delegates_initial_homing_state(self):
        d = make_driver()
        calls = []

        class FakeHoming:
            def apply_initial_state(self):
                calls.append("apply_initial_state")

            def __getattr__(self, name):
                raise AssertionError(f"unexpected homing method {name}")

        d.homing = FakeHoming()
        d._handle_connect()

        self.assertEqual(calls, ["apply_initial_state"])

    def test_initial_homing_state_applies_active_gains_when_enabled(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        calls = []

        d.homing.apply_active_gains_to_firmware = lambda: calls.append("apply")
        d.homing.set_auto_calibrate_on_enable_allowed = lambda allowed: calls.append(
            ("auto", allowed)
        )
        d.homing.install_enable_hooks = lambda: calls.append("hooks")

        d.homing.apply_initial_state()

        self.assertEqual(calls, ["apply", ("auto", True), "hooks"])

    def test_initial_homing_state_keeps_auto_calibrate_closed_when_inhibited(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.state.inhibited = True
        calls = []

        d.homing.apply_active_gains_to_firmware = lambda: calls.append("apply")
        d.homing.set_auto_calibrate_on_enable_allowed = lambda allowed: calls.append(
            ("auto", allowed)
        )
        d.homing.install_enable_hooks = lambda: calls.append("hooks")

        d.homing.apply_initial_state()

        self.assertEqual(calls, [("auto", False), "hooks"])

    def test_connect_allows_auto_calibrate_only_with_valid_config(self):
        d = make_driver()
        d._handle_connect()
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0])

        d = make_driver()
        d.config.autotune_status = "commissioned"
        d.config.pid_flux_p = 100
        d.config.pid_flux_i = 200
        d.config.pid_torque_p = 300
        d.config.pid_torque_i = 400
        d.config.identified_lambda_us = 1200
        d.config.identified_theta_e_us = 100
        d.config.identified_ringing_count = 0
        d.config.identified_bandwidth_hz = 500
        d.config.commissioned_velocity_p = 1100
        d.config.commissioned_velocity_i = 0
        d.config.commissioned_position_p = 700
        d.config.commissioned_position_i = 0
        d.config.commissioned_velocity_limit = 50_000
        d._handle_connect()
        self.assertEqual(d.protocol.commands.set_pid_gains.last_args, [d.oid, 100, 200, 300, 400])
        self.assertEqual(
            d.protocol.commands.set_position_gains.last_args,
            [d.oid, 700, 0, 1100, 0],
        )
        self.assertEqual(d.protocol.commands.set_velocity_limit.last_args, [d.oid, 50_000])
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 1])

    def test_connect_keeps_auto_calibrate_closed_while_inhibited(self):
        d = make_driver()
        d.state.inhibited = True
        d.config.autotune_status = "commissioned"
        d.config.pid_flux_p = 100
        d.config.pid_flux_i = 200
        d.config.pid_torque_p = 300
        d.config.pid_torque_i = 400
        d.config.identified_lambda_us = 1200
        d.config.identified_theta_e_us = 100
        d.config.identified_ringing_count = 0
        d.config.identified_bandwidth_hz = 500
        d.config.commissioned_velocity_p = 1100
        d.config.commissioned_velocity_i = 0
        d.config.commissioned_position_p = 700
        d.config.commissioned_position_i = 0
        d.config.commissioned_velocity_limit = 50_000
        d._handle_connect()
        self.assertEqual(d.protocol.commands.set_auto_calibrate_on_enable.last_args, [d.oid, 0])

    def test_inhibited_blocks_ensure_calibrated(self):
        d = make_driver()
        d.state.inhibited = True
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("inhibited", str(ctx.exception))

    def test_inhibited_reports_last_commission_failure(self):
        d = make_driver()
        d.state.inhibited = True
        d.state.last_commission_failure = (
            "current validation failed: flux validation, cross-axis coupling"
        )
        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()
        self.assertIn("last failure", str(ctx.exception))
        self.assertIn("cross-axis coupling", str(ctx.exception))

    def test_active_gain_apply_resends_configured_voltage_limit(self):
        d = make_driver()
        d.settings.voltage_limit = 29000
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

        d.homing.apply_active_gains_to_firmware()

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 29000])

    def test_disable_callback_clears_calibrated(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.handle_stepper_enable(0.0, False)
        self.assertFalse(d.state.is_calibrated)

    def test_enable_callback_calibrates_before_marking_enabled(self):
        d = make_driver()
        d.state.is_calibrated = False
        d.state.active_gains = {
            "flux_p": 711,
            "flux_i": 2544,
            "torque_p": 711,
            "torque_i": 2544,
            "velocity_p": 1434,
            "velocity_i": 32,
            "position_p": 627,
            "position_i": 16,
            "velocity_limit": 500000,
        }
        d.printer.get_reactor().completion_result = {
            "status": 0,
            "adc_i0": 33152,
            "adc_i1": 33256,
            "encoder_count": 0,
        }
        d.homing.handle_stepper_enable(0.0, True)
        self.assertEqual(d.protocol.commands.calibrate.last_args, [0])
        self.assertTrue(d.state.is_calibrated)

    def test_calibration_failure_labels_legacy_commission_error_code(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()
        d.printer.get_reactor().completion_result = {"status": 3}

        with self.assertRaises(CommandError) as ctx:
            d.homing.ensure_calibrated()

        msg = str(ctx.exception)
        self.assertIn("commissioning status 3", msg)
        self.assertIn("SPI communication error", msg)
        self.assertNotIn("UNKNOWN(3)", msg)

    def test_ensure_calibrated_skips_if_already_true(self):
        d = make_driver()
        d.state.is_calibrated = True
        d.homing.ensure_calibrated()
        self.assertIsNone(d.protocol.commands.calibrate.last_args)


class TestHomingInvalidation(unittest.TestCase):
    def test_noop_without_toolhead(self):
        d = make_driver()
        d.printer._objects.pop("toolhead", None)
        # Should not raise
        d.homing.invalidate_homing()

    def test_noop_for_none_kinematics(self):
        d = make_driver(kinematics=MockNoneKinematics())
        # NoneKinematics has no rails or clear_homing_state — should be a no-op
        d.homing.invalidate_homing()

    def test_noop_when_no_rails_attribute(self):
        """Kinematics with clear_homing_state but no rails attribute."""

        class MinimalKin:
            def clear_homing_state(self, axes):
                raise AssertionError("should not be called")

        d = make_driver(kinematics=MinimalKin())
        d.homing.invalidate_homing()

    def test_noop_when_stepper_not_on_any_rail(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_a", kinematics=kin)
        d.homing.invalidate_homing()
        self.assertIsNone(kin._cleared_axes)

    def test_cartesian_clears_matched_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kin,
        )
        d.homing.invalidate_homing()
        # Cartesian: stepper_x is rail 0 → axis 0 (x)
        self.assertIn(0, kin._cleared_axes)
        self.assertIn("x", kin._cleared_axes)
        self.assertNotIn(1, kin._cleared_axes)

    def test_cartesian_clears_y_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        d.homing.invalidate_homing()
        self.assertIn(1, kin._cleared_axes)
        self.assertIn("y", kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_cartesian_clears_z_axis(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_z", kinematics=kin)
        d.homing.invalidate_homing()
        self.assertIn(2, kin._cleared_axes)
        self.assertIn("z", kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)

    def test_corexy_clears_both_axes_for_either_motor(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(
            stepper_name="stepper_x",
            kinematics=kin,
        )
        d.homing.invalidate_homing()
        # CoreXY: rail 0 maps to axes (0, 1) → x and y
        self.assertIn(0, kin._cleared_axes)
        self.assertIn(1, kin._cleared_axes)
        self.assertIn("x", kin._cleared_axes)
        self.assertIn("y", kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_corexy_clears_both_axes_for_y_motor(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        d.homing.invalidate_homing()
        # CoreXY: rail 1 maps to axes (0, 1) → x and y
        self.assertIn(0, kin._cleared_axes)
        self.assertIn(1, kin._cleared_axes)
        self.assertNotIn(2, kin._cleared_axes)

    def test_corexy_z_only_clears_z(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_z", kinematics=kin)
        d.homing.invalidate_homing()
        # CoreXY: rail 2 maps to axis (2,) → z only
        self.assertIn(2, kin._cleared_axes)
        self.assertNotIn(0, kin._cleared_axes)
        self.assertNotIn(1, kin._cleared_axes)


class TestHomingCalibrationCoupling(unittest.TestCase):
    def test_corexy_homing_x_calibrates_y_motor_too(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d.homing.ensure_calibrated = ensure_calibrated

        d.homing.handle_home_rails_begin(None, [kin.rails[0]])

        self.assertEqual(calls, ["stepper_y"])

    def test_corexy_homing_y_calibrates_x_motor_too(self):
        kin = MockCoreXYKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_x", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d.homing.ensure_calibrated = ensure_calibrated

        d.homing.handle_home_rails_begin(None, [kin.rails[1]])

        self.assertEqual(calls, ["stepper_x"])

    def test_cartesian_homing_x_does_not_calibrate_y_motor(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_y", kinematics=kin)
        calls = []

        def ensure_calibrated():
            calls.append(d.stepper_name)

        d.homing.ensure_calibrated = ensure_calibrated

        d.homing.handle_home_rails_begin(None, [kin.rails[0]])

        self.assertEqual(calls, [])


class TestCommandHomingInvalidation(unittest.TestCase):
    """Verify that commands invalidate homing before starting firmware ops."""

    def _install_live_dump(self, driver):
        def dump_registers():
            driver.dump.handle_dump_value(
                {
                    "addr": REGISTERS["PID_FLUX_P_FLUX_I"],
                    "value": (256 << 16) | 416,
                }
            )
            driver.dump.handle_dump_value(
                {
                    "addr": REGISTERS["PID_TORQUE_P_TORQUE_I"],
                    "value": (256 << 16) | 416,
                }
            )
            driver.dump.handle_dump_done({})

        driver.protocol.dump_registers = dump_registers

    def _driver_with_cartesian(self):
        kin = MockCartesianKinematics([["stepper_x"], ["stepper_y"], ["stepper_z"]])
        d = make_driver(stepper_name="stepper_x", kinematics=kin, homed_axes="xyz")
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
        self._install_live_dump(d)
        return d, kin

    def test_commission_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        gcmd = MockGCmd({"PROFILE": "balanced"})
        d.commissioning.done = True
        d.commissioning.result = SAMPLE_COMMISSION_RESULT
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.commissioning.commission(gcmd)
        # Homing should have been invalidated
        self.assertIsNotNone(kin._cleared_axes)

    def test_autotune_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        gcmd = MockGCmd({"PROFILE": "balanced", "MODE": "nominal"})
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.autotune.autotune(gcmd)
        self.assertIsNotNone(kin._cleared_axes)

    def test_selftest_invalidates_homing(self):
        d, kin = self._driver_with_cartesian()
        with contextlib.suppress(CommandError, AttributeError, TypeError):
            d.selftest.selftest(MockGCmd())
        self.assertIsNotNone(kin._cleared_axes)
