"""Shared constants for the klipper-foci host module."""

MIN_RAW_VOLTAGE_LIMIT = 0
MIN_OPERATIONAL_VOLTAGE_LIMIT = 1024
DEFAULT_OPERATIONAL_VOLTAGE_LIMIT = 16000
MAX_DIAGNOSTIC_VOLTAGE_LIMIT = 32767
MAX_RUN_CURRENT_AMPS = 5.0
PID_GAIN_MAX_RAW = 0x7FFF
ELECTRICAL_ID_WAIT_TIMEOUT_S = 30.0

# Matches firmware's ELECTRICAL_MODEL_RESISTANCE_SCALE: r_count_milli is
# resistance scaled by this factor, so tau_e_us = l_count_micro * SCALE //
# r_count_milli recovers the electrical time constant in microseconds.
ELECTRICAL_MODEL_RESISTANCE_SCALE = 1000

# How long the host waits, after sending foci_commission_cancel, for the
# firmware's Cancelled terminal before giving up and raising the original
# timeout error anyway. See docs/specs/2026-08-30-commission-cancel-quiescence-design.md.
COMMISSION_CANCEL_GRACE_PERIOD_S = 2.0
