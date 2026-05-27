"""FOCI host G-code command registry and global mode config."""

from __future__ import annotations

MODE_LEVELS: dict[str, int] = {
    "default": 0,
    "advanced": 1,
    "expert": 2,
    "developer": 3,
}

MODE_CHOICES: dict[str, str] = {mode: mode for mode in MODE_LEVELS}


class FociGlobalConfig:
    """Global `[foci]` host-module configuration."""

    def __init__(self, config) -> None:
        self.mode: str = config.getchoice("mode", MODE_CHOICES, default="default")
