#!/usr/bin/env python3
"""Generate a collection-specific macOS launcher outside the source tree."""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from video_catalog import CATALOG_DIR_NAME, atomic_write_text, validated_root


def launcher_text(project: Path, root: Path) -> str:
    return f"""#!/bin/zsh
set -e

PROJECT_DIR={shlex.quote(str(project))}
VIDEO_ROOT={shlex.quote(str(root))}

cd "$PROJECT_DIR"
exec .venv/bin/python serve_catalog.py --root "$VIDEO_ROOT" --open
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=validated_root)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    destination = args.root / CATALOG_DIR_NAME / "Launch Video Catalog.command"
    atomic_write_text(destination, launcher_text(project, args.root))
    destination.chmod(destination.stat().st_mode | 0o111)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
