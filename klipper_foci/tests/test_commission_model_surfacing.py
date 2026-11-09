"""Tests for surfacing the commissioning model to the operator."""

import unittest

from tests.mocks import (
    MockConfigFile,
    MockGCmd,
    complete_commission_result,
    make_driver,
)


class CommissionModelSurfacingTests(unittest.TestCase):
    def test_persists_count_space_electrical_model_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile

        driver.commissioning.persist_commission_results(complete_commission_result(), "balanced")

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_milli")],
            "1706",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_theta_source")],
            "1",
        )
        self.assertNotIn((driver.name, "identified_r_mohm"), configfile.values)
        self.assertNotIn((driver.name, "identified_l_uh"), configfile.values)
        self.assertNotIn((driver.name, "identified_r_int"), configfile.values)
        self.assertNotIn((driver.name, "identified_l_int"), configfile.values)

    def test_commission_success_message_includes_count_space_model(self):
        driver = make_driver()
        driver.global_config.debug = True
        result = complete_commission_result()
        result["bandwidth_hz"] = 800
        result["current_candidate_attempt"] = 1
        driver.printer._objects["configfile"] = MockConfigFile()

        class CompleteCommissionCommand:
            def send(self, _args):
                driver.commissioning.result = result
                driver.commissioning.done = True

        driver.protocol.commands.commission = CompleteCommissionCommand()
        gcmd = MockGCmd({"PROFILE": "balanced"})

        with self.assertLogs("klipper_foci.commissioning", level="INFO") as log_ctx:
            driver.commissioning.commission(gcmd)

        self.assertTrue(
            any("r_count_milli=1706 l_count_micro=1245" in message for message in log_ctx.output)
        )
        self.assertTrue(any("bandwidth_hz=800" in message for message in log_ctx.output))
        self.assertTrue(any("current_candidate_attempt=1" in message for message in log_ctx.output))

    def test_commission_success_message_includes_theta_and_its_source(self):
        for source, token in ((0, "measured"), (1, "config"), (None, "config")):
            driver = make_driver()
            driver.global_config.debug = True
            result = complete_commission_result()
            result["theta_e_us"] = 92
            if source is None:
                result.pop("theta_source", None)
            else:
                result["theta_source"] = source
            driver.printer._objects["configfile"] = MockConfigFile()

            class CompleteCommissionCommand:
                def send(self, _args, driver=driver, result=result):
                    driver.commissioning.result = result
                    driver.commissioning.done = True

            driver.protocol.commands.commission = CompleteCommissionCommand()
            gcmd = MockGCmd({"PROFILE": "balanced"})
            with self.assertLogs("klipper_foci.commissioning", level="INFO") as log_ctx:
                driver.commissioning.commission(gcmd)
            self.assertTrue(
                any(f"theta_e_us=92 theta_src={token}" in message for message in log_ctx.output),
                (source, log_ctx.output),
            )

    def test_commission_success_active_gains_use_applied_filter_evidence(
        self,
    ):
        driver = make_driver()
        result = complete_commission_result()
        result["bandwidth_hz"] = 1600
        result["current_torque_filter_hz"] = 3000
        result["current_flux_filter_hz"] = 3000
        driver.printer._objects["configfile"] = MockConfigFile()

        class CompleteCommissionCommand:
            def send(self, _args):
                driver.commissioning.result = result
                driver.commissioning.done = True

        driver.protocol.commands.commission = CompleteCommissionCommand()

        driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

        self.assertEqual(driver.state.active_gains["velocity_filter_hz"], 0)
        self.assertEqual(driver.state.active_gains["torque_filter_hz"], 3000)
        self.assertEqual(driver.state.active_gains["position_filter_hz"], 0)
        self.assertEqual(driver.state.active_gains["flux_filter_hz"], 3000)

    def test_commission_result_derives_tau_and_fallbacks(self):
        """Fields the firmware no longer sends are derived, not read verbatim.

        ``tau_e_us`` is derived from the electrical-model counts; the
        fallback position integrator is always 0; the fallback velocity
        limit comes from the configured PID velocity limit, not the wire
        reply. ``theta_e_us``/``bandwidth_hz`` still pass straight through.
        """
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()
        result["l_count_micro"] = 1234567
        result["r_count_milli"] = 2500
        result["theta_e_us"] = 160
        result["bandwidth_hz"] = 1600

        driver.commissioning.persist_commission_results(result, "balanced")

        self.assertEqual(
            configfile.values[(driver.name, "identified_tau_e_us")],
            str(1234567 * 1000 // 2500),
        )
        self.assertEqual(configfile.values[(driver.name, "pid_position_i")], "0")
        self.assertEqual(
            configfile.values[(driver.name, "pid_velocity_limit")],
            str(int(driver.settings.pid_velocity_limit)),
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_theta_e_us")],
            "160",
        )
        self.assertEqual(
            configfile.values[(driver.name, "identified_bandwidth_hz")],
            "1600",
        )
        self.assertNotIn((driver.name, "identified_ringing_count"), configfile.values)

    def test_commission_persists_resistance_count_space_fields(self):
        driver = make_driver()
        configfile = MockConfigFile()
        driver.printer._objects["configfile"] = configfile
        result = complete_commission_result()
        result.update(
            {
                "resistance_selected_count_slope_milli": 1042,
            }
        )

        driver.commissioning.persist_commission_results(result, "balanced")

        self.assertEqual(
            configfile.values[(driver.name, "identified_r_count_slope_milli")],
            "1042",
        )
        self.assertNotIn((driver.name, "identified_r_power_stage_tripped"), configfile.values)
