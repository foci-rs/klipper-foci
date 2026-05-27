"""Tests for the klipper-foci host-to-firmware protocol boundary."""

from __future__ import annotations

import pytest

from klipper_foci.protocol import FociProtocol

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockCommand,
    MockMCU,
    make_driver,
)


def response_names(mcu):
    return [(name, oid) for _callback, name, oid in mcu._serial.responses]


def test_bind_mcu_looks_up_commands_and_registers_responses():
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    commands = driver.protocol.commands
    assert commands.set_current is not None
    assert commands.set_encoder is not None
    assert commands.calibrate is not None
    assert commands.commission is not None
    assert commands.tune is not None
    assert commands.selftest is not None
    assert commands.dump_registers is not None
    assert commands.trace_fetch is not None
    assert commands.stepper_perf_stats is not None
    assert commands.current_step_test is not None

    assert (
        "stepper_get_position oid=%c",
        "stepper_position oid=%c pos=%i",
        driver.oid,
    ) in mcu.query_cmds
    assert (
        "foci_stepper_perf_stats oid=%c clear=%c",
        commands.STEPPER_PERF_STATS_RESPONSE,
        driver.oid,
    ) in mcu.query_cmds

    registrations = response_names(mcu)
    assert ("foci_dump_value", driver.oid) in registrations
    assert ("foci_dump_done", driver.oid) in registrations
    assert ("foci_calibrate_result", driver.oid) in registrations
    assert ("foci_commission_phase", driver.oid) in registrations
    assert ("foci_commission_result", driver.oid) in registrations
    assert ("foci_tune_result", driver.oid) in registrations
    assert ("foci_selftest_result", driver.oid) in registrations
    assert ("foci_selftest_done", driver.oid) in registrations
    assert ("foci_trace_info_result", driver.oid) in registrations
    assert ("foci_stepper_event", None) in registrations
    assert ("foci_stepper_perf_event", None) in registrations


def test_bind_mcu_keeps_dev_register_read_optional():
    class NoRegisterReadMCU(MockMCU):
        def lookup_query_command(self, send_fmt, recv_fmt, oid=None):
            if send_fmt == "tmc_read_register oid=%c addr=%c":
                raise CommandError("missing tmc_read_register")
            return super().lookup_query_command(send_fmt, recv_fmt, oid=oid)

    driver = make_driver()
    mcu = NoRegisterReadMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    assert driver.protocol.commands.read_register is None
    assert driver.protocol.commands.set_current is not None
    with pytest.raises(
        CommandError, match="Raw register access requires dev firmware build"
    ):
        driver.protocol.read_register(0x6C)


def test_read_register_returns_value_from_optional_query():
    driver = make_driver()
    driver.protocol = FociProtocol(driver)
    driver.protocol.bind_mcu(MockMCU(), driver.oid)
    driver.protocol.commands.read_register = MockCommand({"value": 0x12345678})

    assert driver.protocol.read_register(0x6C) == 0x12345678
    assert driver.protocol.commands.read_register.last_args == [driver.oid, 0x6C]


def test_driver_mcu_identify_binds_protocol_and_keeps_temporary_aliases():
    driver = make_driver(
        stepper_name="stepper_x",
        kinematics=MockCartesianKinematics([["stepper_x"]]),
    )
    driver.mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver._handle_mcu_identify()

    assert driver.protocol.commands.set_current is not None
    assert driver.protocol.commands.set_current is driver.set_current_cmd
    assert driver.protocol.commands.calibrate is driver.calibrate_cmd
    assert ("foci_calibrate_result", driver.oid) in response_names(driver.mcu)
