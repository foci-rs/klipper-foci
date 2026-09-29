import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_dist_version.py"


def _dist(tmp_path, names):
    for name in names:
        (tmp_path / name).write_bytes(b"")
    return tmp_path


def _run(dist, version):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(dist), version], capture_output=True, text=True
    )


def test_passes_when_every_artifact_carries_the_version(tmp_path):
    dist = _dist(
        tmp_path,
        [
            "klipper_foci-0.4.0-py3-none-any.whl",
            "klipper_foci-0.4.0.tar.gz",
            "klipper_foci_diagnostics-0.4.0-py3-none-any.whl",
            "klipper_foci_diagnostics-0.4.0.tar.gz",
        ],
    )
    assert _run(dist, "0.4.0").returncode == 0


def test_accepts_the_tag_spelling_of_a_pre_release(tmp_path):
    dist = _dist(
        tmp_path, ["klipper_foci-0.4.0rc1-py3-none-any.whl", "klipper_foci-0.4.0rc1.tar.gz"]
    )
    assert _run(dist, "0.4.0-rc1").returncode == 0


def test_fails_on_a_dev_version_from_a_dirty_tree(tmp_path):
    dist = _dist(
        tmp_path,
        [
            "klipper_foci-0.4.0-py3-none-any.whl",
            "klipper_foci_diagnostics-0.4.1.dev0+g943704f.d20260929-py3-none-any.whl",
        ],
    )
    result = _run(dist, "0.4.0")
    assert result.returncode == 1
    assert "0.4.1.dev0" in result.stderr


def test_fails_when_nothing_was_built(tmp_path):
    assert _run(tmp_path, "0.4.0").returncode == 1
