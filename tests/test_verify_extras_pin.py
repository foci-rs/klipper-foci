import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_extras_pin.py"


def _make_wheel(tmp_path, requires_dist_lines):
    wheel_path = tmp_path / "klipper_foci-1.4.0-py3-none-any.whl"
    metadata = "Metadata-Version: 2.1\nName: klipper-foci\nVersion: 1.4.0\n"
    metadata += "".join(f"Requires-Dist: {line}\n" for line in requires_dist_lines)
    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("klipper_foci-1.4.0.dist-info/METADATA", metadata)
    return wheel_path


def test_passes_when_both_extras_are_pinned(tmp_path):
    wheel = _make_wheel(
        tmp_path,
        [
            'klipper-foci-diagnostics (==1.4.0) ; extra == "diagnostics"',
            'klipper-foci-tuning (==1.4.0) ; extra == "tuning"',
        ],
    )
    result = subprocess.run([sys.executable, str(SCRIPT), str(wheel), "1.4.0"])
    assert result.returncode == 0


def test_fails_when_an_extra_is_unpinned(tmp_path):
    wheel = _make_wheel(
        tmp_path,
        [
            'klipper-foci-diagnostics ; extra == "diagnostics"',
            'klipper-foci-tuning (==1.4.0) ; extra == "tuning"',
        ],
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(wheel), "1.4.0"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "diagnostics" in result.stderr


def test_fails_when_an_extra_is_pinned_to_the_wrong_version(tmp_path):
    wheel = _make_wheel(
        tmp_path,
        [
            'klipper-foci-diagnostics (==1.4.0) ; extra == "diagnostics"',
            'klipper-foci-tuning (==1.3.9) ; extra == "tuning"',
        ],
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(wheel), "1.4.0"], capture_output=True, text=True
    )
    assert result.returncode == 1
    assert "tuning" in result.stderr
