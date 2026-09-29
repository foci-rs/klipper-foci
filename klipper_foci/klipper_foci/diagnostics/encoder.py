"""Host-side shortest-path encoder delta arithmetic."""

from __future__ import annotations


def encoder_shortest_delta(before: int, after: int, counts_per_rev: int) -> int | None:
    """Return the shortest signed displacement from `before` to `after`.

    Returns `None` when `counts_per_rev` is not positive, or when an even
    domain's displacement is exactly half a revolution and has no unique
    shortest direction.
    """
    if counts_per_rev <= 0:
        return None

    forward = (after - before) % counts_per_rev
    half_turn = counts_per_rev // 2

    if counts_per_rev % 2 == 0 and forward == half_turn:
        return None

    return forward - counts_per_rev if forward > half_turn else forward
