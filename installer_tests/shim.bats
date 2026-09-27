setup() {
  log() { :; }
  export -f log
  source "$BATS_TEST_DIRNAME/../installer.sh"
  export TEST_DIR="$BATS_TMPDIR/foci-shim-$$"
  mkdir -p "$TEST_DIR"
}
teardown() { rm -rf "$TEST_DIR"; }

@test "foci_select_shim_variant returns plugins for a Kalico plugins path" {
  run foci_select_shim_variant "/home/pi/klipper/klippy/plugins"
  [ "$status" -eq 0 ]
  [ "$output" = "plugins" ]
}

@test "foci_select_shim_variant returns extras for a mainline extras path" {
  run foci_select_shim_variant "/home/pi/klipper/klippy/extras"
  [ "$status" -eq 0 ]
  [ "$output" = "extras" ]
}

@test "foci_write_shim writes to a path with no existing file" {
  run foci_write_shim "$TEST_DIR/foci.py" "$FOCI_SHIM_MARKER"$'\n''print("hi")'
  [ "$status" -eq 0 ]
  [ "$(head -1 "$TEST_DIR/foci.py")" = "$FOCI_SHIM_MARKER" ]
}

@test "foci_write_shim overwrites a file that already carries our marker" {
  printf '%s\nold\n' "$FOCI_SHIM_MARKER" > "$TEST_DIR/foci.py"
  run foci_write_shim "$TEST_DIR/foci.py" "$FOCI_SHIM_MARKER"$'\n''new'
  [ "$status" -eq 0 ]
  grep -q '^new$' "$TEST_DIR/foci.py"
}

@test "foci_write_shim refuses an unrelated existing file without --force" {
  printf 'not ours\n' > "$TEST_DIR/foci.py"
  run foci_write_shim "$TEST_DIR/foci.py" "$FOCI_SHIM_MARKER"$'\n''new'
  [ "$status" -eq 1 ]
  grep -q 'not ours' "$TEST_DIR/foci.py"
}

@test "foci_write_shim --force backs up and overwrites an unrelated file" {
  printf 'not ours\n' > "$TEST_DIR/foci.py"
  run foci_write_shim "$TEST_DIR/foci.py" "$FOCI_SHIM_MARKER"$'\n''new' --force
  [ "$status" -eq 0 ]
  grep -q '^new$' "$TEST_DIR/foci.py"
  ls "$TEST_DIR"/foci.py.bak.* >/dev/null 2>&1
}
