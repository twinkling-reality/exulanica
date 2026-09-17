"""The committed catalogs are exactly what this tool builds, and it builds the same bytes twice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica_lettering_tool.__main__ import ROOT, SPECIFICATION, TARGET, catalogs


def test_the_committed_catalogs_are_rebuilt_byte_for_byte_twice():
    first = catalogs(workers=6)
    second = catalogs(workers=3)
    assert first == second
    specification = json.loads(SPECIFICATION.read_text(encoding="utf-8"))
    assert sorted(path.name for path in first) == sorted(
        f"{entry['catalog_id']}.v1.json" for entry in specification["catalogs"]
    )
    for path, data in first.items():
        assert path.read_bytes() == data, path.relative_to(ROOT)
    assert sorted(TARGET.glob("*.json")) == sorted(first)


def test_every_font_is_the_file_its_source_record_names():
    for source in sorted((ROOT / "assets" / "fonts").glob("*/SOURCE.json")):
        record = json.loads(source.read_text(encoding="utf-8"))
        for entry in record["files"]:
            data = (source.parent / entry["path"]).read_bytes()
            assert hashlib.sha256(data).hexdigest() == entry["sha256"]
            assert len(data) == entry["byte_size"]
            assert entry["url"] == (
                f"https://raw.githubusercontent.com/{record['repository']}/{record['commit']}/"
                f"{entry['repository_path']}"
            )
        names = sorted(Path(entry["path"]).name for entry in record["files"])
        assert sorted(p.name for p in source.parent.iterdir()) == sorted([*names, "SOURCE.json"])
