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


SESSION = "0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b"


def living(state="closed", reason="session_minutes"):
    block = {
        "session_id": SESSION,
        "state": state,
        "opened": {
            "tick": 4,
            "at": "2026-10-14T01:00:00Z",
            "state_sha256": "a" * 64,
            "limits": {
                "wall_seconds": 3600,
                "minutes": 60,
                "decisions": 500,
                "usd": "0.5",
                "calls": 600,
            },
        },
        "closed": None,
        "spending": {
            "used": {
                "wall_seconds": 1200,
                "minutes": 57,
                "decisions": 412,
                "usd": "0.0411",
                "calls": 415,
                "unresolved_count": 0,
                "unresolved_usd": "0",
            },
            "bounds": [
                {
                    "provider": "synthetic",
                    "state": "closed",
                    "ceiling_usd": "0.5",
                    "committed_usd": "0.0411",
                    "committed_calls": 415,
                    "known_usage_usd": "0.0371",
                    "unresolved_count": 0,
                    "unresolved_usd": "0",
                    "reconciled_usd": "0",
                }
            ],
        },
    }
    if state == "closed":
        block["closed"] = {
            "tick": 61,
            "at": "2026-10-14T01:20:00Z",
            "state_sha256": "b" * 64,
            "reason": reason,
            "by": "person" if reason in ("stopped_by_person", "paused_by_person") else "system",
        }
    return block


def test_a_living_session_is_one_closed_block_of_codes_and_numbers():
    full = evidence()
    full["session_id"] = f"session:{SESSION}"
    full["living_session"] = living()
    document = evidence_document(full)
    assert document["living_session"]["closed"]["reason"] == "session_minutes"
    assert "living_session" not in evidence_document(evidence())
    for broken in (
        lambda b: b.update(state="open"),  # closed recorded while it says open
        lambda b: b.update(closed=None),  # says closed with nothing recorded
        lambda b: b["closed"].update(by="person"),  # the system closed it at a limit
        lambda b: b["closed"].update(tick=3),  # closed before it opened
        lambda b: b["closed"].update(closed_by="someone"),  # no actor identities
        lambda b: b["opened"]["limits"].pop("calls"),
        lambda b: b["spending"]["used"].update(usd="1e-3"),
        lambda b: b["spending"]["bounds"][0].update(bound_id="x"),
        lambda b: b.update(session_id="not-a-uuid"),
    ):
        bad = deepcopy(full)
        broken(bad["living_session"])
        with pytest.raises(ProjectError):
            evidence_document(bad)
    # A person's stop is said to be a person's.
    stopped = deepcopy(full)
    stopped["living_session"] = living(reason="stopped_by_person")
    assert evidence_document(stopped)["living_session"]["closed"]["by"] == "person"
    # The file names the session it holds.
    other = deepcopy(full)
    other["session_id"] = "session:elsewhere"
    with pytest.raises(ProjectError):
        evidence_document(other)
