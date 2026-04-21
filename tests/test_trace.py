"""Unit tests for FOCI trace capture parsing.

Tests the Python-side sample unpacking, signed field conversion, and
phase filtering logic from cmd_FOCI_TRACE without requiring Klipper
or hardware.

Run: cd foci/klipper-foci && python -m pytest tests/ -v
"""

import struct
import unittest


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


if __name__ == "__main__":
    unittest.main()
