"""Entry point: attach TuningWorkflow and return its GcodeCommandSpecs."""

from __future__ import annotations

from klipper_foci.registry import GcodeCommandSpec

from .workflow import TuningWorkflow


def register(driver) -> tuple[GcodeCommandSpec, ...]:
    driver.tuning = TuningWorkflow(driver)
    return ()
