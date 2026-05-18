"""Unit tests for FOCI trace capture parsing.

Tests the Python-side sample unpacking, signed field conversion, and
phase filtering logic from cmd_FOCI_TRACE without requiring Klipper
or hardware.

Run: cd foci/klipper-foci && python -m pytest tests/ -v
"""

import math
import struct
import unittest

from foci import (
    TRACE_FAST_HEADERS,
    TRACE_FULL_HEADERS,
    TRACE_HOLD_HEADERS,
    TRACE_VELOCITY_HEADERS,
    _format_trace_summary,
    _trace_summary_metrics,
)


def _i16(val: int) -> int:
    """Convert unsigned 16-bit half to signed i16.

    Duplicated from foci.py cmd_FOCI_TRACE (local function).
    """
    return val - 0x10000 if val >= 0x8000 else val


def parse_fast_sample(data: bytes) -> list:
    """Parse a 28-byte fast-preset trace sample.

    Returns: [tick, phase, flags, pos_tgt, pos_act, trq_act, flx_act,
              vel_act, status, abn]
    """
    fmt = "<HBBiiIiIi"
    fields = struct.unpack(fmt, data)
    row = list(fields[:3])  # tick, phase, flags
    row.extend(list(fields[3:5]))  # pos_tgt, pos_act
    tf_act = fields[5]
    row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
    row.append(_i16(tf_act & 0xFFFF))  # flux_actual
    row.extend(list(fields[6:]))  # vel_act, status, abn
    return row


def parse_full_sample(data: bytes) -> list:
    """Parse a 48-byte full-preset trace sample.

    Returns: [tick, phase, flags, pos_tgt, pos_act, trq_act, flx_act,
              vel_act, status, abn, trq_tgt, flx_tgt, vel_ofs,
              esum_pos, esum_vel, esum_trq]
    """
    fmt = "<HBBiiIiIiIiiii"
    fields = struct.unpack(fmt, data)
    row = list(fields[:3])  # tick, phase, flags
    row.extend(list(fields[3:5]))  # pos_tgt, pos_act
    tf_act = fields[5]
    row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
    row.append(_i16(tf_act & 0xFFFF))  # flux_actual
    row.extend(list(fields[6:9]))  # vel_act, status, abn
    tf_tgt = fields[9]
    row.append(_i16((tf_tgt >> 16) & 0xFFFF))  # torque_target
    row.append(_i16(tf_tgt & 0xFFFF))  # flux_target
    row.extend(list(fields[10:]))  # vel_ofs, esum_pos/vel/trq
    return row


def parse_velocity_sample(data: bytes) -> list:
    """Parse a 52-byte velocity-preset trace sample.

    Returns: [tick, phase, flags, pos_tgt, pos_act, trq_act, flx_act,
              pidout_vel, status, abn, pos_err, pidout_trq, pidout_flx,
              pidin_vel, vel_actual, vel_ofs]
    """
    fmt = "<HBBiiIiIiiiiiii"
    fields = struct.unpack(fmt, data)
    row = list(fields[:3])  # tick, phase, flags
    row.extend(list(fields[3:5]))  # pos_tgt, pos_act
    tf_act = fields[5]
    row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
    row.append(_i16(tf_act & 0xFFFF))  # flux_actual
    row.extend(list(fields[6:9]))  # pidout_vel, status, abn
    row.extend(
        list(fields[9:])
    )  # pos_err, pidout_trq, pidout_flx, pidin_vel, vel_actual, vel_ofs
    return row


