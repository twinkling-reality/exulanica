"""The assembly rule and the reference shapes, read and replayed without a database."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from exulanica.api.permissions import ROUTE_RULES
from exulanica.world.project_context_assembly import (
    KIND_ORDER,
    MAX_BYTES,
    MAX_ENTRIES,
    MIN_BYTES,
    Budget,
    Candidate,
    assemble,
    entry_bytes,
)
from exulanica.world.project_context_references import (
    CONTROL_OPERATIONS,
    EDIT_OPERATIONS,
    MAX_REFERENCES,
    STYLE_OPERATIONS,
    InvalidReference,
    ReferenceKind,
    parse_reference,
    parse_references,
)

_T0 = dt.datetime(2026, 9, 30, 12, 0, tzinfo=dt.UTC)


def _candidate(kind: str, text: str, *, minutes: int = 0, revision: int = 1, item=None, ok=True):
    item_id = item or uuid.uuid4()
    return Candidate(
        item_id=item_id,
        revision=revision,
        kind=kind,
        changed_at=_T0 + dt.timedelta(minutes=minutes),
        text=text,
        entry={"item_id": str(item_id), "revision": revision, "kind": kind, "text": text},
        required_available=ok,
    )


def test_entries_come_in_kind_order_then_newest_first():
    older = _candidate("goal", "older goal", minutes=1)
    newer = _candidate("goal", "newer goal", minutes=5)
    event = _candidate("event", "an event", minutes=9)
    task = _candidate("task", "a task")
    preference = _candidate("preference", "a preference")
    out = assemble([event, task, older, preference, newer], project_revision=3, budget=Budget())
    assert [e["text"] for e in out.entries] == [
        "newer goal",
        "older goal",
        "a preference",
        "a task",
        "an event",
    ]
    assert KIND_ORDER == ("goal", "preference", "task", "question", "decision", "event")


def test_a_focus_moves_items_that_share_its_words_first_and_admits_nothing():
    shade = _candidate("preference", "Benches in the SHADE please")
    goal = _candidate("goal", "A busy market")
    out = assemble([goal, shade], project_revision=1, budget=Budget(), focus="where is shade?")
    assert [e["text"] for e in out.entries] == ["Benches in the SHADE please", "A busy market"]
    assert len(assemble([goal], project_revision=1, budget=Budget(), focus="shade").entries) == 1


def test_the_budget_leaves_whole_entries_out_and_counts_why():
    long = _candidate("goal", "x" * 900)
    short = _candidate("preference", "short")
    unavailable = _candidate("decision", "", ok=False)
    budget = Budget(max_entries=5, max_bytes=MIN_BYTES)
    out = assemble(
        [long, short, unavailable],
        project_revision=2,
        budget=budget,
        omitted={"pending_review": 4, "resolved": 1},
    )
    assert [e["text"] for e in out.entries] == ["x" * 900]
    assert out.used_bytes == entry_bytes(long.entry) <= budget.max_bytes
    assert dict(out.omitted) == {
        "over_budget": 1,
        "reference_unavailable": 1,
        "pending_review": 4,
        "resolved": 1,
    }
    capped = assemble([long, short], project_revision=2, budget=Budget(max_entries=1))
    assert len(capped.entries) == 1 and capped.omitted["over_budget"] == 1


def test_the_digest_covers_ids_and_revisions_and_no_words():
    item = uuid.uuid4()
    one = assemble(
        [_candidate("goal", "first words", item=item)], project_revision=7, budget=Budget()
    )
    two = assemble(
        [_candidate("goal", "other words", item=item)], project_revision=7, budget=Budget()
    )
    moved = assemble(
        [_candidate("goal", "first words", item=item, revision=2)],
        project_revision=7,
        budget=Budget(),
    )
    assert one.assembly_sha256 == two.assembly_sha256 != moved.assembly_sha256
    again = assemble(
        [_candidate("goal", "first words", item=item)], project_revision=8, budget=Budget()
    )
    assert again.assembly_sha256 != one.assembly_sha256


@pytest.mark.parametrize(
    ("entries", "size"),
    [(0, 8192), (MAX_ENTRIES + 1, 8192), (24, MIN_BYTES - 1), (24, MAX_BYTES + 1), (True, 8192)],
)
def test_a_budget_outside_the_contract_is_refused(entries, size):
    with pytest.raises(ValueError):
        Budget(max_entries=entries, max_bytes=size)


# -- references ----------------------------------------------------------------------------------


def _edit(**over):
    return {
        "kind": "world_edit",
        "operation": "POST /world/versions/{version_id}/compositions/apply",
        "world_id": "world:authored:x",
        "version_id": str(uuid.uuid4()),
        "edit_id": str(uuid.uuid4()),
        "edit_seq": 1,
        "result_state_sha256": "a" * 64,
        **over,
    }


def test_every_operation_a_reference_names_is_a_declared_write_route():
    declared = {f"{method} {path}" for method, path in ROUTE_RULES}
    for operation in EDIT_OPERATIONS | STYLE_OPERATIONS | CONTROL_OPERATIONS:
        assert operation in declared, operation
        assert not operation.startswith("GET "), operation


def test_a_reference_is_read_in_its_kinds_exact_shape():
    parsed = parse_reference(_edit(version_id=str(uuid.uuid4()).upper()))
    assert parsed.kind is ReferenceKind.WORLD_EDIT
    assert parsed.fields["version_id"] == parsed.fields["version_id"].lower()
    for bad in (
        {**_edit(), "kind": "anything"},
        {k: v for k, v in _edit().items() if k != "edit_seq"},
        {**_edit(), "extra": 1},
        _edit(edit_seq=0),
        _edit(edit_seq=True),
        _edit(result_state_sha256="A" * 64),
        _edit(operation="GET /world/versions/{version_id}"),
        _edit(edit_id="not-a-uuid"),
        _edit(world_id=""),
    ):
        with pytest.raises(InvalidReference):
            parse_reference(bad)


def test_a_control_step_names_its_tick_and_state_and_a_configuration_neither():
    base = {
        "kind": "society_control",
        "world_id": "w",
        "version_id": str(uuid.uuid4()),
        "revision": 2,
    }
    step = "POST /world/versions/{version_id}/society/control/steps"
    put = "PUT /world/versions/{version_id}/society/control"
    parse_reference({**base, "operation": step, "tick": 3, "state_sha256": "b" * 64})
    parse_reference({**base, "operation": put, "tick": None, "state_sha256": None})
    for wrong in (
        {**base, "operation": step, "tick": None, "state_sha256": None},
        {**base, "operation": put, "tick": 3, "state_sha256": "b" * 64},
    ):
        with pytest.raises(InvalidReference):
            parse_reference(wrong)


def test_an_item_names_each_record_once_and_at_most_eight():
    one = _edit()
    with pytest.raises(InvalidReference):
        parse_references([one, dict(one)])
    assert len(parse_references([_edit() for _ in range(MAX_REFERENCES)])) == MAX_REFERENCES
    with pytest.raises(InvalidReference):
        parse_references([_edit() for _ in range(MAX_REFERENCES + 1)])


def test_an_event_names_its_edit_whole_or_not_at_all():
    event = {
        "kind": "society_event",
        "world_id": "w",
        "version_id": str(uuid.uuid4()),
        "event_id": str(uuid.uuid4()),
        "tick": 4,
        "input_seq": 2,
        "object_id": "bench",
        "edit_seq": 3,
        "edit_id": str(uuid.uuid4()),
    }
    parse_reference(event)
    with pytest.raises(InvalidReference):
        parse_reference({**event, "edit_id": None})
