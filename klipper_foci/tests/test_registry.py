"""Tests for FociGlobalConfig."""

from klipper_foci.registry import GCODE_COMMANDS, FociGlobalConfig


class FakeConfigfileGetters:
    """Minimal stand-in for Klipper's ConfigWrapper get*/getchoice methods."""

    def __init__(self, values=None):
        self._values = values or {}

    def get(self, key, default=None):
        return self._values.get(key, default)

    def getchoice(self, key, choices, default=None):
        return self._values.get(key, default)

    def getboolean(self, key, default=None):
        return self._values.get(key, default)

    def error(self, msg):
        return ValueError(msg)


def test_debug_defaults_to_false():
    config = FociGlobalConfig(FakeConfigfileGetters())
    assert config.debug is False


def test_debug_can_be_enabled():
    config = FociGlobalConfig(FakeConfigfileGetters({"debug": True}))
    assert config.debug is True


def test_no_mode_attribute_when_mode_key_absent():
    config = FociGlobalConfig(FakeConfigfileGetters({}))
    assert not hasattr(config, "mode")


def test_no_raw_register_commands_in_gcode_commands():
    names = {spec.name for spec in GCODE_COMMANDS}
    assert "FOCI_TMC_READ_REGISTER" not in names
    assert "FOCI_TMC_WRITE_REGISTER" not in names


def test_dev_gcode_commands_tuple_is_gone():
    import klipper_foci.registry as registry_module

    assert not hasattr(registry_module, "DEV_GCODE_COMMANDS")
