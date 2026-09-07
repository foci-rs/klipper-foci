"""Tests for the klipper-foci host-to-firmware protocol boundary."""

from __future__ import annotations

import pytest
from klipper_foci.protocol import FociProtocol
from klipper_foci.protocol.bindings import (
    MOTION_SCALE_REJECTION_NAMES,
    register_active_diagnostic_responses,
    register_commissioning_responses,
    register_last_boot_diagnostic_response,
)

from tests.mocks import (
    CommandError,
    MockCartesianKinematics,
    MockCommand,
    MockMCU,
    MockSerial,
    make_driver,
)


def response_names(mcu):
    serial = getattr(mcu, "_serial", mcu)
    return [(name, oid) for _callback, name, oid in serial.responses]


def response_callback(mcu, name):
    serial = getattr(mcu, "_serial", mcu)
    return next(
        callback for callback, response_name, _oid in serial.responses if response_name == name
    )


def test_bind_mcu_looks_up_commands_and_registers_responses():
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    commands = driver.protocol.commands
    assert commands.set_current is not None
    assert commands.set_motion_scale is not None
    assert commands.calibrate is not None
    assert commands.commission is not None
    assert commands.tune is not None
    assert commands.selftest is not None
    assert commands.dump_registers is not None
    assert commands.stepper_perf_stats is not None
    assert commands.stack_watermark is not None
    assert commands.query_adc_vm_offset is not None
    assert commands.current_step_test is not None
    assert commands.velocity_limit_latch_test is not None

    assert (
        "stepper_get_position oid=%c",
        "stepper_position oid=%c pos=%i",
        driver.oid,
    ) in mcu.query_commands
    assert (
        "foci_stepper_perf_stats oid=%c clear=%c",
        commands.STEPPER_PERF_STATS_RESPONSE,
        driver.oid,
    ) in mcu.query_commands
    assert (
        "foci_adc_vm_offset oid=%c",
        "foci_adc_vm_offset_result oid=%c offset_raw=%hu sample_count=%c status=%c",
        driver.oid,
    ) in mcu.query_commands

    registrations = response_names(mcu)
    assert ("foci_dump_value", driver.oid) in registrations
    assert ("foci_dump_done", driver.oid) in registrations
    assert ("foci_calibrate_result", driver.oid) in registrations
    assert ("foci_commission_phase", driver.oid) in registrations
    assert ("foci_commission_result", driver.oid) in registrations
    assert ("foci_tune_result", driver.oid) in registrations
    assert ("foci_outer_safety_fault", driver.oid) in registrations
    for name in (
        "foci_commissioning_workflow_plan",
        "foci_velocity_integral_plan_core",
        "foci_velocity_integral_plan_geometry",
        "foci_velocity_integral_plan_authority",
        "foci_velocity_integral_plan_timing",
        "foci_velocity_integral_plan_travel",
        "foci_velocity_integral_plan_recovery",
        "foci_velocity_integral_plan_rung",
        "foci_velocity_integral_terminal",
    ):
        assert (name, driver.oid) in registrations
    assert ("foci_selftest_result", driver.oid) in registrations
    assert ("foci_selftest_done", driver.oid) in registrations
    assert ("foci_stepper_event", None) in registrations
    assert ("foci_stepper_perf_event", None) in registrations
    assert ("foci_commission_detail", driver.oid) in registrations
    assert ("foci_current_step_result", driver.oid) in registrations
    assert ("foci_current_vector_step_result", driver.oid) in registrations
    assert ("foci_current_torque_sample_result", driver.oid) in registrations
    assert (
        "foci_current_torque_sample_detail_result",
        driver.oid,
    ) in registrations
    assert ("foci_voltage_step_result", driver.oid) in registrations
    assert ("foci_resistance_profile", driver.oid) in registrations
    assert ("foci_resistance_run", driver.oid) in registrations
    assert ("foci_resistance_axis", driver.oid) in registrations
    assert ("foci_velocity_limit_latch_flags", driver.oid) in registrations
    assert ("foci_velocity_limit_latch_motion", driver.oid) in registrations
    assert ("foci_velocity_limit_latch_restore", driver.oid) in registrations
    assert ("foci_velocity_limit_latch_core", driver.oid) in registrations
    assert ("foci_encoder_alignment", driver.oid) in registrations
    assert ("foci_adc_residual", driver.oid) in registrations
    assert ("foci_closed_loop_activation", driver.oid) in registrations
    assert ("foci_current_loop_filters", driver.oid) in registrations
    assert ("foci_current_loop_run", driver.oid) in registrations
    assert ("foci_current_validation_axis", driver.oid) in registrations
    assert ("foci_current_validation_envelope", driver.oid) in registrations
    assert ("foci_motion_scale_rejected", driver.oid) in registrations
    assert len(registrations) == len(set(registrations))


