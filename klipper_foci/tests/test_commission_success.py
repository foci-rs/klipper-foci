"""Tests for commissioning success and persistence."""

from tests.mocks import (
    MockConfigFile,
    MockGCmd,
    complete_commission_result,
    make_driver,
    timing_reply,
)


def test_commission_without_configured_velocity_limit_persists_firmware_default():
    driver = make_driver()
    configfile = MockConfigFile()
    driver.printer._objects["configfile"] = configfile
    driver.settings.pid_velocity_limit = None

    def drive_success(_args):
        driver.commissioning.result = complete_commission_result()
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_success
    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert driver.state.active_gains["velocity_limit"] == 500_000
    assert configfile.values[(driver.name, "pid_velocity_limit")] == "500000"
    assert configfile.values[(driver.name, "commissioning_status")] == "commissioned"


def test_commission_success_stages_commissioning_state_and_outer_gains_only():
    driver = make_driver()
    configfile = MockConfigFile()
    driver.printer._objects["configfile"] = configfile
    driver.settings.pid_velocity_limit = 120_000
    result = complete_commission_result()
    result.update(velocity_p=1100, velocity_i=48, position_p=600)

    def drive_success(_args):
        driver.commissioning.result = result
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_success
    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    staged = {key: value for (_section, key), value in configfile.values.items()}
    assert all(section == driver.name for section, _key in configfile.values)
    assert staged["commissioning_status"] == "commissioned"
    assert staged["commissioning_profile"] == "balanced"
    assert staged["pid_velocity_p"] == "1100"
    assert staged["pid_velocity_i"] == "48"
    assert staged["pid_position_p"] == "600"
    assert staged["pid_position_i"] == "0"
    assert staged["pid_velocity_limit"] == "120000"
    assert not [key for key in staged if key.startswith(("commissioned_", "autotune_"))]


COMMISSION_DONE_REPLY_FORMAT = (
    "foci_commission_done oid=%c status=%c r_count_milli=%u l_count_micro=%u flux_p=%hu "
    "flux_i=%hu torque_p=%hu torque_i=%hu lambda_us=%u theta_e_us=%u theta_source=%c "
    "bandwidth_hz=%hu velocity_p=%hu velocity_i=%hu position_p=%hu inner_warning_flags=%c "
    "timing_summary=%u"
)

COMMISSION_DONE_REPLY_VALUES = {
    "oid": 3,
    "status": 0,
    "r_count_milli": 1706,
    "l_count_micro": 1245,
    "flux_p": 256,
    "flux_i": 416,
    "torque_p": 256,
    "torque_i": 416,
    "lambda_us": 0,
    "theta_e_us": 160,
    "theta_source": 1,
    "bandwidth_hz": 0,
    "velocity_p": 1100,
    "velocity_i": 48,
    "position_p": 600,
    "inner_warning_flags": 0,
    "timing_summary": 0,
}


def captured_commission_done_reply() -> dict:
    """Build the params Klipper delivers for the captured foci_commission_done format."""
    message_name, *fields = (
        token.partition("=")[0] for token in COMMISSION_DONE_REPLY_FORMAT.split()
    )
    assert sorted(fields) == sorted(COMMISSION_DONE_REPLY_VALUES)
    return {
        "#name": message_name,
        **{field: COMMISSION_DONE_REPLY_VALUES[field] for field in fields},
    }


def test_commission_done_reply_persists_its_gains_as_pid_keys():
    driver = make_driver()
    configfile = MockConfigFile()
    driver.printer._objects["configfile"] = configfile
    driver.settings.pid_velocity_limit = 120_000

    def drive_reply(_args):
        driver.commissioning.handle_commission_done(captured_commission_done_reply())

    driver.protocol.commands.commission.send = drive_reply
    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    staged = {key: value for (_section, key), value in configfile.values.items()}
    assert staged["pid_velocity_p"] == "1100"
    assert staged["pid_velocity_i"] == "48"
    assert staged["pid_position_p"] == "600"
    assert staged["pid_position_i"] == "0"
    assert staged["pid_velocity_limit"] == "120000"
    assert driver.state.active_gains["velocity_p"] == 1100
    assert driver.state.active_gains["velocity_i"] == 48
    assert driver.state.active_gains["position_p"] == 600


def test_commission_success_replaces_previously_pasted_outer_gains():
    driver = make_driver()
    configfile = MockConfigFile()
    driver.printer._objects["configfile"] = configfile
    configfile.set(driver.name, "pid_velocity_p", "1408")
    configfile.set(driver.name, "pid_position_p", "704")

    def drive_success(_args):
        driver.commissioning.result = complete_commission_result()
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_success
    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert configfile.values[(driver.name, "pid_velocity_p")] == "1152"
    assert configfile.values[(driver.name, "pid_position_p")] == "640"


def test_commission_start_clears_stale_timing_cache():
    driver = make_driver()
    driver.printer._objects["configfile"] = MockConfigFile()
    driver.commissioning.handle_commission_timing(timing_reply())

    def drive_success(_args):
        driver.commissioning.result = complete_commission_result()
        driver.commissioning.done = True

    driver.protocol.commands.commission.send = drive_success
    driver.commissioning.commission(MockGCmd({"PROFILE": "balanced"}))

    assert driver.commissioning.timing_by_method == {}
