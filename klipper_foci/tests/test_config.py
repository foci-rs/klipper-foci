"""Tests for FOCI MCU config-build command emission."""

import pytest

from klipper_foci.config import velocity_mm_s_to_mrev_s
from klipper_foci.registry import GCODE_COMMANDS, GcodeCommandSpec
from tests.mocks import CommandError, MockConfig, MockMCU, make_config_driver, make_config_printer
from tests.test_registry import _FakeEntryPoint


def test_package_entry_points_import_driver_and_global_config():
    import klipper_foci
    from klipper_foci.driver import FociDriver
    from klipper_foci.registry import FociGlobalConfig

    assert klipper_foci.FociDriver is FociDriver
    assert klipper_foci.FociGlobalConfig is FociGlobalConfig
    assert callable(klipper_foci.load_config)
    assert callable(klipper_foci.load_config_prefix)


class OldFirmwareMcu(MockMCU):
    """Mock an old dictionary that lacks the mandatory motion-scale contract."""

    def lookup_command(self, fmt, cq=None):
        if fmt.startswith("tmc_set_motion_scale "):
            raise CommandError("unknown command tmc_set_motion_scale")
        return super().lookup_command(fmt, cq=cq)


class OldFirmwareMcuMissingVelocityFeedforwardRpm(MockMCU):
    """Mock an old dictionary that predates the renamed RPM-domain FF command."""

    def lookup_command(self, fmt, cq=None):
        if fmt.startswith("tmc_set_velocity_feedforward_rpm "):
            raise CommandError("unknown command tmc_set_velocity_feedforward_rpm")
        return super().lookup_command(fmt, cq=cq)


def registered_command_names(printer):
    gcode = printer.lookup_object("gcode")
    return {args[0] for args, _kwargs in gcode._mux_commands}


def build_driver_with_mode():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
    )
    make_config_driver(printer, sections, "foci stepper_x")
    return printer


def test_absent_foci_section_registers_all_gcode_commands():
    printer = build_driver_with_mode()

    assert registered_command_names(printer) == {spec.name for spec in GCODE_COMMANDS}


def test_stale_mode_key_raises_config_error():
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
        foci_mode="expert",
    )
    with pytest.raises(printer.config_error("").__class__):
        printer.load_object(MockConfig(printer, sections, "foci"), "foci")


def test_registry_resolves_component_handler_and_inline_help():
    from klipper_foci.registry import GcodeCommandSpec, register_gcode_commands

    class Component:
        def handle(self, gcmd):
            return None

    class Driver:
        stepper_name = "stepper_x"

        def __init__(self):
            self.component = Component()

    printer = build_driver_with_mode()
    gcode = printer.lookup_object("gcode")
    gcode._mux_commands.clear()

    driver = Driver()
    specs = (
        GcodeCommandSpec(
            name="FOCI_TEST",
            component="component",
            handler_name="handle",
            help_text="test command",
        ),
    )

    register_gcode_commands(driver, gcode, command_specs=specs)

    args, kwargs = gcode._mux_commands[0]
    assert args[:3] == ("FOCI_TEST", "STEPPER", "stepper_x")
    assert args[3].__self__ is driver.component
    assert args[3].__func__ is driver.component.handle.__func__
    assert kwargs["desc"] == "test command"


def test_dump_commands_register_register_dump_workflow_handler():
    printer = build_driver_with_mode()
    gcode = printer.lookup_object("gcode")

    dump_handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in {"DUMP_FOCI", "DUMP_TMC"}
    }

    assert dump_handlers["DUMP_FOCI"].__self__.__class__.__name__ == ("RegisterDumpWorkflow")
    assert dump_handlers["DUMP_TMC"].__self__.__class__.__name__ == ("RegisterDumpWorkflow")


def test_default_control_commands_register_controls_workflow_handlers():
    printer = build_driver_with_mode()
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_SET_GAINS",
        "FOCI_SET_INNER_GAINS",
        "FOCI_SET_CURRENT",
        "FOCI_SET_VELOCITY_FEEDFORWARD",
        "FOCI_SET_VOLTAGE_LIMIT",
    }

    handlers = {
        args[0]: args[3] for args, _kwargs in gcode._mux_commands if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "ControlsWorkflow" for handler in handlers.values()
    )