def test_bind_mcu_registers_only_the_last_boot_diagnostic_response():
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    registrations = response_names(mcu)
    assert ("foci_last_boot_diagnostic", driver.oid) in registrations
    assert ("foci_last_panic", driver.oid) not in registrations


def test_last_boot_diagnostic_labels_interrupted_breakaway_without_a_fault(caplog):
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)
    driver.protocol.bind_mcu(mcu, driver.oid)

    response_callback(mcu, "foci_last_boot_diagnostic")(
        {
            "oid": driver.oid,
            "fault_kind": 0,
            "line": 0,
            "pc": 0,
            "file_hash": 0,
            "breakaway_checkpoint": 5,
            "breakaway_interrupted": 1,
        }
    )

    assert "FOCI board" in caplog.text
    assert "interrupted breakaway campaign" in caplog.text
    assert "checkpoint=5" in caplog.text
    assert "stepper_x" not in caplog.text
    assert "panic" not in caplog.text
    assert "fault" not in caplog.text


@pytest.mark.parametrize(
    ("fault_kind", "fault_name"),
    ((1, "rust_panic"), (2, "hard_fault")),
)
def test_last_boot_diagnostic_preserves_fault_labels_and_context(caplog, fault_kind, fault_name):
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)
    driver.protocol.bind_mcu(mcu, driver.oid)

    response_callback(mcu, "foci_last_boot_diagnostic")(
        {
            "oid": driver.oid,
            "fault_kind": fault_kind,
            "line": 321,
            "pc": 0x12345678,
            "file_hash": 0x90ABCDEF,
            "breakaway_checkpoint": 0,
            "breakaway_interrupted": 0,
        }
    )

    assert fault_name in caplog.text
    assert "line=321" in caplog.text
    assert "pc=0x12345678" in caplog.text
    assert "file_hash=0x90abcdef" in caplog.text
    assert "FOCI board" in caplog.text
    assert "stepper_x" not in caplog.text


def test_last_boot_diagnostic_preserves_fault_and_interruption_context(caplog):
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)
    driver.protocol.bind_mcu(mcu, driver.oid)

    response_callback(mcu, "foci_last_boot_diagnostic")(
        {
            "oid": driver.oid,
            "fault_kind": 2,
            "line": 654,
            "pc": 0x87654321,
            "file_hash": 0xFEDCBA09,
            "breakaway_checkpoint": 4,
            "breakaway_interrupted": 1,
        }
    )

    assert "hard_fault" in caplog.text
    assert "line=654" in caplog.text
    assert "pc=0x87654321" in caplog.text
    assert "file_hash=0xfedcba09" in caplog.text
    assert "interrupted breakaway campaign" in caplog.text
    assert "checkpoint=4" in caplog.text
    assert "FOCI board" in caplog.text
    assert "stepper_x" not in caplog.text


def test_last_boot_diagnostic_is_board_scoped_for_reversed_oid_order(caplog):
    serial = MockSerial()
    driver_0 = make_driver(stepper_name="stepper_x", bind_protocol=False)
    driver_1 = make_driver(stepper_name="stepper_y", bind_protocol=False)
    driver_0.oid = 0
    driver_1.oid = 1
    register_last_boot_diagnostic_response(serial, driver_0, driver_0.oid)
    register_last_boot_diagnostic_response(serial, driver_1, driver_1.oid)
    callbacks = {
        oid: callback
        for callback, name, oid in serial.responses
        if name == "foci_last_boot_diagnostic"
    }
    recovered = {
        "fault_kind": 1,
        "line": 987,
        "pc": 0x10203040,
        "file_hash": 0x50607080,
        "breakaway_checkpoint": 6,
        "breakaway_interrupted": 1,
    }

    callbacks[1]({"oid": 1, **recovered})
    oid_1_messages = [record.getMessage() for record in caplog.records]
    caplog.clear()
    callbacks[0]({"oid": 0, **recovered})
    oid_0_messages = [record.getMessage() for record in caplog.records]

    assert oid_1_messages == oid_0_messages
    assert len(oid_0_messages) == 2
    assert all("FOCI board" in message for message in oid_0_messages)
    assert "rust_panic" in oid_0_messages[0]
    assert "line=987" in oid_0_messages[0]
    assert "pc=0x10203040" in oid_0_messages[0]
    assert "file_hash=0x50607080" in oid_0_messages[0]
    assert "interrupted breakaway campaign" in oid_0_messages[1]
    assert "checkpoint=6" in oid_0_messages[1]
    assert "stepper_x" not in caplog.text
    assert "stepper_y" not in caplog.text


