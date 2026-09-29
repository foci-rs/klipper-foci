#!/usr/bin/env python3
"""Verify every built wheel and sdist carries the release version."""

import sys
from pathlib import Path

from packaging.version import Version


def main(dist_dir: str, version: str) -> int:
    expected = str(Version(version))
    artifacts = sorted(
        p for p in Path(dist_dir).iterdir() if p.suffix == ".whl" or p.name.endswith(".tar.gz")
    )
    if not artifacts:
        print(f"no wheels or sdists found in {dist_dir}", file=sys.stderr)
        return 1

    errors = []
    for artifact in artifacts:
        built = (
            artifact.name.split("-")[1]
            if artifact.suffix == ".whl"
            else artifact.name.removesuffix(".tar.gz").rsplit("-", 1)[1]
        )
        if built != expected:
            errors.append(f"{artifact.name} is version {built}, expected {expected}")
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
