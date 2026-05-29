"""Tests for active FOCI diagnostic command behavior."""

import unittest

from tests.mocks import MockGCmd, make_driver


class TestCurrentStepDiagnosticCommand(unittest.TestCase):
    def test_sends_bounded_current_step_defaults(self):
        d = make_driver()

        gcmd = MockGCmd({"TARGET": 250})
        d.diagnostics.current_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args, [d.oid, 250, 80, 12000]
        )
        self.assertIn("target=250", gcmd.last_info)

    def test_sends_explicit_current_step_parameters(self):
        d = make_driver()

        d.diagnostics.current_step_test(
            MockGCmd({"TARGET": -500, "DURATION_MS": 120, "VOLTAGE_LIMIT": 20000})
        )

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args, [d.oid, -500, 120, 20000]
        )

    def test_current_step_result_formats_motion_and_supply_fields(self):
        d = make_driver()

        d.diagnostics.handle_current_step_result(
            {
                "status": 0,
                "target": 250,
                "torque_during": 240,
                "torque_before": -3,
                "torque_after": 18,
                "flux_during": 4,
                "iq_during": 239,
                "id_during": -5,
                "uq_limited": 1500,
                "ud_limited": -20,
                "encoder_before": 3900,
                "encoder_after": 12,
                "encoder_delta": 112,
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("enc_before=3900", out)
        self.assertIn("enc_after=12", out)
        self.assertIn("enc_delta=112", out)
        self.assertIn("adc_vm_raw=40099", out)

    def test_sends_flux_axis_current_vector_step(self):
        d = make_driver()

        d.diagnostics.current_vector_step_test(
            MockGCmd(
                {
                    "TORQUE_TARGET": 0,
                    "FLUX_TARGET": 250,
                    "DURATION_MS": 120,
                    "VOLTAGE_LIMIT": 20000,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.current_vector_step_test.last_args,
            [d.oid, 0, 250, 120, 20000],
        )

    def test_current_vector_step_result_formats_axis_targets(self):
        d = make_driver()

        d.diagnostics.handle_current_vector_step_result(
            {
                "status": 0,
                "torque_target": 0,
                "flux_target": 250,
                "torque_during": 8,
                "torque_before": -3,
                "torque_after": 18,
                "flux_during": 240,
                "iq_during": 12,
                "id_during": 238,
                "uq_limited": 20,
                "ud_limited": 1500,
                "encoder_before": 3900,
                "encoder_after": 3912,
                "encoder_delta": 12,
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("current vector step", out)
        self.assertIn("torque_target=0", out)
        self.assertIn("flux_target=250", out)
        self.assertIn("actual_torque=8", out)
        self.assertIn("actual_flux=240", out)
        self.assertIn("enc_delta=12", out)

    def test_sends_torque_sample_step_with_short_delay(self):
        d = make_driver()
        d.diagnostics.current_torque_sample_details[(500, -125, 5, 29000)] = {
            "torque_error": 1
        }

        d.diagnostics.current_torque_sample_test(
            MockGCmd(
                {
                    "TARGET": 500,
                    "FLUX_TARGET": -125,
                    "SAMPLE_DELAY_MS": 5,
                    "VOLTAGE_LIMIT": 29000,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.current_torque_sample_test.last_args,
            [d.oid, 500, -125, 5, 29000],
        )
        self.assertEqual(d.diagnostics.current_torque_sample_details, {})

    def test_sends_position_torque_offset_sample(self):
        d = make_driver()
        gcmd = MockGCmd({"TARGET": 500, "SAMPLE_DELAY_MS": 2, "VOLTAGE_LIMIT": 29000})

        d.diagnostics.position_torque_offset_test(gcmd)

        self.assertEqual(
            d.protocol.commands.position_torque_offset_sample_test.last_args,
            [d.oid, 500, 2, 29000],
        )
        self.assertIn("position-torque-offset", gcmd.last_info)

    def test_sends_voltage_step_sample(self):
        d = make_driver()
        gcmd = MockGCmd({"UQ": 512, "UD": -256, "SAMPLE_DELAY_MS": 2})

        d.diagnostics.voltage_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.voltage_step_test.last_args,
            [d.oid, 512, -256, 2],
        )
        self.assertIn("voltage-step", gcmd.last_info)

    def test_voltage_step_result_formats_sample_fields(self):
        d = make_driver()

        d.diagnostics.handle_voltage_step_result(
            {
                "status": 0,
                "uq_ext": 512,
                "ud_ext": -256,
                "sample_delay_ms": 2,
                "torque_before": -3,
                "torque_sample": 42,
                "torque_after": 4,
                "flux_sample": -21,
                "iq_sample": 44,
                "id_sample": -19,
                "uq_limited": 500,
                "ud_limited": -251,
                "uux_sample": 123,
                "uwy_sample": -456,
                "pwm_ux_sample": 120,
                "pwm_wy_sample": -450,
                "pwm_sv_chop": 0x00000007,
                "pwm_bbm": 0x00002828,
                "pwm_maxcnt": 3999,
                "phi_e_sample": 3000,
                "phi_m_sample": -1200,
                "encoder_before": 3900,
                "encoder_sample": 3901,
                "encoder_after": 3900,
                "encoder_delta_sample": 1,
                "encoder_delta_after": 0,
                "adc_vm_raw": 40099,
                "status_flags": 0x70000000,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("voltage step", out)
        self.assertIn("uq_ext=512", out)
        self.assertIn("ud_ext=-256", out)
        self.assertIn("sample_delay_ms=2", out)
        self.assertIn("actual=42", out)
        self.assertIn("flux=-21", out)
        self.assertIn("iq=44", out)
        self.assertIn("id=-19", out)
        self.assertIn("uux_sample=123", out)
        self.assertIn("uwy_sample=-456", out)
        self.assertIn("pwm_ux_sample=120", out)
        self.assertIn("pwm_wy_sample=-450", out)
        self.assertIn("pwm_sv_chop=0x00000007", out)
        self.assertIn("pwm_bbm=0x00002828", out)
        self.assertIn("pwm_maxcnt=3999", out)
        self.assertIn("phi_e_sample=3000", out)
        self.assertIn("phi_m_sample=-1200", out)
        self.assertIn("enc_delta_sample=1", out)
        self.assertIn("enc_delta_after=0", out)
        self.assertIn("status_flags=0x70000000", out)

    def test_current_torque_sample_result_formats_sample_fields(self):
        d = make_driver()

        d.diagnostics.handle_current_torque_sample_detail_result(
            {
                "target": 500,
                "flux_target": -125,
                "sample_delay_ms": 5,
                "voltage_limit": 29000,
                "torque_error": 190,
                "flux_error": -129,
                "torque_error_sum": 12345,
                "flux_error_sum": -2345,
                "uq_prelimit": 3210,
                "ud_prelimit": -30,
                "ff_velocity": 17,
                "ff_torque": -42,
            }
        )
        d.diagnostics.handle_current_torque_sample_result(
            {
                "status": 0,
                "target": 500,
                "flux_target": -125,
                "sample_delay_ms": 5,
                "voltage_limit": 29000,
                "torque_before": -3,
                "torque_sample": 310,
                "torque_after": 18,
                "flux_sample": 4,
                "iq_sample": 309,
                "id_sample": -5,
                "uq_limited": 3200,
                "ud_limited": -20,
                "encoder_before": 3900,
                "encoder_sample": 3902,
                "encoder_after": 3912,
                "encoder_delta_sample": 2,
                "encoder_delta_after": 12,
                "adc_vm_raw": 40099,
                "pidin_target_torque": 500,
                "pidin_target_flux": -125,
                "pidout_target_torque": 3199,
                "pidout_target_flux": -25,
                "pid_torque_target_monitor": 500,
                "status_flags": 0x8000,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("current torque sample", out)
        self.assertIn("target=500", out)
        self.assertIn("flux_target=-125", out)
        self.assertIn("sample_delay_ms=5", out)
        self.assertIn("actual=310", out)
        self.assertIn("enc_sample=3902", out)
        self.assertIn("enc_delta_sample=2", out)
        self.assertIn("enc_delta_after=12", out)
        self.assertIn("pidin_target_torque=500", out)
        self.assertIn("pidin_target_flux=-125", out)
        self.assertIn("pidout_target_torque=3199", out)
        self.assertIn("pidout_target_flux=-25", out)
        self.assertIn("pid_torque_target_monitor=500", out)
        self.assertIn("torque_error=190", out)
        self.assertIn("flux_error=-129", out)
        self.assertIn("torque_error_sum=12345", out)
        self.assertIn("flux_error_sum=-2345", out)
        self.assertIn("uq_prelimit=3210", out)
        self.assertIn("ud_prelimit=-30", out)
        self.assertIn("ff_velocity=17", out)
        self.assertIn("ff_torque=-42", out)
        self.assertIn("status_flags=0x00008000", out)
        self.assertEqual(d.diagnostics.current_torque_sample_details, {})