def test_motion_scale_rejection_response_is_actionable(caplog):
    driver = make_driver()
    mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver.protocol.bind_mcu(mcu, driver.oid)

    callback, _name, _oid = next(
        response
        for response in mcu._serial.responses
        if response[1] == "foci_motion_scale_rejected"
    )
    callback({"oid": driver.oid, "stage": 1, "reason": 9})

    assert "stepper_x" in caplog.text
    assert "P1" in caplog.text
    assert "mapper installation failed" in caplog.text


def test_motion_scale_rejection_reason_names_match_firmware_wire_codes():
    assert MOTION_SCALE_REJECTION_NAMES == {
        1: "encoder_ppr is zero",
        2: "encoder_ppr exceeds 1073741823",
        3: "planner_steps_per_rev is zero",
        4: "planner_steps_per_rev exceeds 16777216",
        5: "motor runtime is enabled",
        6: "armed mirror is set",
        7: "physical step queue is not empty",
        8: "physical step timer is active",
        9: "mapper installation failed",
        10: "ABN_DECODER_PPR write failed",
        11: "STEP_WIDTH write failed",
        12: "TMC request queue is full",
        13: "board channel is unavailable",
    }


def test_inductance_replies_are_registered_as_commissioning_responses():
    driver = make_driver()
    serial = MockSerial()

    register_commissioning_responses(serial, driver, driver.oid)

    registrations = response_names(serial)
    assert ("foci_inductance_run", driver.oid) in registrations
    assert ("foci_inductance_frame", driver.oid) in registrations
    assert ("foci_inductance_estimate", driver.oid) in registrations


def test_commissioning_registers_timing_reply():
    driver = make_driver()
    serial = MockSerial()

    register_commissioning_responses(serial, driver, driver.oid)

    assert ("foci_commission_timing", driver.oid) in response_names(serial)


def test_breakaway_replies_are_registered_and_routed_to_their_handlers():
    """All 16 `FociBreakaway*` replies (replies.rs) must reach a live MCU's
    handler, mirroring the sibling `foci_velocity_integral_*` /
    `foci_fixed_gain_amplitude_*` registrations exactly."""
    driver = make_driver()
    serial = MockSerial()

    register_commissioning_responses(serial, driver, driver.oid)

    registered = {name: callback for callback, name, oid in serial.responses if oid == driver.oid}
    expected = {
        "foci_breakaway_probe_plan": driver.autotune.handle_breakaway_probe_plan,
        "foci_breakaway_probe_result": driver.autotune.handle_breakaway_probe_result,
        "foci_breakaway_probe_terminal": (driver.autotune.handle_breakaway_probe_terminal),
        "foci_breakaway_discovery_plan_identity": (
            driver.autotune.handle_breakaway_discovery_plan_identity
        ),
        "foci_breakaway_discovery_plan_geometry": (
            driver.autotune.handle_breakaway_discovery_plan_geometry
        ),
        "foci_breakaway_ceiling_source": (
            driver.autotune.handle_breakaway_discovery_ceiling_source
        ),
        "foci_breakaway_rung_zero_diagnostic": (
            driver.autotune.handle_breakaway_discovery_rung_zero_diagnostic
        ),
        "foci_breakaway_discovery_terminal": (driver.autotune.handle_breakaway_discovery_terminal),
        "foci_breakaway_confirmation_plan": (driver.autotune.handle_breakaway_confirmation_plan),
        "foci_breakaway_confirmation_terminal_identity": (
            driver.autotune.handle_breakaway_confirmation_terminal_identity
        ),
        "foci_breakaway_confirmation_terminal_masks": (
            driver.autotune.handle_breakaway_confirmation_terminal_masks
        ),
        "foci_breakaway_campaign_terminal": (driver.autotune.handle_breakaway_campaign_terminal),
    }

    assert len(expected) == 12
    assert set(expected) <= set(registered)
    for name, handler in expected.items():
        assert registered[name] == handler, name


