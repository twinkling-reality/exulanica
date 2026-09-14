#!/usr/bin/env python3
"""Prepare the corrected v2 bundle, including locomotion and gestures for every look."""

from pathlib import Path
import runpy


def main():
    runpy.run_path(
        str(Path(__file__).with_name("prepare_character_assets_v2.py")), run_name="__main__"
    )


if __name__ == "__main__":
    main()
