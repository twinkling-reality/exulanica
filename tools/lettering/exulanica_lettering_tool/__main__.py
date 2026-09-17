"""``build`` writes the catalogs; ``check`` rebuilds them in memory and compares byte for byte.

From the repository root: ``uv run --directory tools/lettering --locked --offline python -m
exulanica_lettering_tool check``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from exulanica_lettering_tool.catalog import build_catalog

ROOT = Path(__file__).resolve().parents[3]
SPECIFICATION = ROOT / "tools" / "lettering" / "catalogs.json"
TARGET = ROOT / "assets" / "catalogs" / "lettering"


def catalogs(workers: int) -> dict[Path, bytes]:
    specification = json.loads(SPECIFICATION.read_text(encoding="utf-8"))
    out = {}
    for entry in specification["catalogs"]:
        path = TARGET / f"{entry['catalog_id']}.v1.json"
        out[path] = build_catalog(ROOT, entry["catalog_id"], entry["font"], workers)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(prog="exulanica_lettering_tool")
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    arguments = parser.parse_args()
    built = catalogs(arguments.workers)
    if arguments.command == "build":
        TARGET.mkdir(parents=True, exist_ok=True)
        for path, data in built.items():
            path.write_bytes(data)
            print(f"wrote {path.relative_to(ROOT)} ({len(data)} bytes)")
        return 0
    stale = [
        path for path, data in built.items() if not path.is_file() or path.read_bytes() != data
    ]
    extra = sorted(set(TARGET.glob("*.json")) - set(built))
    for path in stale:
        print(f"differs: {path.relative_to(ROOT)}", file=sys.stderr)
    for path in extra:
        print(f"not built by this tool: {path.relative_to(ROOT)}", file=sys.stderr)
    return 1 if stale or extra else 0


if __name__ == "__main__":
    raise SystemExit(main())
