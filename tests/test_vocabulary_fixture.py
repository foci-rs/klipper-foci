"""Vocabulary parity guard.

Asserts ``commissioning.PHASE_NAMES`` and ``velocity_integral.BREAKAWAY_PHASE_NAMES``
match the checked-in fixture shared with the Rust ``CommissionPhase`` /
``BreakawayPhase`` oracle
(``shared/foci-firmware/src/commissioning/vocabulary_fixture_tests.rs``), so a
single-layer desync between the firmware enums and this host table fails a test.
"""

import json
from pathlib import Path

from klipper_foci.commissioning import PHASE_NAMES
from klipper_foci.velocity_integral import BREAKAWAY_PHASE_NAMES

# tests/ -> klipper-foci -> host -> foci (aggregate root)
_FIXTURE_PATH = (
    Path(__file__).resolve().parents[3]
    / "shared/foci-firmware/src/commissioning/vocabulary_fixture.json"
)


def _fixture_labels(group: str) -> dict[int, str]:
    entries = json.loads(_FIXTURE_PATH.read_text())
    return {entry["wire_code"]: entry["label"] for entry in entries if entry["group"] == group}


def test_phase_names_matches_fixture() -> None:
    assert _fixture_labels("phase") == PHASE_NAMES


def test_breakaway_phase_names_matches_fixture() -> None:
    assert _fixture_labels("breakaway") == BREAKAWAY_PHASE_NAMES
