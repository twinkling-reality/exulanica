"""Count what the evaluation records say about themselves, reading only the record files.

    .venv/bin/python scripts/count_evaluation_records.py

Prints, for ``docs/evaluation/*.json`` records of profile ``exulanica.digest-bound-record/v1``:

*   how many records there are, the first and last date their file names carry, and how many store
    a ``record_sha256`` equal to the SHA-256 of their record's canonical JSON;
*   how many records name at least one other record by path and digest, how many such links there
    are, and how many match the digest of the record they name;
*   how many records carry a field named for a correction, a corrected value or an erratum (its name
    contains ``correction``, ``corrected`` or ``errat``);
*   how many records carry a list named ``limitations`` or ``limits``, and how many items those lists
    hold;
*   how many records have a top-level ``verdict`` or ``status`` that begins with ``FAIL``.

Counts match field names (identifiers, not keys that are file paths), so a correction or a limit
stated only in prose is not counted, and a name match can include a field that names something else. The
write-up of corrections and negative results (docs/evaluation-corrections.md) quotes its output.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exulanica.canonical import canonical_json  # noqa: E402

PROFILE = "exulanica.digest-bound-record/v1"
DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def _walk(value: Any) -> Iterator[tuple[str | None, Any]]:
    """Every (key, value) pair in a JSON value, depth first; list items carry no key."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from _walk(item)


def _digest(record: Any) -> str:
    return hashlib.sha256(canonical_json(record)).hexdigest()


def main() -> int:
    records = {}
    for path in sorted((ROOT / "docs" / "evaluation").glob("*.json")):
        document = json.loads(path.read_bytes())
        if isinstance(document, dict) and document.get("profile") == PROFILE:
            records[path] = document
    dates = sorted(DATED.match(path.name).group(1) for path in records if DATED.match(path.name))
    stored = sum(1 for doc in records.values() if doc["record_sha256"] == _digest(doc["record"]))
    naming = links = matching = 0
    correction = limited = limit_items = failed = 0
    for doc in records.values():
        record = doc["record"]
        named = [
            item
            for _, item in _walk(record)
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and item["path"].startswith("docs/evaluation/")
            and isinstance(item.get("record_sha256"), str)
        ]
        if named:
            naming += 1
        for item in named:
            links += 1
            target = ROOT / item["path"]
            if target.is_file():
                bound = json.loads(target.read_bytes())
                if (
                    isinstance(bound, dict)
                    and _digest(bound.get("record")) == item["record_sha256"]
                ):
                    matching += 1
        keys = [key for key, _ in _walk(record) if key is not None]
        names = [key.lower() for key in keys if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)]
        if any(re.search(r"correction|corrected|errat", name) for name in names):
            correction += 1
        lists = [
            item
            for key, item in _walk(record)
            if key in ("limitations", "limits") and isinstance(item, list)
        ]
        if lists:
            limited += 1
            limit_items += sum(len(item) for item in lists)
        verdicts = [record.get("verdict"), record.get("status")] if isinstance(record, dict) else []
        if any(isinstance(value, str) and value.upper().startswith("FAIL") for value in verdicts):
            failed += 1
    print(f"records: {len(records)}, dated {dates[0]} to {dates[-1]} by file name")
    print(f"stored digest equals the recomputed SHA-256: {stored} of {len(records)}")
    print(f"records naming another record by path and digest: {naming}")
    print(f"links between records: {links}, matching the digest of the record named: {matching}")
    print(f"records with a field named for a correction or an erratum: {correction}")
    print(f"records with a limitations or limits list: {limited}, holding {limit_items} items")
    print(f"records whose top-level verdict or status begins with FAIL: {failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
