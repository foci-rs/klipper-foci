"""Tests for FociGlobalConfig."""

import types

import pytest

from klipper_foci.registry import (
    GCODE_COMMANDS,
    FociGlobalConfig,
    GcodeCommandSpec,
    discover_optional_specs,
)


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


class _FakeEntryPoint:
    """Stand-in for one importlib.metadata.EntryPoint."""

    def __init__(self, name, register_fn):
        self.name = name
        self._register_fn = register_fn

    def load(self):
        return self._register_fn


def _fake_entry_points_factory(specs_by_name):
    def _entry_points(*, group):
        assert group == "klipper_foci.commands"
        return [_FakeEntryPoint(name, fn) for name, fn in specs_by_name.items()]

    return _entry_points


def test_discover_optional_specs_calls_every_register_and_concatenates(monkeypatch):
    # A bare `object()` has no `__dict__`, and `discover_optional_specs`
    # calls `vars(driver)` -- use something that actually has one.
    seen_driver = types.SimpleNamespace()
    fake_spec = GcodeCommandSpec("FOCI_FAKE_TEST", "fake_component", "fake_handler", "test")

    def fake_register(driver):
        assert driver is seen_driver
        return (fake_spec,)

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        _fake_entry_points_factory({"fake": fake_register}),
    )
    result = discover_optional_specs(seen_driver)
    assert result == (fake_spec,)


def test_discover_optional_specs_returns_empty_with_no_entry_points(monkeypatch):
    # A bare `object()` has no `__dict__`, and `discover_optional_specs` now
    # calls `vars(driver)` unconditionally to seed `claimed_by` -- use
    # something that actually has one.
    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        _fake_entry_points_factory({}),
    )
    assert discover_optional_specs(types.SimpleNamespace()) == ()


class _FakePrinter:
    """Minimal stand-in providing the `config_error` FociDriver.printer needs."""

    def config_error(self, msg):
        return ValueError(msg)


def test_discover_optional_specs_rejects_entry_point_overwriting_core_attribute(monkeypatch):
    # `FociDriver.__init__` sets attributes like `controls` before calling
    # `discover_optional_specs` -- an entry point reassigning one of those
    # must be treated as a collision with "core", not as its own first claim.
    def register_overwrite(driver):
        driver.controls = object()
        return ()

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        _fake_entry_points_factory({"overwrite": register_overwrite}),
    )
    seen_driver = types.SimpleNamespace(printer=_FakePrinter(), controls=object())

    with pytest.raises(ValueError, match="controls"):
        discover_optional_specs(seen_driver)


def test_discover_optional_specs_self_clear_reassign_is_not_a_false_collision(monkeypatch):
    # Clearing and reassigning the same attribute within one entry point's own
    # `register()` call must not be mistaken for a collision against itself.
    def register_first(driver):
        driver.shared = object()
        del driver.shared
        driver.shared = object()
        return ()

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        _fake_entry_points_factory({"first": register_first}),
    )
    seen_driver = types.SimpleNamespace()

    assert discover_optional_specs(seen_driver) == ()
    assert hasattr(seen_driver, "shared")


def test_discover_optional_specs_detects_collision_through_clear_and_reassign(monkeypatch):
    # A second entry point clearing and reassigning an attribute already
    # claimed by a first entry point must still be caught as a collision --
    # the old `id()`-based snapshot could miss this if CPython reused the
    # freed attribute's address for the new object.
    def register_first(driver):
        driver.shared = object()
        del driver.shared
        driver.shared = object()
        return ()

    def register_second(driver):
        driver.shared = object()
        del driver.shared
        driver.shared = object()
        return ()

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        _fake_entry_points_factory({"first": register_first, "second": register_second}),
    )
    seen_driver = types.SimpleNamespace(printer=_FakePrinter())

    with pytest.raises(ValueError, match="shared"):
        discover_optional_specs(seen_driver)
