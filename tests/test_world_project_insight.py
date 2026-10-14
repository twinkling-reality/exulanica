"""Insight in a world project's pull request: generated from evidence files alone, synthetic."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from exulanica.world_package.projects.checkpoint import ProjectError, document
from exulanica.world_package.projects.insight import (
    BUDGET,
    choice_words,
    insight,
    verdict,
)

from test_world_project import sample
from test_world_project_repository import evidence_from

CATALOG = Path(__file__).resolve().parents[1] / "assets/catalogs/roles/choice-account-words.v1.json"


def _set(catalog, key, words):
    [entry] = [e for e in catalog["entries"] if e["key"] == key]
    entry["words"] = words


def receipt(status="accepted", disposition="applied", reason="validated_choice", minute=2):
    return {
        "status": status,
        "reason": reason,
        "disposition": disposition,
        "disposition_reason": "applied" if disposition == "applied" else "option_no_longer_offered",
        "consumed_tick": minute,
        "served_model_id": "synthetic-model-rev-1",
        "cost_usd": "0.0001",
        "cost_known": True,
    }


def session(
    count=6, *, readable=True, receipts=True, coverage="consumed", label="rest by the well"
):
    project, _ = sample()
    world, evidence = evidence_from(project)
    base = evidence["decisions"][0]
    decisions = []
    for n in range(count):
        record = deepcopy(base)
        record.update(record_id=f"record:{n}", tick=n + 1, elapsed_ms=100 + n)
        record["options"] = [
            {"option_id": "option:1", "action": "wait", "target_id": None},
            {"option_id": "option:2", "action": "go", "target_id": "well:1"},
        ]
        record["chosen_option_id"] = "option:2"
        if receipts:
            record["receipt"] = receipt(minute=n + 2)
        if readable:
            record["readable"] = {
                "situation": "You are a knight: a knight in plain armour.",
                "options": ["wait here a minute", label],
                "choice": label,
                "line": "Time to sit.",
                "status": "accepted",
                "reason": "validated_choice",
                "consumed_tick": n + 2,
                "disposition": "applied",
                "served_model_id": "synthetic-model-rev-1",
                "cost_usd": "0.0001",
                "cost_known": True,
            }
        decisions.append(record)
    evidence["decisions"] = decisions
    if coverage is not None:
        evidence["coverage"] = {"decisions": coverage}
    return document(world), evidence


def test_verdict_words_follow_the_choice_account():
    words = choice_words()
    assert verdict(receipt(), words) == "Applied in minute 2."
    assert verdict(None, words) == "No answer is recorded yet."
    assert verdict(receipt(disposition=None), words) == "Accepted; no minute has acted on it yet."
    stale = verdict(receipt(disposition="stale", minute=7), words)
    assert stale.startswith("Not applied: the world had moved on before minute 7")
    refused = verdict(receipt(status="rejected", reason="never_heard_of_it"), words)
    assert refused == "Refused: of a reason recorded as never_heard_of_it."
    untaken = verdict({**receipt(status="unavailable"), "consumed_tick": None}, words)
    assert untaken.endswith("No minute has taken it up yet.")
    # A reason with words in the society words catalog reads in those words.
    timed_out = verdict({**receipt(status="unavailable", reason="model_timed_out")}, words)
    assert (
        timed_out == "No usable answer: it did not answer in time. Its routine acted in minute 2."
    )


def test_the_words_come_from_the_shared_catalog(tmp_path):
    changed = json.loads(CATALOG.read_text(encoding="utf-8"))
    _set(changed, "verdict.applied", "Done in minute {minute}.")
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert verdict(receipt(), choice_words(path)) == "Done in minute 2."
    assert changed["verdict_order"] == [
        "awaiting_answer",
        "refused",
        "no_answer",
        "stale",
        "not_applied",
        "pending",
        "applied",
    ]


def test_private_repositories_read_labels_and_public_ones_codes_only():
    world, evidence = session()
    private = "\n".join(insight(world, {"session-one.json": evidence}, readable=True))
    public = "\n".join(insight(world, {"session-one.json": evidence}, readable=False))
    assert "“rest by the well”" in private
    for text in ("rest by the well", "Time to sit", "plain armour"):
        assert text not in public
    assert "option 2 (go)" in public
    for text in (private, public):
        assert "6 decisions" in text and "applied 6 of 6" in text
        assert "not a bill" in text


def test_what_the_files_cannot_support_is_named_never_zero():
    world, evidence = session(count=3)
    text = "\n".join(insight(world, {"session-one.json": evidence}, readable=True))
    assert "not enough data yet" in text  # 3 latencies, 5 needed.
    assert "Unavailable here" in text and "took up" in text
    assert "0 timeouts" not in text
    world, old = session(count=6, receipts=False, coverage=None)
    text = "\n".join(insight(world, {"session-one.json": old}, readable=True))
    assert "receipts were not recorded" in text
    assert "applied 6 of 6" not in text


def test_the_generated_text_passes_the_value_scan(tmp_path):
    changed = json.loads(CATALOG.read_text(encoding="utf-8"))
    _set(changed, "verdict.applied", "Applied; see /Users/someone/notes in minute {minute}.")
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    world, evidence = session()
    with pytest.raises(ProjectError, match="value scan"):
        insight(world, {"session-one.json": evidence}, readable=True, words=choice_words(path))


def test_a_long_history_stays_within_the_budget_and_keeps_its_counts():
    world, evidence = session(count=1024, label="rest by the well " + "x" * 300)
    sessions = {}
    for n in range(100):
        copy = deepcopy(evidence)
        copy["session_id"] = f"session:s{n:02d}"
        sessions[f"session-s{n:02d}.json"] = copy
    lines = insight(world, sessions, readable=True)
    text = "\n".join(lines)
    assert len(text) <= BUDGET
    assert "1024 decisions" in text
    # Unshortened it would not fit; the text says what was left out.
    assert "Shortened to fit: decision lines are left out" in text
    # The model table is never cut.
    assert "How each model did" in text and "applied 102400 of 102400" in text


def test_many_sessions_collapse_older_ones_to_a_line_each():
    world, evidence = session(count=1)
    sessions = {}
    for n in range(500):
        copy = deepcopy(evidence)
        copy["session_id"] = f"session:s{n:03d}"
        sessions[f"session-s{n:03d}.json"] = copy
    text = "\n".join(insight(world, sessions, readable=True))
    assert len(text) <= BUDGET
    assert "older sessions' detail are left out" in text
    assert "- session:s000: 1 decision, see its file evidence/session-s000.json." in text
    assert "session:s499, minutes 1 to 1" in text
    assert "applied 500 of 500" in text