def parse_hold_sample(data: bytes) -> list:
    """Parse a 52-byte hold-preset trace sample.

    Returns: [tick, phase, flags, pos_tgt, pos_act, trq_act, flx_act,
              pidout_vel, status, abn, pidout_trq, pidout_flx, foc_uq,
              foc_ud, foc_uq_lim, foc_ud_lim, esum_trq, esum_flx]
    """
    fmt = "<HBBiiIiIiiiIIii"
    fields = struct.unpack(fmt, data)
    row = list(fields[:3])  # tick, phase, flags
    row.extend(list(fields[3:5]))  # pos_tgt, pos_act
    tf_act = fields[5]
    row.append(_i16((tf_act >> 16) & 0xFFFF))  # torque_actual
    row.append(_i16(tf_act & 0xFFFF))  # flux_actual
    row.extend(list(fields[6:9]))  # pidout_vel, status, abn
    row.extend(list(fields[9:11]))  # pidout_trq, pidout_flx
    foc_uq_ud = fields[11]
    row.append(_i16((foc_uq_ud >> 16) & 0xFFFF))  # foc_uq
    row.append(_i16(foc_uq_ud & 0xFFFF))  # foc_ud
    foc_uq_ud_limited = fields[12]
    row.append(_i16((foc_uq_ud_limited >> 16) & 0xFFFF))  # foc_uq_lim
    row.append(_i16(foc_uq_ud_limited & 0xFFFF))  # foc_ud_lim
    row.extend(list(fields[13:]))  # esum_trq, esum_flx
    return row


