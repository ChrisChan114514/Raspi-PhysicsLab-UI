#!/usr/bin/env python3
"""Raspberry Pi GPIO-UART entrypoint for the EMM V5.0 position test."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    script = Path(__file__).resolve().parent / "test" / "test_position.py"
    if not script.is_file():
        raise SystemExit(f"missing test script: {script}")

    sys.argv[0] = str(script)
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
