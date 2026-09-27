"""The workflow-plan digest must match the firmware's standard FNV-1a 64."""

import pytest

from klipper_foci.wire_digest import fnv1a64


@pytest.mark.parametrize(
    "data,expected",
    [
        (b"", 0xCBF29CE484222325),
        (b"a", 0xAF63DC4C8601EC8C),
        (b"foobar", 0x85944171F73967E8),
    ],
)
def test_fnv1a64_matches_published_vectors(data, expected):
    assert fnv1a64(data) == expected
