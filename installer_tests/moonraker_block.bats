setup() {
  log() { :; }
  export -f log
  source "$BATS_TEST_DIRNAME/../installer.sh"
  export TEST_CONF="$BATS_TMPDIR/moonraker-$$.conf"
  printf '[printer]\nkinematics: corexy\n' > "$TEST_CONF"
}
teardown() { rm -f "$TEST_CONF"; }

@test "foci_write_moonraker_block adds a new marked section" {
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  [ "$status" -eq 0 ]
  grep -q '\[update_manager klipper-foci\]' "$TEST_CONF"
  grep -q 'virtualenv: /home/pi/klippy-env' "$TEST_CONF"
}

@test "foci_write_moonraker_block is idempotent on a repeat run" {
  foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  [ "$status" -eq 0 ]
  [ "$(grep -c '\[update_manager klipper-foci\]' "$TEST_CONF")" -eq 1 ]
}

@test "foci_write_moonraker_block emits project_name with extras when passed" {
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env" "klipper-foci[diagnostics,tuning]"
  [ "$status" -eq 0 ]
  grep -q 'project_name: klipper-foci\[diagnostics,tuning\]' "$TEST_CONF"
}

@test "foci_write_moonraker_block refuses a pre-existing unmarked matching section" {
  printf '\n[update_manager klipper-foci]\ntype: git_repo\n' >> "$TEST_CONF"
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  [ "$status" -eq 1 ]
  grep -q 'type: git_repo' "$TEST_CONF"
}

@test "foci_write_moonraker_block ignores an unrelated update_manager section" {
  printf '\n[update_manager other_plugin]\ntype: git_repo\n' >> "$TEST_CONF"
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  [ "$status" -eq 0 ]
  grep -q '\[update_manager klipper-foci\]' "$TEST_CONF"
  grep -q '\[update_manager other_plugin\]' "$TEST_CONF"
}

@test "foci_write_moonraker_block refuses when a second, unmarked matching section exists alongside our own managed one" {
  foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  printf '\n[update_manager klipper-foci]\ntype: git_repo\n' >> "$TEST_CONF"
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  [ "$status" -eq 1 ]
  grep -q 'type: git_repo' "$TEST_CONF"
}

@test "foci_write_moonraker_block refuses and leaves the file untouched when the begin marker has no matching end marker" {
  printf '\n# BEGIN foci-managed: update_manager klipper-foci\n[update_manager klipper-foci]\ntype: python\n\n[some_other_section]\nkey: value\n' >> "$TEST_CONF"
  before="$(cat "$TEST_CONF")"
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  [ "$status" -eq 1 ]
  [ "$(cat "$TEST_CONF")" = "$before" ]
  grep -q '\[some_other_section\]' "$TEST_CONF"
}

@test "re-running with a different project_name updates the existing managed block instead of ignoring it" {
  foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env"
  run foci_write_moonraker_block "$TEST_CONF" "/home/pi/klippy-env" "klipper-foci[diagnostics]"
  [ "$status" -eq 0 ]
  [ "$(grep -c '\[update_manager klipper-foci\]' "$TEST_CONF")" -eq 1 ]
  grep -q 'project_name: klipper-foci\[diagnostics\]' "$TEST_CONF"
}
