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

CATALOG = Path(__file__).resolve().parents[1] / "assets/catalogs/roles/choice-account-words.v2.json"


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
    assert verdict(receipt(), words) == "Done in minute 2."
    assert verdict(None, words) == "No answer is recorded yet."
    assert verdict(receipt(disposition=None), words) == "Chosen; no minute has acted on it yet."
    stale = verdict(receipt(disposition="stale", minute=7), words)
    assert stale.startswith("Not done: the world had moved on before minute 7")
    refused = verdict(receipt(status="rejected", reason="never_heard_of_it"), words)
    # A reason with no words is in the record alone: no code in the sentence.
    assert refused == "Refused: the reason is only in the record."
    untaken = verdict({**receipt(status="unavailable"), "consumed_tick": None}, words)
    assert untaken.endswith("No minute has taken it up yet.")
    # A reason with words in the society words catalog reads in those words.
    timed_out = verdict({**receipt(status="unavailable", reason="model_timed_out")}, words)
    assert (
        timed_out
        == "No usable answer: their model did not answer in time. The routine acted in minute 2."
    )


def test_the_words_come_from_the_shared_catalog(tmp_path):
    changed = json.loads(CATALOG.read_text(encoding="utf-8"))
    _set(changed, "verdict.applied", "Finished in minute {minute}.")
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    assert verdict(receipt(), choice_words(path)) == "Finished in minute 2."
    assert changed["verdict_order"] == [
        "awaiting_answer",
        "refused",
        "no_answer",
        "stale",
        "not_applied",
        "pending",
        "applied",
    ]


def test_private_repositories_read_the_chosen_words_and_public_ones_none():
    world, evidence = session()
    private = "\n".join(insight(world, {"session-one.json": evidence}, readable=True))
    public = "\n".join(insight(world, {"session-one.json": evidence}, readable=False))
    assert "Minute 1: chose \u201crest by the well\u201d, from 2 choices. Done in minute 2." in (
        private
    )
    for text in ("rest by the well", "Time to sit", "plain armour", "(go)", "option 2"):
        assert text not in public
    assert "Minute 1: chose one of 2 choices. Done in minute 2." in public
    for text in (private, public):
        assert "- The knight, with synthetic-model: 6 decisions, 6 done" in text
        assert "| synthetic-model | The knight | 6 | 6 of 6 |" in text
        assert "It is not a bill." in text
    assert "| not shown on a public repository |" in public


def test_a_public_repository_s_text_names_no_character_whatever_the_files_hold():
    world, evidence = session()
    world["characters"] = [
        {"thing_id": "knight:1", "revision": 1, "words": {"name": "Sir Pip", "about": None}}
    ]
    public = "\n".join(insight(world, {"session-one.json": evidence}, readable=False))
    assert "Sir Pip" not in public and "- The knight, with synthetic-model" in public
    private = "\n".join(insight(world, {"session-one.json": evidence}, readable=True))
    assert "- Sir Pip, with synthetic-model" in private


def test_what_the_files_cannot_support_is_named_never_zero():
    world, evidence = session(count=3)
    text = "\n".join(insight(world, {"session-one.json": evidence}, readable=True))
    assert "| 3 of 3, not enough yet |" in text  # 3 decisions, 5 needed.
    assert "| not enough yet |" in text  # 3 latencies, 5 needed.
    assert "only the decisions the world acted on" in text
    assert "timeout" not in text
    world, old = session(count=6, receipts=False, coverage=None)
    text = "\n".join(insight(world, {"session-one.json": old}, readable=True))
    assert "6 decisions; what the world did with them was not recorded" in text
    assert "| not recorded | not recorded | not recorded | not recorded |" in text
    assert "6 of 6" not in text


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
    assert "Shortened to fit: each run's file has every decision." in text
    # The model table is never cut.
    assert "## How each model did" in text
    assert "| synthetic-model | The knight | 102400 | 102400 of 102400 |" in text


