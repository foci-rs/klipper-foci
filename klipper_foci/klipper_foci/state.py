"""Shared runtime state for one FOCI driver instance."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

CalibrationResponse = Mapping[str, int]
RuntimeStatus = Literal[
    "uncommissioned",
    "commissioned",
    "tuned",
]


class CalibrationCompletion(Protocol):
    """Minimal protocol used by Klipper reactor completion objects."""

    def complete(self, result: CalibrationResponse) -> None:
        """Complete the wait with a firmware calibration response."""
        ...

    def wait(self, deadline: float) -> CalibrationResponse | None:
        """Wait until `deadline` and return the response or `None`."""
        ...


@dataclass
class FociRuntimeState:
    """Mutable runtime state shared by FOCI workflows for one stepper."""

    is_calibrated: bool = False
    inhibited: bool = False
    last_commission_failure: str | None = None
    commissioned_result: dict[str, int] | None = None
    active_gains: dict[str, int | None] | None = None
    pre_tune_snapshot: dict | None = None
    adc_vm_offset_raw: int | None = None
    runtime_status: RuntimeStatus = "uncommissioned"
    operation_lock: bool = False
    active_label: str | None = None
    calibration_completion: CalibrationCompletion | None = None

    def try_acquire(self, label: str) -> bool:
        """Try to acquire the per-driver operation lock under `label`."""
        if self.operation_lock:
            return False
        self.operation_lock = True
        self.active_label = label
        return True

    def release(self) -> None:
        """Release the per-driver operation lock."""
        self.operation_lock = False
        self.active_label = None