def test_inductance_replies_are_not_active_diagnostic_responses():
    driver = make_driver()
    serial = MockSerial()

    register_active_diagnostic_responses(serial, driver, driver.oid)

    registrations = response_names(serial)
    assert ("foci_inductance_run", driver.oid) not in registrations
    assert ("foci_inductance_frame", driver.oid) not in registrations
    assert ("foci_inductance_estimate", driver.oid) not in registrations


def test_registers_current_loop_hold_reply():
    driver = make_driver()
    serial = MockSerial()

    register_active_diagnostic_responses(serial, driver, driver.oid)

    assert (
        driver.diagnostics.active.handle_current_loop_hold,
        "foci_current_loop_hold",
        driver.oid,
    ) in serial.responses


def test_registers_closed_loop_activation_reply():
    driver = make_driver()
    serial = MockSerial()

    register_active_diagnostic_responses(serial, driver, driver.oid)

    assert (
        driver.diagnostics.active.handle_closed_loop_activation,
        "foci_closed_loop_activation",
        driver.oid,
    ) in serial.responses


def test_driver_mcu_identify_binds_protocol_without_driver_aliases():
    driver = make_driver(
        stepper_name="stepper_x",
        kinematics=MockCartesianKinematics([["stepper_x"]]),
    )
    driver.mcu = MockMCU()
    driver.protocol = FociProtocol(driver)

    driver._handle_mcu_identify()

    assert driver.protocol.commands.set_current is not None
    assert driver.protocol.commands.calibrate is not None
    assert not hasattr(driver, "set_current_cmd")
    assert not hasattr(driver, "calibrate_cmd")
    assert ("foci_calibrate_result", driver.oid) in response_names(driver.mcu)


class RecordingCommand:
    def __init__(self, name, calls, response=None):
        self.name = name
        self.calls = calls
        self.last_args = None
        self.response = response

    def send(self, args=None):
        self.last_args = args
        self.calls.append((self.name, args))
        return self.response


def install_recording_commands(commands, names, responses=None):
    calls = []
    responses = responses or {}
    for name in names:
        setattr(commands, name, RecordingCommand(name, calls, responses.get(name)))
    return calls


def test_configure_startup_sends_existing_connect_payload_order():
    driver = make_driver()
    commands = driver.protocol.commands
    calls = install_recording_commands(
        commands,
        [
            "set_current",
            "set_voltage_limit",
            "query_adc_vm_offset",
            "set_motion_scale",
            "set_encoder_dir",
            "set_pid_gains",
            "set_velocity_filter",
            "set_torque_filter",
            "set_position_filter",
            "set_flux_filter",
            "set_position_gains",
            "set_velocity_feedforward",
            "set_velocity_limit",
        ],
        responses={
            "query_adc_vm_offset": {
                "offset_raw": 33662,
                "sample_count": 8,
                "status": 0,
            },
        },
    )

    driver.protocol.configure_startup(
        current_ma=800,
        voltage_limit=16000,
        channel=0,
        encoder_ppr=1000,
        planner_steps_per_rev=3200,
        encoder_reversed=True,
        pid_gains=(100, 200, 300, 400),
        filter_hz={
            "velocity": 80,
            "torque": 90,
            "position": 100,
            "flux": 110,
        },
        position_gains=(700, 0, 1100, 0),
        velocity_feedforward=(True, 8),
        velocity_limit=50000,
    )

    assert calls == [
        ("set_current", [driver.oid, 800]),
        ("set_voltage_limit", [driver.oid, 16000]),
        ("query_adc_vm_offset", [driver.oid]),
        ("set_motion_scale", [driver.oid, 0, 1000, 3200]),
        ("set_encoder_dir", [driver.oid, 0, 1]),
        ("set_pid_gains", [driver.oid, 100, 200, 300, 400]),
        ("set_velocity_filter", [driver.oid, 80]),
        ("set_torque_filter", [driver.oid, 90]),
        ("set_position_filter", [driver.oid, 100]),
        ("set_flux_filter", [driver.oid, 110]),
        ("set_position_gains", [driver.oid, 700, 0, 1100, 0]),
        ("set_velocity_feedforward", [driver.oid, 1, 8]),
        ("set_velocity_limit", [driver.oid, 50000]),
    ]
    assert driver.state.adc_vm_offset_raw == 33662