class TestI16Conversion(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(_i16(200), 200)

    def test_zero(self):
        self.assertEqual(_i16(0), 0)

    def test_max_positive(self):
        self.assertEqual(_i16(0x7FFF), 32767)

    def test_minus_one(self):
        self.assertEqual(_i16(0xFFFF), -1)

    def test_min_negative(self):
        self.assertEqual(_i16(0x8000), -32768)

    def test_small_negative(self):
        self.assertEqual(_i16(0xFFFA), -6)


class TestFastPresetParsing(unittest.TestCase):
    def test_basic_sample(self):
        """Pack a known fast sample and verify unpacking."""
        tick = 42
        phase = 17
        flags = 0
        pos_tgt = 65536
        pos_act = 65530
        # torque=200, flux=-6 → packed as (200 << 16) | (0xFFFA)
        tf_act = (200 << 16) | 0xFFFA
        vel_act = 1000
        status = 0x70000080
        abn = 100

        data = struct.pack(
            "<HBBiiIiIi",
            tick,
            phase,
            flags,
            pos_tgt,
            pos_act,
            tf_act,
            vel_act,
            status,
            abn,
        )
        self.assertEqual(len(data), 28)

        row = parse_fast_sample(data)
        self.assertEqual(row[0], 42)  # tick
        self.assertEqual(row[1], 17)  # phase
        self.assertEqual(row[2], 0)  # flags
        self.assertEqual(row[3], 65536)  # pos_tgt
        self.assertEqual(row[4], 65530)  # pos_act
        self.assertEqual(row[5], 200)  # torque_actual (signed)
        self.assertEqual(row[6], -6)  # flux_actual (signed)
        self.assertEqual(row[7], 1000)  # vel_act
        self.assertEqual(row[8], 0x70000080)  # status
        self.assertEqual(row[9], 100)  # abn

    def test_negative_torque(self):
        """Negative torque value should unpack correctly."""
        # torque=-100 (0xFF9C), flux=0
        tf_act = (0xFF9C << 16) | 0
        data = struct.pack(
            "<HBBiiUiUi".replace("U", "I"), 0, 0, 0, 0, 0, tf_act, 0, 0, 0
        )
        row = parse_fast_sample(data)
        self.assertEqual(row[5], -100)  # torque
        self.assertEqual(row[6], 0)  # flux


class TestFullPresetParsing(unittest.TestCase):
    def test_basic_sample(self):
        """Pack a known full sample and verify unpacking."""
        tick = 10
        phase = 9
        flags = 1  # budget drop flag
        pos_tgt = -1000
        pos_act = -1005
        tf_act = (50 << 16) | 0xFFF0  # torque=50, flux=-16
        vel_act = -200
        status = 0x70000000
        abn = 42
        tf_tgt = (100 << 16) | 0xFFE0  # torque_tgt=100, flux_tgt=-32
        vel_ofs = 500
        esum_pos = 0
        esum_vel = -10
        esum_trq = 5

        data = struct.pack(
            "<HBBiiIiIiIiiii",
            tick,
            phase,
            flags,
            pos_tgt,
            pos_act,
            tf_act,
            vel_act,
            status,
            abn,
            tf_tgt,
            vel_ofs,
            esum_pos,
            esum_vel,
            esum_trq,
        )
        self.assertEqual(len(data), 48)

        row = parse_full_sample(data)
        self.assertEqual(row[0], 10)  # tick
        self.assertEqual(row[1], 9)  # phase
        self.assertEqual(row[2], 1)  # flags
        self.assertEqual(row[3], -1000)  # pos_tgt
        self.assertEqual(row[4], -1005)  # pos_act
        self.assertEqual(row[5], 50)  # torque_actual
        self.assertEqual(row[6], -16)  # flux_actual
        self.assertEqual(row[7], -200)  # vel_act
        self.assertEqual(row[8], 0x70000000)  # status
        self.assertEqual(row[9], 42)  # abn
        self.assertEqual(row[10], 100)  # torque_target
        self.assertEqual(row[11], -32)  # flux_target
        self.assertEqual(row[12], 500)  # vel_ofs
        self.assertEqual(row[13], 0)  # esum_pos
        self.assertEqual(row[14], -10)  # esum_vel
        self.assertEqual(row[15], 5)  # esum_trq


class TestVelocityPresetParsing(unittest.TestCase):
    def test_basic_sample(self):
        """Pack a known velocity sample and verify unpacking."""
        tick = 12
        phase = 4
        flags = 0
        pos_tgt = 2000
        pos_act = 1992
        tf_act = (30 << 16) | 0xFFF8  # torque=30, flux=-8
        pidout_vel = 96
        status = 0x70000080
        abn = 1234
        pos_err = -8
        pidout_trq = 80
        pidout_flx = -20
        pidin_vel = 104
        vel_actual = 91
        vel_ofs = 3

        data = struct.pack(
            "<HBBiiIiIiiiiiii",
            tick,
            phase,
            flags,
            pos_tgt,
            pos_act,
            tf_act,
            pidout_vel,
            status,
            abn,
            pos_err,
            pidout_trq,
            pidout_flx,
            pidin_vel,
            vel_actual,
            vel_ofs,
        )
        self.assertEqual(len(data), 52)

        row = parse_velocity_sample(data)
        self.assertEqual(row[0], 12)  # tick
        self.assertEqual(row[1], 4)  # phase
        self.assertEqual(row[2], 0)  # flags
        self.assertEqual(row[3], 2000)  # pos_tgt
        self.assertEqual(row[4], 1992)  # pos_act
        self.assertEqual(row[5], 30)  # torque_actual
        self.assertEqual(row[6], -8)  # flux_actual
        self.assertEqual(row[7], 96)  # pidout_vel
        self.assertEqual(row[8], 0x70000080)  # status
        self.assertEqual(row[9], 1234)  # abn
        self.assertEqual(row[10], -8)  # pos_err
        self.assertEqual(row[11], 80)  # pidout_target_torque
        self.assertEqual(row[12], -20)  # pidout_target_flux
        self.assertEqual(row[13], 104)  # pidin_vel
        self.assertEqual(row[14], 91)  # vel_actual
        self.assertEqual(row[15], 3)  # vel_ofs


class TestHoldPresetParsing(unittest.TestCase):
    def test_basic_sample(self):
        """Pack a known hold sample and verify unpacking."""
        tick = 120
        phase = 0
        flags = 0
        pos_tgt = 4000
        pos_act = 4000
        tf_act = (0xFFFE << 16) | 6  # torque=-2, flux=6
        pidout_vel = 0
        status = 0x70000000
        abn = 99
        pidout_trq = 18
        pidout_flx = -4
        foc_uq_ud = (24 << 16) | 0xFFF7  # uq=24, ud=-9
        foc_uq_ud_limited = (20 << 16) | 0xFFFA  # uq_lim=20, ud_lim=-6
        esum_trq = 12345
        esum_flx = -23456

        data = struct.pack(
            "<HBBiiIiIiiiIIii",
            tick,
            phase,
            flags,
            pos_tgt,
            pos_act,
            tf_act,
            pidout_vel,
            status,
            abn,
            pidout_trq,
            pidout_flx,
            foc_uq_ud,
            foc_uq_ud_limited,
            esum_trq,
            esum_flx,
        )
        self.assertEqual(len(data), 52)

        row = parse_hold_sample(data)
        self.assertEqual(row[0], 120)
        self.assertEqual(row[3], 4000)
        self.assertEqual(row[4], 4000)
        self.assertEqual(row[5], -2)
        self.assertEqual(row[6], 6)
        self.assertEqual(row[10], 18)
        self.assertEqual(row[11], -4)
        self.assertEqual(row[12], 24)
        self.assertEqual(row[13], -9)
        self.assertEqual(row[14], 20)
        self.assertEqual(row[15], -6)
        self.assertEqual(row[16], 12345)
        self.assertEqual(row[17], -23456)


class TestPhaseFiltering(unittest.TestCase):
    def test_filter_by_phase(self):
        samples = [
            [0, 9, 0],  # phase 9
            [1, 9, 0],  # phase 9
            [2, 17, 0],  # phase 17
            [3, 9, 0],  # phase 9
        ]
        phase_col = 1
        filtered = [s for s in samples if s[phase_col] == 9]
        self.assertEqual(len(filtered), 3)
        self.assertTrue(all(s[1] == 9 for s in filtered))

    def test_no_matching_phase(self):
        samples = [
            [0, 9, 0],
            [1, 17, 0],
        ]
        filtered = [s for s in samples if s[1] == 5]
        self.assertEqual(len(filtered), 0)


class TestSampleSizes(unittest.TestCase):
    def test_fast_sample_is_28_bytes(self):
        self.assertEqual(struct.calcsize("<HBBiiIiIi"), 28)

    def test_full_sample_is_48_bytes(self):
        self.assertEqual(struct.calcsize("<HBBiiIiIiIiiii"), 48)

    def test_velocity_sample_is_52_bytes(self):
        self.assertEqual(struct.calcsize("<HBBiiIiIiiiiiii"), 52)

    def test_hold_sample_is_52_bytes(self):
        self.assertEqual(struct.calcsize("<HBBiiIiIiiiIIii"), 52)


class TestTraceHeaders(unittest.TestCase):
    def test_velocity_column_names_pidout_signal(self):
        self.assertIn("pidout_vel", TRACE_FAST_HEADERS)
        self.assertIn("pidout_vel", TRACE_FULL_HEADERS)
        self.assertIn("pidout_vel", TRACE_VELOCITY_HEADERS)
        self.assertIn("pidout_vel", TRACE_HOLD_HEADERS)
        self.assertIn("pidout_trq", TRACE_VELOCITY_HEADERS)
        self.assertIn("pidout_flx", TRACE_VELOCITY_HEADERS)
        self.assertIn("pos_err", TRACE_VELOCITY_HEADERS)
        self.assertIn("vel_actual", TRACE_VELOCITY_HEADERS)
        self.assertIn("pidin_vel", TRACE_VELOCITY_HEADERS)
        self.assertNotIn("trq_tgt", TRACE_VELOCITY_HEADERS)
        self.assertNotIn("flx_tgt", TRACE_VELOCITY_HEADERS)
        self.assertNotIn("vel_act", TRACE_FAST_HEADERS)
        self.assertNotIn("vel_act", TRACE_FULL_HEADERS)

    def test_hold_column_names_expose_current_loop_signals(self):
        self.assertIn("trq_act", TRACE_HOLD_HEADERS)
        self.assertIn("flx_act", TRACE_HOLD_HEADERS)
        self.assertIn("pidout_trq", TRACE_HOLD_HEADERS)
        self.assertIn("pidout_flx", TRACE_HOLD_HEADERS)
        self.assertIn("foc_uq", TRACE_HOLD_HEADERS)
        self.assertIn("foc_ud", TRACE_HOLD_HEADERS)
        self.assertIn("foc_uq_lim", TRACE_HOLD_HEADERS)
        self.assertIn("foc_ud_lim", TRACE_HOLD_HEADERS)
        self.assertIn("esum_trq", TRACE_HOLD_HEADERS)
        self.assertIn("esum_flx", TRACE_HOLD_HEADERS)


class TestTraceSummary(unittest.TestCase):
    def test_velocity_metrics_quantify_tracking_and_sampling(self):
        samples = [
            # tick phase flags pos_tgt pos_act trq flx pidout status abn pos_err pidout_trq pidout_flx pidin vel_act ofs
            [0, 0, 0, 0, 0, 0, 0, 0, 0x70000000, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 100, 80, 0, 0, 90, 0x70000080, 0, 18, 12, -1, 100, 0, 2],
            [4, 0, 0, 200, 160, 0, 0, 95, 0x70000080, 0, 36, 14, -2, 100, 0, 3],
            [8, 0, 0, 300, 290, 0, 0, 20, 0x70000000, 0, 8, -5, 1, 25, 5, 1],
            [8, 0, 0, 300, 290, 0, 0, 20, 0x70000000, 0, 8, -5, 1, 25, 5, 1],
        ]

        metrics = _trace_summary_metrics(
            samples, TRACE_VELOCITY_HEADERS, expected_tick_step=2
        )

        self.assertEqual(metrics["sample_count"], 5)
        self.assertEqual(metrics["tick_start"], 0)
        self.assertEqual(metrics["tick_end"], 8)
        self.assertEqual(metrics["duplicate_ticks"], 1)
        self.assertEqual(metrics["missed_samples"], 1)
        self.assertEqual(metrics["position_error"]["min"], 0)
        self.assertEqual(metrics["position_error"]["max"], 40)
        self.assertEqual(metrics["position_error"]["final"], 10)
        self.assertEqual(metrics["position_error"]["max_abs"], 40)
        self.assertEqual(metrics["position_error"]["max_abs_tick"], 4)
        self.assertEqual(metrics["hardware_position_error"]["min"], 0)
        self.assertEqual(metrics["hardware_position_error"]["max"], 36)
        self.assertEqual(metrics["hardware_position_error"]["final"], 8)
        self.assertEqual(metrics["hardware_position_error"]["max_abs"], 36)
        self.assertEqual(metrics["hardware_position_error"]["max_abs_tick"], 4)
        self.assertEqual(metrics["derived_velocity"]["min"], 32.5)
        self.assertEqual(metrics["derived_velocity"]["max"], 40.0)
        self.assertEqual(metrics["derived_target_velocity"]["min"], 25.0)
        self.assertEqual(metrics["derived_target_velocity"]["max"], 50.0)
        self.assertEqual(metrics["derived_velocity_error"]["min"], -10.0)
        self.assertEqual(metrics["derived_velocity_error"]["max"], 7.5)
        self.assertEqual(metrics["pidin_vel"]["min"], 0)
        self.assertEqual(metrics["pidin_vel"]["max"], 100)
        self.assertEqual(metrics["pidout_vel"]["min"], 0)
        self.assertEqual(metrics["pidout_vel"]["max"], 95)
        self.assertEqual(metrics["vel_actual"]["nonzero"], 2)
        self.assertEqual(metrics["vel_ofs"]["max"], 3)
        self.assertEqual(metrics["pidout_trq"]["min"], -5)
        self.assertEqual(metrics["pidout_trq"]["max"], 14)
        self.assertEqual(metrics["pidout_flx"]["min"], -2)
        self.assertEqual(metrics["pidout_flx"]["max"], 1)
        self.assertEqual(metrics["status"]["pid_v_output_limit_samples"], 2)

    def test_velocity_metrics_bucket_position_error_by_motion_phase(self):
        samples = [
            # tick phase flags pos_tgt pos_act trq flx pidout status abn pos_err pidout_trq pidout_flx pidin vel_act ofs
            [0, 0, 0, 0, 0, 0, 0, 0, 0x70000000, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 20, 18, 0, 0, 0, 0x70000000, 0, 2, 0, 0, 0, 0, 0],
            [4, 0, 0, 60, 55, 0, 0, 0, 0x70000000, 0, 5, 0, 0, 0, 0, 0],
            [6, 0, 0, 100, 102, 0, 0, 0, 0x70000000, 0, -2, 0, 0, 0, 0, 0],
            [8, 0, 0, 120, 118, 0, 0, 0, 0x70000000, 0, 2, 0, 0, 0, 0, 0],
            [10, 0, 0, 120, 120, 0, 0, 0, 0x70000000, 0, 0, 0, 0, 0, 0, 0],
        ]

        metrics = _trace_summary_metrics(
            samples, TRACE_VELOCITY_HEADERS, expected_tick_step=2
        )

        phase_errors = metrics["position_error_by_motion_phase"]
        self.assertEqual(phase_errors["accel"]["count"], 1)
        self.assertEqual(phase_errors["accel"]["max_abs"], 5)
        self.assertEqual(phase_errors["cruise"]["count"], 1)
        self.assertEqual(phase_errors["cruise"]["max_abs"], -2)
        self.assertEqual(phase_errors["decel"]["count"], 1)
        self.assertEqual(phase_errors["decel"]["max_abs"], 2)

    def test_velocity_metrics_bucket_hardware_position_error_by_motion_phase(self):
        samples = [
            # tick phase flags pos_tgt pos_act trq flx pidout status abn pos_err pidout_trq pidout_flx pidin vel_act ofs
            [0, 0, 0, 0, 0, 0, 0, 0, 0x70000000, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 20, 18, 0, 0, 0, 0x70000000, 0, 3, 0, 0, 0, 0, 0],
            [4, 0, 0, 60, 55, 0, 0, 0, 0x70000000, 0, 7, 0, 0, 0, 0, 0],
            [6, 0, 0, 100, 102, 0, 0, 0, 0x70000000, 0, -4, 0, 0, 0, 0, 0],
            [8, 0, 0, 120, 118, 0, 0, 0, 0x70000000, 0, 5, 0, 0, 0, 0, 0],
            [10, 0, 0, 120, 120, 0, 0, 0, 0x70000000, 0, -1, 0, 0, 0, 0, 0],
        ]

        metrics = _trace_summary_metrics(
            samples, TRACE_VELOCITY_HEADERS, expected_tick_step=2
        )

        phase_errors = metrics["hardware_position_error_by_motion_phase"]
        self.assertEqual(phase_errors["accel"]["count"], 1)
        self.assertEqual(phase_errors["accel"]["max_abs"], 7)
        self.assertEqual(phase_errors["cruise"]["count"], 1)
        self.assertEqual(phase_errors["cruise"]["max_abs"], -4)
        self.assertEqual(phase_errors["decel"]["count"], 1)
        self.assertEqual(phase_errors["decel"]["max_abs"], 5)

    def test_velocity_metrics_report_final_settle_tail(self):
        samples = []
        for idx in range(40):
            pos_tgt = idx * 20
            if idx < 10:
                pos_err = 999
                pidout_vel = 999
                pidout_trq = 999
                vel_actual = 999
            else:
                tail_idx = idx - 9
                sign = -1 if tail_idx % 2 else 1
                pos_err = sign * tail_idx
                pidout_vel = 4
                pidout_trq = -3
                vel_actual = 5

            samples.append(
                [
                    idx * 2,
                    0,
                    0,
                    pos_tgt,
                    pos_tgt - pos_err,
                    0,
                    0,
                    pidout_vel,
                    0x70000000,
                    0,
                    pos_err,
                    pidout_trq,
                    0,
                    0,
                    vel_actual,
                    0,
                ]
            )

        metrics = _trace_summary_metrics(
            samples, TRACE_VELOCITY_HEADERS, expected_tick_step=2
        )

        settle = metrics["final_settle"]
        self.assertEqual(settle["window_size"], 30)
        self.assertEqual(settle["sample_count"], 30)
        self.assertEqual(settle["pos_err"]["max_abs"], 30)
        self.assertEqual(settle["pos_err"]["final"], 30)
        self.assertAlmostEqual(
            settle["pos_err"]["rms"],
            math.sqrt(sum(value * value for value in range(1, 31)) / 30),
        )
        self.assertEqual(settle["pidout_vel"]["max_abs"], 4)
        self.assertEqual(settle["pidout_vel"]["final"], 4)
        self.assertEqual(settle["pidout_vel"]["rms"], 4.0)
        self.assertEqual(settle["pidout_trq"]["max_abs"], 3)
        self.assertEqual(settle["pidout_trq"]["final"], -3)
        self.assertEqual(settle["pidout_trq"]["rms"], 3.0)
        self.assertEqual(settle["vel_actual"]["max_abs"], 5)
        self.assertEqual(settle["vel_actual"]["final"], 5)
        self.assertEqual(settle["vel_actual"]["rms"], 5.0)

    def test_summary_format_includes_velocity_fields(self):
        samples = [
            [0, 0, 0, 0, 0, 0, 0, 0, 0x70000000, 0, 0, 0, 0, 0, 0, 0],
            [2, 0, 0, 100, 80, 0, 0, 90, 0x70000080, 0, 18, 12, -1, 100, 0, 2],
        ]

        lines = _format_trace_summary(
            "foci stepper_x",
            samples,
            TRACE_VELOCITY_HEADERS,
            preset_name="velocity",
            sample_period_us=1000,
            dropped=0,
            expected_tick_step=2,
        )

        text = "\n".join(lines)
        self.assertIn("FOCI foci stepper_x trace summary: 2 samples", text)
        self.assertIn("1000us tick, 2000us samples", text)
        self.assertIn("position_error_counts:", text)
        self.assertIn("position_error_by_phase:", text)
        self.assertIn("hardware_position_error_counts:", text)
        self.assertIn("hardware_position_error_by_phase:", text)
        self.assertIn("derived_target_velocity_counts_per_tick:", text)
        self.assertIn("derived_actual_velocity_counts_per_tick:", text)
        self.assertIn("derived_velocity_error_counts_per_tick:", text)
        self.assertIn("pidin_vel:", text)
        self.assertIn("pidout_vel:", text)
        self.assertIn("pidout_trq:", text)
        self.assertIn("pidout_flx:", text)
        self.assertIn("vel_actual:", text)
        self.assertIn("vel_ofs:", text)
        self.assertIn("final_settle_last_30:", text)
        self.assertIn("pos_err(rms=", text)
        self.assertIn("pidout_vel(rms=", text)
        self.assertIn("pidout_trq(rms=", text)
        self.assertIn("vel_actual(rms=", text)

    def test_hold_metrics_report_current_loop_fields_and_100hz_period(self):
        samples = [
            # tick phase flags pos_tgt pos_act trq flx pidout status abn pidout_trq pidout_flx foc_uq foc_ud foc_uq_lim foc_ud_lim esum_trq esum_flx
            [
                0,
                0,
                0,
                1000,
                1000,
                4,
                -1,
                0,
                0x70000000,
                0,
                12,
                -2,
                20,
                -5,
                18,
                -4,
                100,
                -50,
            ],
            [
                10,
                0,
                0,
                1000,
                1000,
                -6,
                3,
                0,
                0x70000000,
                0,
                10,
                -3,
                22,
                -7,
                19,
                -6,
                90,
                -45,
            ],
        ]

        metrics = _trace_summary_metrics(
            samples, TRACE_HOLD_HEADERS, expected_tick_step=10
        )

        self.assertEqual(metrics["expected_tick_step"], 10)
        self.assertEqual(metrics["trq_act"]["min"], -6)
        self.assertEqual(metrics["flx_act"]["max"], 3)
        self.assertEqual(metrics["foc_uq"]["max"], 22)
        self.assertEqual(metrics["foc_ud"]["min"], -7)
        self.assertEqual(metrics["foc_uq_lim"]["final"], 19)
        self.assertEqual(metrics["foc_ud_lim"]["final"], -6)
        self.assertEqual(metrics["esum_trq"]["final"], 90)
        self.assertEqual(metrics["esum_flx"]["final"], -45)

        lines = _format_trace_summary(
            "foci stepper_x",
            samples,
            TRACE_HOLD_HEADERS,
            preset_name="hold",
            sample_period_us=1000,
            dropped=0,
            expected_tick_step=10,
        )
        text = "\n".join(lines)
        self.assertIn("hold preset, 1000us tick, 10000us samples", text)
        self.assertIn("trq_act:", text)
        self.assertIn("flx_act:", text)
        self.assertIn("foc_uq:", text)
        self.assertIn("foc_ud:", text)
        self.assertIn("foc_uq_lim:", text)
        self.assertIn("foc_ud_lim:", text)
        self.assertIn("esum_trq:", text)
        self.assertIn("esum_flx:", text)
        self.assertIn("final_settle_last_30:", text)
        self.assertIn("trq_act(rms=", text)
        self.assertIn("foc_uq_lim(rms=", text)
        self.assertIn("esum_trq(rms=", text)


if __name__ == "__main__":
    unittest.main()
