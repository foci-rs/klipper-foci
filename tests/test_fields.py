#!/usr/bin/env python3
# Unit tests for TMC4671 field formatting.
# Run: cd foci/klipper-foci && python -m pytest tests/ -v
#
# Copyright (C) 2026 Morton Jonuschat
# SPDX-License-Identifier: GPL-3.0-or-later

import unittest

from klipper_foci.driver import (
    DUMP_GROUPS,
    FieldHelper,
    Fields,
    REGISTERS,
    SIGNED_FIELDS,
    FIELD_FORMATTERS,
    _ffs,
    _fmt_q4_12,
    _fmt_q8_8,
    _fmt_motor_type,
    _fmt_phi_e,
    _fmt_motion_mode,
    _fmt_angle_source,
    _fmt_velocity_meter,
)


class TestFFS(unittest.TestCase):
    def test_bit0(self):
        self.assertEqual(_ffs(0x01), 0)

    def test_bit8(self):
        self.assertEqual(_ffs(0xFF00), 8)

    def test_bit16(self):
        self.assertEqual(_ffs(0xFFFF0000), 16)

    def test_single_high_bit(self):
        self.assertEqual(_ffs(1 << 31), 31)


class TestFieldExtraction(unittest.TestCase):
    def setUp(self):
        self.fh = FieldHelper(Fields, SIGNED_FIELDS, FIELD_FORMATTERS)

    def test_unsigned_lower_half(self):
        val = self.fh.get_field("n_pole_pairs", "MOTOR_TYPE_N_POLE_PAIRS", 0x00020032)
        self.assertEqual(val, 50)

    def test_unsigned_upper_half(self):
        val = self.fh.get_field("motor_type", "MOTOR_TYPE_N_POLE_PAIRS", 0x00020032)
        self.assertEqual(val, 2)

    def test_unsigned_3bit_field(self):
        val = self.fh.get_field("phi_e", "PHI_E_SELECTION", 0x00000003)
        self.assertEqual(val, 3)

    def test_velocity_selection_fields(self):
        val = self.fh.get_field("velocity_selection", "VELOCITY_SELECTION", 0x00000109)
        self.assertEqual(val, 9)
        val = self.fh.get_field(
            "velocity_meter_selection", "VELOCITY_SELECTION", 0x00000109
        )
        self.assertEqual(val, 1)

    def test_position_selection_field(self):
        val = self.fh.get_field("position_selection", "POSITION_SELECTION", 0x00000009)
        self.assertEqual(val, 9)

    def test_signed_positive(self):
        val = self.fh.get_field("torque_actual", "PID_TORQUE_FLUX_ACTUAL", 0x00C80000)
        self.assertEqual(val, 200)

    def test_signed_negative(self):
        val = self.fh.get_field("flux_actual", "PID_TORQUE_FLUX_ACTUAL", 0x0000FFFA)
        self.assertEqual(val, -6)

    def test_signed_zero(self):
        val = self.fh.get_field("flux_actual", "PID_TORQUE_FLUX_ACTUAL", 0x00C80000)
        self.assertEqual(val, 0)

    def test_single_bit_set(self):
        val = self.fh.get_field("abn_direction", "ABN_DECODER_MODE", 0x00001000)
        self.assertEqual(val, 1)

    def test_single_bit_clear(self):
        val = self.fh.get_field("abn_direction", "ABN_DECODER_MODE", 0x00000000)
        self.assertEqual(val, 0)


class TestFormatters(unittest.TestCase):
    def test_q4_12(self):
        self.assertEqual(_fmt_q4_12(4096), "1.000")

    def test_q4_12_fractional(self):
        self.assertEqual(_fmt_q4_12(404), "0.099")

    def test_q8_8(self):
        self.assertEqual(_fmt_q8_8(256), "1.000")

    def test_q8_8_integer(self):
        self.assertEqual(_fmt_q8_8(25600), "100.000")

    def test_motor_type_stepper(self):
        self.assertEqual(_fmt_motor_type(2), "2(stepper)")

    def test_motor_type_bldc(self):
        self.assertEqual(_fmt_motor_type(3), "3(bldc)")

    def test_phi_e_abn(self):
        self.assertEqual(_fmt_phi_e(3), "abn")

    def test_motion_mode_position(self):
        self.assertEqual(_fmt_motion_mode(3), "position")

    def test_motion_mode_stopped(self):
        self.assertEqual(_fmt_motion_mode(0), "stopped")

    def test_angle_source_phi_m_abn(self):
        self.assertEqual(_fmt_angle_source(9), "9(phi_m_abn)")

    def test_velocity_meter_advanced(self):
        self.assertEqual(_fmt_velocity_meter(1), "1(advanced)")


