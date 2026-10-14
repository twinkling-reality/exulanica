"""The evidence file as a public format: optional fields, the committed schema, the reference.

Synthetic content only. The committed JSON Schema and the format document are checked against
the model they describe, so neither can drift from the code.
"""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest
from exulanica.world_package.projects.checkpoint import (
    ProjectError,
    evidence_digest,
    evidence_document,
)
from exulanica.world_package.projects.schema import Evidence

from test_world_project import sample
from test_world_project_repository import evidence_from

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILE = ROOT / "exulanica/world_package/projects/schemas/world-project-evidence.v1.json"
FORMAT_DOC = ROOT / "docs/world-project-evidence-format.md"

RECEIPT = {
    "status": "accepted",
    "reason": "validated_choice",
    "disposition": "applied",
    "disposition_reason": "applied",
    "consumed_tick": 2,
    "served_model_id": "synthetic-model-rev-1",
    "cost_usd": "0.00001",
    "cost_known": True,
}


def evidence():
    project, _ = sample()
    return evidence_from(project)[1]


def test_files_without_the_new_fields_keep_their_form_and_digest():
    plain = evidence()
    document = evidence_document(plain)
    assert "coverage" not in document and "captured_at" not in document
    assert "receipt" not in document["decisions"][0]
    # The digest is over the same canonical form it had before the fields existed.
    assert evidence_digest(plain) == evidence_digest(document)


def test_receipt_coverage_and_capture_time_are_closed_and_exact():
    full = evidence()
    full["coverage"] = {"decisions": "consumed"}
    full["captured_at"] = "2026-10-14T01:02:03Z"
    full["decisions"][0]["receipt"] = dict(RECEIPT)
    document = evidence_document(full)
    assert document["decisions"][0]["receipt"] == RECEIPT
    assert evidence_digest(full) != evidence_digest(evidence())
    for broken in (
        lambda e: e["decisions"][0]["receipt"].update(status="maybe"),
        lambda e: e["decisions"][0]["receipt"].update(cost_usd="1e-5"),
        lambda e: e["decisions"][0]["receipt"].update(words="a line"),
        lambda e: e.update(coverage={"decisions": "some"}),
        lambda e: e.update(captured_at="yesterday"),
        lambda e: e.update(captured_at="2026-10-14T01:02:03+02:00"),
    ):
        bad = deepcopy(full)
        broken(bad)
        with pytest.raises(ProjectError):
            evidence_document(bad)


def test_the_committed_json_schema_is_the_model_s_schema():
    committed = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    generated = Evidence.model_json_schema()
    assert committed["$id"] == "exulanica.world-project-evidence/v1"
    assert {k: v for k, v in committed.items() if k not in ("$id", "$schema")} == generated


def test_the_format_document_describes_every_field():
    text = FORMAT_DOC.read_text(encoding="utf-8")
    described = set(re.findall(r"^\| `([a-z0-9_]+)` \|", text, flags=re.MULTILINE))
    schema = Evidence.model_json_schema()
    fields = set(schema["properties"])
    for definition in schema["$defs"].values():
        fields |= set(definition.get("properties", {}))
    assert fields - described == set()
    assert "exulanica.world-project-evidence/v1" in text