def test_tuning_entry_point_registers_all_three_commands(monkeypatch):
    from klipper_foci_tuning.registry import register as tuning_register

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("tuning", tuning_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    gcode = printer.lookup_object("gcode")
    handlers_by_name = {args[0]: args[3] for args, _kwargs in gcode._mux_commands}
    expected = {
        "FOCI_SET_ACCEL_FEEDFORWARD": "set_accel_feedforward",
        "FOCI_SET_POSITION_LEAD": "set_position_lead",
        "FOCI_SET_PHASE_ADVANCE": "set_phase_advance",
    }
    assert len(expected) == 3
    for command_name, handler_name in expected.items():
        assert command_name in handlers_by_name
        bound_method = handlers_by_name[command_name]
        assert bound_method.__self__ is driver.tuning
        assert bound_method.__func__.__name__ == handler_name
    # Computed, not a literal: len(GCODE_COMMANDS) always reflects core's
    # current static table, so this stays correct if that table's size
    # ever changes again.
    assert len(handlers_by_name) == len(GCODE_COMMANDS) + len(expected)


def test_diagnostics_active_and_passive_absent_with_core_only(monkeypatch):
    monkeypatch.setattr("klipper_foci.registry.entry_points", lambda *, group: [])
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    assert not hasattr(driver, "diagnostics_active")
    assert not hasattr(driver, "diagnostics_passive")


def test_diagnostics_entry_point_registers_all_nine_commands(monkeypatch):
    from klipper_foci_diagnostics.registry import register as diagnostics_register

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("diagnostics", diagnostics_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    gcode = printer.lookup_object("gcode")
    handlers_by_name = {args[0]: args[3] for args, _kwargs in gcode._mux_commands}
    expected = {
        "FOCI_STEP_POSITION": ("diagnostics_passive", "step_position"),
        "FOCI_STEPPER_STATS": ("diagnostics_passive", "stepper_stats"),
        "FOCI_STACK_WATERMARK": ("diagnostics_passive", "stack_watermark"),
        "FOCI_CURRENT_STEP_TEST": ("diagnostics_active", "current_step_test"),
        "FOCI_CURRENT_VECTOR_STEP_TEST": ("diagnostics_active", "current_vector_step_test"),
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST": ("diagnostics_active", "current_torque_sample_test"),
        "FOCI_POSITION_TORQUE_OFFSET_TEST": ("diagnostics_active", "position_torque_offset_test"),
        "FOCI_VOLTAGE_STEP_TEST": ("diagnostics_active", "voltage_step_test"),
        "FOCI_RESISTANCE_TEST": ("diagnostics_active", "resistance_test"),
    }
    for command_name, (component_attr, handler_name) in expected.items():
        assert command_name in handlers_by_name
        bound_method = handlers_by_name[command_name]
        assert bound_method.__self__ is getattr(driver, component_attr)
        assert bound_method.__func__.__name__ == handler_name
    # Computed, not a literal: len(GCODE_COMMANDS) always reflects core's
    # current static table.
    assert len(handlers_by_name) == len(GCODE_COMMANDS) + len(expected)


def test_core_alone_registers_exactly_eleven_commands(monkeypatch):
    monkeypatch.setattr("klipper_foci.registry.entry_points", lambda *, group: [])
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    make_config_driver(printer, sections, "foci stepper_x")
    gcode = printer.lookup_object("gcode")
    registered_names = {args[0] for args, _kwargs in gcode._mux_commands}
    assert registered_names == {spec.name for spec in GCODE_COMMANDS}
    assert len(registered_names) == 11


def test_diagnostics_alone_without_tuning_works(monkeypatch):
    from klipper_foci_diagnostics.registry import register as diagnostics_register

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("diagnostics", diagnostics_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    make_config_driver(printer, sections, "foci stepper_x")  # must not raise
    gcode = printer.lookup_object("gcode")
    registered_names = {args[0] for args, _kwargs in gcode._mux_commands}
    assert "FOCI_CURRENT_STEP_TEST" in registered_names
    assert "FOCI_SET_PHASE_ADVANCE" not in registered_names


def test_tuning_alone_without_diagnostics_works(monkeypatch):
    from klipper_foci_tuning.registry import register as tuning_register

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("tuning", tuning_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    make_config_driver(printer, sections, "foci stepper_x")  # must not raise
    gcode = printer.lookup_object("gcode")
    registered_names = {args[0] for args, _kwargs in gcode._mux_commands}
    assert "FOCI_SET_PHASE_ADVANCE" in registered_names
    assert "FOCI_CURRENT_STEP_TEST" not in registered_names


def test_homing_events_register_homing_workflow_callbacks():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    make_config_driver(printer, sections, "foci stepper_x")

    for event in (
        "homing:home_rails_begin",
        "homing:homing_move_begin",
        "homing:homing_move_end",
    ):
        callbacks = printer._event_handlers[event]
        assert callbacks[0].__self__.__class__.__name__ == "HomingWorkflow"


def test_setup_registers_commissioning_workflow_handler():
    printer = build_driver_with_mode()
    gcode = printer.lookup_object("gcode")

    handler = next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_SETUP")

    assert handler.__self__.__class__.__name__ == "CommissioningWorkflow"


def test_selftest_registers_selftest_workflow_handler():
    printer = build_driver_with_mode()
    gcode = printer.lookup_object("gcode")

    handler = next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_SELFTEST")

    assert handler.__self__.__class__.__name__ == "SelftestWorkflow"


def test_autotune_registers_autotune_workflow_handler():
    printer = build_driver_with_mode()
    gcode = printer.lookup_object("gcode")

    handler = next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_AUTOTUNE")

    assert handler.__self__.__class__.__name__ == "AutotuneWorkflow"


def test_foci_driver_no_longer_exposes_gcode_command_methods():
    from klipper_foci.driver import FociDriver

    command_methods = [name for name in dir(FociDriver) if name.startswith("cmd_FOCI_")]

    assert command_methods == []
    assert not hasattr(FociDriver, "cmd_DUMP_FOCI")


def test_registry_no_longer_points_at_driver_component():
    from klipper_foci.registry import GCODE_COMMANDS

    assert all(spec.component != "driver" for spec in GCODE_COMMANDS)


def test_same_mcu_dual_channel_uses_stepper_oids_without_foci_config():
    printer, chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
            },
        }
    )
    mcu = chips["foci"]
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    mcu.run_config_callbacks()
    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert mcu.config_commands == []
    assert driver_x.oid == 10
    assert driver_y.oid == 12


def test_same_mcu_dual_channel_response_handlers_use_distinct_oids():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
            },
        }
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    response_oids = {(name, oid) for _callback, name, oid in driver_x.mcu._serial.responses}
    assert ("foci_commission_result", 10) in response_oids
    assert ("foci_commission_result", 12) in response_oids


