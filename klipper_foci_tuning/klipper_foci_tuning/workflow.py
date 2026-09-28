"""Rare FOCI fine-tuning setters, split out of ControlsWorkflow."""

from __future__ import annotations


class TuningWorkflow:
    """Rare, expert-only FOCI tuning setters."""

    def __init__(self, driver) -> None:
        self.driver = driver
