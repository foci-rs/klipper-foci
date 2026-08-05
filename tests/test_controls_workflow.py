"""Tests for FOCI runtime controls workflow behavior."""

import unittest

from tests.mocks import (
    SAMPLE_ACTIVE_GAINS,
    CommandError,
    MockGCmd,
    make_driver,
)


class TestDebugGainsCommand(unittest.TestCase):
    def test_inner_gain_boundary_rejects_negative_register_encoding(self):
        d = make_driver()
        command = d.protocol.commands.set_pid_gains
        maximum = {
            "FLUX_P": 32767,
            "FLUX_I": 32767,
            "TORQUE_P": 32767,
            "TORQUE_I": 32767,
        }

        d.controls.set_inner_gains(MockGCmd(maximum))

        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.last_args, [d.oid, 32767, 32767, 32767, 32767])

        for key in maximum:
            with self.subTest(key=key):
                params = dict(maximum)
                params[key] = 32768
                previous_args = list(command.last_args)
                previous_count = command.call_count

                with self.assertRaises(CommandError):
                    d.controls.set_inner_gains(MockGCmd(params))

                self.assertEqual(command.call_count, previous_count)
                self.assertEqual(command.last_args, previous_args)

    def test_outer_gain_boundary_rejects_negative_register_encoding(self):
        d = make_driver()
        command = d.protocol.commands.set_position_gains
        maximum = {
            "VELOCITY_P": 32767.0 / 256.0,
            "VELOCITY_I": 32767.0 / 4096.0,
            "POSITION_P": 32767.0 / 256.0,
            "POSITION_I": 32767.0 / 4096.0,
        }

        d.controls.set_gains(MockGCmd(maximum))

        self.assertEqual(command.call_count, 1)
        self.assertEqual(command.last_args, [d.oid, 32767, 32767, 32767, 32767])

        for key in maximum:
            with self.subTest(key=key):
                params = dict(maximum)
                params[key] = 128.0 if key.endswith("_P") else 8.0
                previous_args = list(command.last_args)
                previous_count = command.call_count

                with self.assertRaises(CommandError):
                    d.controls.set_gains(MockGCmd(params))

                self.assertEqual(command.call_count, previous_count)
                self.assertEqual(command.last_args, previous_args)

    def test_sets_run_current_in_milliamps_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"RUN_CURRENT": 5.0})
        d.controls.set_current(gcmd)

        self.assertEqual(d.protocol.commands.set_current.last_args, [d.oid, 5000])
        self.assertEqual(d.settings.run_current, 5.0)
        self.assertEqual(d.config.run_current, 0.8)
        self.assertIn("run_current=5.000A", gcmd.last_info)

        previous_count = d.protocol.commands.set_current.call_count
        with self.assertRaises(CommandError):
            d.controls.set_current(MockGCmd({"RUN_CURRENT": 5.001}))
        self.assertEqual(d.protocol.commands.set_current.call_count, previous_count)

    def test_requests_position_and_velocity_gains_without_claiming_applied_state(self):
        d = make_driver()
        d.settings.pid_velocity_p = 101
        d.settings.pid_velocity_i = 102
        d.settings.pid_position_p = 103
        d.settings.pid_position_i = 104
        previous_active_gains = dict(SAMPLE_ACTIVE_GAINS)
        previous_active_gains.update(
            velocity_p=301,
            velocity_i=302,
            position_p=303,
            position_i=304,
        )
        d.state.active_gains = previous_active_gains.copy()

        gcmd = MockGCmd(
            {
                "VELOCITY_P": "2.0",
                "VELOCITY_I": "0.1015625",
                "POSITION_P": "1.0",
                "POSITION_I": "0.62109375",
            }
        )
        d.controls.set_gains(gcmd)

        self.assertEqual(
            d.protocol.commands.set_position_gains.last_args,
            [d.oid, 256, 2544, 512, 416],
        )
        self.assertEqual(d.settings.pid_velocity_p, 101)
        self.assertEqual(d.settings.pid_velocity_i, 102)
        self.assertEqual(d.settings.pid_position_p, 103)
        self.assertEqual(d.settings.pid_position_i, 104)
        self.assertEqual(d.state.active_gains, previous_active_gains)
        self.assertIn("requested", gcmd.last_info)

    def test_requests_inner_gains_without_claiming_applied_state(self):
        d = make_driver()
        d.settings.pid_flux_p = 201
        d.settings.pid_flux_i = 202
        d.settings.pid_torque_p = 203
        d.settings.pid_torque_i = 204
        previous_active_gains = dict(SAMPLE_ACTIVE_GAINS)
        previous_active_gains.update(
            flux_p=401,
            flux_i=402,
            torque_p=403,
            torque_i=404,
        )
        d.state.active_gains = previous_active_gains.copy()

        gcmd = MockGCmd(
            {
                "FLUX_P": 706,
                "FLUX_I": 2592,
                "TORQUE_P": 706,
                "TORQUE_I": 2592,
            }
        )
        d.controls.set_inner_gains(gcmd)

        self.assertEqual(
            d.protocol.commands.set_pid_gains.last_args,
            [d.oid, 706, 2592, 706, 2592],
        )
        self.assertEqual(d.settings.pid_flux_p, 201)
        self.assertEqual(d.settings.pid_flux_i, 202)
        self.assertEqual(d.settings.pid_torque_p, 203)
        self.assertEqual(d.settings.pid_torque_i, 204)
        self.assertEqual(d.state.active_gains, previous_active_gains)
        self.assertIn("requested", gcmd.last_info)


