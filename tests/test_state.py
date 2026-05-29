"""Unit tests for FociDriver two-stage commissioning state machine.

Tests precondition gates, state transitions, homing invalidation, and
operation lock without requiring Klipper or hardware.

Run: cd foci/klipper-foci && python -m pytest tests/ -v
"""
