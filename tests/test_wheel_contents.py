"""Verify genuine code absence in the built wheels, not just source-tree checks."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

_HOST_KLIPPER_FOCI = Path(__file__).parent.parent


def _build_wheel(package_dir: Path, tmp_path: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path), str(package_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel in {tmp_path}, found {wheels}"
    return wheels[0]


def _wheel_module_names(wheel_path: Path) -> set[str]:
    with zipfile.ZipFile(wheel_path) as archive:
        return {name for name in archive.namelist() if name.endswith(".py")}


def test_core_wheel_contains_expected_files_and_no_optional_modules(tmp_path):
    core_wheel = _build_wheel(_HOST_KLIPPER_FOCI / "klipper_foci", tmp_path / "core")
    modules = _wheel_module_names(core_wheel)
    # Positive assertions first -- an empty or truncated wheel must not
    # pass just because it also happens to contain nothing forbidden.
    assert any(name.endswith("klipper_foci/driver.py") for name in modules)
    assert any(name.endswith("klipper_foci/registry.py") for name in modules)
    assert any(name.endswith("klipper_foci/diagnostics/workflow.py") for name in modules)
    assert len(modules) >= 20  # core has ~20 top-level modules plus diagnostics/protocol subpackages
    # Then the negative assertions this task exists for.
    assert not any("diagnostics_active" in name for name in modules)
    assert not any("diagnostics_passive" in name for name in modules)
    assert not any("klipper_foci_tuning" in name for name in modules)
    assert not any("klipper_foci_diagnostics" in name for name in modules)


def test_diagnostics_wheel_contains_only_its_own_modules(tmp_path):
    diagnostics_wheel = _build_wheel(
        _HOST_KLIPPER_FOCI / "klipper_foci_diagnostics", tmp_path / "diagnostics"
    )
    modules = _wheel_module_names(diagnostics_wheel)
    assert modules, "diagnostics wheel must not be empty"
    assert all(name.startswith("klipper_foci_diagnostics/") for name in modules)
    assert any(name.endswith("active.py") for name in modules)
    assert any(name.endswith("passive.py") for name in modules)


def test_tuning_wheel_contains_only_its_own_modules(tmp_path):
    tuning_wheel = _build_wheel(_HOST_KLIPPER_FOCI / "klipper_foci_tuning", tmp_path / "tuning")
    modules = _wheel_module_names(tuning_wheel)
    assert modules, "tuning wheel must not be empty"
    assert all(name.startswith("klipper_foci_tuning/") for name in modules)
    assert any(name.endswith("workflow.py") for name in modules)


def test_core_alone_install_cannot_import_optional_packages(tmp_path):
    """Install the built core wheel into an isolated venv and confirm
    diagnostics/tuning genuinely aren't importable -- the file-listing
    checks above prove the wheel's contents; this proves what actually
    happens after a real `pip install`."""
    core_wheel = _build_wheel(_HOST_KLIPPER_FOCI / "klipper_foci", tmp_path / "core_for_install")
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    venv_python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", str(core_wheel)], check=True
    )
    # cwd is pinned away from the source tree: host/klipper-foci contains
    # sibling directories named exactly klipper_foci_diagnostics and
    # klipper_foci_tuning (their package project roots, no __init__.py), which
    # `python -c` would otherwise pick up from cwd as spurious PEP 420
    # namespace packages, masking a real "not installed" result.
    result = subprocess.run(
        [str(venv_python), "-c", "import klipper_foci.driver"],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    for missing_module in ("klipper_foci_diagnostics", "klipper_foci_tuning"):
        result = subprocess.run(
            [str(venv_python), "-c", f"import {missing_module}"],
            capture_output=True, text=True, cwd=tmp_path,
        )
        assert result.returncode != 0
        assert "ModuleNotFoundError" in result.stderr


def test_core_alone_install_supports_deploy_shim(tmp_path):
    """Confirm both deploy shims actually resolve against a real install.

    The re-export module `klipper_foci.klipper` and the two deploy
    artifacts -- `deploy/klippy-plugins/foci.py` (Kalico, whose loader
    scans klippy/plugins/) and `deploy/klippy-extras/foci.py` (mainline
    Klipper, whose loader never scans klippy/plugins/, only
    klippy/extras/) -- are all load-bearing: Klipper's loader only finds
    a shim file on disk, never the installed package directly, so a
    broken re-export would only surface once someone copied a shim onto
    a real Klipper/Kalico install. This exercises the re-export and both
    shims, from outside the source tree, against a core-only install.
    """
    core_wheel = _build_wheel(_HOST_KLIPPER_FOCI / "klipper_foci", tmp_path / "core_for_shim")
    venv_dir = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    venv_python = venv_dir / "bin" / "python"
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", str(core_wheel)], check=True
    )

    # cwd is pinned to tmp_path for the same PEP 420 namespace-package reason
    # as test_core_alone_install_cannot_import_optional_packages above.
    result = subprocess.run(
        [
            str(venv_python),
            "-c",
            "from klipper_foci.klipper import load_config, load_config_prefix\n"
            "assert callable(load_config)\n"
            "assert callable(load_config_prefix)\n",
        ],
        capture_output=True, text=True, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr

    for shim_dir in ("klippy-plugins", "klippy-extras"):
        deploy_shim = _HOST_KLIPPER_FOCI / "deploy" / shim_dir / "foci.py"
        load_shim_script = (
            "import importlib.util\n"
            f"spec = importlib.util.spec_from_file_location('foci_deploy_shim', {str(deploy_shim)!r})\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "assert callable(module.load_config)\n"
            "assert callable(module.load_config_prefix)\n"
        )
        result = subprocess.run(
            [str(venv_python), "-c", load_shim_script],
            capture_output=True, text=True, cwd=tmp_path,
        )
        assert result.returncode == 0, f"{shim_dir}: {result.stderr}"
