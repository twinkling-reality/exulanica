"""The nine canonical visual gate keys, the drift table, and the reconciliation record.

The three retained rejection records are local-only evidence: they are listed in the checkout's
exclude file and exist only where they were produced. Every assertion that reads one runs when the
file is present and skips, naming the file, when it is not, so a checkout without them says what
it could not check instead of passing it silently.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.evaluation import gate_keys
from exulanica.evaluation.gate_keys import (
    CANONICAL_KEYS,
    CANONICAL_SPELLINGS,
    CAPTURE_LABELS,
    MELBOURNE_ENVELOPE,
    RETAINED_RECORDS,
    RUBRIC_QUESTIONS,
    THRESHOLDS,
    UnknownGateKey,
    resolve,
)

_ROOT = Path(__file__).resolve().parents[1]
_RECONCILIATION = _ROOT / "docs/evaluation/2026-09-15-visual-gate-key-reconciliation.json"

#: The drift the operator's plan proposed, restated here so the module is checked against it
#: rather than against itself.
_PROPOSED = {
    "continuousTexturedStreetAndFacades": {
        "continuousTexturedGround",
        "continuousTexturedStreet",
        "continuousSourceTexturedStreetAndFacades",
    },
    "readsAsInhabitedStreet": {
        "recognizableUrbanStreet",
        "recognizableUrbanScene",
        "recognizableMelbourneUrbanScene",
    },
    "noCutsOrFloatingGeometry": {
        "noFloatingOrCutGeometry",
        "noCutOrFloatingGeometry",
        "noLargeCutsOrFloatingGeometry",
    },
    "usefulEyeLevelMovement": {
        "eyeLevelMovement",
        "verifiedEyeLevelMovement",
        "usefulEyeLevelMovement",
    },
    "completeCapsuleClearanceVerification": {"completeCapsuleClearanceVerification"},
    "practicalBrowserBudget": {"practicalBrowserBudget"},
    "companionPresent": {"companionPresent"},
    "reticlePresent": {"reticlePresent"},
    "authenticatedShellAndAuthoredHandlersPreserved": {
        "authenticatedShellAndAuthoredHandlersPreserved"
    },
}


def _retained(path: str) -> dict:
    file = _ROOT / path
    if not file.is_file():
        pytest.skip(f"{path} is local-only retained evidence and is not in this checkout")
    return json.loads(file.read_bytes())


def _reconciliation() -> dict:
    assert _RECONCILIATION.is_file(), "the key reconciliation record is a retained deliverable"
    return json.loads(_RECONCILIATION.read_bytes())


def test_the_canonical_set_has_exactly_nine_members_in_one_spelling_each():
    assert len(CANONICAL_KEYS) == 9
    assert len(set(CANONICAL_SPELLINGS)) == 9
    assert set(CANONICAL_SPELLINGS) == set(_PROPOSED)
    assert {item.evidence_kind for item in CANONICAL_KEYS} == {"mechanical", "judged"}
    judged = [item.spelling for item in CANONICAL_KEYS if item.evidence_kind == "judged"]
    assert judged == ["readsAsInhabitedStreet"]


def test_no_canonical_spelling_names_a_source_or_a_city():
    for spelling in CANONICAL_SPELLINGS:
        assert "Source" not in spelling, spelling
        assert "Melbourne" not in spelling, spelling
        assert "Helsinki" not in spelling, spelling


def test_every_mechanical_key_names_the_measurement_that_decides_it():
    for item in CANONICAL_KEYS:
        assert item.definition.startswith("True only when"), item.spelling
        if item.evidence_kind == "mechanical":
            assert item.measurement, item.spelling
            assert item.decided_by, item.spelling
        else:
            assert item.measurement is None
            assert item.decided_by == ()


def test_the_mapping_is_the_proposed_one_and_is_unambiguous():
    resolved: dict[str, set[str]] = {}
    for canonical, spellings in _PROPOSED.items():
        for spelling in spellings:
            resolved.setdefault(spelling, set()).add(resolve(spelling))
            assert resolve(spelling) == canonical, spelling
    assert all(len(targets) == 1 for targets in resolved.values()), resolved
    for item in CANONICAL_KEYS:
        assert set(item.predecessor_spellings) | {item.spelling} == _PROPOSED[item.spelling] | {
            item.spelling
        }


def test_the_resolver_raises_on_an_invented_spelling_rather_than_passing_it_through():
    for invented in (
        "recognisableUrbanScene",
        "continuousTexturedFacades",
        "readsAsInhabitedStreets",
        "noFloatingGeometry",
        "",
        "companionpresent",
    ):
        with pytest.raises(UnknownGateKey):
            resolve(invented)


def test_an_ambiguous_table_refuses_to_build(monkeypatch):
    duplicate = gate_keys.GateKey(
        spelling="reticlePresent",
        definition="True only when duplicated.",
        evidence_kind="mechanical",
        measurement="x",
        decided_by=("captures",),
        predecessor_spellings=("companionPresent",),
    )
    monkeypatch.setattr(gate_keys, "CANONICAL_KEYS", (*gate_keys.CANONICAL_KEYS, duplicate))
    with pytest.raises(RuntimeError, match="resolves to both"):
        gate_keys._resolution_table()


@pytest.mark.parametrize("retained", RETAINED_RECORDS, ids=lambda record: record.label)
def test_every_retained_spelling_resolves_and_the_table_matches_the_record(retained):
    document = _retained(retained.path)
    hard_pass = document["record"]["hardPass"]
    resolved = {resolve(spelling): spelling for spelling in hard_pass}
    assert len(resolved) == len(hard_pass), "two spellings of one record resolve to one key"
    assert resolved == dict(retained.spellings)
    digest = hashlib.sha256(canonical_json(document["record"])).hexdigest()
    assert digest == document["record_sha256"] == retained.record_sha256


def test_the_retained_key_counts_are_six_seven_and_nine():
    counts = {record.label: len(record.spellings) for record in RETAINED_RECORDS}
    assert counts == {
        "helsinki-visual-feasibility": 6,
        "helsinki-terminal-lod-successor": 7,
        "melbourne-c4-29-visual-feasibility": 9,
    }


def test_the_reconciliation_record_reproduces_its_digest_and_binds_the_three_rejections():
    document = _reconciliation()
    record = document["record"]
    assert document["profile"] == "exulanica.digest-bound-record/v1"
    assert document["record_sha256"] == hashlib.sha256(canonical_json(record)).hexdigest()
    bindings = {item["path"]: item["record_sha256"] for item in record["predecessor_records"]}
    assert bindings == {record.path: record.record_sha256 for record in RETAINED_RECORDS}
    assert record["mappingChecks"] == {
        "retainedSpellings": 17,
        "retainedSpellingsResolved": 17,
        "total": True,
        "unambiguous": True,
        "canonicalKeys": 9,
    }


def test_the_reconciliation_record_states_the_module_it_was_written_from():
    """A later edit to the definitions has to come with a new record, not drift past this one."""
    record = _reconciliation()["record"]
    assert [entry["key"] for entry in record["canonicalKeys"]] == list(CANONICAL_SPELLINGS)
    for entry, item in zip(record["canonicalKeys"], CANONICAL_KEYS, strict=True):
        assert entry["definition"] == item.definition
        assert entry["evidenceKind"] == item.evidence_kind
        assert entry["predecessorSpellings"] == list(item.predecessor_spellings)
        if item.evidence_kind == "mechanical":
            assert entry["measurement"] == item.measurement
            assert entry["decidedBy"] == list(item.decided_by)
        else:
            assert entry["rubric"] == "docs/visual-gate-rubric.md"
    assert record["thresholds"] == dict(THRESHOLDS)
    assert record["melbourneEnvelope"] == dict(MELBOURNE_ENVELOPE)
    assert record["judgedKey"]["captures"] == list(CAPTURE_LABELS)
    assert [(q["id"], q["text"]) for q in record["judgedKey"]["questions"]] == list(
        RUBRIC_QUESTIONS
    )


@pytest.mark.parametrize("retained", RETAINED_RECORDS, ids=lambda record: record.label)
def test_the_reconciliation_declares_each_records_actual_spellings(retained):
    document = _retained(retained.path)
    actual = set(document["record"]["hardPass"])
    entry = next(
        item
        for item in _reconciliation()["record"]["retainedRecords"]
        if item["label"] == retained.label
    )
    assert entry["record_sha256"] == retained.record_sha256
    declared = {value["spelling"] for value in entry["keys"].values() if value["state"] == "scored"}
    assert declared == actual
    for canonical, value in entry["keys"].items():
        if value["state"] == "scored":
            assert value["retainedValue"] is document["record"]["hardPass"][value["spelling"]]
            assert resolve(value["spelling"]) == canonical


def _booleans(node) -> list:
    if isinstance(node, bool):
        return [node]
    if isinstance(node, dict):
        return [found for item in node.values() for found in _booleans(item)]
    if isinstance(node, list):
        return [found for item in node for found in _booleans(item)]
    return []


def test_absence_is_recorded_as_absence_and_never_as_a_boolean():
    entries = {item["label"]: item for item in _reconciliation()["record"]["retainedRecords"]}
    expected_absent = {
        "helsinki-visual-feasibility": {
            "completeCapsuleClearanceVerification",
            "practicalBrowserBudget",
            "authenticatedShellAndAuthoredHandlersPreserved",
        },
        "helsinki-terminal-lod-successor": {
            "completeCapsuleClearanceVerification",
            "practicalBrowserBudget",
        },
        "melbourne-c4-29-visual-feasibility": set(),
    }
    for label, absent in expected_absent.items():
        keys = entries[label]["keys"]
        assert set(keys) == set(CANONICAL_SPELLINGS)
        found = {name for name, value in keys.items() if value["state"] == "absent"}
        assert found == absent, label
        for name in absent:
            assert set(keys[name]) <= {"state", "note", "briefedCriterion"}
            assert _booleans(keys[name]) == [], (label, name)
            assert "retainedValue" not in keys[name]


def test_the_shell_key_is_anchored_to_melbournes_preview_condition():
    anchor = _reconciliation()["record"]["authenticatedShellUnderMelbourne"]
    assert anchor["retainedValue"] is True
    assert [item["status"] for item in anchor["previewApi404s"]] == [404, 404, 404]
    assert all("/preview-api/" in item["url"] for item in anchor["previewApi404s"])
    assert "does not by itself assert a real bearer token" in anchor["statement"]
    melbourne = _retained("docs/evaluation/2026-09-12-melbourne-c4-29-visual-feasibility.json")
    assert anchor["previewApi404s"] == melbourne["record"]["browser"]["previewApi404s"]