class TestRuntimeFiltersCommand(unittest.TestCase):
    def test_sets_current_filters_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"TORQUE_HZ": 3000, "FLUX_HZ": 1600})
        d.controls.set_filters(gcmd)

        self.assertEqual(d.protocol.commands.set_torque_filter.last_args, [d.oid, 3000])
        self.assertEqual(d.protocol.commands.set_flux_filter.last_args, [d.oid, 1600])
        self.assertEqual(d.settings.torque_filter_hz, 3000)
        self.assertEqual(d.settings.flux_filter_hz, 1600)
        self.assertIsNone(d.config.torque_filter_hz)
        self.assertIsNone(d.config.flux_filter_hz)
        self.assertIn("torque=3000Hz", gcmd.last_info)
        self.assertIn("flux=1600Hz", gcmd.last_info)

    def test_allows_disabling_current_filters(self):
        d = make_driver()
        d.settings.torque_filter_hz = 1200
        d.settings.flux_filter_hz = 800

        d.controls.set_filters(MockGCmd({"TORQUE_HZ": 0, "FLUX_HZ": 0}))

        self.assertEqual(d.protocol.commands.set_torque_filter.last_args, [d.oid, 0])
        self.assertEqual(d.protocol.commands.set_flux_filter.last_args, [d.oid, 0])
        self.assertEqual(d.settings.torque_filter_hz, 0)
        self.assertEqual(d.settings.flux_filter_hz, 0)

    def test_keeps_motion_filter_cap_at_one_khz(self):
        d = make_driver()

        with self.assertRaisesRegex(CommandError, "VELOCITY_HZ"):
            d.controls.set_filters(MockGCmd({"VELOCITY_HZ": 1001}))

        with self.assertRaisesRegex(CommandError, "POSITION_HZ"):
            d.controls.set_filters(MockGCmd({"POSITION_HZ": 1001}))

    def test_rejects_missing_filter_parameter(self):
        d = make_driver()

        with self.assertRaisesRegex(CommandError, "at least one"):
            d.controls.set_filters(MockGCmd({}))


class TestVelocityFeedforwardCommand(unittest.TestCase):
    def test_sets_feedforward_enable_and_multiplier(self):
        d = make_driver()

        d.controls.set_velocity_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "MULTIPLIER": 8,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_velocity_feedforward.last_args, [d.oid, 1, 8])
        self.assertTrue(d.settings.velocity_feedforward)
        self.assertEqual(d.settings.velocity_feedforward_multiplier, 8)

    def test_disable_preserves_configured_multiplier(self):
        d = make_driver()
        d.settings.velocity_feedforward_multiplier = 4

        d.controls.set_velocity_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_velocity_feedforward.last_args, [d.oid, 0, 4])
        self.assertFalse(d.settings.velocity_feedforward)
        self.assertEqual(d.settings.velocity_feedforward_multiplier, 4)


