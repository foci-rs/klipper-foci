setup() {
  log() { :; }
  export -f log
  source "$BATS_TEST_DIRNAME/../installer.sh"
  export TEST_VENV="$BATS_TMPDIR/klippy-env-$$"
  mkdir -p "$TEST_VENV/bin"
  touch "$TEST_VENV/bin/python"
}

teardown() {
  rm -rf "$TEST_VENV"
}

@test "foci_resolve_venv derives the venv root from the python interpreter path" {
  run foci_resolve_venv "$TEST_VENV/bin/python"
  [ "$status" -eq 0 ]
  [ "$output" = "$TEST_VENV" ]
}

@test "foci_write_pip_conf creates pip.conf with our index-url when none exists" {
  run foci_write_pip_conf "$TEST_VENV" "https://example.test/simple/"
  [ "$status" -eq 0 ]
  grep -q '^index-url = https://example.test/simple/$' "$TEST_VENV/pip.conf"
}

@test "foci_write_pip_conf is idempotent on a repeat run" {
  foci_write_pip_conf "$TEST_VENV" "https://example.test/simple/"
  run foci_write_pip_conf "$TEST_VENV" "https://example.test/simple/"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^index-url' "$TEST_VENV/pip.conf")" -eq 1 ]
}

@test "foci_write_pip_conf refuses a conflicting existing index-url without --force" {
  printf '[global]\nindex-url = https://other.example/simple/\n' > "$TEST_VENV/pip.conf"
  run foci_write_pip_conf "$TEST_VENV" "https://example.test/simple/"
  [ "$status" -eq 1 ]
  grep -q 'other.example' "$TEST_VENV/pip.conf"
}

@test "foci_write_pip_conf --force overwrites a conflicting index-url and strips extra-index-url" {
  printf '[global]\nindex-url = https://other.example/simple/\nextra-index-url = https://pypi.org/simple/\n' > "$TEST_VENV/pip.conf"
  run foci_write_pip_conf "$TEST_VENV" "https://example.test/simple/" --force
  [ "$status" -eq 0 ]
  grep -q '^index-url = https://example.test/simple/$' "$TEST_VENV/pip.conf"
  ! grep -q 'extra-index-url' "$TEST_VENV/pip.conf"
}

@test "foci_write_pip_conf preserves unrelated pip.conf settings" {
  printf '[global]\ntimeout = 60\ncert = /etc/ssl/custom.pem\n[install]\nno-warn-script-location = true\n' > "$TEST_VENV/pip.conf"
  run foci_write_pip_conf "$TEST_VENV" "https://example.test/simple/"
  [ "$status" -eq 0 ]
  grep -q '^timeout = 60$' "$TEST_VENV/pip.conf"
  grep -q '^cert = /etc/ssl/custom.pem$' "$TEST_VENV/pip.conf"
  grep -q '^\[install\]$' "$TEST_VENV/pip.conf"
  grep -q '^no-warn-script-location = true$' "$TEST_VENV/pip.conf"
  grep -q '^index-url = https://example.test/simple/$' "$TEST_VENV/pip.conf"
}
