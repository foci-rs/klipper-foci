"""Tests for FOCI MCU config-build command emission."""

import pytest
from klipper_foci.config import velocity_mm_s_to_mrev_s

from tests.mocks import CommandError, MockMCU, make_config_driver, make_config_printer


def test_package_entry_points_import_driver_and_global_config():
    import klipper_foci
    from klipper_foci.driver import FociDriver
    from klipper_foci.registry import FociGlobalConfig

    assert klipper_foci.FociDriver is FociDriver
    assert klipper_foci.FociGlobalConfig is FociGlobalConfig
    assert callable(klipper_foci.load_config)
    assert callable(klipper_foci.load_config_prefix)


DEFAULT_COMMANDS = {
    "FOCI_SELFTEST",
    "FOCI_SETUP",
    "FOCI_AUTOTUNE",
    "DUMP_FOCI",
    "DUMP_TMC",
    "FOCI_SET_GAINS",
    "FOCI_SET_INNER_GAINS",
    "FOCI_SET_FILTERS",
    "FOCI_SET_CURRENT",
    "FOCI_SET_VELOCITY_FEEDFORWARD",
}

ADVANCED_COMMANDS = {
    "FOCI_STEP_POSITION",
    "FOCI_STEPPER_STATS",
    "FOCI_STACK_WATERMARK",
}

EXPERT_COMMANDS = {
    "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
    "FOCI_SET_ACCEL_FEEDFORWARD",
    "FOCI_SET_DECOUPLING_FEEDFORWARD",
    "FOCI_SET_POSITION_LEAD",
    "FOCI_SET_PHASE_ADVANCE",
    "FOCI_SET_VOLTAGE_LIMIT",
    "FOCI_CURRENT_STEP_TEST",
    "FOCI_CURRENT_VECTOR_STEP_TEST",
    "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
    "FOCI_POSITION_TORQUE_OFFSET_TEST",
    "FOCI_VOLTAGE_STEP_TEST",
    "FOCI_RESISTANCE_TEST",
}

DEVELOPER_COMMANDS = {
    "FOCI_TMC_READ_REGISTER",
    "FOCI_TMC_WRITE_REGISTER",
}


class ProductionMcu(MockMCU):
    """Mock MCU whose data dictionary does not expose dev TMC commands."""

    def lookup_command(self, fmt, cq=None):
        if fmt.startswith("tmc_write_register "):
            raise CommandError("unknown command")
        return super().lookup_command(fmt, cq=cq)

    def lookup_query_command(self, send_fmt, recv_fmt, oid=None):
        if send_fmt.startswith("tmc_read_register "):
            raise CommandError("unknown query command")
        return super().lookup_query_command(send_fmt, recv_fmt, oid=oid)


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


def build_driver_with_mode(mode=None):
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
        foci_mode=mode,
    )
    make_config_driver(printer, sections, "foci stepper_x")
    return printer


def test_absent_foci_section_registers_default_commands_only():
    printer = build_driver_with_mode(None)

    assert registered_command_names(printer) == DEFAULT_COMMANDS


def test_explicit_default_mode_registers_default_commands_only():
    printer = build_driver_with_mode("default")

    assert registered_command_names(printer) == DEFAULT_COMMANDS


def test_advanced_mode_registers_default_and_advanced_commands_only():
    printer = build_driver_with_mode("advanced")

    assert registered_command_names(printer) == DEFAULT_COMMANDS | ADVANCED_COMMANDS


def test_expert_mode_registers_default_advanced_and_expert_commands():
    printer = build_driver_with_mode("expert")

    assert registered_command_names(printer) == (
        DEFAULT_COMMANDS | ADVANCED_COMMANDS | EXPERT_COMMANDS
    )


def test_developer_mode_defers_raw_tmc_commands_until_mcu_identify():
    printer = build_driver_with_mode("developer")

    assert registered_command_names(printer) == (
        DEFAULT_COMMANDS | ADVANCED_COMMANDS | EXPERT_COMMANDS
    )


def test_developer_mode_registers_raw_tmc_commands_for_dev_firmware():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
        foci_mode="developer",
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")

    assert DEVELOPER_COMMANDS.isdisjoint(registered_command_names(printer))

    driver._handle_mcu_identify()

    assert registered_command_names(printer) == (
        DEFAULT_COMMANDS | ADVANCED_COMMANDS | EXPERT_COMMANDS | DEVELOPER_COMMANDS
    )


def test_developer_mode_omits_raw_tmc_commands_for_production_firmware():
    printer, _chips, sections = make_config_printer(
        {
            "stepper_x": {
                "step_pin": "foci:STEP0",
                "dir_pin": "foci:DIR0",
                "oid": 10,
            },
        },
        chips={"foci": ProductionMcu("foci")},
        foci_mode="developer",
    )
    driver = make_config_driver(printer, sections, "foci stepper_x")

    driver._handle_mcu_identify()

    assert registered_command_names(printer) == (
        DEFAULT_COMMANDS | ADVANCED_COMMANDS | EXPERT_COMMANDS
    )


def test_invalid_global_foci_mode_reports_valid_modes():
    with pytest.raises(CommandError) as excinfo:
        build_driver_with_mode("unsafe")

    message = str(excinfo.value)
    assert "mode" in message
    for mode in ("default", "advanced", "expert", "developer"):
        assert mode in message


