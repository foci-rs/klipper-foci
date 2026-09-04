"""Shared constants for the klipper-foci host module."""

MIN_RAW_VOLTAGE_LIMIT = 0
MIN_OPERATIONAL_VOLTAGE_LIMIT = 1024
DEFAULT_OPERATIONAL_VOLTAGE_LIMIT = 16000
MAX_DIAGNOSTIC_VOLTAGE_LIMIT = 32767
MAX_RUN_CURRENT_AMPS = 5.0
PID_GAIN_MAX_RAW = 0x7FFF
ELECTRICAL_ID_WAIT_TIMEOUT_S = 30.0

# How long the host waits, after sending foci_commission_cancel, for the
# firmware's Cancelled terminal before giving up and raising the original
# timeout error anyway. Bounds firmware's own worst-case time to reach
# GPIO-first safe-state after observing the cancel; it is a practical
# engineering margin, not a proven end-to-end delivery bound -- the same
# class of bound ELECTRICAL_ID_WAIT_TIMEOUT_S already relies on for its own
# firmware-completion wait. See docs/specs/2026-08-30-commission-cancel-quiescence-design.md.
COMMISSION_CANCEL_GRACE_PERIOD_S = 2.0
