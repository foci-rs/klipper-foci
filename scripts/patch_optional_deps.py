#!/usr/bin/env python3
"""Pin klipper-foci's optional-dependency extras to an exact release version."""

import re
import sys
from pathlib import Path

EXTRAS = ("klipper-foci-diagnostics", "klipper-foci-tuning")


def main(pyproject_path: str, version: str) -> None:
    path = Path(pyproject_path)
    text = path.read_text()
    for name in EXTRAS:
        pattern = re.compile(rf'"{re.escape(name)}(==[^"]*)?"')
        replacement = f'"{name}=={version}"'
        text, count = pattern.subn(replacement, text)
        if count != 1:
            raise SystemExit(f"expected exactly one occurrence of {name!r}, found {count}")
    path.write_text(text)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
