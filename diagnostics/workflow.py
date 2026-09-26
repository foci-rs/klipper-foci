"""Diagnostic FOCI host workflow facade."""

from __future__ import annotations

from .active import ActiveDiagnostics
from .passive import PassiveDiagnostics


class DiagnosticsWorkflow:
    """Route passive and active FOCI diagnostic commands and responses."""

    def __init__(self, driver) -> None:
        self.driver = driver
        self.passive = PassiveDiagnostics(driver)
        self.active = ActiveDiagnostics(driver)

    def handle_current_step_result(self, params: dict) -> None:
        return self.active.handle_current_step_result(params)

    def handle_current_vector_step_result(self, params: dict) -> None:
        return self.active.handle_current_vector_step_result(params)

    def handle_current_torque_sample_result(self, params: dict) -> None:
        return self.active.handle_current_torque_sample_result(params)

    def handle_current_torque_sample_pid_result(self, params: dict) -> None:
        return self.active.handle_current_torque_sample_pid_result(params)

    def handle_current_torque_sample_detail_result(self, params: dict) -> None:
        return self.active.handle_current_torque_sample_detail_result(params)

    def handle_voltage_step_detail_result(self, params: dict) -> None:
        return self.active.handle_voltage_step_detail_result(params)

    def handle_voltage_step_result(self, params: dict) -> None:
        return self.active.handle_voltage_step_result(params)

    def handle_resistance_profile(self, params: dict) -> None:
        return self.active.handle_resistance_profile(params)

    def handle_resistance_run(self, params: dict) -> None:
        return self.active.handle_resistance_run(params)

    def handle_resistance_axis(self, params: dict) -> None:
        return self.active.handle_resistance_axis(params)

    def pop_resistance_cache(self, oid: int) -> dict:
        return self.active.pop_resistance_cache(oid)

    def clear_resistance_cache(self, oid: int) -> dict:
        return self.active.clear_resistance_cache(oid)

    def handle_stepper_event(self, params: dict) -> None:
        return self.passive.handle_stepper_event(params)

    def step_position(self, gcmd) -> None:
        return self.passive.step_position(gcmd)

    def stepper_stats(self, gcmd) -> None:
        return self.passive.stepper_stats(gcmd)

    def stack_watermark(self, gcmd) -> None:
        return self.passive.stack_watermark(gcmd)

    def tmc_read_register(self, gcmd) -> None:
        return self.passive.tmc_read_register(gcmd)

    def current_step_test(self, gcmd) -> None:
        return self.active.current_step_test(gcmd)

    def current_vector_step_test(self, gcmd) -> None:
        return self.active.current_vector_step_test(gcmd)

    def current_torque_sample_test(self, gcmd) -> None:
        return self.active.current_torque_sample_test(gcmd)

    def position_torque_offset_test(self, gcmd) -> None:
        return self.active.position_torque_offset_test(gcmd)

    def voltage_step_test(self, gcmd) -> None:
        return self.active.voltage_step_test(gcmd)

    def resistance_test(self, gcmd) -> None:
        return self.active.resistance_test(gcmd)