class TestPrettyFormat(unittest.TestCase):
    def setUp(self):
        self.fh = FieldHelper(Fields, SIGNED_FIELDS, FIELD_FORMATTERS)

    def test_all_zeros_no_fields(self):
        out = self.fh.pretty_format("STATUS_FLAGS", 0x00000000)
        self.assertIn("STATUS_FLAGS:", out)
        self.assertIn("00000000", out)
        self.assertNotIn("=", out)

    def test_status_errsum_flags(self):
        out = self.fh.pretty_format("STATUS_FLAGS", 0x00004488)
        self.assertIn("pid_x_output_limit=1", out)
        self.assertIn("pid_v_output_limit=1", out)
        self.assertIn("pid_id_errsum_limit=1", out)
        self.assertIn("pid_iq_errsum_limit=1", out)

    def test_pid_error_sums_are_signed(self):
        out = self.fh.pretty_format("PID_TORQUE_ERROR_SUM", 0xFFFFFFFE)
        self.assertIn("torque_error_sum=-2", out)

    def test_pid_velocity_actual_is_dumped_as_signed_register(self):
        self.assertEqual(REGISTERS["PID_VELOCITY_ACTUAL"], 0x6A)
        out = self.fh.pretty_format("PID_VELOCITY_ACTUAL", 0xFFFFFFFE)
        self.assertIn("velocity_actual=-2", out)

    def test_advanced_pi_representation_is_named_dump_field(self):
        self.assertEqual(REGISTERS["CONFIG_ADVANCED_PI_REPRESENT"], 0x86)
        out = self.fh.pretty_format("CONFIG_ADVANCED_PI_REPRESENT", 0x00000015)
        self.assertIn("current_i_q4_12=1", out)
        self.assertIn("velocity_i_q4_12=1", out)
        self.assertIn("position_i_q4_12=1", out)
        self.assertNotIn("current_p_q4_12", out)

    def test_adc_i_select_is_named_current_dump_field(self):
        self.assertEqual(REGISTERS["ADC_I_SELECT"], 0x0A)
        current_group = next(regs for title, regs in DUMP_GROUPS if title == "Current")
        self.assertIn("ADC_I_SELECT", current_group)
        out = self.fh.pretty_format("ADC_I_SELECT", 0x18000100)
        self.assertIn("adc_i1_select=1", out)
        self.assertIn("adc_i_v_select=2", out)
        self.assertIn("adc_i_wy_select=1", out)

    def test_pwm_bbm_is_named_status_dump_field(self):
        self.assertEqual(REGISTERS["PWM_BBM_H_BBM_L"], 0x19)
        status_group = next(regs for title, regs in DUMP_GROUPS if title == "Status")
        self.assertIn("PWM_BBM_H_BBM_L", status_group)
        out = self.fh.pretty_format("PWM_BBM_H_BBM_L", 0x00002828)
        self.assertIn("bbm_l=40", out)
        self.assertIn("bbm_h=40", out)

    def test_motor_type_fields(self):
        out = self.fh.pretty_format("MOTOR_TYPE_N_POLE_PAIRS", 0x00020032)
        self.assertIn("motor_type=2(stepper)", out)
        self.assertIn("n_pole_pairs=50", out)

    def test_selection_fields_are_pretty_formatted(self):
        out = self.fh.pretty_format("VELOCITY_SELECTION", 0x00000109)
        self.assertIn("velocity_selection=9(phi_m_abn)", out)
        self.assertIn("velocity_meter_selection=1(advanced)", out)
        out = self.fh.pretty_format("POSITION_SELECTION", 0x00000009)
        self.assertIn("position_selection=9(phi_m_abn)", out)

    def test_signed_negative_shown(self):
        out = self.fh.pretty_format("PID_TORQUE_FLUX_ACTUAL", 0x00C8FFFA)
        self.assertIn("flux_actual=-6", out)
        self.assertIn("torque_actual=200", out)

    def test_zero_fields_hidden(self):
        out = self.fh.pretty_format("PID_TORQUE_FLUX_ACTUAL", 0x0000FFFA)
        self.assertNotIn("torque_actual", out)
        self.assertIn("flux_actual=-6", out)

    def test_pid_torque_flux_limits_is_single_current_limit(self):
        out = self.fh.pretty_format("PID_TORQUE_FLUX_LIMITS", 0x0000072C)
        self.assertIn("current_limit=1836", out)
        self.assertNotIn("flux_limit", out)
        self.assertNotIn("torque_limit", out)

    def test_pid_q_format(self):
        out = self.fh.pretty_format("PID_FLUX_P_FLUX_I", 0x10000800)
        self.assertIn("flux_p=", out)
        self.assertIn("flux_i=", out)

    def test_current_i_uses_advanced_pi_zero_scale(self):
        out = self.fh.pretty_format("PID_FLUX_P_FLUX_I", 0x01000100)
        self.assertIn("flux_p=1.000", out)
        self.assertIn("flux_i=256(q8.8=1.000,zero=256/65536)", out)
        self.assertNotIn("flux_i=1.000", out)

    def test_register_without_fields(self):
        fh = FieldHelper({}, [], {})
        out = fh.pretty_format("UNKNOWN_REG", 0xDEADBEEF)
        self.assertIn("UNKNOWN_REG:", out)
        self.assertIn("deadbeef", out)


if __name__ == "__main__":
    unittest.main()