class TestVelocityTransientFeedforwardCommand(unittest.TestCase):
    def test_sets_transient_feedforward_parameters(self):
        d = make_driver()

        d.controls.set_velocity_transient_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "LEAD_TIME_US": 400,
                    "GAIN": 750,
                    "MAX_OFFSET": 1200,
                    "RATE_HZ": 10000,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_velocity_transient_feedforward.last_args,
            [d.oid, 1, 400, 750, 1200, 10000],
        )
        self.assertTrue(d.settings.velocity_transient_feedforward)
        self.assertEqual(d.settings.velocity_transient_lead_time_us, 400)
        self.assertEqual(d.settings.velocity_transient_gain, 750)
        self.assertEqual(d.settings.velocity_transient_max_offset, 1200)
        self.assertEqual(d.settings.velocity_transient_rate_hz, 10000)

    def test_disable_preserves_transient_parameters(self):
        d = make_driver()
        d.settings.velocity_transient_lead_time_us = 250
        d.settings.velocity_transient_gain = 500
        d.settings.velocity_transient_max_offset = 900
        d.settings.velocity_transient_rate_hz = 10000

        d.controls.set_velocity_transient_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_velocity_transient_feedforward.last_args,
            [d.oid, 0, 250, 500, 900, 10000],
        )
        self.assertFalse(d.settings.velocity_transient_feedforward)
        self.assertEqual(d.settings.velocity_transient_lead_time_us, 250)
        self.assertEqual(d.settings.velocity_transient_gain, 500)
        self.assertEqual(d.settings.velocity_transient_max_offset, 900)
        self.assertEqual(d.settings.velocity_transient_rate_hz, 10000)


class TestAccelFeedforwardCommand(unittest.TestCase):
    def test_sets_accel_feedforward_enable_and_split_gains(self):
        d = make_driver()

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "ACCEL_GAIN": 750,
                    "DECEL_GAIN": 250,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 1, 750, 250])
        self.assertTrue(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 250)

    def test_gain_alias_sets_both_split_gains(self):
        d = make_driver()

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN": 500,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 1, 500, 500])
        self.assertTrue(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 500)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 500)

    def test_disable_preserves_configured_gain(self):
        d = make_driver()
        d.settings.accel_feedforward_accel_gain = 750
        d.settings.accel_feedforward_decel_gain = 250

        d.controls.set_accel_feedforward(
            MockGCmd(
                {
                    "ENABLE": 0,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_accel_feedforward.last_args, [d.oid, 0, 750, 250])
        self.assertFalse(d.settings.accel_feedforward)
        self.assertEqual(d.settings.accel_feedforward_accel_gain, 750)
        self.assertEqual(d.settings.accel_feedforward_decel_gain, 250)


class TestDecouplingFeedforwardCommand(unittest.TestCase):
    def test_sets_decoupling_feedforward_enable_and_model(self):
        d = make_driver()

        d.controls.set_decoupling_feedforward(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "R_INT": 3000,
                    "L_INT": 4095,
                    "POLE_PAIRS": 50,
                    "POSITION_UNITS_PER_REV": 65536,
                    "F_PWM_HZ": 25000,
                    "MAX_OFFSET": 500,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_decoupling_feedforward.last_args,
            [d.oid, 1, 3000, 4095, 50, 65536, 25000, 500],
        )
        self.assertTrue(d.settings.decoupling_feedforward)
        self.assertEqual(d.settings.decoupling_r_int, 3000)
        self.assertEqual(d.settings.decoupling_l_int, 4095)
        self.assertEqual(d.settings.decoupling_pole_pairs, 50)
        self.assertEqual(d.settings.decoupling_position_units_per_rev, 65536)
        self.assertEqual(d.settings.decoupling_f_pwm_hz, 25000)
        self.assertEqual(d.settings.decoupling_max_offset, 500)


class TestPositionLeadCommand(unittest.TestCase):
    def test_sets_position_lead_enable_gain_and_cap(self):
        d = make_driver()

        d.controls.set_position_lead(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN": 10,
                    "MAX_COUNTS": 20,
                }
            )
        )

        self.assertEqual(d.protocol.commands.set_position_lead.last_args, [d.oid, 1, 10, 20])
        self.assertTrue(d.settings.position_lead)
        self.assertEqual(d.settings.position_lead_gain, 10)
        self.assertEqual(d.settings.position_lead_max_counts, 20)

    def test_disable_preserves_position_lead_gain_and_cap(self):
        d = make_driver()
        d.settings.position_lead_gain = 10
        d.settings.position_lead_max_counts = 20

        d.controls.set_position_lead(MockGCmd({"ENABLE": 0}))

        self.assertEqual(d.protocol.commands.set_position_lead.last_args, [d.oid, 0, 10, 20])
        self.assertFalse(d.settings.position_lead)
        self.assertEqual(d.settings.position_lead_gain, 10)
        self.assertEqual(d.settings.position_lead_max_counts, 20)


