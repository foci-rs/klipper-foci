import pytest

from tests.mocks import CommandError, make_config_driver, make_config_printer, make_driver


def test_driver_registers_virtual_endstop_chip():
    driver = make_driver(stepper_name="stepper_x")
    pins = driver.printer.lookup_object("pins")
    assert "foci_stepper_x" in pins.registered_chips


def test_virtual_endstop_resolves_to_channel_stall_pin():
    driver = make_driver(stepper_name="stepper_x")
    pins = driver.printer.lookup_object("pins")
    chip = pins.registered_chips["foci_stepper_x"]
    endstop = chip.setup_pin("endstop", {"pin": "virtual_endstop"})
    assert endstop.pin_desc == f"{driver.mcu.get_name()}:STALL{driver.channel}"
    assert pins.setup_calls == [("endstop", endstop.pin_desc)]


def test_virtual_endstop_rejects_non_endstop_use_and_zero_homing_current():
    driver = make_driver(stepper_name="stepper_x")
    chip = driver.printer.lookup_object("pins").registered_chips["foci_stepper_x"]
    with pytest.raises(CommandError):
        chip.setup_pin("digital_out", {"pin": "virtual_endstop"})
    with pytest.raises(CommandError):
        chip.setup_pin("endstop", {"pin": "something_else"})
    driver.config.homing_current = 0.0
    with pytest.raises(CommandError):
        chip.setup_pin("endstop", {"pin": "virtual_endstop"})


def test_virtual_endstop_rejects_omitted_homing_current():
    """Integration path: an omitted homing_current parses to 0.0 and is
    still caught by the virtual-endstop guard, not just an explicitly
    mutated field."""
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "rotation_distance": 40.0}}
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    chip = driver.printer.lookup_object("pins").registered_chips["foci_stepper_x"]
    with pytest.raises(CommandError):
        chip.setup_pin("endstop", {"pin": "virtual_endstop"})
