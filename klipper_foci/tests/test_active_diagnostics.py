"""Tests for active FOCI diagnostic command behavior."""

import logging
import unittest

from tests.mocks import (
    MockCoreXYKinematics,
    make_driver,
)

ACTIVE_LOGGER = "klipper_foci.diagnostics.active"


def test_current_loop_hold_caches_last_evidence(caplog):
    d = make_driver()
    d.global_config.debug = True
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

    with caplog.at_level(logging.INFO, logger=ACTIVE_LOGGER):
        d.diagnostics.active.handle_current_loop_hold(params)

    assert d.diagnostics.active.last_current_loop_hold_evidence(d.oid) == params
    assert d.diagnostics.active.last_current_loop_hold_evidence(d.oid + 1) == {}
    assert d.printer.lookup_object("gcode")._responses == []
    out = caplog.records[-1].message
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


def test_current_loop_run_prints_failure_reason_name(caplog):
    d = make_driver()
    d.global_config.debug = True
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

    with caplog.at_level(logging.INFO, logger=ACTIVE_LOGGER):
        d.diagnostics.active.handle_current_loop_run(params)

    assert d.printer.lookup_object("gcode")._responses == []
    out = caplog.records[-1].message
    assert "failure_reason=4/flux_validation" in out


def test_closed_loop_activation_caches_last_evidence(caplog):
    d = make_driver()
    d.global_config.debug = True
    params = {
        "oid": d.oid,
        "entry_status": 3,
        "position_1": -3,
        "position_2": 4,
        "drift_count": 7,
        "threshold_count": 2,
        "runaway": 0,
    }

    with caplog.at_level(logging.INFO, logger=ACTIVE_LOGGER):
        d.diagnostics.active.handle_closed_loop_activation(params)

    assert d.diagnostics.active.last_closed_loop_activation_evidence(d.oid) == params
    assert d.diagnostics.active.last_closed_loop_activation_evidence(d.oid + 1) == {}
    assert d.printer.lookup_object("gcode")._responses == []
    out = caplog.records[-1].message
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
        d.global_config.debug = True

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
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

        self.assertEqual(d.printer.lookup_object("gcode")._responses, [])
        responses = [record.message for record in log_ctx.records]
        self.assertIn("inductance run:", responses[0])
        self.assertIn("realized_frequency_millihz=1000000", responses[0])
        self.assertIn("inductance frame:", responses[1])
        self.assertIn("iq_mean_milli_count=-84000", responses[1])
        self.assertIn("drift_permille=40", responses[1])
        self.assertIn("inductance estimate:", responses[2])
        self.assertIn("x_average_count_ratio_milli=8600", responses[2])

    def test_current_step_result_formats_motion_and_supply_fields(self):
        d = make_driver()

        d.diagnostics.handle_current_step_result(
            {
                "status": 0,
                "axis": 0,
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
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("axis=torque", out)
        self.assertIn("enc_before=3900", out)
        self.assertIn("enc_after=12", out)
        self.assertIn("enc_delta=112", out)
        self.assertIn("adc_vm_raw=40099", out)

    def test_current_step_result_reports_axis_from_reply(self):
        d = make_driver()

        d.diagnostics.handle_current_step_result(
            {
                "status": 0,
                "axis": 1,
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
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("axis=flux", out)

        d.diagnostics.handle_current_step_result(
            {
                "status": 0,
                "axis": 7,
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
                "adc_vm_raw": 40099,
            }
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("axis=7", out)

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

    def test_voltage_step_result_formats_sample_fields(self):
        d = make_driver()

        d.diagnostics.handle_voltage_step_detail_result(
            {
                "oid": d.oid,
                "report_seq": 1,
                "encoder_before": 3900,
                "encoder_sample": 3901,
                "encoder_after": 3900,
            }
        )
        d.diagnostics.handle_voltage_step_result(
            {
                "oid": d.oid,
                "report_seq": 1,
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
        self.assertIn("enc_before=3900", out)
        self.assertIn("enc_sample=3901", out)
        self.assertIn("enc_after=3900", out)
        self.assertIn("enc_delta_sample=1", out)
        self.assertIn("enc_delta_after=0", out)
        self.assertIn("status_flags=0x70000000", out)
        for field in (
            "uux_sample",
            "uwy_sample",
            "pwm_ux_sample",
            "pwm_wy_sample",
            "pwm_sv_chop",
            "pwm_bbm",
            "pwm_maxcnt",
            "phi_e_sample",
            "phi_m_sample",
        ):
            self.assertNotIn(field, out)

    def test_current_torque_sample_result_formats_sample_fields(self):
        d = make_driver()

        d.diagnostics.handle_current_torque_sample_pid_result(
            {
                "oid": d.oid,
                "report_seq": 1,
                "pidin_target_torque": 500,
                "pidin_target_flux": -125,
                "pidout_target_torque": 3199,
                "pidout_target_flux": -25,
                "pid_torque_target_monitor": 500,
                "torque_error": 190,
                "flux_error": -129,
                "torque_error_sum": 12345,
                "flux_error_sum": -2345,
            }
        )
        d.diagnostics.handle_current_torque_sample_detail_result(
            {
                "oid": d.oid,
                "report_seq": 1,
                "encoder_before": 3900,
                "encoder_sample": 3902,
                "encoder_after": 3912,
                "encoder_delta_sample": 2,
                "encoder_delta_after": 12,
                "uq_prelimit": 3210,
                "ud_prelimit": -30,
                "ff_velocity": 17,
                "ff_torque": -42,
            }
        )
        d.diagnostics.handle_current_torque_sample_result(
            {
                "oid": d.oid,
                "report_seq": 1,
                "kind": 0,
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
                "adc_vm_raw": 40099,
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


def _torque_terminal(oid, status=0, kind=0, report_seq=1):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "kind": kind,
        "status": status,
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
        "adc_vm_raw": 40099,
        "status_flags": 0x8000,
    }


def _torque_pid(oid, error_sum, report_seq=1):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "pidin_target_torque": 500,
        "pidin_target_flux": -125,
        "pidout_target_torque": 3199,
        "pidout_target_flux": -25,
        "pid_torque_target_monitor": 500,
        "torque_error": 190,
        "flux_error": -129,
        "torque_error_sum": error_sum,
        "flux_error_sum": -2345,
    }


def _torque_detail(oid, encoder_sample, report_seq=1):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "encoder_before": 3900,
        "encoder_sample": encoder_sample,
        "encoder_after": 3912,
        "encoder_delta_sample": 2,
        "encoder_delta_after": 12,
        "uq_prelimit": 3210,
        "ud_prelimit": -30,
        "ff_velocity": 17,
        "ff_torque": -42,
    }


def _voltage_terminal(oid, status=0, report_seq=1):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "status": status,
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
        "adc_vm_raw": 40099,
        "status_flags": 0x70000000,
    }


def _voltage_detail(oid, encoder_sample, report_seq=1):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "encoder_before": 3900,
        "encoder_sample": encoder_sample,
        "encoder_after": 3900,
    }


class TestTorqueSampleStitching(unittest.TestCase):
    def _out(self, d):
        return d.printer.lookup_object("gcode")._responses[-1]

    def test_label_comes_from_kind(self):
        d = make_driver()
        for kind, label in (
            (0, "current torque sample:"),
            (1, "position torque offset sample:"),
            (9, "torque sample kind=9:"),
        ):
            d.diagnostics.handle_current_torque_sample_result(_torque_terminal(d.oid, kind=kind))
            self.assertIn(label, self._out(d))

    def test_nonzero_status_terminal_discards_leftover_fragments(self):
        d = make_driver()
        d.diagnostics.handle_current_torque_sample_pid_result(_torque_pid(d.oid, 777777))
        d.diagnostics.handle_current_torque_sample_detail_result(_torque_detail(d.oid, 55555))

        d.diagnostics.handle_current_torque_sample_result(_torque_terminal(d.oid, status=1))
        out = self._out(d)

        self.assertIn("status=1", out)
        self.assertNotIn("777777", out)
        self.assertNotIn("55555", out)
        d.diagnostics.handle_current_torque_sample_result(_torque_terminal(d.oid))
        self.assertNotIn("777777", self._out(d))

    def test_success_terminal_with_missing_fragment_reports_missing(self):
        d = make_driver()
        d.diagnostics.handle_current_torque_sample_pid_result(_torque_pid(d.oid, 12345))

        d.diagnostics.handle_current_torque_sample_result(_torque_terminal(d.oid))
        out = self._out(d)

        self.assertIn("torque_error_sum=12345", out)
        self.assertIn("missing=detail", out)

    def test_fragments_stitch_per_oid(self):
        d = make_driver()
        other = d.oid + 1
        d.diagnostics.handle_current_torque_sample_pid_result(_torque_pid(d.oid, 111))
        d.diagnostics.handle_current_torque_sample_pid_result(_torque_pid(other, 222))
        d.diagnostics.handle_current_torque_sample_detail_result(_torque_detail(d.oid, 3333))
        d.diagnostics.handle_current_torque_sample_detail_result(_torque_detail(other, 4444))

        d.diagnostics.handle_current_torque_sample_result(_torque_terminal(other))
        out_other = self._out(d)
        d.diagnostics.handle_current_torque_sample_result(_torque_terminal(d.oid))
        out_own = self._out(d)

        self.assertIn("torque_error_sum=222", out_other)
        self.assertIn("enc_sample=4444", out_other)
        self.assertIn("torque_error_sum=111", out_own)
        self.assertIn("enc_sample=3333", out_own)


class TestVoltageStepStitching(unittest.TestCase):
    def _out(self, d):
        return d.printer.lookup_object("gcode")._responses[-1]

    def test_voltage_step_stitches_detail_by_seq(self):
        d = make_driver()
        d.diagnostics.handle_voltage_step_detail_result(
            _voltage_detail(d.oid, encoder_sample=4001, report_seq=7)
        )

        d.diagnostics.handle_voltage_step_result(_voltage_terminal(d.oid, report_seq=7))
        out = self._out(d)

        self.assertIn("enc_before=3900", out)
        self.assertIn("enc_sample=4001", out)
        self.assertIn("enc_after=3900", out)

    def test_fragment_with_other_report_seq_is_discarded(self):
        d = make_driver()
        d.diagnostics.handle_voltage_step_detail_result(
            _voltage_detail(d.oid, encoder_sample=9999, report_seq=5)
        )

        d.diagnostics.handle_voltage_step_result(_voltage_terminal(d.oid, report_seq=6))
        out = self._out(d)

        self.assertNotIn("9999", out)
        self.assertIn("missing=detail", out)

    def test_voltage_step_failure_ignores_cached_detail(self):
        d = make_driver()
        d.diagnostics.handle_voltage_step_detail_result(
            _voltage_detail(d.oid, encoder_sample=8888, report_seq=3)
        )

        d.diagnostics.handle_voltage_step_result(_voltage_terminal(d.oid, status=1, report_seq=3))
        out = self._out(d)

        self.assertIn("status=1", out)
        self.assertNotIn("8888", out)
        self.assertNotIn("missing=", out)

    def test_voltage_step_fragments_stitch_per_oid(self):
        d = make_driver()
        other = d.oid + 1
        d.diagnostics.handle_voltage_step_detail_result(_voltage_detail(d.oid, encoder_sample=111))
        d.diagnostics.handle_voltage_step_detail_result(_voltage_detail(other, encoder_sample=222))

        d.diagnostics.handle_voltage_step_result(_voltage_terminal(other))
        out_other = self._out(d)
        d.diagnostics.handle_voltage_step_result(_voltage_terminal(d.oid))
        out_own = self._out(d)

        self.assertIn("enc_sample=222", out_other)
        self.assertIn("enc_sample=111", out_own)

    def test_voltage_step_line_omits_removed_fields(self):
        d = make_driver()
        d.diagnostics.handle_voltage_step_detail_result(_voltage_detail(d.oid, encoder_sample=1))

        d.diagnostics.handle_voltage_step_result(_voltage_terminal(d.oid))
        out = self._out(d)

        for field in (
            "uux_sample",
            "uwy_sample",
            "pwm_ux_sample",
            "pwm_wy_sample",
            "pwm_sv_chop",
            "pwm_bbm",
            "pwm_maxcnt",
            "phi_e_sample",
            "phi_m_sample",
        ):
            self.assertNotIn(field, out)


class TestResistanceTestDiagnosticCommand(unittest.TestCase):
    def test_resistance_profile_reply_prints_firmware_metadata(self):
        d = make_driver()
        d.global_config.debug = True

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
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

        self.assertEqual(d.printer.lookup_object("gcode")._responses, [])
        out = log_ctx.records[-1].message
        self.assertIn("pwm_maxcnt=3999", out)
        self.assertIn("bbm_h=9", out)
        self.assertIn("bbm_l=9", out)
        self.assertIn("scale_metadata_validated=1", out)

    def test_resistance_run_reply_prints_firmware_run_summary(self):
        kinematics = MockCoreXYKinematics([["manual_stepper stepper_x"], ["stepper_y"]])
        d = make_driver(kinematics=kinematics, homed_axes="xy")
        d.global_config.debug = True
        d.state.is_calibrated = True
        enable_line = d.printer.lookup_object("stepper_enable").lookup_enable(d.stepper_name)
        enable_line.motor_enable(0.0)

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
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

        self.assertEqual(d.printer.lookup_object("gcode")._responses, [])
        out = log_ctx.records[-1].message
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
        d.global_config.debug = True

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
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

        self.assertEqual(d.printer.lookup_object("gcode")._responses, [])
        out = log_ctx.records[-1].message
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
        d.global_config.debug = True

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
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

        self.assertEqual(d.printer.lookup_object("gcode")._responses, [])
        out = log_ctx.records[-1].message
        self.assertIn("electrical_axis=0", out)
        self.assertIn("count_slope=1042", out)
        self.assertIn("intercept_count=24", out)
        self.assertIn("rmse_permille=8", out)
        self.assertIn("signed_count_slope=1041", out)
        self.assertIn("drift_permille=5", out)

    def test_resistance_diagnostic_does_not_compute_fit_in_host(self):
        d = make_driver()
        d.global_config.debug = True

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
            d.diagnostics.active.handle_resistance_axis(
                {
                    "oid": d.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1042,
                    "warning_flags": 0,
                }
            )

        self.assertEqual(d.printer.lookup_object("gcode")._responses, [])
        out = log_ctx.records[-1].message
        self.assertIn("count_slope=1042", out)
        self.assertFalse(hasattr(d.diagnostics.active, "fit_resistance_axis"))


def test_diagnostics_has_no_raw_register_method():
    driver = make_driver()
    assert not hasattr(driver.diagnostics, "tmc_read_register")
    assert not hasattr(driver.diagnostics.passive, "tmc_read_register")


def test_active_diagnostics_no_longer_has_trigger_methods():
    driver = make_driver()
    for name in (
        "current_step_test",
        "current_vector_step_test",
        "current_torque_sample_test",
        "position_torque_offset_test",
        "voltage_step_test",
        "resistance_test",
    ):
        assert not hasattr(driver.diagnostics.active, name)
