setup() {
  REPO_ROOT="$BATS_TEST_DIRNAME/.."
  rm -rf "$REPO_ROOT/build"
}
teardown() { rm -rf "$REPO_ROOT/build"; }

@test "make installer produces a self-contained, valid installer script" {
  run make -C "$REPO_ROOT" installer VERSION=1.2.3 INDEX_URL=https://example.test/simple/
  [ "$status" -eq 0 ]
  [ -f "$REPO_ROOT/build/klipper-foci-installer.sh" ]
  bash -n "$REPO_ROOT/build/klipper-foci-installer.sh"
  grep -q 'INSTALLER_VERSION="1.2.3"' "$REPO_ROOT/build/klipper-foci-installer.sh"
  grep -q 'FOCI_INDEX_URL="https://example.test/simple/"' "$REPO_ROOT/build/klipper-foci-installer.sh"
  grep -c 'foci-shim: klipper-foci' "$REPO_ROOT/build/klipper-foci-installer.sh" | grep -q '^3$'
  grep -q 'foci_main "\$@"' "$REPO_ROOT/build/klipper-foci-installer.sh"
}

@test "the generated installer runs --help without touching the filesystem" {
  make -C "$REPO_ROOT" installer VERSION=1.2.3 INDEX_URL=https://example.test/simple/
  run bash "$REPO_ROOT/build/klipper-foci-installer.sh" --help
  [ "$status" -eq 0 ]
  [[ "$output" == *"Usage:"* ]]
}

@test "a second build with a different VERSION actually regenerates the script" {
  run make -C "$REPO_ROOT" installer VERSION=1.2.3 INDEX_URL=https://example.test/simple/
  [ "$status" -eq 0 ]
  run make -C "$REPO_ROOT" installer VERSION=9.9.9 INDEX_URL=https://example.test/simple/
  [ "$status" -eq 0 ]
  grep -q 'INSTALLER_VERSION="9.9.9"' "$REPO_ROOT/build/klipper-foci-installer.sh"
  ! grep -q 'INSTALLER_VERSION="1.2.3"' "$REPO_ROOT/build/klipper-foci-installer.sh"
}
