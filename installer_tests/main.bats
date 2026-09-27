setup() {
  export TEST_ROOT="$BATS_TMPDIR/foci-main-$$"
  mkdir -p "$TEST_ROOT/klipper/klippy/extras" "$TEST_ROOT/klippy-env/bin"
  touch "$TEST_ROOT/klippy-env/bin/python"
  /usr/bin/git init -q "$TEST_ROOT/klipper"
  export FOCI_SHIM_EXTRAS="# foci-shim: klipper-foci (do not edit; managed by install.sh)"$'\n''print("extras shim")'
  export FOCI_SHIM_PLUGINS="# foci-shim: klipper-foci (do not edit; managed by install.sh)"$'\n''print("plugins shim")'
  export FOCI_INDEX_URL="https://example.test/simple/"
  export INSTALLER_VERSION="0.3.0"

  # Stub kpi-sh functions this task does not own, so main.bats exercises
  # only installer.sh's own orchestration logic.
  discover_klipper_env() {
    KLIPPER_PATH="$TEST_ROOT/klipper"
    KLIPPY_PYTHON="$TEST_ROOT/klippy-env/bin/python"
    KLIPPER_PLUGINS_PATH="$TEST_ROOT/klipper/klippy/extras"
    MOONRAKER_CONFIG="$TEST_ROOT/moonraker.conf"
  }
  check_no_active_print() { return 0; }
  service_restart_if() { echo "restarted:$1" >> "$TEST_ROOT/restarts.log"; }
  log() { :; }

  export -f discover_klipper_env check_no_active_print service_restart_if log
  source "$BATS_TEST_DIRNAME/../installer.sh"
  printf '[printer]\n' > "$TEST_ROOT/moonraker.conf"

  # Override installer.sh's real pip_install (which shells out to
  # $KLIPPY_PYTHON -m pip) with a recorder, so tests observe what it would
  # have run without actually invoking pip.
  pip_install() { echo "pip_install:$*" >> "$TEST_ROOT/pip.log"; }
  export -f pip_install
}
teardown() { rm -rf "$TEST_ROOT"; }

@test "foci_main with no flags installs core only, pinned, no extras" {
  run foci_main
  [ "$status" -eq 0 ]
  grep -q 'pip_install:klipper-foci==0.3.0' "$TEST_ROOT/pip.log"
  ! grep -q '\[' "$TEST_ROOT/pip.log"
  grep -q "$FOCI_SHIM_MARKER" "$TEST_ROOT/klipper/klippy/extras/foci.py"
  grep -q 'extras shim' "$TEST_ROOT/klipper/klippy/extras/foci.py"
  grep -q 'index-url = https://example.test/simple/' "$TEST_ROOT/klippy-env/pip.conf"
  grep -q '\[update_manager klipper-foci\]' "$TEST_ROOT/moonraker.conf"
  ! grep -q 'project_name' "$TEST_ROOT/moonraker.conf"
  grep -q 'restarted:klipper' "$TEST_ROOT/restarts.log"
  grep -q 'restarted:moonraker' "$TEST_ROOT/restarts.log"
}

@test "foci_main --diagnostics --tuning installs with both extras, pinned together" {
  run foci_main --diagnostics --tuning
  [ "$status" -eq 0 ]
  grep -q 'pip_install:klipper-foci\[diagnostics,tuning\]==0.3.0' "$TEST_ROOT/pip.log"
  grep -q 'project_name: klipper-foci\[diagnostics,tuning\]' "$TEST_ROOT/moonraker.conf"
}

@test "re-running with a different flag combination recomputes the extras set fresh" {
  foci_main
  rm -f "$TEST_ROOT/pip.log"
  run foci_main --diagnostics
  [ "$status" -eq 0 ]
  grep -q 'pip_install:klipper-foci\[diagnostics\]==0.3.0' "$TEST_ROOT/pip.log"
  ! grep -q 'tuning' "$TEST_ROOT/pip.log"
  grep -q 'project_name: klipper-foci\[diagnostics\]' "$TEST_ROOT/moonraker.conf"
}

@test "foci_main appends the shim path to .git/info/exclude" {
  run foci_main
  [ "$status" -eq 0 ]
  grep -q 'klippy/extras/foci.py' "$TEST_ROOT/klipper/.git/info/exclude"
}

@test "foci_main fails closed when KLIPPER_PATH is not a git checkout" {
  rm -rf "$TEST_ROOT/klipper/.git"
  # The suite-wide log() stub is a silent no-op so other tests' $output stays
  # clean; this test needs the real message, so it overrides log() locally.
  log() { echo "$*"; }
  export -f log
  run foci_main
  [ "$status" -eq 1 ]
  [[ "$output" == *"not a git checkout"* ]]
}

@test "foci_main aborts and does not restart services when a print is active" {
  check_no_active_print() { return 1; }
  export -f check_no_active_print
  run foci_main
  [ "$status" -eq 1 ]
  [ ! -f "$TEST_ROOT/restarts.log" ]
}

@test "foci_main aborts and skips shim/moonraker/restart when pip_install fails" {
  pip_install() { echo "pip_install:$*" >> "$TEST_ROOT/pip.log"; return 1; }
  export -f pip_install
  run foci_main
  [ "$status" -eq 1 ]
  [ ! -f "$TEST_ROOT/klipper/klippy/extras/foci.py" ]
  [ ! -f "$TEST_ROOT/restarts.log" ]
}

@test "foci_main --help prints usage and does nothing else" {
  run foci_main --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage:"* ]]
  [ ! -f "$TEST_ROOT/pip.log" ]
  [ ! -f "$TEST_ROOT/klipper/klippy/extras/foci.py" ]
}

@test "foci_main run twice with identical flags is fully idempotent end to end" {
  run foci_main --diagnostics --tuning
  [ "$status" -eq 0 ]
  run foci_main --diagnostics --tuning
  [ "$status" -eq 0 ]
  [ "$(grep -c 'pip_install' "$TEST_ROOT/pip.log")" -eq 2 ]
  grep -c 'pip_install:klipper-foci\[diagnostics,tuning\]==0.3.0' "$TEST_ROOT/pip.log" | grep -q '^2$'
  [ "$(grep -c 'klippy/extras/foci.py' "$TEST_ROOT/klipper/.git/info/exclude")" -eq 1 ]
  [ "$(grep -c '\[update_manager klipper-foci\]' "$TEST_ROOT/moonraker.conf")" -eq 1 ]
  [ "$(grep -c 'project_name: klipper-foci\[diagnostics,tuning\]' "$TEST_ROOT/moonraker.conf")" -eq 1 ]
}
