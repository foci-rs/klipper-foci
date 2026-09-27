"""Tests for the FOCI bounded-actuation diagnostic trigger commands."""

import unittest

from mocks import CommandError, MockGCmd, make_driver

from klipper_foci_diagnostics.active import DiagnosticsActive

ACTIVE_LOGGER = "klipper_foci.diagnostics.active"


def _torque_terminal(
    oid,
    status=0,
    kind=0,
    report_seq=1,
    target=500,
    flux_target=-125,
    sample_delay_ms=5,
    voltage_limit=29000,
):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "kind": kind,
        "status": status,
        "target": target,
        "flux_target": flux_target,
        "sample_delay_ms": sample_delay_ms,
        "voltage_limit": voltage_limit,
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


def _voltage_terminal(oid, status=0, report_seq=1, uq_ext=512, ud_ext=-256, sample_delay_ms=2):
    return {
        "oid": oid,
        "report_seq": report_seq,
        "status": status,
        "uq_ext": uq_ext,
        "ud_ext": ud_ext,
        "sample_delay_ms": sample_delay_ms,
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


class TestCurrentStepDiagnosticCommand(unittest.TestCase):
    def test_sends_bounded_current_step_defaults(self):
        d = make_driver()
        active = DiagnosticsActive(d)

        gcmd = MockGCmd({"TARGET": 250})
        active.current_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.current_step_test.last_args, [d.oid, 0, 250, 80, 12000]
        )
        self.assertIn("axis=torque", gcmd.last_info)
        self.assertIn("target=250", gcmd.last_info)

    def test_sends_explicit_current_step_parameters(self):
        d = make_driver()
        active = DiagnosticsActive(d)

        active.current_step_test(
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
        active = DiagnosticsActive(d)

        with self.assertRaises(CommandError):
            active.current_step_test(MockGCmd({"AXIS": "position", "TARGET": 250}))

    def test_current_step_trigger_leaves_active_diagnostics_state_untouched(self):
        d = make_driver()
        before = dict(vars(d.diagnostics.active))
        active = DiagnosticsActive(d)

        active.current_step_test(MockGCmd({"AXIS": "flux", "TARGET": 250}))

        self.assertEqual(vars(d.diagnostics.active), before)

    def test_sends_flux_axis_current_vector_step(self):
        d = make_driver()
        active = DiagnosticsActive(d)

        active.current_vector_step_test(
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

    def test_sends_torque_sample_step_with_long_diagnostic_delay(self):
        d = make_driver()
        active = DiagnosticsActive(d)

        active.current_torque_sample_test(
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

    def test_sends_position_torque_offset_sample(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"TARGET": 500, "SAMPLE_DELAY_MS": 2, "VOLTAGE_LIMIT": 29000})

        active.position_torque_offset_test(gcmd)

        self.assertEqual(
            d.protocol.commands.position_torque_offset_sample_test.last_args,
            [d.oid, 500, 2, 29000],
        )
        self.assertIn("position-torque-offset", gcmd.last_info)

    def test_sends_voltage_step_sample(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"UQ": 512, "UD": -256, "SAMPLE_DELAY_MS": 2})

        active.voltage_step_test(gcmd)

        self.assertEqual(
            d.protocol.commands.voltage_step_test.last_args,
            [d.oid, 512, -256, 2],
        )
        self.assertIn("voltage-step", gcmd.last_info)

    def test_torque_sample_triggers_leave_active_diagnostics_state_untouched(self):
        d = make_driver()
        before = dict(vars(d.diagnostics.active))
        active = DiagnosticsActive(d)

        active.current_torque_sample_test(MockGCmd({"TARGET": 500}))
        active.position_torque_offset_test(MockGCmd({"TARGET": 500}))

        self.assertEqual(vars(d.diagnostics.active), before)


class TestResistanceTestDiagnosticCommand(unittest.TestCase):
    def test_sends_resistance_test_request(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({})

        active.resistance_test(gcmd)

        self.assertEqual(d.protocol.commands.resistance_test.last_args, [d.oid, 0])
        self.assertIn("resistance-test", gcmd.last_info)


class TestFullDiagnosticChains(unittest.TestCase):
    """Trigger -> protocol send -> simulated firmware reply -> core-resident
    handle_* callback -> formatted gcode output, for each of the six moved
    trigger commands. This confirms the split leaves the wiring between the
    relocated trigger and the still-core-resident reply handler intact."""

    def test_current_step_full_chain(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"AXIS": "flux", "TARGET": 250})

        active.current_step_test(gcmd)

        self.assertIn("axis=flux", gcmd.last_info)
        self.assertIn("target=250", gcmd.last_info)
        # Derive the reply's correlating fields from what the trigger
        # actually sent, not a literal that happens to match today -- a
        # broken axis/target pass-through must fail this test.
        _oid, axis, target, _duration_ms, _voltage_limit = (
            d.protocol.commands.current_step_test.last_args
        )
        d.diagnostics.active.handle_current_step_result(
            {
                "status": 0,
                "axis": axis,
                "target": target,
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
        self.assertIn("axis=flux", out)
        self.assertIn("target=250", out)
        self.assertIn("enc_delta=12", out)

    def test_current_vector_step_full_chain(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"TORQUE_TARGET": 17, "FLUX_TARGET": 250})

        active.current_vector_step_test(gcmd)

        self.assertIn("torque_target=17", gcmd.last_info)
        self.assertIn("flux_target=250", gcmd.last_info)
        _oid, torque_target, flux_target, _duration_ms, _voltage_limit = (
            d.protocol.commands.current_vector_step_test.last_args
        )
        d.diagnostics.active.handle_current_vector_step_result(
            {
                "status": 0,
                "torque_target": torque_target,
                "flux_target": flux_target,
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
        self.assertIn(f"torque_target={torque_target}", out)
        self.assertIn(f"flux_target={flux_target}", out)

    def test_current_torque_sample_full_chain(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"TARGET": 500, "FLUX_TARGET": -125, "SAMPLE_DELAY_MS": 5})

        active.current_torque_sample_test(gcmd)

        self.assertIn("target=500", gcmd.last_info)
        self.assertIn("flux_target=-125", gcmd.last_info)
        self.assertIn("sample_delay_ms=5", gcmd.last_info)
        _oid, target, flux_target, sample_delay_ms, voltage_limit = (
            d.protocol.commands.current_torque_sample_test.last_args
        )
        d.diagnostics.active.handle_current_torque_sample_pid_result(_torque_pid(d.oid, 12345))
        d.diagnostics.active.handle_current_torque_sample_detail_result(
            _torque_detail(d.oid, encoder_sample=3902)
        )
        d.diagnostics.active.handle_current_torque_sample_result(
            _torque_terminal(
                d.oid,
                kind=0,
                target=target,
                flux_target=flux_target,
                sample_delay_ms=sample_delay_ms,
                voltage_limit=voltage_limit,
            )
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("current torque sample", out)
        self.assertIn(f"target={target}", out)
        self.assertIn(f"flux_target={flux_target}", out)
        self.assertIn(f"sample_delay_ms={sample_delay_ms}", out)
        self.assertIn("torque_error_sum=12345", out)
        self.assertIn("enc_sample=3902", out)

    def test_position_torque_offset_full_chain(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"TARGET": 500, "SAMPLE_DELAY_MS": 2})

        active.position_torque_offset_test(gcmd)

        self.assertIn("target=500", gcmd.last_info)
        self.assertIn("sample_delay_ms=2", gcmd.last_info)
        _oid, target, sample_delay_ms, voltage_limit = (
            d.protocol.commands.position_torque_offset_sample_test.last_args
        )
        d.diagnostics.active.handle_current_torque_sample_pid_result(_torque_pid(d.oid, 6789))
        d.diagnostics.active.handle_current_torque_sample_detail_result(
            _torque_detail(d.oid, encoder_sample=4001)
        )
        d.diagnostics.active.handle_current_torque_sample_result(
            _torque_terminal(
                d.oid,
                kind=1,
                target=target,
                sample_delay_ms=sample_delay_ms,
                voltage_limit=voltage_limit,
            )
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("position torque offset sample", out)
        self.assertIn(f"target={target}", out)
        self.assertIn(f"sample_delay_ms={sample_delay_ms}", out)
        self.assertIn("torque_error_sum=6789", out)
        self.assertIn("enc_sample=4001", out)

    def test_voltage_step_full_chain(self):
        d = make_driver()
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"UQ": 512, "UD": -256, "SAMPLE_DELAY_MS": 2})

        active.voltage_step_test(gcmd)

        self.assertIn("uq_ext=512", gcmd.last_info)
        self.assertIn("ud_ext=-256", gcmd.last_info)
        _oid, uq_ext, ud_ext, sample_delay_ms = d.protocol.commands.voltage_step_test.last_args
        d.diagnostics.active.handle_voltage_step_detail_result(
            _voltage_detail(d.oid, encoder_sample=4001)
        )
        d.diagnostics.active.handle_voltage_step_result(
            _voltage_terminal(
                d.oid,
                uq_ext=uq_ext,
                ud_ext=ud_ext,
                sample_delay_ms=sample_delay_ms,
            )
        )

        out = d.printer.lookup_object("gcode")._responses[-1]
        self.assertIn("voltage step", out)
        self.assertIn(f"uq_ext={uq_ext}", out)
        self.assertIn(f"ud_ext={ud_ext}", out)
        self.assertIn("enc_sample=4001", out)

    def test_resistance_test_full_chain(self):
        d = make_driver()
        d.global_config.debug = True
        active = DiagnosticsActive(d)
        gcmd = MockGCmd({"DETAIL": 1})

        active.resistance_test(gcmd)

        self.assertIn("resistance-test", gcmd.last_info)
        self.assertIn("detail=1", gcmd.last_info)
        oid, _detail = d.protocol.commands.resistance_test.last_args

        with self.assertLogs(ACTIVE_LOGGER, level="INFO") as log_ctx:
            d.diagnostics.active.handle_resistance_run(
                {
                    "oid": oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "warning_flags": 0,
                    "status_flags_or": 0,
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

        out = log_ctx.records[-1].message
        self.assertIn("resistance run:", out)
        self.assertIn("selected_r_count_slope_milli=1042", out)