def test_configure_startup_skips_unset_optional_payloads():
    driver = make_driver()
    commands = driver.protocol.commands
    calls = install_recording_commands(
        commands,
        [
            "set_current",
            "set_voltage_limit",
            "query_adc_vm_offset",
            "set_motion_scale",
            "set_encoder_dir",
            "set_pid_gains",
            "set_velocity_filter",
            "set_position_gains",
            "set_velocity_feedforward",
            "set_velocity_limit",
        ],
        responses={
            "query_adc_vm_offset": {
                "offset_raw": 33662,
                "sample_count": 8,
                "status": 0,
            },
        },
    )

    driver.protocol.configure_startup(
        current_ma=800,
        voltage_limit=16000,
        channel=0,
        encoder_ppr=1000,
        planner_steps_per_rev=3200,
        encoder_reversed=False,
        pid_gains=None,
        filter_hz={"velocity": None, "torque": None, "position": None, "flux": None},
        position_gains=None,
        velocity_feedforward=(False, 1),
        velocity_limit=None,
    )

    assert calls == [
        ("set_current", [driver.oid, 800]),
        ("set_voltage_limit", [driver.oid, 16000]),
        ("query_adc_vm_offset", [driver.oid]),
        ("set_motion_scale", [driver.oid, 0, 1000, 3200]),
        ("set_encoder_dir", [driver.oid, 0, 0]),
    ]
    assert driver.state.adc_vm_offset_raw == 33662


def test_configure_startup_sends_explicit_zero_filter_disables():
    driver = make_driver()
    commands = driver.protocol.commands
    calls = install_recording_commands(
        commands,
        [
            "set_current",
            "set_voltage_limit",
            "query_adc_vm_offset",
            "set_motion_scale",
            "set_encoder_dir",
            "set_velocity_filter",
            "set_torque_filter",
            "set_position_filter",
            "set_flux_filter",
        ],
        responses={
            "query_adc_vm_offset": {
                "offset_raw": 33662,
                "sample_count": 8,
                "status": 0,
            },
        },
    )

    driver.protocol.configure_startup(
        current_ma=800,
        voltage_limit=16000,
        channel=0,
        encoder_ppr=1000,
        planner_steps_per_rev=3200,
        encoder_reversed=False,
        pid_gains=None,
        filter_hz={"velocity": 0, "torque": 0, "position": 0, "flux": 0},
        position_gains=None,
        velocity_feedforward=(False, 1),
        velocity_limit=None,
    )

    assert calls == [
        ("set_current", [driver.oid, 800]),
        ("set_voltage_limit", [driver.oid, 16000]),
        ("query_adc_vm_offset", [driver.oid]),
        ("set_motion_scale", [driver.oid, 0, 1000, 3200]),
        ("set_encoder_dir", [driver.oid, 0, 0]),
        ("set_velocity_filter", [driver.oid, 0]),
        ("set_torque_filter", [driver.oid, 0]),
        ("set_position_filter", [driver.oid, 0]),
        ("set_flux_filter", [driver.oid, 0]),
    ]


def test_configure_startup_requires_runtime_adc_vm_offset():
    driver = make_driver()
    commands = driver.protocol.commands
    install_recording_commands(
        commands,
        [
            "set_current",
            "set_voltage_limit",
            "query_adc_vm_offset",
        ],
        responses={"query_adc_vm_offset": None},
    )

    with pytest.raises(CommandError, match="cached ADC_VM offset query returned no data"):
        driver.protocol.configure_startup(
            current_ma=800,
            voltage_limit=16000,
            channel=0,
            encoder_ppr=1000,
            planner_steps_per_rev=3200,
            encoder_reversed=False,
            pid_gains=None,
            filter_hz={"velocity": 0, "torque": 0, "position": 0, "flux": 0},
            position_gains=None,
            velocity_feedforward=(False, 1),
            velocity_limit=None,
        )

    assert driver.state.adc_vm_offset_raw is None


