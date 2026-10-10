"""Each named part of a world's setting, composed for every look the library holds at its current
version, written from the parts file and the committed manifests.

    uv run python scripts/style_packs/composed_settings.py          # write the file
    uv run python scripts/style_packs/composed_settings.py --check  # refuse if it differs

``assets/style-packs/settings/setting-composed.v1.json`` holds, for each committed pack and each
part of ``setting-parts.v1.json``, the exact setting the server composes
(``exulanica.world.world_settings.compose_setting``), and one setting of a part from every axis
together. The page never composes a setting, so this file is what its tests draw: the browser's
reader applies each to its pack, and each is held to the rule every look's own light is held to, a
surface in shade lit at most twice as blue as red
(``web/packages/atlas-react/test/world-setting-parts.test.ts``).
``tests/test_world_settings.py`` holds the committed file to this script, so a part or a look that
changes says so here before a page test reads a stale setting.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from exulanica.world import world_settings as ws  # noqa: E402
from exulanica.world.style_packs import load_context, read_manifest  # noqa: E402

PROFILE = "exulanica.world-setting-composed/v1"
PACKS = ROOT / "assets" / "style-packs" / "packs"
OUT = ROOT / "assets" / "style-packs" / "settings" / "setting-composed.v1.json"
ABOUT = (
    "Each named part of a world's setting composed for every look of the library at its current "
    "version, and one part of every axis together: what exulanica.world.world_settings."
    "compose_setting returns, written by scripts/style_packs/composed_settings.py and held to it "
    "by tests/test_world_settings.py. The page's tests draw these."
)


def composed() -> dict[str, Any]:
    context = load_context(ROOT)
    parts = ws.setting_parts()
    rows: list[dict[str, Any]] = []
    for folder in sorted(PACKS.iterdir()):
        text = (folder / "manifest.json").read_bytes()
        manifest = read_manifest(json.loads(text), context)
        pack = ws.resolve_chain([manifest])
        chosen: list[dict[str, str]] = [{axis: key} for axis, key in parts.parts]
        last: dict[str, str] = {}
        for axis, key in parts.parts:
            last[axis] = key
        chosen.append(last)
        for one in chosen:
            rows.append(
                {
                    "pack_id": manifest["pack_id"],
                    "version": manifest["version"],
                    "manifest_sha256": hashlib.sha256(text[:-1]).hexdigest(),
                    "parts": one,
                    "setting": ws.compose_setting(one, pack, context, parts),
                }
            )
    return {"profile": PROFILE, "about": ABOUT, "parts_version": parts.version, "composed": rows}


def text() -> str:
    return json.dumps(composed(), indent=1) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="refuse if the committed file differs")
    args = parser.parse_args(argv)
    wanted = text()
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != wanted:
            print(f"{OUT.relative_to(ROOT)} is not what this script writes", file=sys.stderr)
            return 1
        return 0
    OUT.write_text(wanted, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
