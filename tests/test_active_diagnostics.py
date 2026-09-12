"""Tests for active FOCI diagnostic command behavior."""

import unittest

from tests.mocks import (
    CommandError,
    MockCoreXYKinematics,
    MockGCmd,
    make_driver,
)


def test_current_loop_hold_caches_last_evidence():
    d = make_driver()
    params = {
        "oid": d.oid,
        "hold_status": 1,
        "warning_flags": 0,
        "elapsed_us": 250000,
        "requested_sample_period_us": 1000,
        "sample_count": 250,
        "position_span_count": 1,
        "position_drift_count": 1,
        "torque_mean_count": 0,
        "torque_rms_count": 12,
        "torque_peak_to_peak_count": 34,
        "torque_crossing_count": 17,
        "flux_mean_count": 0,
        "flux_rms_count": 9,
        "flux_peak_to_peak_count": 21,
        "flux_crossing_count": 11,
        "status_flags_or": 0,
        "actionable_status_count": 0,
    }

    d.diagnostics.active.handle_current_loop_hold(params)

    assert d.diagnostics.active.last_current_loop_hold_evidence(d.oid) == params
    assert d.diagnostics.active.last_current_loop_hold_evidence(d.oid + 1) == {}
    out = d.printer.lookup_object("gcode")._responses[-1]
    for field_name in (
        "hold_status",
        "warnings",
        "samples",
        "elapsed_us",
        "period_us",
        "pos_span",
        "pos_drift",
        "torque_rms",
        "torque_span",
        "torque_crossings",
        "flux_rms",
        "flux_span",
        "flux_crossings",
        "status_or",
        "actionable_status_count",
    ):
        assert field_name in out


def test_current_loop_run_prints_failure_reason_name():
    d = make_driver()
    params = {
        "oid": d.oid,
        "status": 1,
        "gains_source": 1,
        "gains_tier": 1,
        "axis_split_source": 0,
        "measured_axis_split_permille": 500,
        "applied_axis_split_permille": 500,
        "axis_split_clamped": 0,
        "current_validation_axes": 3,
        "retry_budget_exhausted": 0,
        "failure_reason": 4,
        "candidate_gains_source": 1,
        "candidate_gains_tier": 1,
        "candidate_attempt": 0,
        "candidate_flux_p": 100,
        "candidate_flux_i": 50,
        "candidate_torque_p": 100,
        "candidate_torque_i": 50,
    }

    d.diagnostics.active.handle_current_loop_run(params)

    out = d.printer.lookup_object("gcode")._responses[-1]
    assert "failure_reason=4/flux_validation" in out


def test_closed_loop_activation_caches_last_evidence():
    d = make_driver()
    params = {
        "oid": d.oid,
        "entry_status": 3,
        "position_1": -3,
        "position_2": 4,
        "drift_count": 7,
        "threshold_count": 2,
        "runaway": 0,
    }

    d.diagnostics.active.handle_closed_loop_activation(params)

    assert d.diagnostics.active.last_closed_loop_activation_evidence(d.oid) == params
    assert d.diagnostics.active.last_closed_loop_activation_evidence(d.oid + 1) == {}
    out = d.printer.lookup_object("gcode")._responses[-1]
    for field_name in (
        "entry_status",
        "position_1",
        "position_2",
        "drift_count",
        "threshold_count",
        "runaway",
    ):
        assert field_name in out


def test_current_loop_filters_fold_into_commission_result_cache():
    d = make_driver()

    d.diagnostics.active.handle_current_loop_filters(
        {
            "oid": d.oid,
            "velocity_filter_hz": 0,
            "torque_filter_hz": 3000,
            "position_filter_hz": 0,
            "flux_filter_hz": 3000,
        }
    )

    folded = d.diagnostics.active.pop_current_loop_cache(d.oid)

    assert folded["velocity_filter_hz"] == 0
    assert folded["current_torque_filter_hz"] == 3000
    assert folded["position_filter_hz"] == 0
    assert folded["current_flux_filter_hz"] == 3000


