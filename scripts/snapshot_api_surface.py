"""Write or check the reviewed snapshots of the API surface.

    uv run python scripts/snapshot_api_surface.py          # rewrite tests/snapshots/api-*.json
    uv run python scripts/snapshot_api_surface.py --check  # exit 1 and show the difference

``tests/test_api_surface_snapshot.py`` fails whenever the application's routes or OpenAPI document
differ from the files below. The change is accepted by running this script and committing the
rewritten files beside the change that caused them, so the diff a reviewer reads shows every route,
status, schema, database role and permission rule the change moved. The content comes from
:mod:`exulanica.api.surface`; this script only decides where it is kept.
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIRECTORY = ROOT / "tests" / "snapshots"
ROUTE_TABLE = SNAPSHOT_DIRECTORY / "api-routes.json"
OPENAPI = SNAPSHOT_DIRECTORY / "api-openapi.json"
COMMAND = "uv run python scripts/snapshot_api_surface.py"
#: Enough of a unified diff to show what moved without flooding a failing test's output.
DIFF_LINES_SHOWN = 80


def expected_files() -> dict[Path, str]:
    """Each snapshot file and the text the application generates for it now."""
    from exulanica.api.surface import (
        render_openapi,
        render_route_table,
        route_table,
        routing_only_application,
    )

    app = routing_only_application()
    return {
        ROUTE_TABLE: render_route_table(route_table(app)),
        OPENAPI: render_openapi(app.openapi()),
    }


def differences(expected: dict[Path, str]) -> list[str]:
    """A bounded unified diff for every snapshot whose file differs from what is generated."""
    found: list[str] = []
    for target, text in expected.items():
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if current == text:
            continue
        diff = list(
            difflib.unified_diff(
                current.splitlines(),
                text.splitlines(),
                fromfile=f"{target.relative_to(ROOT)} (committed)",
                tofile=f"{target.relative_to(ROOT)} (generated)",
                lineterm="",
            )
        )
        shown = diff[:DIFF_LINES_SHOWN]
        if len(diff) > DIFF_LINES_SHOWN:
            shown.append(f"... {len(diff) - DIFF_LINES_SHOWN} more diff lines")
        found.append("\n".join(shown))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if a snapshot is stale")
    arguments = parser.parse_args(argv)
    expected = expected_files()
    if arguments.check:
        found = differences(expected)
        for diff in found:
            print(diff)
        return 1 if found else 0
    SNAPSHOT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for target, text in expected.items():
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
