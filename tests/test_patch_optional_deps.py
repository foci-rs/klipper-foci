import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "patch_optional_deps.py"

FIXTURE = """\
[project]
name = "klipper-foci"
dynamic = ["version"]

[project.optional-dependencies]
diagnostics = ["klipper-foci-diagnostics"]
tuning = ["klipper-foci-tuning"]
"""


def test_pins_both_extras_to_the_given_version(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(FIXTURE)

    subprocess.run([sys.executable, str(SCRIPT), str(pyproject), "1.4.0"], check=True)

    text = pyproject.read_text()
    assert 'diagnostics = ["klipper-foci-diagnostics==1.4.0"]' in text
    assert 'tuning = ["klipper-foci-tuning==1.4.0"]' in text
