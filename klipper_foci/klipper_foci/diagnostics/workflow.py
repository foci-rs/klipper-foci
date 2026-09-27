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
