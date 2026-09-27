"""Tests for FociGlobalConfig."""

from klipper_foci.registry import FociGlobalConfig


class FakeConfigfileGetters:
    """Minimal stand-in for Klipper's ConfigWrapper get*/getchoice methods."""

    def __init__(self, values=None):
        self._values = values or {}

    def getchoice(self, key, choices, default=None):
        return self._values.get(key, default)

    def getboolean(self, key, default=None):
        return self._values.get(key, default)


def test_debug_defaults_to_false():
    config = FociGlobalConfig(FakeConfigfileGetters())
    assert config.debug is False


def test_debug_can_be_enabled():
    config = FociGlobalConfig(FakeConfigfileGetters({"debug": True}))
    assert config.debug is True


def test_debug_is_independent_of_mode():
    config = FociGlobalConfig(FakeConfigfileGetters({"mode": "developer"}))
    assert config.debug is False
