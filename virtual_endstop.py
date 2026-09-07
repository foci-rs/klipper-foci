"""Klipper pin chip exposing the firmware stall latch as a virtual endstop.

Registers a per-driver ``foci_<stepper_name>`` pin chip so printer configs
can write ``endstop_pin: foci_<stepper_name>:virtual_endstop`` and have it
resolve to the board's real ``STALL<channel>`` MCU pin.
"""

from __future__ import annotations


class FociVirtualEndstop:
    def __init__(self, driver) -> None:
        self.driver = driver
        ppins = driver.printer.lookup_object("pins")
        ppins.register_chip(f"foci_{driver.stepper_name}", self)

    def setup_pin(self, pin_type, pin_params):
        ppins = self.driver.printer.lookup_object("pins")
        if pin_type != "endstop" or pin_params["pin"] != "virtual_endstop":
            raise ppins.error("foci virtual endstop only useful as endstop pin")
        if self.driver.config.homing_current <= 0.0:
            raise ppins.error(
                f"[foci {self.driver.stepper_name}] homing_current must be above 0 "
                "to use virtual_endstop"
            )
        stall_pin = f"{self.driver.mcu.get_name()}:STALL{self.driver.channel}"
        return ppins.setup_pin("endstop", stall_pin)