def test_registry_resolves_component_handler_and_inline_help():
    from klipper_foci.registry import GcodeCommandSpec, register_gcode_commands

    class Component:
        def handle(self, gcmd):
            return None

    class Driver:
        stepper_name = "stepper_x"

        def __init__(self):
            self.component = Component()

    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")
    gcode._mux_commands.clear()

    driver = Driver()
    specs = (
        GcodeCommandSpec(
            name="FOCI_TEST",
            min_mode="default",
            component="component",
            handler_name="handle",
            help_text="test command",
        ),
    )

    register_gcode_commands(driver, gcode, "default", command_specs=specs)

    args, kwargs = gcode._mux_commands[0]
    assert args[:3] == ("FOCI_TEST", "STEPPER", "stepper_x")
    assert args[3].__self__ is driver.component
    assert args[3].__func__ is driver.component.handle.__func__
    assert kwargs["desc"] == "test command"


def test_dump_commands_register_register_dump_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    dump_handlers = {
        args[0]: args[3]
        for args, _kwargs in gcode._mux_commands
        if args[0] in {"DUMP_FOCI", "DUMP_TMC"}
    }

    assert dump_handlers["DUMP_FOCI"].__self__.__class__.__name__ == ("RegisterDumpWorkflow")
    assert dump_handlers["DUMP_TMC"].__self__.__class__.__name__ == ("RegisterDumpWorkflow")


def test_default_control_commands_register_controls_workflow_handlers():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_SET_GAINS",
        "FOCI_SET_INNER_GAINS",
        "FOCI_SET_CURRENT",
        "FOCI_SET_VELOCITY_FEEDFORWARD",
    }

    handlers = {
        args[0]: args[3] for args, _kwargs in gcode._mux_commands if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "ControlsWorkflow" for handler in handlers.values()
    )


def test_expert_control_commands_register_controls_workflow_handlers():
    printer = build_driver_with_mode("expert")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_SET_VELOCITY_TRANSIENT_FEEDFORWARD",
        "FOCI_SET_ACCEL_FEEDFORWARD",
        "FOCI_SET_DECOUPLING_FEEDFORWARD",
        "FOCI_SET_POSITION_LEAD",
        "FOCI_SET_PHASE_ADVANCE",
        "FOCI_SET_VOLTAGE_LIMIT",
    }

    handlers = {
        args[0]: args[3] for args, _kwargs in gcode._mux_commands if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "ControlsWorkflow" for handler in handlers.values()
    )


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
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    handler = next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_SETUP")

    assert handler.__self__.__class__.__name__ == "CommissioningWorkflow"


def test_selftest_registers_selftest_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    handler = next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_SELFTEST")

    assert handler.__self__.__class__.__name__ == "SelftestWorkflow"


def test_autotune_registers_autotune_workflow_handler():
    printer = build_driver_with_mode("default")
    gcode = printer.lookup_object("gcode")

    handler = next(args[3] for args, _kwargs in gcode._mux_commands if args[0] == "FOCI_AUTOTUNE")

    assert handler.__self__.__class__.__name__ == "AutotuneWorkflow"


def test_observation_diagnostics_register_diagnostics_workflow_handlers():
    printer = build_driver_with_mode("advanced")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_STEP_POSITION",
        "FOCI_STEPPER_STATS",
    }

    handlers = {
        args[0]: args[3] for args, _kwargs in gcode._mux_commands if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "DiagnosticsWorkflow"
        for handler in handlers.values()
    )


def test_active_diagnostics_register_diagnostics_workflow_handlers():
    printer = build_driver_with_mode("expert")
    gcode = printer.lookup_object("gcode")
    command_names = {
        "FOCI_CURRENT_STEP_TEST",
        "FOCI_CURRENT_VECTOR_STEP_TEST",
        "FOCI_CURRENT_TORQUE_SAMPLE_TEST",
        "FOCI_POSITION_TORQUE_OFFSET_TEST",
        "FOCI_VOLTAGE_STEP_TEST",
        "FOCI_RESISTANCE_TEST",
    }

    handlers = {
        args[0]: args[3] for args, _kwargs in gcode._mux_commands if args[0] in command_names
    }

    assert set(handlers) == command_names
    assert all(
        handler.__self__.__class__.__name__ == "DiagnosticsWorkflow"
        for handler in handlers.values()
    )


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
        "foci_stepper_exec_stats_result oid=%c channel=%c"
        " executed_pos_steps=%u executed_neg_steps=%u"
        " physical_pos_pulses=%u physical_neg_pulses=%u"
        " planner_steps_per_rev=%u encoder_ppr=%u"
        " encoder_counts_per_rev=%u tmc_grid=%u"
        " physical_step_width=%u motion_scale_configured=%c"
        " step_half_period_ticks=%u dir_setup_ticks=%u"
        " waveform_worst_case_ticks=%u fatal_lateness_ticks=%u"
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
            "identified_ringing_count": 7,
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


def test_resistance_test_registers_in_expert_mode():
    printer = build_driver_with_mode("expert")

    assert "FOCI_RESISTANCE_TEST" in registered_command_names(printer)


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