def test_many_sessions_collapse_older_ones_to_a_line_each():
    world, evidence = session(count=1)
    sessions = {}
    for n in range(800):
        copy = deepcopy(evidence)
        copy["session_id"] = f"session:s{n:03d}"
        sessions[f"session-s{n:03d}.json"] = copy
    text = "\n".join(insight(world, sessions, readable=True))
    assert len(text) <= BUDGET
    assert "older runs are counted only" in text
    assert text.count("A record of decisions: 1 decision, in its file.") == 797
    assert text.count("### Decisions, minutes 1 to 1") == 3
    assert "| 800 | 800 of 800 |" in text
    assert "s000" not in text and "s799" not in text


def living_evidence(
    state="closed", reason="session_minutes", coverage="all", unresolved=0, session_id=None
):
    from test_world_project_evidence_format import living

    world, evidence = session(coverage=coverage)
    block = living(state=state, reason=reason)
    if session_id is not None:
        block["session_id"] = session_id
    evidence["session_id"] = f"session:{block['session_id']}"
    if unresolved:
        block["spending"]["used"].update(unresolved_count=unresolved, unresolved_usd="0.004")
    evidence["living_session"] = block
    return world, {f"session-{block['session_id']}.json": evidence}


def test_a_run_says_how_long_it_ran_what_it_spent_and_why_it_ended():
    world, sessions = living_evidence()
    text = "\n".join(insight(world, sessions, readable=True))
    assert "### Run 1 \u00b7 14 October, 01:00 UTC" in text
    assert (
        "Ran 57 minutes with the knight's model \u00b7 minutes 4 to 61 \u00b7 6 decisions "
        "\u00b7 spent $0.04 of at most $0.50. The run played all its minutes."
    ) in text
    # Every request of the run was read, so nothing is left uncounted.
    assert "acted on" not in text
    assert "0190a1b2" not in text and "session" not in text.lower()


def test_the_stop_words_are_the_society_s_own(monkeypatch):
    from exulanica.world import society_sessions

    monkeypatch.setitem(
        society_sessions.SESSION_CLOSED_WORDS, "session_minutes", "It ran out of minutes."
    )
    world, sessions = living_evidence()
    assert "It ran out of minutes." in "\n".join(insight(world, sessions, readable=True))


def test_an_open_run_and_an_unknown_cost_are_said_as_they_are():
    world, sessions = living_evidence(state="open", unresolved=3)
    text = "\n".join(insight(world, sessions, readable=False))
    assert (
        "Running when recorded: 57 minutes so far with the knight's model \u00b7 from minute 4 "
        "\u00b7 6 decisions \u00b7 spent $0.04 of at most $0.50, and up to $0.0040 more is not "
        "known yet."
    ) in text


def test_runs_are_numbered_by_when_they_opened():
    world, later = living_evidence(session_id="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a50")
    _, earlier = living_evidence(session_id="0190a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5f")
    [(name, run)] = earlier.items()
    run["living_session"]["opened"]["at"] = "2026-10-13T22:30:00Z"
    text = "\n".join(insight(world, {**later, name: run}, readable=True))
    assert text.index("### Run 1 \u00b7 13 October, 22:30 UTC") < text.index(
        "### Run 2 \u00b7 14 October, 01:00 UTC"
    )
    assert "| synthetic-model | The knight | 12 | 12 of 12 |" in text


def test_decisions_asked_under_an_earlier_model_stay_under_that_model():
    from exulanica.canonical import canonical_json
    from exulanica.world_package.projects.checkpoint import digest

    world, sessions = living_evidence()
    [evidence] = sessions.values()
    earlier = {**evidence["models"][0], "model_id": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"}
    evidence["models"].append(earlier)
    for decision in evidence["decisions"][:2]:
        decision["binding_sha256"] = digest(canonical_json(earlier))
    text = "\n".join(insight(world, sessions, readable=True))
    assert "- The knight, with Nemotron 3 Nano 30B: 2 decisions, 2 done" in text
    assert "- The knight, with synthetic-model: 4 decisions, 4 done" in text
    assert "| Nemotron 3 Nano 30B | The knight | 2 |" in text
    assert "NVIDIA-Nemotron" not in text
