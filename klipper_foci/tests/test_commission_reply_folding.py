"""Tests for folding commissioning replies into driver state."""

import unittest
from typing import ClassVar

from klipper_foci.commissioning import (
    CommissioningWorkflow,
)
from tests.mocks import (
    CommandError,
    MockConfigFile,
    MockGCmd,
    complete_commission_result,
    make_driver,
)


class CommissionResistanceReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream resistance replies get folded into result.

    W1 made firmware emit foci_resistance_run + two foci_resistance_axis
    replies during FOCI_SETUP, just before foci_commission_done.
    These tests drive that exact reply sequence through the host's
    response handlers and confirm the values end up persisted via
    persist_commission_results, with axis0/axis1 correctly routed by
    electrical_axis (not arrival order).
    """

    def test_commission_replies_are_folded_and_persisted(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_success(_args):
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
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
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 1,
                    "phi_e_ext": 16384,
                    "r_count_slope_milli": 1046,
                    "intercept_count": 27,
                    "rmse_permille": 9,
                    "selected_mask": 0b11110000,
                    "excluded_point_mask": 0b00001111,
                    "selected_count": 4,
                    "signed_count_slope_milli": 1047,
                    "signed_asymmetry_permille": 15,
                    "drift_permille": 6,
                    "warning_flags": 0,
                }
            )
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1038,
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
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_slope_milli")],
            "1042",
        )
        self.assertNotIn((driver.name, "identified_r_power_stage_tripped"), configfile.values)

    def test_commission_with_partial_resistance_cache_persists_nothing(self):
        """A commission that completes with a partial resistance cache.

        W1 firmware emits foci_resistance_run + two foci_resistance_axis
        replies, but if the commission stream completes before axis1
        arrives (e.g. run + axis0 only), the fold must be all-or-nothing:
        no identified_r_* keys get persisted, is_calibrated still becomes
        True (commission itself succeeded), and no exception is raised.
        Before the atomic fix, the presence-gate in
        _persist_resistance_identification only checked for
        resistance_selected_count_slope_milli (populated by the run
        reply alone) and then unconditionally indexed
        resistance_axis1_count_slope_milli and friends, raising KeyError
        on this exact partial-cache shape.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_partial_success(_args):
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
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
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1038,
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
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_partial_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        self.assertTrue(driver.state.is_calibrated)

        resistance_config_keys = {
            config_key for _, config_key in CommissioningWorkflow.RESISTANCE_RESULT_KEYS
        }
        persisted_resistance_keys = [
            key for key in configfile.values if key[1] in resistance_config_keys
        ]
        self.assertEqual(persisted_resistance_keys, [])

        self.assertNotIn(driver.oid, driver.diagnostics.active.resistance_cache)

    def test_standalone_resistance_test_does_not_persist(self):
        """FOCI_RESISTANCE_TEST replies must only display, never persist.

        Folding into the commission result dict happens at commission
        completion only. A standalone diagnostic run (not part of a
        commission) must leave no trace in persisted config.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile

        driver.diagnostics.handle_resistance_run(
            {
                "oid": driver.oid,
                "status": 0,
                "selected_r_count_slope_milli": 1042,
                "gain_path_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
                "peak_abs_current_count": 1200,
                "max_abs_steady_mean_current_count": 900,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 0,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0,
                "dsadc_mdec_readback": 0,
                "pwm_sv_chop_readback": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 0,
                "phi_e_ext": 0,
                "r_count_slope_milli": 1038,
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
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 1,
                "phi_e_ext": 16384,
                "r_count_slope_milli": 1046,
                "intercept_count": 27,
                "rmse_permille": 9,
                "selected_mask": 0b11110000,
                "excluded_point_mask": 0b00001111,
                "selected_count": 4,
                "signed_count_slope_milli": 1047,
                "signed_asymmetry_permille": 15,
                "drift_permille": 6,
                "warning_flags": 0,
            }
        )

        resistance_keys = [key for key in configfile.values if "identified_r_" in key[1]]
        self.assertEqual(resistance_keys, [])

    def test_stale_standalone_cache_does_not_leak_into_later_partial_commission(self):
        """A standalone FOCI_RESISTANCE_TEST must not pre-populate a later
        commission's fold with stale axis data.

        Before the fix, the resistance_cache was only cleared at commission
        exit (success via pop_resistance_cache, failure/timeout via
        clear_resistance_cache), never at commission start. If a standalone
        FOCI_RESISTANCE_TEST left a full run+axis0+axis1 cache entry behind,
        and a later commission then delivered only run+axis0 (axis1 never
        arriving in that commission attempt), handle_resistance_axis would
        overwrite only axis0 in the cache, leaving the stale axis1 from the
        unrelated standalone run still present. pop_resistance_cache's
        all-or-nothing check would then see run+axis0+axis1 all "present"
        (axis1 being stale) and fold/persist a mixed result that blends
        data from two unrelated runs.

        The fix clears the per-oid cache at the start of commission(),
        before the firmware can emit any commission-stream resistance
        replies, so no standalone leftovers can survive into the fold.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        driver.diagnostics.handle_resistance_run(
            {
                "oid": driver.oid,
                "status": 0,
                "selected_r_count_slope_milli": 9999,
                "gain_path_count_slope_milli": 0,
                "warning_flags": 0,
                "status_flags_or": 0,
                "peak_abs_current_count": 1200,
                "max_abs_steady_mean_current_count": 900,
                "current_ceiling_count": 1600,
                "power_stage_tripped": 0,
                "pwm_maxcnt_readback": 3999,
                "bbm_readback": 0,
                "dsadc_mdec_readback": 0,
                "pwm_sv_chop_readback": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 0,
                "phi_e_ext": 0,
                "r_count_slope_milli": 8888,
                "intercept_count": 1,
                "rmse_permille": 1,
                "selected_mask": 0b11111000,
                "excluded_point_mask": 0b00000111,
                "selected_count": 5,
                "signed_count_slope_milli": 8887,
                "signed_asymmetry_permille": 1,
                "drift_permille": 1,
                "warning_flags": 0,
            }
        )
        driver.diagnostics.handle_resistance_axis(
            {
                "oid": driver.oid,
                "electrical_axis": 1,
                "phi_e_ext": 16384,
                "r_count_slope_milli": 7777,
                "intercept_count": 2,
                "rmse_permille": 2,
                "selected_mask": 0b11110000,
                "excluded_point_mask": 0b00001111,
                "selected_count": 4,
                "signed_count_slope_milli": 7778,
                "signed_asymmetry_permille": 2,
                "drift_permille": 2,
                "warning_flags": 0,
            }
        )
        self.assertIn(driver.oid, driver.diagnostics.active.resistance_cache)
        stale_entry = driver.diagnostics.active.resistance_cache[driver.oid]
        self.assertIn("run", stale_entry)
        self.assertIn("axis0", stale_entry)
        self.assertIn("axis1", stale_entry)

        def drive_partial_commission(_args):
            driver.diagnostics.handle_resistance_run(
                {
                    "oid": driver.oid,
                    "status": 0,
                    "selected_r_count_slope_milli": 1042,
                    "gain_path_count_slope_milli": 66752,
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
            driver.diagnostics.handle_resistance_axis(
                {
                    "oid": driver.oid,
                    "electrical_axis": 0,
                    "phi_e_ext": 0,
                    "r_count_slope_milli": 1038,
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
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_partial_commission
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        self.assertTrue(driver.state.is_calibrated)

        resistance_config_keys = {
            config_key for _, config_key in CommissioningWorkflow.RESISTANCE_RESULT_KEYS
        }
        persisted_resistance_keys = [
            key for key in configfile.values if key[1] in resistance_config_keys
        ]
        self.assertEqual(persisted_resistance_keys, [])

        self.assertNotIn(driver.oid, driver.diagnostics.active.resistance_cache)


class CommissionCurrentLoopReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream current-loop replies get folded into result."""

    CURRENT_VALIDATION_SAMPLES = (
        # axis, sample_index, delay_ms, positive, negative, cross, voltage,
        # encoder_abs, encoder_positive, encoder_negative
        (0, 0, 1, 720, 710, 28, 390, 0, 0, 0),
        (0, 1, 2, 960, 940, 35, 420, 0, 0, 0),
        (0, 2, 5, 1010, 1000, 40, 430, 0, 0, 0),
        (0, 3, 100, 1015, 1008, 38, 410, 0, 0, 0),
        (1, 0, 0, 640, 630, 44, 500, 0, 0, 0),
        (1, 1, 1, 610, 590, 42, 510, 2, 2, -1),
        (1, 2, 2, 780, 770, 38, 530, 4, 4, -2),
    )
    CURRENT_LOOP_RUN: ClassVar[dict[str, int]] = {
        "status": 0,
        "gains_source": 1,
        "candidate_gains_source": 1,
        "axis_split_source": 1,
        "candidate_axis_split_source": 1,
        "gains_tier": 2,
        "candidate_gains_tier": 2,
        "measured_axis_split_permille": 1840,
        "candidate_measured_axis_split_permille": 1840,
        "applied_axis_split_permille": 1500,
        "candidate_applied_axis_split_permille": 1500,
        "axis_split_clamped": 1,
        "candidate_axis_split_clamped": 1,
        "candidate_flux_p": 711,
        "candidate_flux_i": 416,
        "candidate_torque_p": 650,
        "candidate_torque_i": 336,
        "candidate_attempt": 1,
        "current_validation_axes": 3,
        "flux_validation_sample_count": 4,
        "torque_validation_sample_count": 3,
        "retry_budget_exhausted": 0,
        "failure_reason": 0,
    }
    EXPECTED_CURRENT_CONFIG: ClassVar[dict[str, str]] = {
        "identified_current_gains_source": "1",
        "identified_current_gains_tier": "2",
        "identified_current_retry_budget_exhausted": "0",
        "identified_current_failure_reason": "0",
    }

    def _emit_current_validation_sample(self, driver, sample) -> None:
        (
            axis,
            sample_index,
            delay_ms,
            positive,
            negative,
            cross,
            voltage,
            encoder,
            positive_encoder,
            negative_encoder,
        ) = sample
        driver.diagnostics.active.handle_current_validation_axis(
            {
                "oid": driver.oid,
                "axis": axis,
                "sample_index": sample_index,
                "status": 0,
                "attempt": 0,
                "target": 250,
                "sample_delay_ms": delay_ms,
                "positive_response_permille": positive,
                "negative_response_permille": negative,
                "cross_axis_permille": cross,
                "voltage_output_permille": voltage,
                "encoder_delta_counts": encoder,
                "positive_encoder_delta_counts": positive_encoder,
                "negative_encoder_delta_counts": negative_encoder,
                "status_flags_or": 0,
            }
        )

    def _emit_current_loop_run(self, driver) -> None:
        driver.diagnostics.active.handle_current_loop_run(
            {"oid": driver.oid, **self.CURRENT_LOOP_RUN}
        )

    def test_commission_replies_are_folded_and_persisted(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_success(_args):
            for sample in self.CURRENT_VALIDATION_SAMPLES:
                self._emit_current_validation_sample(driver, sample)
            self._emit_current_loop_run(driver)
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        for config_key, expected in self.EXPECTED_CURRENT_CONFIG.items():
            self.assertEqual(configfile.values[(driver.name, config_key)], expected)
        last_samples = driver.diagnostics.active.last_current_loop_samples(driver.oid)
        self.assertEqual(last_samples["flux"][0]["gate_role"], "telemetry")
        self.assertEqual(last_samples["flux"][3]["gate_role"], "gate")
        self.assertEqual(last_samples["torque"][0]["gate_role"], "gate")
        self.assertEqual(last_samples["torque"][2]["gate_role"], "telemetry")
        self.assertEqual(last_samples["torque"][2]["positive_encoder_delta_counts"], 4)
        self.assertEqual(last_samples["torque"][2]["negative_encoder_delta_counts"], -2)
        self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)

    def test_partial_current_loop_cache_folds_nothing_and_clears(self):
        driver = make_driver()

        self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[0])
        self._emit_current_loop_run(driver)

        self.assertEqual(driver.diagnostics.active.pop_current_loop_cache(driver.oid), {})
        self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)

    def test_unknown_current_validation_axis_does_not_complete_torque_evidence(self):
        driver = make_driver()
        self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[0])
        self._emit_current_validation_sample(driver, (2, 0, 2, 650, 640, 44, 500, 9, 9, -3))
        self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[3])
        run = {
            **self.CURRENT_LOOP_RUN,
            "flux_validation_sample_count": 1,
            "torque_validation_sample_count": 3,
        }
        driver.diagnostics.active.handle_current_loop_run({"oid": driver.oid, **run})

        self.assertEqual(driver.diagnostics.active.pop_current_loop_cache(driver.oid), {})
        self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)

    def test_zero_current_validation_sample_counts_fold_nothing_and_clear(self):
        for axis_key in ("flux", "torque"):
            with self.subTest(axis_key=axis_key):
                driver = make_driver()
                if axis_key == "flux":
                    self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[3])
                    sample_counts = {
                        "flux_validation_sample_count": 0,
                        "torque_validation_sample_count": 1,
                    }
                else:
                    self._emit_current_validation_sample(driver, self.CURRENT_VALIDATION_SAMPLES[0])
                    sample_counts = {
                        "flux_validation_sample_count": 1,
                        "torque_validation_sample_count": 0,
                    }
                run = {**self.CURRENT_LOOP_RUN, **sample_counts}
                driver.diagnostics.active.handle_current_loop_run({"oid": driver.oid, **run})

                self.assertEqual(driver.diagnostics.active.pop_current_loop_cache(driver.oid), {})
                self.assertNotIn(driver.oid, driver.diagnostics.active.current_loop_cache)


class CommissionInductanceReplyFoldingTests(unittest.TestCase):
    """Verify commission-stream inductance evidence gets folded into result."""

    RUN: ClassVar[dict[str, int]] = {
        "source": 1,
        "status": 0,
        "warning_flags": 0,
        "ud_count": 768,
        "realized_frequency_millihz": 1_000_000,
        "elapsed_us": 8000,
        "openloop_phi_delta_counts": 524_288,
        "sample_count": 104,
        "encoder_delta_counts": 0,
        "status_flags_or": 0,
    }
    FRAME: ClassVar[dict[str, int]] = {
        "id_mean_milli_count": 20_000,
        "iq_mean_milli_count": -84_000,
        "id_rms_milli_count": 5000,
        "iq_rms_milli_count": 21_000,
        "drift_permille": 40,
        "zero_id_mean_milli_count": 100,
        "zero_iq_mean_milli_count": -200,
    }
    ESTIMATE: ClassVar[dict[str, int]] = {
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
    EXPECTED_CONFIG: ClassVar[dict[str, str]] = {
        "identified_l_source": "1",
        "identified_l_reactance_count_ratio_milli": "8600",
        "identified_l_saliency_status": "1",
    }

    def _emit_run(self, driver, params=None) -> None:
        payload = self.RUN if params is None else params
        driver.diagnostics.active.handle_inductance_run({"oid": driver.oid, **payload})

    def _emit_frame(self, driver, params=None) -> None:
        payload = self.FRAME if params is None else params
        driver.diagnostics.active.handle_inductance_frame({"oid": driver.oid, **payload})

    def _emit_estimate(self, driver, params=None) -> None:
        payload = self.ESTIMATE if params is None else params
        driver.diagnostics.active.handle_inductance_estimate({"oid": driver.oid, **payload})

    def test_complete_replies_are_folded_and_persisted(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_success(_args):
            self._emit_frame(driver)
            self._emit_run(driver)
            self._emit_estimate(driver)
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        for config_key, expected in self.EXPECTED_CONFIG.items():
            self.assertEqual(configfile.values[(driver.name, config_key)], expected)
        last_evidence = driver.diagnostics.active.last_inductance_evidence(driver.oid)
        self.assertEqual(last_evidence["run"]["realized_frequency_millihz"], 1_000_000)
        self.assertEqual(last_evidence["frame"]["iq_mean_milli_count"], -84_000)
        self.assertEqual(last_evidence["estimate"]["x_average_count_ratio_milli"], 8600)
        self.assertNotIn(driver.oid, driver.diagnostics.active.inductance_cache)

    def test_partial_cache_folds_nothing_and_clears(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()

        def drive_partial_success(_args):
            self._emit_run(driver)
            self._emit_frame(driver)
            driver.commissioning.result = result
            driver.commissioning.done = True

        driver.protocol.commands.commission.send = drive_partial_success
        gcmd = MockGCmd({"PROFILE": "balanced"})

        driver.commissioning.commission(gcmd)

        inductance_keys = {
            config_key for _, config_key in CommissioningWorkflow.INDUCTANCE_RESULT_KEYS
        }
        persisted_inductance_keys = [key for key in configfile.values if key[1] in inductance_keys]
        self.assertEqual(persisted_inductance_keys, [])
        self.assertNotIn(driver.oid, driver.diagnostics.active.inductance_cache)

    def test_failed_and_timeout_commission_clear_inductance_cache(self):
        def drive_failure(driver):
            self._emit_run(driver)
            driver.commissioning.error_code = 19

        for label, sender in (("failure", drive_failure), ("timeout", None)):
            with self.subTest(label=label):
                driver = make_driver()
                driver.diagnostics.active.inductance_cache[driver.oid] = {
                    "run": dict(self.RUN),
                    "frame": dict(self.FRAME),
                    "estimate": dict(self.ESTIMATE),
                }
                if sender is not None:
                    driver.protocol.commands.commission.send = (
                        lambda _args, sender=sender, driver=driver: sender(driver)
                    )

                with self.assertRaises(CommandError):
                    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

                self.assertNotIn(driver.oid, driver.diagnostics.active.inductance_cache)
