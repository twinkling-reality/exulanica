"""Piece requests on a migrated database: what the table and the store promise.

A request is written whole and only its progress moves; a caller's key answers with the ask it
named or refuses another body; an open request for the same world and digest is held once; a person
cancels only a request no session has taken; the workspace's limits are counted; a workspace
tombstone cancels every open request and refuses new ones. The rows are read back with SQL of the
test's own, not through the store.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid

import psycopg
import pytest
from exulanica.errors import TombstonedError
from exulanica.generation import store
from exulanica.generation.requests import (
    GPU_PROVIDER,
    LookReference,
    PieceAskRefused,
    generation_catalogs,
    plan_requests,
)
from exulanica.world.style_pack_library import style_pack_library
from exulanica_pieces.canonical import canonical_bytes, sha256_hex
from psycopg.rows import dict_row

from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

ACTOR = uuid.UUID("5b0c7d1e-2f3a-4b5c-9d6e-7f8091a2b3c4")
LIBRARY = style_pack_library()


def _look() -> LookReference:
    pack = LIBRARY.default_pack
    return LookReference(pack.pack_id, pack.version, pack.manifest_sha256)


def _ask(connection, workspace_id, kinds=(("well", 1),), **changes):
    planned = plan_requests(list(kinds), _look(), library=LIBRARY)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    arguments = dict(
        requested_by=ACTOR,
        world_id=FIXTURE_WORLD_ID,
        look=_look(),
        planned=planned,
        worst_cases=[compute.worst_case_usd(plan.variants) for plan in planned],
    )
    arguments.update(changes)
    return store.create_piece_requests(connection, workspace_id, **arguments)


@pytest.fixture
def world(repository):
    registered_world(repository.connection, repository.workspace_id, actor=ACTOR)
    return repository


def _row(connection, piece_request_id) -> dict:
    with connection.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(
            "select state, failure, queued_at, finished_at, request_canonical, request_sha256, "
            "world_id from piece_request where piece_request_id = %s",
            (piece_request_id,),
        ).fetchone()


def test_an_ask_makes_one_request_a_kind_holding_its_document(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    made, new = _ask(connection, workspace_id, kinds=(("well", 1), ("lantern", 1)))
    assert new and [record.kind_key for record in made] == ["well", "lantern"]
    for record in made:
        row = _row(connection, record.piece_request_id)
        assert (row["state"], row["queued_at"], row["finished_at"]) == ("requested", None, None)
        assert row["world_id"] == FIXTURE_WORLD_ID
        assert hashlib.sha256(row["request_canonical"].encode()).hexdigest() == (
            record.request_sha256
        )
        assert record.cache_scope == "catalog" and record.variants == 4
    assert {
        r.piece_request_id
        for r in store.list_piece_requests(connection, workspace_id, FIXTURE_WORLD_ID)
    } == {r.piece_request_id for r in made}
    assert store.read_piece_request(connection, workspace_id, made[0].piece_request_id) == made[0]
    assert store.read_piece_request(connection, workspace_id, uuid.uuid4()) is None


def test_a_key_answers_with_its_ask_or_refuses_another_body(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    key = uuid.uuid4()
    first, made = _ask(connection, workspace_id, request_id=key, ask_sha256="a" * 64)
    again, made_again = _ask(connection, workspace_id, request_id=key, ask_sha256="a" * 64)
    assert made and not made_again and again == first
    with pytest.raises(store.PieceAskKeyReused):
        _ask(connection, workspace_id, request_id=key, ask_sha256="b" * 64)


def test_an_open_request_for_the_same_world_and_digest_is_held_once(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    first, _ = _ask(connection, workspace_id)
    again, made = _ask(connection, workspace_id)
    assert not made and again[0].piece_request_id == first[0].piece_request_id
    # Once it has ended, the same ask makes a new request.
    store.cancel_piece_request(connection, workspace_id, first[0].piece_request_id)
    later, made_later = _ask(connection, workspace_id)
    assert made_later and later[0].piece_request_id != first[0].piece_request_id


def test_a_person_cancels_only_a_request_no_session_has_taken(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (made,), _ = _ask(connection, workspace_id)
    cancelled = store.cancel_piece_request(connection, workspace_id, made.piece_request_id)
    assert cancelled is not None and cancelled.state == "cancelled"
    row = _row(connection, made.piece_request_id)
    assert (row["state"], row["failure"]) == ("cancelled", "cancelled_by_person")
    assert row["finished_at"] is not None
    with pytest.raises(store.PieceRequestNotCancellable) as refused:
        store.cancel_piece_request(connection, workspace_id, made.piece_request_id)
    assert refused.value.state == "cancelled"
    assert store.cancel_piece_request(connection, workspace_id, uuid.uuid4()) is None
    (taken,), _ = _ask(connection, workspace_id, kinds=(("gate", 1),))
    connection.execute(
        "update piece_request set state = 'queued', queued_at = statement_timestamp() "
        "where piece_request_id = %s and world_id = %s",
        (taken.piece_request_id, FIXTURE_WORLD_ID),
    )
    with pytest.raises(store.PieceRequestNotCancellable):
        store.cancel_piece_request(connection, workspace_id, taken.piece_request_id)


@pytest.mark.parametrize(
    ("assignment", "match"),
    [
        ("kind_key = 'gate'", "not what it asked"),
        ("worst_case_usd = 0", "not what it asked"),
        ("request_canonical = request_canonical || ' '", "not what it asked"),
        ("state = 'made', finished_at = statement_timestamp()", "requested to queued"),
    ],
)
def test_what_was_asked_never_changes_and_progress_only_moves_forward(
    world, assignment: str, match: str
) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (made,), _ = _ask(connection, workspace_id)
    with pytest.raises(psycopg.errors.CheckViolation, match=match):
        connection.execute(
            f"update piece_request set {assignment} where piece_request_id = %s and world_id = %s",
            (made.piece_request_id, FIXTURE_WORLD_ID),
        )


def test_a_finished_request_never_changes(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (made,), _ = _ask(connection, workspace_id)
    store.cancel_piece_request(connection, workspace_id, made.piece_request_id)
    with pytest.raises(psycopg.errors.CheckViolation, match="never changes"):
        connection.execute(
            "update piece_request set state = 'requested', failure = null, finished_at = null "
            "where piece_request_id = %s and world_id = %s",
            (made.piece_request_id, FIXTURE_WORLD_ID),
        )


def _insert(connection, workspace_id, canonical: str, **columns):
    values = {
        "workspace_id": workspace_id,
        "requested_by": ACTOR,
        "world_id": FIXTURE_WORLD_ID,
        "kind_key": "well",
        "kind_version": 1,
        "kind_sha256": "1" * 64,
        "pack_id": "exulanica.cozy-town",
        "pack_version": 1,
        "pack_manifest_sha256": "2" * 64,
        "look_role": "fixture.well",
        "variants": 4,
        "request_canonical": canonical,
        "request_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "cache_scope": "catalog",
        "worst_case_usd": 0,
        **columns,
    }
    names = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    connection.execute(
        f"insert into piece_request ({names}) values ({marks})", tuple(values.values())
    )


def test_a_request_s_digest_is_its_bytes_and_it_starts_requested(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    with pytest.raises(psycopg.errors.CheckViolation, match="digest_is_its_bytes"):
        _insert(connection, workspace_id, '{"n":0}', request_sha256="3" * 64)
    with pytest.raises(psycopg.errors.CheckViolation, match="starts requested"):
        _insert(
            connection,
            workspace_id,
            '{"n":1}',
            state="queued",
            queued_at="2026-10-07T00:00:00Z",
        )


def test_the_workspace_s_open_requests_are_counted(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    with connection.cursor(row_factory=dict_row) as cursor:
        limits = cursor.execute(
            "select per_day, open_at_once from piece_request_limits()"
        ).fetchone()
    assert limits["open_at_once"] < limits["per_day"]
    for n in range(limits["open_at_once"]):
        _insert(connection, workspace_id, f'{{"n":{n}}}')
    with pytest.raises(store.PieceQuotaExceeded):
        _ask(connection, workspace_id)


def test_a_workspace_tombstone_cancels_every_open_request_and_takes_no_new_one(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    open_, _ = _ask(connection, workspace_id, kinds=(("well", 1), ("gate", 1)))
    connection.execute(
        "update piece_request set state = 'queued', queued_at = statement_timestamp() "
        "where piece_request_id = %s and world_id = %s",
        (open_[1].piece_request_id, FIXTURE_WORLD_ID),
    )
    (ended,), _ = _ask(connection, workspace_id, kinds=(("lantern", 1),))
    store.cancel_piece_request(connection, workspace_id, ended.piece_request_id)
    tombstone = connection.execute(
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (%s, 'workspace', %s, 'test') returning effective_at",
        (workspace_id, ACTOR),
    ).fetchone()
    for record in open_:
        row = _row(connection, record.piece_request_id)
        assert (row["state"], row["failure"]) == ("cancelled", "workspace_deleted")
        assert row["finished_at"] == tombstone["effective_at"]
    # A request that had already ended keeps how it ended.
    assert _row(connection, ended.piece_request_id)["failure"] == "cancelled_by_person"
    with pytest.raises(TombstonedError, match="tombstoned"):
        _ask(connection, workspace_id, kinds=(("bench", 1),))


def test_the_store_writes_no_request_holding_a_person_s_words(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (gate,) = plan_requests([("gate", 1)], _look(), library=LIBRARY)
    document = json.loads(gate.request)
    document["description"] = "the gate outside the house I grew up in"
    raw = canonical_bytes(document)
    forged = dataclasses.replace(gate, request=raw, request_sha256=sha256_hex(raw))
    with pytest.raises(PieceAskRefused) as refused:
        _ask(connection, workspace_id, planned=[forged])
    assert refused.value.code == "words_not_from_catalog"
    assert connection.execute("select count(*) as n from piece_request").fetchone()["n"] == 0


def test_a_key_answers_the_first_answer_s_requests_and_is_bound_when_it_made_none(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    # The well is waiting already, so an ask for it under a key makes nothing new.
    (waiting,), _ = _ask(connection, workspace_id)
    key = uuid.uuid4()
    first, made = _ask(connection, workspace_id, request_id=key, ask_sha256="a" * 64)
    assert not made and first == [waiting]
    # Asked again, the key answers the same request, though the ask made none of it.
    again, made_again = _ask(connection, workspace_id, request_id=key, ask_sha256="a" * 64)
    assert not made_again and again == first
    # And it stays bound to that ask: another body under it is refused.
    with pytest.raises(store.PieceAskKeyReused):
        _ask(
            connection,
            workspace_id,
            kinds=(("gate", 1),),
            request_id=key,
            ask_sha256="b" * 64,
        )
    # A key whose ask made two requests answers both, in the order asked.
    other = uuid.uuid4()
    pair, _ = _ask(
        connection,
        workspace_id,
        kinds=(("gate", 1), ("lantern", 1)),
        request_id=other,
        ask_sha256="c" * 64,
    )
    replay, _ = _ask(
        connection,
        workspace_id,
        kinds=(("gate", 1), ("lantern", 1)),
        request_id=other,
        ask_sha256="c" * 64,
    )
    assert [r.piece_request_id for r in replay] == [r.piece_request_id for r in pair]


def test_a_request_is_dated_when_it_is_asked(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    _insert(connection, workspace_id, '{"n":"dated"}', requested_at="2020-01-01T00:00:00Z")
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select requested_at > now() - interval '1 minute' as now_ish from piece_request "
            "where request_canonical = %s",
            ('{"n":"dated"}',),
        ).fetchone()
    assert row["now_ish"]


@pytest.mark.parametrize("field", ["kind", "look"])
def test_the_store_writes_no_request_whose_row_and_document_disagree(world, field) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (gate,) = plan_requests([("gate", 1)], _look(), library=LIBRARY)
    if field == "kind":
        forged = dataclasses.replace(gate, kind_key="bench")
        changes = {"planned": [forged]}
    else:
        changes = {"look": dataclasses.replace(_look(), version=_look().version + 1)}
    with pytest.raises(ValueError, match="names the"):
        _ask(connection, workspace_id, **changes)
    assert connection.execute("select count(*) as n from piece_request").fetchone()["n"] == 0


@pytest.mark.parametrize("role", ["fixture.bench", "prop.bench", "fixture.gate.bench"])
def test_the_store_writes_no_request_whose_look_role_is_not_its_kinds(world, role) -> None:
    # The role's last part is what a request with no description is drawn as.
    connection, workspace_id = world.connection, world.workspace_id
    (gate,) = plan_requests([("gate", 1)], _look(), library=LIBRARY)
    raw = canonical_bytes({**json.loads(gate.request), "look_role": role})
    forged = dataclasses.replace(gate, look_role=role, request=raw, request_sha256=sha256_hex(raw))
    with pytest.raises(ValueError, match="look role"):
        _ask(connection, workspace_id, planned=[forged])
    assert connection.execute("select count(*) as n from piece_request").fetchone()["n"] == 0
