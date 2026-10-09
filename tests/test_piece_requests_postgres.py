"""Piece requests on a migrated database: what the table and the store promise.

A request is written whole and only its progress moves; a caller's key answers with the ask it
named or refuses another body; an open request for the same world and digest is held once; a person
cancels only a request no session has taken; the workspace's limits are counted; a workspace
tombstone cancels every open request and refuses new ones. The rows are read back with SQL of the
test's own, not through the store.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.errors import TombstonedError
from exulanica.generation import batches, store
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

from generated_piece_support import kept_output
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


def _queue(
    connection, workspace_id, piece_request_id, job_raw: bytes = b'{"a job":"for the test"}'
) -> uuid.UUID:
    """Queue one request into a batch of its own, as the generation worker does."""
    queued_at = dt.datetime.now(dt.UTC)
    return batches.record_batch(
        connection,
        workspace_id,
        generation_session_id=uuid.uuid4(),
        job_raw=job_raw,
        queued_at=queued_at,
        not_after=queued_at + dt.timedelta(hours=1),
        queued=[
            batches.QueuedReservation(
                piece_request_id=piece_request_id,
                reservation_id=uuid.uuid4(),
                authority_id=uuid.uuid4(),
                holder="worker:test",
            )
        ],
    )


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


def test_at_its_limit_of_generated_looks_an_ask_is_refused_after_its_key_s_answer(
    world, monkeypatch
) -> None:
    # A workspace holding as many live looks of generated pieces as it may takes no ask that would
    # make a request, but a retry of an ask it took answers as before, and so does an ask whose
    # request is already open.
    connection, workspace_id = world.connection, world.workspace_id
    key = uuid.uuid4()
    first, made = _ask(connection, workspace_id, request_id=key, ask_sha256="a" * 64)
    assert made
    monkeypatch.setattr(store, "generated_looks_full", lambda *_: True)
    again, made_again = _ask(connection, workspace_id, request_id=key, ask_sha256="a" * 64)
    assert again == first and not made_again
    open_again, made_open = _ask(connection, workspace_id)
    assert open_again == first and not made_open
    with pytest.raises(store.PieceLookLimit):
        _ask(connection, workspace_id, kinds=(("gate", 1),))


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
    _queue(connection, workspace_id, taken.piece_request_id)
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
    _queue(connection, workspace_id, open_[1].piece_request_id)
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


def test_a_workspace_holding_an_open_piece_request_cannot_be_seeded(world, tmp_path) -> None:
    """A judge seed carries a workspace to another deployment; an open ask for GPU time does not
    go with it, and an ended one does."""
    from exulanica.orchestration.judge_seed import SeedRefused, export_seed
    from exulanica.store.local import LocalContentAddressedStore

    connection, workspace_id = world.connection, world.workspace_id
    blobs = LocalContentAddressedStore(tmp_path / "blobs")

    def export(name: str) -> None:
        export_seed(
            connection,
            blobs,
            workspace_id=workspace_id,
            destination=tmp_path / name,
            created_at="2026-10-08T00:00:00Z",
            allow_absent=True,
        )

    export("before")  # the control: nothing open, so the seed is written
    (made,), _ = _ask(connection, workspace_id)
    with pytest.raises(SeedRefused, match="holds 1 open piece request"):
        export("open")
    store.cancel_piece_request(connection, workspace_id, made.piece_request_id)
    export("ended")


def _export(connection, workspace_id, destination):
    from exulanica.orchestration import judge_seed
    from exulanica.store.local import LocalContentAddressedStore

    judge_seed.export_seed(
        connection,
        LocalContentAddressedStore(destination.parent / "blobs"),
        workspace_id=workspace_id,
        destination=destination,
        created_at="2026-10-08T00:00:00Z",
        allow_absent=True,
    )
    return {
        entry["table"]: entry["rows"]
        for entry in json.loads((destination / "manifest.json").read_text())["rows"].values()
    }


def test_a_workspace_holding_generated_outputs_cannot_be_seeded(world, tmp_path) -> None:
    """A generated piece's bytes are in the shared store, which a seed does not carry, so a seed
    of a workspace holding outputs would restore pieces its destination cannot serve."""
    from exulanica.orchestration.judge_seed import SeedRefused

    connection, workspace_id = world.connection, world.workspace_id
    (well,), _ = _ask(connection, workspace_id)
    _queue(connection, workspace_id, well.piece_request_id)
    [batch] = batches.batches_in_flight(connection, workspace_id)
    batches.end_batch(
        connection,
        workspace_id,
        batch,
        state="done",
        ended_at=dt.datetime.now(dt.UTC),
        settlements={well.piece_request_id: ("reported", Decimal("0.01"))},
        outputs=[kept_output(batch.requests[0].request_sha256)],
    )
    connection.commit()
    with pytest.raises(SeedRefused, match="generated piece output"):
        _export(connection, workspace_id, tmp_path / "seed")


def test_a_seed_carries_only_ended_requests_and_batches_and_no_settlement(
    world, tmp_path, monkeypatch
) -> None:
    """A request asked, and a batch queued, after the export refused open requests but before it
    copied, are not carried open; settlements are money and never travel."""
    from exulanica.orchestration import judge_seed

    connection, workspace_id = world.connection, world.workspace_id
    (well,), _ = _ask(connection, workspace_id)
    _queue(connection, workspace_id, well.piece_request_id)
    [batch] = batches.batches_in_flight(connection, workspace_id)
    batches.end_batch(
        connection,
        workspace_id,
        batch,
        state="expired",
        ended_at=dt.datetime.now(dt.UTC),
        settlements={well.piece_request_id: ("not_sent", Decimal(0))},
    )
    # The race: the export's refusal of open requests has run, and then a request is asked and
    # queued.
    monkeypatch.setattr(judge_seed, "_refuse_open_piece_requests", lambda *_: None)
    (lantern,), _ = _ask(connection, workspace_id, kinds=(("lantern", 1),))
    _queue(connection, workspace_id, lantern.piece_request_id)
    connection.commit()
    rows = _export(connection, workspace_id, tmp_path / "seed")
    assert (rows["piece_request"], rows["piece_batch"], rows["generated_piece"]) == (1, 1, 0)
    assert "piece_settlement" not in rows


def test_a_request_is_queued_only_into_an_open_batch_of_its_workspace(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (well, lantern), _ = _ask(connection, workspace_id, kinds=(("well", 1), ("lantern", 1)))
    batch = _queue(connection, workspace_id, well.piece_request_id)
    connection.execute(
        "update piece_batch set state = 'expired', ended_at = statement_timestamp() "
        "where workspace_id = %s and piece_batch_id = %s",
        (workspace_id, batch),
    )
    connection.commit()

    def queue_into(piece_batch_id: uuid.UUID) -> None:
        with connection.transaction():
            connection.execute(
                "update piece_request set state = 'queued', queued_at = statement_timestamp(), "
                "piece_batch_id = %s, reservation_id = %s, reservation_authority_id = %s, "
                "reservation_holder = 'worker:test' where workspace_id = %s "
                "and piece_request_id = %s",
                (
                    piece_batch_id,
                    uuid.uuid4(),
                    uuid.uuid4(),
                    workspace_id,
                    lantern.piece_request_id,
                ),
            )

    with pytest.raises(psycopg.errors.CheckViolation, match="open batches"):
        queue_into(batch)
    with pytest.raises(psycopg.errors.CheckViolation, match="open batches"):
        queue_into(uuid.uuid4())
    # The control: an open batch of the workspace takes it.
    _queue(connection, workspace_id, lantern.piece_request_id, b'{"a second job":"for the test"}')
    assert _row(connection, lantern.piece_request_id)["state"] == "queued"


def test_a_kept_piece_s_index_row_is_its_receipt_s_own(world) -> None:
    """Every column of an index row is read from its receipt, and its cache key computed from
    them, by the table itself: no row can name a piece its receipt does not."""
    connection = world.connection
    (well,), _ = _ask(connection, world.workspace_id)
    kept = kept_output(well.request_sha256)
    columns = (
        "cache_key", "variant", "request_sha256", "components_sha256", "postprocess_version",
        "receipt_canonical", "receipt_sha256", "piece_sha256", "piece_bytes", "within",
        "over_checks",
    )  # fmt: skip
    row = {
        "cache_key": kept.cache_key,
        "variant": 0,
        "request_sha256": well.request_sha256,
        "components_sha256": kept.components_sha256,
        "postprocess_version": kept.postprocess_version,
        "receipt_canonical": kept.output.receipt.decode("ascii"),
        "receipt_sha256": kept.output.receipt_sha256,
        "piece_sha256": kept.output.piece_sha256,
        "piece_bytes": len(kept.output.piece),
        "within": True,
        "over_checks": [],
    }
    insert = (
        f"insert into generated_piece ({', '.join(columns)}) "
        f"values ({', '.join(f'%({name})s' for name in columns)})"
    )
    for change in (
        {"variant": 1},
        {"request_sha256": "0" * 64},
        {"piece_sha256": "0" * 64},
        {"piece_bytes": 1},
        {"within": False, "over_checks": ["triangles"]},
        {"cache_key": "0" * 64},
    ):
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(insert, {**row, **change})
    # A receipt lacking the members the check compares makes each comparison null, which a check
    # would pass: it is refused, its digest its own.
    for receipt in ("{}", "[]", json.dumps({"variant": 0})):
        bare = {
            **row,
            "receipt_canonical": receipt,
            "receipt_sha256": hashlib.sha256(receipt.encode("utf-8")).hexdigest(),
        }
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(insert, bare)
    # The control: the row as its receipt states it goes in.
    with connection.transaction():
        connection.execute(insert, row)


def test_an_output_answered_from_the_index_is_the_index_row_s_receipt(world) -> None:
    connection, workspace_id = world.connection, world.workspace_id
    (well,), _ = _ask(connection, workspace_id)
    kept = kept_output(well.request_sha256)
    with connection.cursor() as cursor:
        batches._record_generated(cursor, kept)
    connection.commit()
    other = kept_output(well.request_sha256, within=False)
    with pytest.raises(psycopg.errors.CheckViolation, match="kept receipt"):
        batches.answer_from_cache(
            connection,
            workspace_id,
            well.piece_request_id,
            cache_key=kept.cache_key,
            cached=[
                {
                    "variant": 0,
                    "receipt_canonical": other.output.receipt.decode("ascii"),
                    "receipt_sha256": other.output.receipt_sha256,
                    "piece_sha256": other.output.piece_sha256,
                    "within": False,
                    "over_checks": ["triangles"],
                }
            ],
        )
    connection.rollback()
    assert _row(connection, well.piece_request_id)["state"] == "requested"


def test_an_output_answered_from_the_index_carries_the_index_row_s_verdict(world) -> None:
    """The kept receipt and piece with another verdict is not the index row's: a piece the index
    holds as refused is never answered as passed."""
    connection, workspace_id = world.connection, world.workspace_id
    (well,), _ = _ask(connection, workspace_id)
    refused = kept_output(well.request_sha256, within=False)
    with connection.cursor() as cursor:
        batches._record_generated(cursor, refused)
    connection.commit()
    claimed = {
        "variant": 0,
        "receipt_canonical": refused.output.receipt.decode("ascii"),
        "receipt_sha256": refused.output.receipt_sha256,
        "piece_sha256": refused.output.piece_sha256,
    }
    with pytest.raises(psycopg.errors.CheckViolation, match="kept receipt"):
        batches.answer_from_cache(
            connection,
            workspace_id,
            well.piece_request_id,
            cache_key=refused.cache_key,
            cached=[{**claimed, "within": True, "over_checks": []}],
        )
    connection.rollback()
    assert _row(connection, well.piece_request_id)["state"] == "requested"


def test_a_queued_request_is_not_counted_again_against_the_allowance(world) -> None:
    """The allowance left already leaves out what a queued request reserved, so the open worst
    case counts only requests that hold no reservation."""
    connection, workspace_id = world.connection, world.workspace_id
    (well, lantern), _ = _ask(connection, workspace_id, kinds=(("well", 1), ("lantern", 1)))
    both = store.open_worst_case(connection, workspace_id)
    assert both == well.worst_case_usd + lantern.worst_case_usd
    _queue(connection, workspace_id, well.piece_request_id)
    assert store.open_worst_case(connection, workspace_id) == lantern.worst_case_usd
