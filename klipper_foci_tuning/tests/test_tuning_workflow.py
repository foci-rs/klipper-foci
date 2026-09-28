"""Tests for FOCI rare fine-tuning workflow behavior."""

import unittest

from mocks import MockGCmd, make_driver

from klipper_foci_tuning.workflow import TuningWorkflow


class TestAccelFeedforwardCommand(unittest.TestCase):
    def test_sets_accel_feedforward_enable_and_split_gains(self):
        d = make_driver()
        tuning = TuningWorkflow(d)

        tuning.set_accel_feedforward(
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
        tuning = TuningWorkflow(d)

        tuning.set_accel_feedforward(
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
        tuning = TuningWorkflow(d)
        d.settings.accel_feedforward_accel_gain = 750
        d.settings.accel_feedforward_decel_gain = 250

        tuning.set_accel_feedforward(
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