def test_fine_grained_control_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.set_current(1700)
    driver.protocol.set_pid_gains(1, 2, 3, 4)
    driver.protocol.set_position_gains(5, 6, 7, 8)
    driver.protocol.set_velocity_feedforward(True, 9)
    driver.protocol.set_velocity_limit(10)
    driver.protocol.set_voltage_limit(11000)

    commands = driver.protocol.commands
    assert commands.set_current.last_args == [driver.oid, 1700]
    assert commands.set_pid_gains.last_args == [driver.oid, 1, 2, 3, 4]
    assert commands.set_position_gains.last_args == [driver.oid, 5, 6, 7, 8]
    assert commands.set_velocity_feedforward.last_args == [driver.oid, 1, 9]
    assert commands.set_velocity_limit.last_args == [driver.oid, 10]
    assert commands.set_voltage_limit.last_args == [driver.oid, 11000]


def test_expert_control_protocol_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.set_velocity_transient_feedforward(
        enable=True,
        lead_time_us=400,
        gain=750,
        max_offset=1200,
        rate_hz=10000,
    )
    driver.protocol.set_accel_feedforward(
        enable=False,
        accel_gain=750,
        decel_gain=250,
    )
    driver.protocol.set_decoupling_feedforward(
        enable=True,
        r_int=3000,
        l_int=4095,
        pole_pairs=50,
        position_units_per_rev=65536,
        f_pwm_hz=25000,
        max_offset=500,
    )
    driver.protocol.set_position_lead(
        enable=True,
        gain=10,
        max_counts=20,
    )
    driver.protocol.set_phase_advance(
        enable=False,
        gain_ppm=60000,
        max_counts=64,
        deadband=16,
    )

    commands = driver.protocol.commands
    assert commands.set_velocity_transient_feedforward.last_args == [
        driver.oid,
        1,
        400,
        750,
        1200,
        10000,
    ]
    assert commands.set_accel_feedforward.last_args == [
        driver.oid,
        0,
        750,
        250,
    ]
    assert commands.set_decoupling_feedforward.last_args == [
        driver.oid,
        1,
        3000,
        4095,
        50,
        65536,
        25000,
        500,
    ]
    assert commands.set_position_lead.last_args == [driver.oid, 1, 10, 20]
    assert commands.set_phase_advance.last_args == [
        driver.oid,
        0,
        60000,
        64,
        16,
    ]


def test_passive_diagnostic_protocol_methods_send_existing_payloads():
    driver = make_driver()
    driver.protocol.commands.stepper_get_position = MockCommand({"pos": -19176})
    driver.protocol.commands.stepper_stats = MockCommand({"position": -26360})
    driver.protocol.commands.stepper_exec_stats = MockCommand(
        {
            "executed_pos_steps": 39538,
            "physical_pos_pulses": 50609,
            "physical_neg_pulses": 0,
            "planner_steps_per_rev": 3200,
            "encoder_ppr": 1000,
            "encoder_counts_per_rev": 4000,
            "tmc_grid": 4096,
            "physical_step_width": 16,
            "motion_scale_configured": 1,
            "step_half_period_ticks": 4,
            "dir_setup_ticks": 8,
            "waveform_worst_case_ticks": 24,
            "fatal_lateness_ticks": 84000,
        }
    )
    driver.protocol.commands.stepper_timing_stats = MockCommand({"activation_count": 2})
    driver.protocol.commands.stepper_stop_stats = MockCommand({"stop_count": 1})
    driver.protocol.commands.stepper_perf_stats = MockCommand(
        {
            "crit_max_cycles": 190000,
            "shutdown_site_count": 3,
            "shutdown_site_max_cycles": 6000,
            "reset_site_count": 2,
            "reset_site_max_cycles": 4200,
            "trigger_stop_site_count": 15,
            "trigger_stop_site_max_cycles": 900,
        }
    )

    assert driver.protocol.get_step_position() == {"pos": -19176}
    stats = driver.protocol.get_stepper_stats()
    perf = driver.protocol.get_stepper_perf_stats(clear=True)

    assert stats == (
        {"position": -26360},
        driver.protocol.commands.stepper_exec_stats.response,
        {"activation_count": 2},
        {"stop_count": 1},
    )
    assert perf == {
        "crit_max_cycles": 190000,
        "shutdown_site_count": 3,
        "shutdown_site_max_cycles": 6000,
        "reset_site_count": 2,
        "reset_site_max_cycles": 4200,
        "trigger_stop_site_count": 15,
        "trigger_stop_site_max_cycles": 900,
    }
    assert driver.protocol.commands.stepper_get_position.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_exec_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_timing_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_stop_stats.last_args == [driver.oid]
    assert driver.protocol.commands.stepper_perf_stats.last_args == [driver.oid, 1]


