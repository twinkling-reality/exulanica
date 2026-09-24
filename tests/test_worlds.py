"""The world registry: one row per world, its kind, and how many of a kind a workspace may hold.

``exulanica.world.worlds`` states the kinds and reads the count policy; migration 0099 creates
``world_identity`` and anchors every world table to it. These tests hold the Python and SQL
statements of the kinds equal, derive the anchoring from the live schema rather than from a list,
and run creation, refusal and resolution against PostgreSQL, including a policy raised in the test
to show that allowing more worlds is a policy value and nothing else.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import threading
import uuid
from types import MappingProxyType

import psycopg
import pytest
from exulanica.world import worlds
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.style_structure import STARTER_WORLD_ID_PREFIX
from exulanica.world.worlds import (
    AUTHORED_STARTER,
    PERSONAL_SOURCE,
    WORLD_COUNT_POLICY,
    WORLD_KINDS,
    NoPersonalSourceWorld,
    SeveralPersonalSourceWorlds,
    WorldKindConflict,
    WorldLimitReached,
    ensure_personal_source_world,
    load_world_count_policy,
    new_world_id,
    register_world,
    resolve_personal_source_world,
    workspace_worlds,
    world_kind,
)
from psycopg.types.json import Jsonb

from pg_harness import open_scratch_connection
from test_api import deployment as deployment

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "exulanica" / "migrations" / ("0099_a_world_is_registered_before_it_holds_anything.sql")
)
POLICY = ROOT / "exulanica" / "world" / "world-count-policy.v1.json"

#: World tables whose rows do not all name a world: the stored generated column each one's key
#: reads instead of ``world_id``, and that column's expression as the catalog prints it.
#: ``world_package_export`` is the ledger of every signed package, and a training dataset export
#: (migration 0039, ``training_terms`` set) keeps its dataset package id in ``world_id``. 0099
#: states the same table and predicate once, in ``migration_0099_world_rows``; the key test holds
#: the schema equal to this. May only shrink.
KEYED_THROUGH: dict[str, tuple[str, str]] = {
    "world_package_export": (
        "named_world_id",
        "CASE WHEN (training_terms IS NULL) THEN world_id ELSE NULL::text END",
    ),
}


def _raised(limit: int) -> worlds.WorldCountPolicy:
    """The shipped policy with the personal-source limit changed, as a new version would state."""
    return dataclasses.replace(
        WORLD_COUNT_POLICY,
        version=WORLD_COUNT_POLICY.version + 1,
        limits=MappingProxyType({**WORLD_COUNT_POLICY.limits, PERSONAL_SOURCE: limit}),
    )


# -- the kinds and the policy, as data --------------------------------------------------------


def test_the_policy_allows_one_personal_source_world_and_states_every_kind():
    assert WORLD_COUNT_POLICY.policy_id == "exulanica.world-count"
    assert WORLD_COUNT_POLICY.version == 1
    assert WORLD_COUNT_POLICY.limit(PERSONAL_SOURCE) == 1
    assert WORLD_COUNT_POLICY.limit(AUTHORED_STARTER) is None
    assert set(WORLD_COUNT_POLICY.limits) == {kind.name for kind in WORLD_KINDS}
    document = json.loads(POLICY.read_text(encoding="utf-8"))
    assert WORLD_COUNT_POLICY.limits == document["limits"]


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (lambda d: d["limits"].pop(AUTHORED_STARTER), "exactly the kinds"),
        (lambda d: d["limits"].update({"district": 3}), "exactly the kinds"),
        (lambda d: d["limits"].update({PERSONAL_SOURCE: 0}), "a limit is null or >= 1"),
        (lambda d: d["limits"].update({PERSONAL_SOURCE: True}), "a limit is null or >= 1"),
        (lambda d: d.update({"scope": "account"}), "only workspace is read"),
        (lambda d: d.update({"version": 0}), "positive integer version"),
        (lambda d: d.update({"note": "x"}), "policy_id, version, scope and limits only"),
    ],
)
def test_a_policy_document_that_does_not_state_each_kind_once_is_refused(tmp_path, change, refusal):
    document = json.loads(POLICY.read_text(encoding="utf-8"))
    change(document)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match=re.escape(refusal)):
        load_world_count_policy(path)


def test_the_migration_check_lists_exactly_the_registered_kinds():
    text = MIGRATION.read_text(encoding="utf-8")
    listed = re.search(r"kind\s+text not null check \(kind in \(([^)]*)\)\)", text)
    assert listed is not None, "0099's kind CHECK is not where this test reads it"
    assert re.findall(r"'([a-z-]+)'", listed.group(1)) == [kind.name for kind in WORLD_KINDS]
    assert {kind.admitted_by for kind in WORLD_KINDS} == {MIGRATION.stem}


def test_a_new_world_id_is_fresh_and_spelled_by_its_kind():
    first, second = new_world_id(PERSONAL_SOURCE), new_world_id(PERSONAL_SOURCE)
    assert first != second
    assert first.startswith(world_kind(PERSONAL_SOURCE).id_prefix)
    assert new_world_id(AUTHORED_STARTER).startswith(world_kind(AUTHORED_STARTER).id_prefix)
    with pytest.raises(worlds.UnknownWorldKind):
        new_world_id("district")


def test_the_starter_prefix_the_compatibility_check_reads_is_the_kind_s():
    """``style_structure`` reads a starter by this prefix when no stored origin is supplied."""
    assert world_kind(AUTHORED_STARTER).id_prefix == STARTER_WORLD_ID_PREFIX


# -- the schema, read from the live catalog ----------------------------------------------------


def _world_tables(connection) -> list[str]:
    rows = connection.execute(
        "select c.relname as name from pg_class c join pg_namespace n on n.oid=c.relnamespace "
        "where n.nspname=current_schema() and c.relkind='r' and c.relname<>'world_identity' "
        "and exists (select 1 from pg_attribute a where a.attrelid=c.oid "
        "and a.attname='world_id' and a.attnum>0 and not a.attisdropped) order by c.relname"
    ).fetchall()
    return [row["name"] for row in rows]


def test_every_world_table_names_a_registered_world(repository):
    """Derived from the catalog: a world table a later migration adds without the key fails.

    A table in ``KEYED_THROUGH`` is keyed through the generated column named there, and the
    generated columns any key to the registry reads are exactly those, with those expressions.
    """
    connection = repository.connection
    tables = _world_tables(connection)
    assert len(tables) > 30, "the catalog read found almost no world table"
    keys = {
        (row["child"], tuple(row["cols"]))
        for row in connection.execute(
            "select c.conrelid::regclass::text as child, "
            "array(select attname from unnest(c.conkey) with ordinality k(n, i) "
            "join pg_attribute a on a.attrelid=c.conrelid and a.attnum=k.n order by i) as cols, "
            "array(select attname from unnest(c.confkey) with ordinality k(n, i) "
            "join pg_attribute a on a.attrelid=c.confrelid and a.attnum=k.n order by i) "
            "as parent_cols "
            "from pg_constraint c where c.contype='f' "
            "and c.confrelid='world_identity'::regclass"
        ).fetchall()
        if row["parent_cols"] == ["workspace_id", "world_id"]
    }
    unkeyed = [
        table
        for table in tables
        if (table, ("workspace_id", KEYED_THROUGH.get(table, ("world_id",))[0])) not in keys
    ]
    assert unkeyed == []
    generated = {
        # The catalog's layout of the expression is PostgreSQL's; its words are the migration's.
        row["table_name"]: (row["column_name"], " ".join(row["expression"].split()))
        for row in connection.execute(
            "select c.relname as table_name, a.attname as column_name, "
            "pg_get_expr(d.adbin, d.adrelid) as expression "
            "from pg_attribute a join pg_class c on c.oid=a.attrelid "
            "join pg_namespace n on n.oid=c.relnamespace "
            "join pg_attrdef d on d.adrelid=a.attrelid and d.adnum=a.attnum "
            "where n.nspname=current_schema() and a.attgenerated='s' and exists ("
            "select 1 from pg_constraint k where k.conrelid=c.oid and k.contype='f' "
            "and k.confrelid='world_identity'::regclass and a.attnum=any(k.conkey))"
        ).fetchall()
    }
    assert generated == KEYED_THROUGH


def test_no_world_column_has_a_default_and_none_is_nullable(repository):
    rows = repository.connection.execute(
        "select table_name, column_default, is_nullable from information_schema.columns "
        "where table_schema=current_schema() and column_name='world_id'"
    ).fetchall()
    assert rows
    assert [r["table_name"] for r in rows if r["column_default"] is not None] == []
    assert [r["table_name"] for r in rows if r["is_nullable"] != "NO"] == []


def test_the_kind_check_in_the_schema_is_the_registry_s(repository):
    definition = repository.connection.execute(
        "select pg_get_constraintdef(c.oid) as sql from pg_constraint c "
        "where c.conrelid='world_identity'::regclass and c.contype='c' "
        "and pg_get_constraintdef(c.oid) like '%%kind%%'"
    ).fetchone()["sql"]
    assert re.findall(r"'([a-z-]+)'::text", definition) == [kind.name for kind in WORLD_KINDS]


def test_the_registry_is_forced_row_secure_and_refuses_every_update_and_delete(repository):
    connection = repository.connection
    forced = connection.execute(
        "select relrowsecurity, relforcerowsecurity from pg_class "
        "where oid='world_identity'::regclass"
    ).fetchone()
    assert (forced["relrowsecurity"], forced["relforcerowsecurity"]) == (True, True)
    world_id = register_world(
        connection,
        repository.workspace_id,
        world_id=new_world_id(PERSONAL_SOURCE),
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="append-only check",
    ).world_id
    for statement in (
        "update world_identity set kind='authored-starter' where world_id=%s",
        "delete from world_identity where world_id=%s",
    ):
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
            connection.execute(statement, (world_id,))


# -- creation, refusal and resolution ---------------------------------------------------------


def test_a_world_table_refuses_a_row_for_a_world_nobody_registered(repository):
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        repository.connection.execute(
            "insert into world_topology_contract "
            "(workspace_id,world_id,topology_digest,compatibility_key) values (%s,%s,%s,%s)",
            (repository.workspace_id, "world:personal:unregistered", "d", "atlas-topology-v1"),
        )
    assert refused.value.diag.constraint_name == "world_topology_contract_world_is_registered"


def test_a_dataset_export_names_its_package_and_a_world_export_a_registered_world(repository):
    """The export ledger's key covers the rows that export a world, and only those.

    A training dataset export keeps its dataset package id in ``world_id`` and is written with
    nothing registered under that id, and no world comes to exist by it. An export of a world
    nobody registered is refused by the key every world table has.
    """
    connection, workspace = repository.connection, repository.workspace_id
    statement = (
        "insert into world_package_export (export_id,workspace_id,world_id,profile_version,"
        "merkle_root_sha256,manifest_sha256,signature_algorithm,signing_public_key_sha256,"
        "export_policy,actor,training_terms) "
        "values (%s,%s,%s,%s,%s,%s,'Ed25519',%s,'{}',%s,%s)"
    )
    connection.execute(
        statement,
        (
            uuid.uuid4(),
            workspace,
            "dataset:package-sample",
            "exulanica-wmp-training-1.1",
            "a" * 64,
            "b" * 64,
            "c" * 64,
            uuid.uuid4(),
            Jsonb({"terms": {"package_id": "dataset:package-sample"}}),
        ),
    )
    assert [world.world_id for world in workspace_worlds(connection, workspace)] == []
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as refused:
        connection.execute(
            statement,
            (
                uuid.uuid4(),
                workspace,
                "world:personal:unregistered",
                "exulanica-wmp-1.0",
                "a" * 64,
                "b" * 64,
                "c" * 64,
                uuid.uuid4(),
                None,
            ),
        )
    assert refused.value.diag.constraint_name == "world_package_export_world_is_registered"


def test_registering_again_returns_the_same_world_and_another_kind_is_refused(repository):
    connection, workspace = repository.connection, repository.workspace_id
    actor = uuid.uuid4()
    world_id = new_world_id(PERSONAL_SOURCE)
    first = register_world(
        connection,
        workspace,
        world_id=world_id,
        kind=PERSONAL_SOURCE,
        created_by=actor,
        reason="first",
    )
    again = register_world(
        connection,
        workspace,
        world_id=world_id,
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="retry",
    )
    assert again == first
    assert first.created_by == actor
    assert first.provenance == {
        "origin": "created",
        "reason": "first",
        "policy": WORLD_COUNT_POLICY.reference(),
    }
    with pytest.raises(WorldKindConflict):
        register_world(
            connection,
            workspace,
            world_id=world_id,
            kind=AUTHORED_STARTER,
            created_by=actor,
            reason="another kind",
        )
    assert [w.world_id for w in workspace_worlds(connection, workspace)] == [world_id]


def test_a_second_personal_source_world_is_refused_by_name_under_the_shipped_policy(repository):
    connection, workspace = repository.connection, repository.workspace_id
    kept = register_world(
        connection,
        workspace,
        world_id=new_world_id(PERSONAL_SOURCE),
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="the one allowed",
    )
    with pytest.raises(WorldLimitReached) as refused:
        register_world(
            connection,
            workspace,
            world_id=new_world_id(PERSONAL_SOURCE),
            kind=PERSONAL_SOURCE,
            created_by=uuid.uuid4(),
            reason="one too many",
        )
    assert (refused.value.kind, refused.value.limit) == (PERSONAL_SOURCE, 1)
    assert refused.value.policy is WORLD_COUNT_POLICY
    assert refused.value.code == "world_limit_reached"
    assert "exulanica.world-count version 1" in str(refused.value)
    assert [w.world_id for w in workspace_worlds(connection, workspace)] == [kept.world_id]
    # An uncounted kind is not refused, however many there are.
    for _ in range(3):
        register_world(
            connection,
            workspace,
            world_id=new_world_id(AUTHORED_STARTER),
            kind=AUTHORED_STARTER,
            created_by=uuid.uuid4(),
            reason="starter",
        )


def test_raising_the_limit_is_a_policy_value_and_the_new_limit_is_enforced(repository, monkeypatch):
    monkeypatch.setattr(worlds, "WORLD_COUNT_POLICY", _raised(2))
    connection, workspace = repository.connection, repository.workspace_id
    made = [
        register_world(
            connection,
            workspace,
            world_id=new_world_id(PERSONAL_SOURCE),
            kind=PERSONAL_SOURCE,
            created_by=uuid.uuid4(),
            reason=f"world {n}",
        )
        for n in range(2)
    ]
    assert all(world.provenance["policy"]["version"] == 2 for world in made)
    with pytest.raises(WorldLimitReached) as refused:
        register_world(
            connection,
            workspace,
            world_id=new_world_id(PERSONAL_SOURCE),
            kind=PERSONAL_SOURCE,
            created_by=uuid.uuid4(),
            reason="a third",
        )
    assert refused.value.limit == 2


def test_the_personal_source_world_resolves_from_the_registry_and_never_guesses(
    repository, monkeypatch
):
    connection, workspace = repository.connection, repository.workspace_id
    with pytest.raises(NoPersonalSourceWorld):
        resolve_personal_source_world(connection, workspace)
    register_world(
        connection,
        workspace,
        world_id=new_world_id(AUTHORED_STARTER),
        kind=AUTHORED_STARTER,
        created_by=uuid.uuid4(),
        reason="a starter is not a personal-source world",
    )
    with pytest.raises(NoPersonalSourceWorld):
        resolve_personal_source_world(connection, workspace)
    one = register_world(
        connection,
        workspace,
        world_id=new_world_id(PERSONAL_SOURCE),
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="one",
    )
    assert resolve_personal_source_world(connection, workspace) == one.world_id
    monkeypatch.setattr(worlds, "WORLD_COUNT_POLICY", _raised(2))
    two = register_world(
        connection,
        workspace,
        world_id=new_world_id(PERSONAL_SOURCE),
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="two",
    )
    with pytest.raises(SeveralPersonalSourceWorlds) as several:
        resolve_personal_source_world(connection, workspace)
    assert set(several.value.world_ids) == {one.world_id, two.world_id}


def test_two_callers_on_an_empty_workspace_create_one_personal_source_world(spine_schema):
    """Resolution and creation share the workspace lock, so concurrency cannot make two."""
    psycopg_module, scratch = spine_schema
    workspace = uuid.uuid4()
    connections = [open_scratch_connection(psycopg_module, scratch) for _ in range(2)]
    for connection in connections:
        connection.row_factory = psycopg.rows.dict_row
    barrier = threading.Barrier(2)
    results: list[str] = []
    failures: list[BaseException] = []

    def create(connection) -> None:
        try:
            barrier.wait(timeout=10)
            results.append(
                ensure_personal_source_world(
                    connection, workspace, created_by=uuid.uuid4(), reason="concurrent"
                )
            )
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=create, args=(c,)) for c in connections]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        assert failures == []
        assert len(results) == 2 and results[0] == results[1]
        registered = (
            connections[0]
            .execute(
                "select world_id, kind from world_identity where workspace_id=%s", (workspace,)
            )
            .fetchall()
        )
        assert registered == [{"world_id": results[0], "kind": PERSONAL_SOURCE}]
    finally:
        for connection in connections:
            connection.close()


def test_an_authored_starter_registers_its_world_with_its_kind_and_policy(repository):
    entry = SavedWorldEntryRepository(
        repository.connection, repository.workspace_id
    ).create_starter(title="My world", created_by=uuid.uuid4())
    [world] = workspace_worlds(repository.connection, repository.workspace_id)
    assert world.world_id == entry.world_id
    assert world.world_id.startswith(world_kind(AUTHORED_STARTER).id_prefix)
    assert world.kind == AUTHORED_STARTER
    assert world.provenance["origin"] == "created"
    assert world.provenance["policy"] == WORLD_COUNT_POLICY.reference()


# -- the route --------------------------------------------------------------------------------


def test_the_world_list_names_every_world_and_the_policy_and_nothing_of_another_workspace(
    deployment, repository
):
    starter = SavedWorldEntryRepository(
        repository.connection, repository.workspace_id
    ).create_starter(title="My world", created_by=uuid.uuid4())
    personal = register_world(
        repository.connection,
        repository.workspace_id,
        world_id=new_world_id(PERSONAL_SOURCE),
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="composed",
    )
    listed = deployment.as_owner("GET", "/worlds")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["policy"] == {
        "policy_id": WORLD_COUNT_POLICY.policy_id,
        "version": WORLD_COUNT_POLICY.version,
        "sha256": WORLD_COUNT_POLICY.sha256,
        "limits": dict(WORLD_COUNT_POLICY.limits),
    }
    assert {(w["world_id"], w["kind"]) for w in body["worlds"]} == {
        (starter.world_id, AUTHORED_STARTER),
        (personal.world_id, PERSONAL_SOURCE),
    }
    stranger = deployment.as_stranger("GET", "/worlds")
    assert stranger.status_code == 200
    assert stranger.json()["worlds"] == []


def test_another_workspace_s_world_answers_exactly_as_an_invented_one(deployment, repository):
    real = register_world(
        repository.connection,
        repository.workspace_id,
        world_id=new_world_id(PERSONAL_SOURCE),
        kind=PERSONAL_SOURCE,
        created_by=uuid.uuid4(),
        reason="owner's world",
    )
    answers = [
        deployment.as_stranger("GET", f"/world/styles/current?world_id={world}")
        for world in (real.world_id, new_world_id(PERSONAL_SOURCE))
    ]
    assert [(a.status_code, a.json()) for a in answers] == [
        (404, {"code": "unknown_reference", "detail": "no such world resource"}),
    ] * 2
