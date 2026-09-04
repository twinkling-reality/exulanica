"""Integrity and disclosure rules for retained machine-readable campaign evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.canonical import canonical_json

_ROOT = Path(__file__).resolve().parents[1]


def _records() -> list[Path]:
    return sorted((_ROOT / "docs" / "evaluation").glob("*.json"))


def test_every_retained_evaluation_record_reproduces_its_canonical_digest():
    paths = _records()
    assert paths, "no machine-readable evaluation record is retained"
    for path in paths:
        document = json.loads(path.read_bytes())
        assert document["profile"] == "exulanica.digest-bound-record/v1", path
        assert document["record_sha256"] == hashlib.sha256(
            canonical_json(document["record"])
        ).hexdigest(), path


def test_retained_evaluation_records_contain_no_personal_path_or_credential_material():
    for path in _records():
        text = path.read_text(encoding="utf-8")
        assert "/Users/" not in text, path
        assert "Bearer " not in text, path
        assert "api-token" not in text, path


def test_depth_image_forward_record_does_not_claim_normal_worker_or_host_performance():
    path = _ROOT / "docs" / "evaluation" / "2026-09-04-linux-amd64-depth-forward.json"
    record = json.loads(path.read_bytes())["record"]
    assert record["corpus_class"] == "synthetic"
    assert record["execution"]["production_adapter"].endswith("MoGeDepthModel")
    assert record["execution"]["production_worker_orchestration"] is False
    assert any("do not represent a production host" in item for item in record["limitations"])