class TestPhaseAdvanceCommand(unittest.TestCase):
    def test_sets_phase_advance_enable_gain_cap_and_deadband(self):
        d = make_driver()

        d.controls.set_phase_advance(
            MockGCmd(
                {
                    "ENABLE": 1,
                    "GAIN_PPM": -60000,
                    "MAX_COUNTS": 64,
                    "DEADBAND": 16,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.set_phase_advance.last_args,
            [d.oid, 1, -60000, 64, 16],
        )
        self.assertTrue(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, -60000)
        self.assertEqual(d.settings.phase_advance_max_counts, 64)
        self.assertEqual(d.settings.phase_advance_deadband, 16)

    def test_disable_preserves_phase_advance_parameters(self):
        d = make_driver()
        d.settings.phase_advance_gain_ppm = 60000
        d.settings.phase_advance_max_counts = 64
        d.settings.phase_advance_deadband = 16

        d.controls.set_phase_advance(MockGCmd({"ENABLE": 0}))

        self.assertEqual(
            d.protocol.commands.set_phase_advance.last_args,
            [d.oid, 0, 60000, 64, 16],
        )
        self.assertFalse(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, 60000)
        self.assertEqual(d.settings.phase_advance_max_counts, 64)
        self.assertEqual(d.settings.phase_advance_deadband, 16)

    def test_enable_with_no_parameters_is_safe_noop(self):
        d = make_driver()

        d.controls.set_phase_advance(MockGCmd({}))

        self.assertEqual(d.protocol.commands.set_phase_advance.last_args, [d.oid, 1, 0, 0, 16])
        self.assertTrue(d.settings.phase_advance)
        self.assertEqual(d.settings.phase_advance_gain_ppm, 0)
        self.assertEqual(d.settings.phase_advance_max_counts, 0)
        self.assertEqual(d.settings.phase_advance_deadband, 16)


class TestVoltageLimitCommand(unittest.TestCase):
    def test_sets_pidout_voltage_limit_without_persisting(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 20000})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 20000])
        self.assertIn("pidout_uq_ud_limit=20000", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_max(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 32767})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 32767])
        self.assertIn("pidout_uq_ud_limit=32767", gcmd.last_info)

    def test_accepts_voltage_limit_at_chip_min(self):
        d = make_driver()

        gcmd = MockGCmd({"VOLTAGE_LIMIT": 0})
        d.controls.set_voltage_limit(gcmd)

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 0])
        self.assertIn("pidout_uq_ud_limit=0", gcmd.last_info)

    def test_voltage_limit_change_is_used_by_homing_preload(self):
        d = make_driver()
        d.state.active_gains = SAMPLE_ACTIVE_GAINS.copy()

        d.controls.set_voltage_limit(MockGCmd({"VOLTAGE_LIMIT": 20000}))
        d.homing.apply_active_gains_to_firmware()

        self.assertEqual(d.protocol.commands.set_voltage_limit.last_args, [d.oid, 20000])
