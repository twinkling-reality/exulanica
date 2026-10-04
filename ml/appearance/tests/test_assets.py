"""The stub route end to end: receipts the dry run writes, read back and refused when tampered.

The formats themselves are tested in the repository's tests (test_pieces_format.py,
test_pieces_geometry.py); this file holds what needs the appearance package's dry run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from exulanica_pieces.canonical import Refused, canonical_bytes, sha256_hex
from exulanica_pieces.records import REGENERATION, read_receipt, read_request

from exulanica_appearance.assets.dryrun import dry_run


def test_dry_run_receipts_read_back_and_refuse_tampering(repository: Path, tmp_path: Path) -> None:
    run = dry_run(repository, tmp_path)
    receipts = sorted((tmp_path / "receipts").glob("*.json"))
    requests = {
        sha256_hex(p.read_bytes()): read_request(p.read_bytes())
        for p in tmp_path.glob("request-*.json")
    }
    document = json.loads(receipts[0].read_bytes())
    request_of = requests[document["request_sha256"]]
    read_receipt(receipts[0].read_bytes(), request_of)
    assert document["regeneration"] == REGENERATION
    for change, match in (
        (
            {
                "verdict": {"over": [], "within": True},
                "measured": dict(document["measured"], triangles=10**6),
            },
            "verdict",
        ),
        ({"origin": "authored"}, "origin generated"),
        (
            {
                "postprocess": dict(
                    document["postprocess"], steps=document["postprocess"]["steps"][::-1]
                )
            },
            "in that order",
        ),
    ):
        with pytest.raises(Refused, match=match):
            read_receipt(canonical_bytes(dict(document, **change)), request_of)
    assert all(piece["within"] for piece in run["pieces"])
    assert len(run["pieces"]) == 5