def test_motion_scale_and_stats_dictionary_contract_is_mandatory():
    printer, chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")

    driver._handle_mcu_identify()

    assert (
        "tmc_set_motion_scale oid=%c channel=%c encoder_ppr=%u planner_steps_per_rev=%u"
    ) in chips["foci"].command_formats
    _send_fmt, recv_fmt, _oid = next(
        query
        for query in chips["foci"].query_commands
        if query[0] == "foci_stepper_exec_stats oid=%c"
    )
    assert recv_fmt == (
        "foci_stepper_exec_stats_result oid=%c"
        " executed_pos_steps=%u executed_neg_steps=%u"
        " physical_pos_pulses=%u physical_neg_pulses=%u"
        " planner_steps_per_rev=%u encoder_ppr=%u"
        " queue_empty_count=%u missed_deadline_count=%u"
    )


def test_old_firmware_dictionary_fails_identification_without_fallback():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
        chips={"foci": OldFirmwareMcu("foci")},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")

    with pytest.raises(CommandError, match="unknown command tmc_set_motion_scale"):
        driver._handle_mcu_identify()


def test_old_firmware_dictionary_fails_identification_without_velocity_feedforward_rpm():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
        chips={"foci": OldFirmwareMcuMissingVelocityFeedforwardRpm("foci")},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")

    with pytest.raises(CommandError, match="unknown command tmc_set_velocity_feedforward_rpm"):
        driver._handle_mcu_identify()


