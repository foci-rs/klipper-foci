#!/usr/bin/env python3
"""Verify a built klipper-foci wheel pins its diagnostics extra."""

import re
import sys
import zipfile

EXTRAS = ("diagnostics",)
NAMES = {"diagnostics": "klipper-foci-diagnostics"}


def main(wheel_path: str, version: str) -> int:
    with zipfile.ZipFile(wheel_path) as zf:
        metadata_name = next(n for n in zf.namelist() if n.endswith("dist-info/METADATA"))
        metadata = zf.read(metadata_name).decode()

    errors = []
    for extra in EXTRAS:
        name = NAMES[extra]
        pattern = re.compile(
            rf"Requires-Dist:\s*{re.escape(name)}\s*\(?==([^)\s;]+)\)?"
            rf"\s*;\s*extra == ['\"]{extra}['\"]"
        )
        match = pattern.search(metadata)
        if not match:
            errors.append(f"{extra} ({name}) has no exact-pinned Requires-Dist entry")
        elif match.group(1) != version:
            errors.append(f"{extra} ({name}) is pinned to {match.group(1)!r}, expected {version!r}")

    if errors:
        for err in errors:
            print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
