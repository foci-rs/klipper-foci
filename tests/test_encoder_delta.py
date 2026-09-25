"""Tests for the host-side shortest-path encoder delta helper."""

from klipper_foci.diagnostics.encoder import encoder_shortest_delta


def test_encoder_delta_forward_and_backward():
    assert encoder_shortest_delta(100, 142, 4000) == 42
    assert encoder_shortest_delta(142, 100, 4000) == -42


def test_encoder_delta_wraps_shortest():
    assert encoder_shortest_delta(3990, 10, 4000) == 20
    assert encoder_shortest_delta(10, 3990, 4000) == -20


def test_encoder_delta_half_turn_and_bad_domain_are_none():
    assert encoder_shortest_delta(0, 2000, 4000) is None
    assert encoder_shortest_delta(0, 5, 0) is None