def test_configured_voltage_limit_is_sent_on_connect():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "voltage_limit": 29000,
            },
        }
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert driver.settings.voltage_limit == 29000
    assert driver.protocol.commands.set_voltage_limit.last_args == [10, 29000]


def test_configured_voltage_limit_accepts_raw_chip_range():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "voltage_limit": 0,
            },
            "stepper_y": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 12,
                "voltage_limit": 32767,
            },
        }
    )

    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    assert driver_x.settings.voltage_limit == 0
    assert driver_y.settings.voltage_limit == 32767


def test_configured_voltage_limit_rejects_values_above_chip_range():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "voltage_limit": 32768,
            },
        }
    )

    with pytest.raises(CommandError, match="voltage_limit above maximum"):
        make_config_driver(printer, sections, "foci stepper_x")


def test_dual_mcu_single_channel_uses_stepper_oids_without_foci_config():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci_x:STEP0",
                "dir_pin": "foci_x:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci_y:STEP0",
                "dir_pin": "foci_y:DIR0",
                "oid": 12,
            },
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    mcu_x.run_config_callbacks()
    mcu_y.run_config_callbacks()
    driver_x._handle_mcu_identify()
    driver_y._handle_mcu_identify()

    assert mcu_x.config_commands == []
    assert mcu_y.config_commands == []
    assert driver_x.oid == 10
    assert driver_y.oid == 12


def test_dual_mcu_drivers_keep_runtime_state_separate():
    mcu_x = MockMCU("foci_x")
    mcu_y = MockMCU("foci_y")
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci_x:STEP0",
                "dir_pin": "foci_x:DIR0",
                "oid": 10,
            },
            "stepper_y": {
                "step_pin": "foci_y:STEP0",
                "dir_pin": "foci_y:DIR0",
                "oid": 12,
            },
        },
        chips={"foci_x": mcu_x, "foci_y": mcu_y},
    )
    driver_x = make_config_driver(printer, sections, "foci stepper_x")
    driver_y = make_config_driver(printer, sections, "foci stepper_y")

    driver_x.state.operation_lock = True
    driver_x.state.inhibited = True

    assert driver_y.state.operation_lock is False
    assert driver_y.state.inhibited is False


def test_step1_rejected_when_mcu_pin_dictionary_lacks_step1():
    mcu = MockMCU(
        "foci",
        allowed_pins={"STEP0", "DIR0", "ENA0"},
    )
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP1",
                "dir_pin": "foci:DIR1",
                "oid": 10,
            },
        },
        chips={"foci": mcu},
    )

    with pytest.raises(CommandError, match="Unknown pin STEP1"):
        make_config_driver(printer, sections, "foci stepper_x")