class TestCurrentStepDiagnosticCommand(unittest.TestCase):
    def test_inductance_evidence_replies_format_gcode_lines(self):
        d = make_driver()

        d.diagnostics.active.handle_inductance_run(
            {
                "oid": d.oid,
                "source": 1,
                "status": 0,
                "warning_flags": 2,
                "ud_count": 768,
                "realized_frequency_millihz": 1_000_000,
                "elapsed_us": 8000,
                "openloop_phi_delta_counts": 524_288,
                "sample_count": 104,
                "encoder_delta_counts": 0,
                "status_flags_or": 0,
            }
        )
        d.diagnostics.active.handle_inductance_frame(
            {
                "oid": d.oid,
                "id_mean_milli_count": 20_000,
                "iq_mean_milli_count": -84_000,
                "id_rms_milli_count": 5000,
                "iq_rms_milli_count": 21_000,
                "drift_permille": 40,
                "zero_id_mean_milli_count": 100,
                "zero_iq_mean_milli_count": -200,
            }
        )
        d.diagnostics.active.handle_inductance_estimate(
            {
                "oid": d.oid,
                "x_average_count_ratio_milli": 8600,
                "x_d_count_ratio_milli": 9200,
                "x_q_count_ratio_milli": 8000,
                "saliency_status": 1,
                "saliency_permille": 140,
                "x_mag_nominal_count_ratio_milli": 8770,
                "x_mag_shift_minus_permille": 4,
                "x_mag_shift_plus_permille": 4,
                "x_mag_vs_quad_permille": 20,
            }
        )

        responses = d.printer.lookup_object("gcode")._responses[-3:]
        self.assertIn("inductance run:", responses[0])
        self.assertIn("realized_frequency_millihz=1000000", responses[0])
        self.assertIn("inductance frame:", responses[1])
        self.assertIn("iq_mean_milli_count=-84000", responses[1])
        self.assertIn("drift_permille=40", responses[1])
        self.assertIn("inductance estimate:", responses[2])
        self.assertIn("x_average_count_ratio_milli=8600", responses[2])

    def test_sends_bounded_current_step_defaults(self):
        d = make_driver()

        gcmd = MockGCmd({"TARGET": 250})
        d.diagnostics.current_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args, [d.oid, 0, 250, 80, 12000]
        )
        self.assertIn("axis=torque", gcmd.last_info)
        self.assertIn("target=250", gcmd.last_info)

    def test_sends_explicit_current_step_parameters(self):
        d = make_driver()

        d.diagnostics.current_step_test(
            MockGCmd(
                {
                    "AXIS": "flux",
                    "TARGET": -500,
                    "DURATION_MS": 120,
                    "VOLTAGE_LIMIT": 20000,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args,
            [d.oid, 1, -500, 120, 20000],
        )

    def test_current_step_rejects_unknown_axis(self):
        d = make_driver()

        with self.assertRaises(CommandError):
            d.diagnostics.current_step_test(MockGCmd({"AXIS": "position", "TARGET": 250}))

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

    def test_sends_torque_sample_step_with_long_diagnostic_delay(self):
        d = make_driver()
        d.diagnostics.current_torque_sample_details[(500, -125, 100, 29000)] = {"torque_error": 1}

        d.diagnostics.current_torque_sample_test(
            MockGCmd(
                {
                    "TARGET": 500,
                    "FLUX_TARGET": -125,
                    "SAMPLE_DELAY_MS": 100,
                    "VOLTAGE_LIMIT": 29000,
                }
            )
        )

        self.assertEqual(
            d.protocol.commands.current_torque_sample_test.last_args,
            [d.oid, 500, -125, 100, 29000],
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


class TestResistanceTestDiagnosticCommand(unittest.TestCase):
    def test_sends_resistance_test_request(self):
        d = make_driver()
        gcmd = MockGCmd({})

        d.diagnostics.resistance_test(gcmd)

        self.assertEqual(d.protocol.commands.resistance_test.last_args, [d.oid, 0])
        self.assertIn("resistance-test", gcmd.last_info)

    def test_resistance_profile_reply_prints_firmware_metadata(self):
        d = make_driver()

        d.diagnostics.active.handle_resistance_profile(
            {
                "oid": d.oid,
                "pwm_maxcnt": 3999,
                "bbm_h": 9,
                "bbm_l": 9,
                "dsadc_mdec_a": 8,
                "dsadc_mdec_b": 8,
                "linear_current_threshold_count": 256,
                "encoder_move_warn_counts": 4,
                "status_flags_warn_mask": 0x00080000,
                "scale_metadata_validated": 1,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("pwm_maxcnt=3999", out)
        self.assertIn("bbm_h=9", out)
        self.assertIn("bbm_l=9", out)
        self.assertIn("scale_metadata_validated=1", out)

    def test_resistance_run_reply_prints_firmware_run_summary(self):
        kinematics = MockCoreXYKinematics([["manual_stepper stepper_x"], ["stepper_y"]])
        d = make_driver(kinematics=kinematics, homed_axes="xy")
        d.state.is_calibrated = True
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
        enable_line.motor_enable(0.0)

        d.diagnostics.active.handle_resistance_run(
            {
                "oid": d.oid,
                "status": 0,
                "selected_r_count_slope_milli": 1042,
                "warning_flags": 0,
                "status_flags_or": 0x00080000,
                "peak_abs_current_count": 1200,
                "max_abs_steady_mean_current_count": 900,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 0,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0x00000909,
                "dsadc_mdec_readback": 0x00080008,
                "pwm_sv_chop_readback": 0x00000007,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("status=0", out)
        self.assertIn("selected_r_count_slope_milli=1042", out)
        self.assertIn("warning_flags=0", out)
        self.assertIn("status_flags_or=0x00080000", out)
        self.assertIn("peak_abs_current_count=1200", out)
        self.assertIn("max_abs_steady_mean_current_count=900", out)
        self.assertIn("current_ceiling_count=1600", out)
        self.assertIn("power_stage_tripped=0", out)
        cached_run = d.diagnostics.active.resistance_cache[d.oid]["run"]
        self.assertEqual(cached_run["peak_abs_current_count"], 1200)
        self.assertEqual(cached_run["max_abs_steady_mean_current_count"], 900)
        self.assertEqual(cached_run["current_ceiling_count"], 1600)
        self.assertEqual(cached_run["power_stage_tripped"], 0)
        self.assertTrue(enable_line.is_motor_enabled())
        self.assertTrue(d.state.is_calibrated)
        self.assertIsNone(kinematics._cleared_axes)
        self.assertEqual(d.protocol.commands.commission.call_count, 0)

    def test_resistance_run_reply_prints_specific_failure_name(self):
        d = make_driver()

        d.diagnostics.active.handle_resistance_run(
            {
                "oid": d.oid,
                "status": 23,
                "selected_r_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
                "peak_abs_current_count": 0,
                "max_abs_steady_mean_current_count": 0,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 0,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0x00000909,
                "dsadc_mdec_readback": 0x00080008,
                "pwm_sv_chop_readback": 0,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("status=23", out)
        self.assertIn("status_name=resistance insufficient linear points", out)

    def test_cleanup_error_with_trip_reconciles_disabled_motor_and_homing(self):
        kinematics = MockCoreXYKinematics([["manual_stepper stepper_x"], ["stepper_y"]])
        d = make_driver(kinematics=kinematics, homed_axes="xy")
        d.state.is_calibrated = True
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
        enable_line.motor_enable(0.0)

        d.diagnostics.active.handle_resistance_run(
            {
                "oid": d.oid,
                "status": 3,
                "selected_r_count_slope_milli": 0,
                "gain_path_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
                "peak_abs_current_count": 1800,
                "max_abs_steady_mean_current_count": 1000,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 1,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0x00000909,
                "dsadc_mdec_readback": 0x00080008,
                "pwm_sv_chop_readback": 0,
            }
        )

        self.assertFalse(enable_line.is_motor_enabled())
        self.assertFalse(d.state.is_calibrated)
        self.assertEqual(kinematics._cleared_axes, {0, 1, "x", "y"})
        self.assertEqual(d.protocol.commands.commission.call_count, 0)
        out = "\n".join(d.printer.lookup_object("gcode")._responses)
        self.assertIn("firmware disabled the motor", out)
        self.assertIn("rehoming is required", out)

    def test_resistance_axis_reply_prints_firmware_fit_result(self):
        d = make_driver()

        d.diagnostics.active.handle_resistance_axis(
            {
                "oid": d.oid,
                "electrical_axis": 0,
                "phi_e_ext": 0,
                "r_count_slope_milli": 1042,
                "intercept_count": 24,
                "rmse_permille": 8,
                "selected_mask": 0b11111000,
                "excluded_point_mask": 0b00000111,
                "selected_count": 5,
                "signed_count_slope_milli": 1041,
                "signed_asymmetry_permille": 12,
                "drift_permille": 5,
                "warning_flags": 0,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("electrical_axis=0", out)
        self.assertIn("count_slope=1042", out)
        self.assertIn("intercept_count=24", out)
        self.assertIn("rmse_permille=8", out)
        self.assertIn("signed_count_slope=1041", out)
        self.assertIn("drift_permille=5", out)

    def test_resistance_diagnostic_does_not_compute_fit_in_host(self):
        d = make_driver()

        d.diagnostics.active.handle_resistance_axis(
            {
                "oid": d.oid,
                "electrical_axis": 0,
                "phi_e_ext": 0,
                "r_count_slope_milli": 1042,
                "warning_flags": 0,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("count_slope=1042", out)
        self.assertFalse(hasattr(d.diagnostics.active, "fit_resistance_axis"))


class TestVelocityLimitLatchDiagnosticCommand(unittest.TestCase):
    def test_sends_explicit_channel(self):
        d = make_driver()
        d.diagnostics.active.velocity_limit_latch_cache[d.oid] = {
            "flags": {"active_status_flags": 0x80}
        }

        d.diagnostics.velocity_limit_latch_test(MockGCmd({}))

        self.assertEqual(
            d.protocol.commands.velocity_limit_latch_test.last_args,
            [d.oid, d.channel],
        )
        self.assertNotIn(d.oid, d.diagnostics.active.velocity_limit_latch_cache)

    def test_terminal_core_assembles_all_causal_fragments(self):
        d = make_driver()
        active = d.diagnostics.active
        active.handle_velocity_limit_latch_flags(
            {
                "oid": d.oid,
                "active_status_flags": 0x80,
                "post_pulse_status_flags": 0x80,
                "delayed_status_flags": 0x80,
                "post_clear_status_flags": 0,
            }
        )
        active.handle_velocity_limit_latch_motion(
            {
                "oid": d.oid,
                "pulse_elapsed_us": 104,
                "delayed_read_elapsed_us": 1008,
                "encoder_before": 100,
                "encoder_after": 101,
                "encoder_delta": 1,
            }
        )
        active.handle_velocity_limit_latch_restore(
            {
                "oid": d.oid,
                "saved_limit": 2816,
                "saved_gains": 0x01000002,
                "saved_target": 0,
                "saved_mode": 3,
                "restored_limit_readback": 2816,
                "restored_gains_readback": 0x01000002,
                "restored_target_readback": 0,
                "restored_mode_readback": 3,
                "restore_verified_mask": 0x0F,
            }
        )

        active.handle_velocity_limit_latch_core(
            {
                "oid": d.oid,
                "status": 0,
                "test_limit": 1,
                "p_raw": 512,
                "i_raw": 0,
                "target_velocity_rpm": 1,
                "limit_readback": 1,
                "gains_readback": 0x02000000,
                "target_readback": 1,
                "power_stage_tripped": 1,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("status=0", out)
        self.assertIn("active_status=0x00000080", out)
        self.assertIn("delayed_status=0x00000080", out)
        self.assertIn("post_clear_status=0x00000000", out)
        self.assertIn("pulse_us=104", out)
        self.assertIn("encoder_delta=1", out)
        self.assertIn("saved_gains=0x01000002", out)
        self.assertIn("restored_gains=0x01000002", out)
        self.assertIn("saved_target=0", out)
        self.assertIn("restored_target=0", out)
        self.assertIn("saved_mode=0x00000003", out)
        self.assertIn("restored_mode=0x00000003", out)
        self.assertIn("restore_mask=0x0f", out)
        self.assertIn("power_stage_tripped=1", out)
        self.assertNotIn(d.oid, active.velocity_limit_latch_cache)
