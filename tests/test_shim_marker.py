from pathlib import Path

MARKER = "# foci-shim: klipper-foci (do not edit; managed by install.sh)"
REPO_ROOT = Path(__file__).resolve().parents[1]


def test_klippy_extras_shim_has_marker():
    text = (REPO_ROOT / "deploy" / "klippy-extras" / "foci.py").read_text()
    assert text.splitlines()[0] == MARKER


def test_klippy_plugins_shim_has_marker():
    text = (REPO_ROOT / "deploy" / "klippy-plugins" / "foci.py").read_text()
    assert text.splitlines()[0] == MARKER