def test_saved_commission_and_tune_fields_are_accepted_on_restart():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    sections["foci stepper_x"].update(
        {
            "identified_r_count_milli": 1792,
            "identified_lambda_us": 0,
            "identified_theta_e_us": 160,
            "identified_bandwidth_hz": 0,
            "identified_tau_e_us": 1154,
            "identified_inner_warning_flags": 36,
            "autotune_profile": "conservative",
            "autotune_mode": "nominal",
            "autotune_status": "commissioned",
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.config.identified_r_count_milli == 1792
    assert driver.config.identified_tau_e_us == 1154
    assert not hasattr(driver.config, "identified_j_eff")
    assert not hasattr(driver.config, "identified_b_eff")
    assert driver.config.autotune_profile == "conservative"
    assert driver.config.autotune_mode == "nominal"
    assert driver.config.autotune_status == "commissioned"


def test_config_reads_optional_provenance():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    sections["foci stepper_x"].update(
        {
            "autotune_status": "tuned",
            "autotune_probed_velocity_mrev_s": "5366",
            "autotune_d_eq_q": "1234",
            "autotune_confidence_q": "5000",
            "autotune_band_lower_percent": "70",
            "autotune_band_upper_percent": "80",
            "autotune_band_position_q": "3000",
            "autotune_position_bound_units": "409",
            "autotune_position_homing_peak_units": "300",
            "autotune_position_motion_cruise_units": "210",
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.config.autotune_probed_velocity_mrev_s == 5366
    assert driver.config.autotune_d_eq_q == 1234
    assert driver.config.autotune_confidence_q == 5000
    assert driver.config.autotune_band_lower_percent == 70
    assert driver.config.autotune_band_upper_percent == 80
    assert driver.config.autotune_band_position_q == 3000
    assert driver.config.autotune_position_bound_units == 409
    assert driver.config.autotune_position_homing_peak_units == 300
    assert driver.config.autotune_position_motion_cruise_units == 210


def test_config_provenance_defaults_to_none_when_absent():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.config.autotune_probed_velocity_mrev_s is None
    assert driver.config.autotune_d_eq_q is None
    assert driver.config.autotune_confidence_q is None
    assert driver.config.autotune_band_lower_percent is None
    assert driver.config.autotune_band_upper_percent is None
    assert driver.config.autotune_band_position_q is None
    assert driver.config.autotune_position_bound_units is None
    assert driver.config.autotune_position_homing_peak_units is None
    assert driver.config.autotune_position_motion_cruise_units is None


def test_saved_resistance_identification_fields_are_accepted_on_restart():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )
    sections["foci stepper_x"].update(
        {
            "identified_r_count_slope_milli": 1042,
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.config.identified_r_count_slope_milli == 1042


def test_resistance_identification_fields_default_to_none():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        }
    )

    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert driver.config.identified_r_count_slope_milli is None


def test_velocity_mm_s_to_mrev_s_converts_via_rotation_distance():
    # rotation_distance=40mm/rev, 300mm/s -> 7.5rev/s -> 7500mrev/s
    assert velocity_mm_s_to_mrev_s(300.0, 40.0) == pytest.approx(7500.0)


def test_staleness_warns_when_operating_exceeds_probed(caplog):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "rotation_distance": 40.0,
            },
        }
    )
    sections["foci stepper_x"]["autotune_status"] = "tuned"
    sections["foci stepper_x"]["autotune_probed_velocity_mrev_s"] = "5366"
    printer._objects["toolhead"].max_velocity = 300.0  # 7500mrev/s, well above probed

    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert "tuned below operating range" in caplog.text
    assert "FOCI_AUTOTUNE" in caplog.text


@pytest.mark.parametrize(
    ("probed_mrev_s", "max_velocity_mm_s", "case"),
    (
        (8000, 300.0, "below_probed"),  # 7500mrev/s < 8000mrev/s
        (7500, 300.0, "equal_to_probed"),  # 7500mrev/s == 7500mrev/s
        (1000, 44.0, "exactly_at_margin_threshold"),  # 1100mrev/s == 1000 * 1.10
    ),
)
def test_staleness_does_not_warn_at_or_within_margin_boundary(
    caplog, probed_mrev_s, max_velocity_mm_s, case
):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "rotation_distance": 40.0,
            },
        }
    )
    sections["foci stepper_x"]["autotune_status"] = "tuned"
    sections["foci stepper_x"]["autotune_probed_velocity_mrev_s"] = str(probed_mrev_s)
    printer._objects["toolhead"].max_velocity = max_velocity_mm_s

    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert "tuned below operating range" not in caplog.text, case


def test_staleness_does_not_raise_or_warn_when_max_velocity_is_non_numeric(caplog):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "rotation_distance": 40.0,
            },
        }
    )
    sections["foci stepper_x"]["autotune_status"] = "tuned"
    sections["foci stepper_x"]["autotune_probed_velocity_mrev_s"] = "5366"
    printer._objects["toolhead"].max_velocity = "not-a-number"

    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()  # must not raise

    assert "tuned below operating range" not in caplog.text