def test_motion_scale_protocol_sends_only_truthful_scale_values():
    driver = make_driver()

    driver.protocol.set_motion_scale(channel=0, encoder_ppr=1000, planner_steps_per_rev=3200)

    assert driver.protocol.commands.set_motion_scale.last_args == [
        driver.oid,
        0,
        1000,
        3200,
    ]


def test_passive_diagnostic_protocol_methods_preserve_errors():
    driver = make_driver()
    driver.protocol.commands.stepper_get_position = None
    with pytest.raises(
        CommandError, match="FOCI_STEP_POSITION is not available before MCU identify"
    ):
        driver.protocol.get_step_position()

    driver.protocol.commands.stepper_get_position = MockCommand({})
    with pytest.raises(CommandError, match="FOCI_STEP_POSITION query returned no position"):
        driver.protocol.get_step_position()

    driver.protocol.commands.stepper_stats = MockCommand(None)
    with pytest.raises(CommandError, match="FOCI_STEPPER_STATS stats query returned no data"):
        driver.protocol.get_stepper_stats()


def test_stepper_stats_rejects_incomplete_new_firmware_response():
    driver = make_driver()
    driver.protocol.commands.stepper_stats = MockCommand({"position": 0})
    driver.protocol.commands.stepper_exec_stats = MockCommand(
        {"executed_pos_steps": 1, "executed_neg_steps": 0}
    )
    driver.protocol.commands.stepper_timing_stats = MockCommand({"activation_count": 1})
    driver.protocol.commands.stepper_stop_stats = MockCommand({"stop_count": 0})

    with pytest.raises(
        CommandError,
        match="FOCI_STEPPER_STATS exec_stats query returned incomplete data",
    ):
        driver.protocol.get_stepper_stats()


def test_active_diagnostic_protocol_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.run_current_step_test(
        axis=1,
        target=250,
        duration_ms=80,
        voltage_limit=12000,
    )
    driver.protocol.run_current_vector_step_test(
        torque_target=0,
        flux_target=300,
        duration_ms=90,
        voltage_limit=13000,
    )
    driver.protocol.run_current_torque_sample_test(
        target=-400,
        flux_target=25,
        sample_delay_ms=5,
        voltage_limit=14000,
    )
    driver.protocol.run_position_torque_offset_sample_test(
        target=500,
        sample_delay_ms=2,
        voltage_limit=15000,
    )
    driver.protocol.run_voltage_step_test(
        uq_ext=256,
        ud_ext=-128,
        sample_delay_ms=3,
    )
    driver.protocol.run_velocity_limit_latch_test(channel=driver.channel)

    commands = driver.protocol.commands
    assert commands.current_step_test.last_args == [
        driver.oid,
        1,
        250,
        80,
        12000,
    ]
    assert commands.current_vector_step_test.last_args == [
        driver.oid,
        0,
        300,
        90,
        13000,
    ]
    assert commands.current_torque_sample_test.last_args == [
        driver.oid,
        -400,
        25,
        5,
        14000,
    ]
    assert commands.position_torque_offset_sample_test.last_args == [
        driver.oid,
        500,
        2,
        15000,
    ]
    assert commands.velocity_limit_latch_test.last_args == [
        driver.oid,
        driver.channel,
    ]
    assert commands.voltage_step_test.last_args == [
        driver.oid,
        256,
        -128,
        3,
    ]


def test_core_workflow_methods_send_existing_payloads():
    driver = make_driver()

    driver.protocol.set_auto_calibrate_on_enable(True)
    driver.protocol.run_calibration()
    driver.protocol.run_commission(2)
    driver.protocol.run_selftest()
    driver.protocol.dump_registers()

    commands = driver.protocol.commands
    assert commands.set_auto_calibrate_on_enable.last_args == [driver.oid, 1]
    assert commands.calibrate.last_args == [driver.oid]
    assert commands.commission.last_args == [driver.oid, 2]
    assert commands.selftest.last_args == [driver.oid]
    assert commands.dump_registers.last_args == [driver.oid]