def test_staleness_does_not_raise_or_warn_when_toolhead_status_raises(caplog):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "rotation_distance": 40.0,
            },
        }
    )
    sections["foci stepper_x"]["autotune_status"] = "tuned"
    sections["foci stepper_x"]["autotune_probed_velocity_mrev_s"] = "5366"

    def _raise_get_status(_time):
        raise AttributeError("toolhead status unavailable")

    printer._objects["toolhead"].get_status = _raise_get_status

    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()  # must not raise

    assert "tuned below operating range" not in caplog.text


def test_staleness_does_not_warn_when_probed_velocity_absent(caplog):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
                "rotation_distance": 40.0,
            },
        }
    )
    printer._objects["toolhead"].max_velocity = 300.0

    driver = make_config_driver(printer, sections, "foci stepper_x")
    driver._handle_mcu_identify()

    driver._handle_connect()

    assert "tuned below operating range" not in caplog.text


def test_component_collision_across_entry_points_is_detected(monkeypatch):
    class FirstCommands:
        def __init__(self, driver):
            self.driver = driver

        def do_first(self, gcmd):
            pass

    class SecondCommands:
        def __init__(self, driver):
            self.driver = driver

        def do_second(self, gcmd):
            pass

    def register_first(driver):
        driver.shared_component = FirstCommands(driver)
        return (GcodeCommandSpec("FOCI_FIRST", "shared_component", "do_first", "first"),)

    def register_second(driver):
        driver.shared_component = SecondCommands(driver)
        return (GcodeCommandSpec("FOCI_SECOND", "shared_component", "do_second", "second"),)

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [
            _FakeEntryPoint("first", register_first),
            _FakeEntryPoint("second", register_second),
        ],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    with pytest.raises(printer.config_error("").__class__):
        make_config_driver(printer, sections, "foci stepper_x")


def test_register_returning_spec_for_unset_component_fails_loudly(monkeypatch):
    def broken_register(driver):
        # forgets to set driver.something before returning its spec
        return (GcodeCommandSpec("FOCI_BROKEN", "something", "do_it", "broken"),)

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("broken", broken_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    with pytest.raises(printer.config_error("").__class__, match="something"):
        make_config_driver(printer, sections, "foci stepper_x")


def test_register_returning_spec_for_unset_handler_fails_loudly(monkeypatch):
    class FakeComponent:
        def __init__(self, driver):
            self.driver = driver

        # deliberately has no `do_it` method

    def broken_register(driver):
        driver.fake_component = FakeComponent(driver)
        return (GcodeCommandSpec("FOCI_BROKEN_HANDLER", "fake_component", "do_it", "broken"),)

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("broken", broken_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    with pytest.raises(printer.config_error("").__class__, match="do_it"):
        make_config_driver(printer, sections, "foci stepper_x")


def test_successful_entry_point_command_registers_alongside_core(monkeypatch):
    class FakeComponent:
        def __init__(self, driver):
            self.driver = driver

        def do_fake_thing(self, gcmd):
            pass

    def fake_register(driver):
        driver.fake_component = FakeComponent(driver)
        return (GcodeCommandSpec("FOCI_FAKE_THING", "fake_component", "do_fake_thing", "test"),)

    monkeypatch.setattr(
        "klipper_foci.registry.entry_points",
        lambda *, group: [_FakeEntryPoint("fake", fake_register)],
    )
    printer, _chips, sections = make_config_printer(
        {"stepper_x": {"step_pin": "foci:STEP0", "dir_pin": "foci:DIR0", "oid": 10}},
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")
    gcode = printer.lookup_object("gcode")
    handlers_by_name = {args[0]: args[3] for args, _kwargs in gcode._mux_commands}
    assert "FOCI_FAKE_THING" in handlers_by_name
    bound_method = handlers_by_name["FOCI_FAKE_THING"]
    assert bound_method.__self__ is driver.fake_component
    assert bound_method.__func__.__name__ == "do_fake_thing"
    # Not an exact-count assertion: GCODE_COMMANDS may contain more entries
    # than any one entry point's specs, and this only needs to confirm none
    # of them were displaced by the entry-point registration pass.
    for spec in GCODE_COMMANDS:
        assert spec.name in handlers_by_name