def test_run_commission_cancel_sends_the_command():
    driver = make_driver()

    driver.protocol.run_commission_cancel()

    commands = driver.protocol.commands
    assert commands.commission_cancel.last_args == [driver.oid]


def test_run_tune_sends_planning_payload():
    driver = make_driver()

    driver.protocol.run_tune(
        profile_code=1,
        mode_code=2,
        inner_lambda=1200,
        theta_e=160,
        current_ringing=7,
        current_bw=500,
        inner_warning_flags=8,
        requested_velocity_mrev_s=5000,
        machine_velocity_ceiling_mrev_s=7500,
        requested_velocity_source=1,
        max_stroke_travel_mrev=1000,
        settle_travel_reserve_mrev=250,
        negative_position_headroom_mrev=1250,
        positive_position_headroom_mrev=1250,
        max_duration_ms=3000,
    )

    assert driver.protocol.commands.tune.last_args == [
        driver.oid,
        0,
        1,
        2,
        1200,
        160,
        7,
        500,
        8,
        5000,
        7500,
        1,
        1000,
        250,
        1250,
        1250,
        3000,
    ]


def test_run_tune_forwards_only_the_explicit_action_selector():
    driver = make_driver()

    driver.protocol.run_tune(
        action=2,
        profile_code=1,
        mode_code=2,
        inner_lambda=1200,
        theta_e=160,
        current_ringing=7,
        current_bw=500,
        inner_warning_flags=8,
        requested_velocity_mrev_s=5000,
        machine_velocity_ceiling_mrev_s=7500,
        requested_velocity_source=1,
        max_stroke_travel_mrev=1000,
        settle_travel_reserve_mrev=250,
        negative_position_headroom_mrev=1250,
        positive_position_headroom_mrev=1250,
        max_duration_ms=3000,
    )

    assert driver.protocol.commands.tune.last_args[1] == 2
    assert len(driver.protocol.commands.tune.last_args) == 17


def test_tune_command_matches_firmware_field_order_without_legacy_budget():
    driver = make_driver()

    formats = [fmt for fmt in driver.mcu.command_formats if fmt.startswith("foci_tune ")]

    assert formats == [
        "foci_tune oid=%c action=%c profile=%c mode=%c"
        " inner_lambda=%u theta_e=%u current_ringing=%c current_bw=%u"
        " inner_warning_flags=%c requested_velocity_mrev_s=%u"
        " machine_velocity_ceiling_mrev_s=%u requested_velocity_source=%c"
        " max_stroke_travel_mrev=%u settle_travel_reserve_mrev=%u"
        " negative_position_headroom_mrev=%u positive_position_headroom_mrev=%u"
        " max_duration_ms=%hu"
    ]


def test_preload_active_gains_sends_existing_payloads():
    driver = make_driver()
    gains = {
        "flux_p": 11,
        "flux_i": 416,
        "torque_p": 13,
        "torque_i": 2544,
        "velocity_p": 21,
        "velocity_i": 8192,
        "position_p": 23,
        "position_i": 2048,
        "velocity_limit": 25000,
        "velocity_filter_hz": 80,
        "torque_filter_hz": 90,
        "position_filter_hz": 100,
        "flux_filter_hz": 110,
    }

    driver.protocol.preload_active_gains(gains, voltage_limit=29000)

    commands = driver.protocol.commands
    assert commands.set_voltage_limit.last_args == [driver.oid, 29000]
    assert commands.set_pid_gains.last_args == [driver.oid, 11, 416, 13, 2544]
    assert commands.set_position_gains.last_args == [
        driver.oid,
        23,
        2048,
        21,
        8192,
    ]
    assert commands.set_velocity_limit.last_args == [driver.oid, 25000]
    assert commands.set_velocity_filter.last_args == [driver.oid, 80]
    assert commands.set_torque_filter.last_args == [driver.oid, 90]
    assert commands.set_position_filter.last_args == [driver.oid, 100]
    assert commands.set_flux_filter.last_args == [driver.oid, 110]


def test_mock_driver_exposes_protocol_commands_without_driver_command_aliases():
    driver = make_driver()

    assert driver.protocol.commands.set_current is not None
    assert driver.protocol.commands.current_step_test is not None

    for name in (
        "set_current_cmd",
        "calibrate_cmd",
        "commission_cmd",
        "tune_cmd",
        "selftest_cmd",
        "dump_cmd",
        "current_step_test_cmd",
    ):
        assert not hasattr(driver, name)
