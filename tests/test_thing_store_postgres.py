"""A workspace's own things, as the database and the store keep them (migration 0159).

What is shown, against PostgreSQL, as the deployed writer (the runtime role) unless said:

*   a creature drafted from words is kept whole (its recipe, plan, sketch with its container, and
    kind) and read back at the digests its assembly gave, its container served byte for byte;
*   every version is appended once: the runtime may neither change nor remove one, and the
    append-only trigger refuses even the table owner;
*   a workspace's things are its own: another workspace reads none of them, and may keep a thing
    of the same name in its own library; a row is written only in its own workspace's context,
    even by a role that row-level security does not hold;
*   the store refuses by name before it writes anything, the container's bytes included: a shipped
    kind, plan or look key, a container that is not the one its look names, a version or document
    the workspace holds, a full library of kinds or of looks;
*   a look made elsewhere is kept only after its intake's own check, with what its container's
    reader measured and its licence as columns;
*   the table holds what the application states: a share-alike look's credit, a look's container
    profile following its kind, a kind's plan digest as its document names it, and a withdrawal
    naming the digest its look was kept at;
*   a withdrawn look stays held and every read passes it by unless it asks for one, while a kind
    naming it still reads; the row is what is withdrawn, so a look the reader now refuses can be
    withdrawn; :func:`admitted_look` and :func:`admitted_look_by_digest` answer only a look this
    workspace holds, not withdrawn, at exactly the reference or digest asked.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import uuid
from pathlib import Path
from types import MappingProxyType
from typing import Any

import psycopg
import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.db.session import set_workspace
from exulanica.evidence.blob import BlobId
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.authored import container_of
from exulanica.things.catalogs import thing_catalogs
from exulanica.things.creatures import Creature, assemble_creature
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.things.looks import Look
from exulanica.world import thing_store
from exulanica.world.thing_store import (
    ThingStore,
    ThingStoreRefused,
    admitted_look,
    admitted_look_by_digest,
)
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from conftest import scratch_role_database
from test_creature_bodies import BY, _form, _recipe
from test_thing_store_admission import _imported, _sculpted

pytestmark = pytest.mark.postgres

TABLES = (
    "body_recipe_version",
    "body_plan_version",
    "thing_kind_version",
    "look_version",
    "look_withdrawal",
)
ACTOR = uuid.UUID("00000000-0000-4000-8000-00000000c5a2")


def _runtime(spine_schema, workspace_id):
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(workspace_id)


@pytest.fixture
def provisioned(repository):
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    return repository


def _creature(label: str = "store ten legs", recipe: str = "ten_legs") -> Creature:
    return assemble_creature(_form(_recipe(recipe), label=label), by=BY)


def _store(connection, workspace_id, root: Path) -> ThingStore:
    return ThingStore(connection, workspace_id, LocalContentAddressedStore(root))


def _counts(connection) -> dict[str, int]:
    return {
        table: connection.execute(f"select count(*) as n from {table}").fetchone()["n"]
        for table in TABLES
    }


def _container(store: ThingStore, kept: thing_store.KeptLook) -> bytes:
    """A kept look's container, read from the workspace's looks namespace as the routes read it."""
    assert store.looks is not None
    return store.looks.get(BlobId.from_hex(kept.container_sha256))


def _held(store: ThingStore, container: bytes) -> bool:
    """Whether the workspace's looks namespace holds these bytes."""
    assert store.looks is not None
    return store.looks.exists(BlobId.from_hex(hashlib.sha256(container).hexdigest()))


def _admit_any(look: Look) -> None:
    """An intake's own check that admits every look: these tests are of the store's checks."""


def _drawn_from(container: bytes) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(container).hexdigest(),
        "bytes": len(container),
        "media_type": "model/gltf-binary",
    }


def _redrawn(creature: Creature, container: bytes) -> Creature:
    """The creature with its sketch drawn from other bytes, under the same keys and versions."""
    document = {**creature.sketch.document, "container": _drawn_from(container)}
    sketch = dataclasses.replace(
        creature.sketch,
        document=MappingProxyType(document),
        sha256=sha256_of_canonical(document).hex(),
    )
    return dataclasses.replace(creature, sketch=sketch, sketch_container=container)


def test_a_drafted_creature_is_kept_whole_and_read_back_as_the_runtime_role(
    provisioned, spine_schema, tmp_path
):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        for table in TABLES:
            for privilege, allowed in (
                ("SELECT", True),
                ("INSERT", True),
                ("UPDATE", False),
                ("DELETE", False),
            ):
                held = connection.execute(
                    "select has_table_privilege(current_user,%s,%s) as allowed",
                    (table, privilege),
                ).fetchone()["allowed"]
                assert held is allowed, (table, privilege)
        store = _store(connection, workspace_id, tmp_path)
        store.keep_creature(creature, created_by=ACTOR)
        assert _counts(connection) == {
            "body_recipe_version": 1,
            "body_plan_version": 1,
            "thing_kind_version": 1,
            "look_version": 1,
            "look_withdrawal": 0,
        }
        # Read back at the digests the assembly gave, by the readers every thing passes.
        kind = store.kind(creature.kind.kind, creature.kind.version)
        assert kind is not None and kind.sha256 == creature.kind.sha256
        assert kind.looks[0]["sha256"] == creature.sketch.sha256
        assert store.kind_by_digest(creature.kind.sha256) == kind
        plan = store.plan(creature.plan.name)
        assert plan is not None and plan.sha256 == creature.plan.sha256
        kept = store.look(creature.sketch.look, creature.sketch.version)
        assert kept is not None and not kept.withdrawn
        assert kept.look.sha256 == creature.sketch.sha256
        assert kept.container_profile == "exulanica.static-glb/v1"
        assert _container(store, kept) == creature.sketch_container
        assert kept.container_sha256 == hashlib.sha256(creature.sketch_container).hexdigest()
        assert store.look_by_digest(creature.sketch.sha256) == kept
        row = connection.execute(
            "select r.words_sha256, l.admission, l.spdx, l.share_alike, l.origin_class, "
            "k.plan_sha256 from body_recipe_version r, look_version l, thing_kind_version k"
        ).fetchone()
        # The words are held only as the digest the drafter's provenance names.
        assert row["words_sha256"] == BY["words_sha256"]
        assert row["admission"]["reader"] == "exulanica.world.static_glb.inspect_static_glb"
        assert row["admission"]["counts"]["meshes"] > 0
        assert (row["spdx"], row["share_alike"], row["origin_class"]) == (
            creature.sketch.document["origin"]["licence"]["spdx"],
            False,
            "authored",
        )
        assert row["plan_sha256"] == creature.plan.sha256


def test_a_kept_version_is_never_changed_even_by_its_owner(provisioned, spine_schema, tmp_path):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _store(connection, workspace_id, tmp_path).keep_creature(creature, created_by=ACTOR)
    owner = provisioned.connection
    set_workspace(owner, workspace_id)
    owner.commit()
    for statement in (
        "update look_version set container_profile='exulanica.skinned-glb/v1'",
        "delete from thing_kind_version",
        "update body_plan_version set created_by=gen_random_uuid()",
        "delete from body_recipe_version",
    ):
        with pytest.raises(psycopg.Error):
            owner.execute(statement)
        owner.rollback()
    with _runtime(spine_schema, workspace_id) as connection:
        assert _counts(connection)["thing_kind_version"] == 1


def test_another_workspace_holds_none_of_it_and_keeps_its_own(provisioned, spine_schema, tmp_path):
    creature = _creature()
    mine, theirs = provisioned.workspace_id, uuid.uuid4()
    with _runtime(spine_schema, mine) as connection:
        _store(connection, mine, tmp_path / "mine").keep_creature(creature, created_by=ACTOR)
        assert admitted_look(connection, mine, creature.sketch.reference()) == creature.sketch
        assert admitted_look_by_digest(connection, mine, creature.sketch.sha256) == creature.sketch
    with _runtime(spine_schema, theirs) as connection:
        other = _store(connection, theirs, tmp_path / "theirs")
        assert other.kind(creature.kind.kind, 1) is None
        assert other.plan(creature.plan.name) is None
        assert other.look(creature.sketch.look, 1, include_withdrawn=True) is None
        assert admitted_look(connection, theirs, creature.sketch.reference()) is None
        assert admitted_look_by_digest(connection, theirs, creature.sketch.sha256) is None
        assert set(_counts(connection).values()) == {0}
        # The same name in its own library: every key is a workspace's own.
        other.keep_creature(creature, created_by=ACTOR)
        assert _counts(connection)["thing_kind_version"] == 1
    with _runtime(spine_schema, mine) as connection:
        assert _counts(connection)["thing_kind_version"] == 1


def _bound_rows(holder: uuid.UUID) -> dict[str, tuple[str, tuple[Any, ...]]]:
    """For each table, a row of ``holder``'s that its checks and keys admit, as a statement and
    its values; a look's withdrawal and a plan name rows ``_bind_parents`` writes first."""
    look = _imported()
    look["look"] = "bound-look"
    return {
        "body_recipe_version": (
            "insert into body_recipe_version (workspace_id,sha256,document,created_by) "
            "values (%s,%s,%s,%s)",
            (holder, "a" * 64, Jsonb({"profile": "exulanica.body-recipe/v1"}), ACTOR),
        ),
        "body_plan_version": (
            "insert into body_plan_version (workspace_id,key,version,sha256,document,"
            "recipe_sha256,created_by) values (%s,'bound_plan',1,%s,%s,%s,%s)",
            (
                holder,
                "b" * 64,
                Jsonb({"profile": "exulanica.body-plan/v1", "key": "bound_plan", "version": 1}),
                "e" * 64,
                ACTOR,
            ),
        ),
        "thing_kind_version": (
            "insert into thing_kind_version (workspace_id,key,version,sha256,document,plan,"
            "created_by) values (%s,'bound_kind',1,%s,%s,'rigid/v1',%s)",
            (
                holder,
                "c" * 64,
                Jsonb(
                    {
                        "profile": "exulanica.thing-kind/v1",
                        "kind": "bound_kind",
                        "version": 1,
                        "body": {"plan": "rigid/v1"},
                    }
                ),
                ACTOR,
            ),
        ),
        "look_version": (
            "insert into look_version (workspace_id,key,version,sha256,document,"
            "container_profile,admission,created_by) values (%s,'bound-look',1,%s,%s,%s,%s,%s)",
            (holder, "d" * 64, Jsonb(look), "exulanica.static-glb/v1", Jsonb({}), ACTOR),
        ),
        "look_withdrawal": (
            "insert into look_withdrawal (workspace_id,key,version,sha256,reason,withdrawn_by) "
            "values (%s,'parent-look',1,%s,'no longer worn',%s)",
            (holder, "f" * 64, ACTOR),
        ),
    }


def _bind_parents(connection, holder: uuid.UUID) -> None:
    """The rows the plan's and the withdrawal's keys name, written in ``holder``'s own context."""
    parent = _imported()
    parent["look"] = "parent-look"
    set_workspace(connection, holder)
    connection.execute(
        "insert into body_recipe_version (workspace_id,sha256,document,created_by) "
        "values (%s,%s,%s,%s)",
        (holder, "e" * 64, Jsonb({"profile": "exulanica.body-recipe/v1"}), ACTOR),
    )
    connection.execute(
        "insert into look_version (workspace_id,key,version,sha256,document,container_profile,"
        "admission,created_by) values (%s,'parent-look',1,%s,%s,%s,%s,%s)",
        (holder, "f" * 64, Jsonb(parent), "exulanica.static-glb/v1", Jsonb({}), ACTOR),
    )


@pytest.mark.parametrize("table", TABLES)
def test_a_row_is_written_only_in_its_own_workspace_s_context(provisioned, table):
    # The owner here is the harness's superuser, which row-level security never holds: only the
    # binding trigger stands between it and another workspace's rows.
    owner = provisioned.connection
    with owner.cursor(row_factory=dict_row) as cursor:
        assert (
            cursor.execute("select current_setting('is_superuser') as su").fetchone()["su"] == "on"
        )
    holder = uuid.uuid4()
    statement, values = _bound_rows(holder)[table]
    try:
        _bind_parents(owner, holder)
        # The positive control: in its own workspace's context the row is admitted.
        with owner.transaction():
            owner.execute(statement, values)
            raise psycopg.Rollback()
        set_workspace(owner, provisioned.workspace_id)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="workspace context"):
            owner.execute(statement, values)
    finally:
        owner.rollback()


def test_the_store_refuses_by_name_before_it_writes(
    provisioned, spine_schema, tmp_path, monkeypatch
):
    creature = _creature()
    shipped_kind = sorted(key for key, _version in shipped_thing_kinds())[0]
    shipped_plan = sorted(plan.key for plan in thing_catalogs().plans.values())[0]
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _store(connection, workspace_id, tmp_path)
        # A shipped key, whichever of the creature's pieces takes it.
        for shadowing in (
            dataclasses.replace(
                creature, kind=dataclasses.replace(creature.kind, kind=shipped_kind)
            ),
            dataclasses.replace(
                creature, plan=dataclasses.replace(creature.plan, key=shipped_plan)
            ),
            dataclasses.replace(
                creature, sketch=dataclasses.replace(creature.sketch, look="blocky-traveller")
            ),
        ):
            with pytest.raises(ThingStoreRefused) as refused:
                store.keep_creature(shadowing, created_by=ACTOR)
            assert refused.value.code == "thing_key_shipped"
        other_bytes = dataclasses.replace(creature, sketch_container=b"glTF" + b"\x00" * 64)
        with pytest.raises(ThingStoreRefused) as refused:
            store.keep_creature(other_bytes, created_by=ACTOR)
        assert refused.value.code == "look_container_mismatch"
        assert set(_counts(connection).values()) == {0}
        assert not _held(store, creature.sketch_container)
        # The positive control, then the same creature again, and the same versions drawn from
        # other bytes: refused before those bytes are written.
        store.keep_creature(creature, created_by=ACTOR)
        assert _held(store, creature.sketch_container)
        with pytest.raises(ThingStoreRefused) as refused:
            store.keep_creature(creature, created_by=ACTOR)
        assert refused.value.code == "thing_version_exists"
        redrawn = _redrawn(creature, container_of("blocky-knight"))
        with pytest.raises(ThingStoreRefused) as refused:
            store.keep_creature(redrawn, created_by=ACTOR)
        assert refused.value.code == "thing_version_exists"
        assert not _held(store, redrawn.sketch_container)
        # A full library, of kinds or of looks.
        dragon = _creature("store dragon", "dragon")
        for cap in ("KINDS_PER_WORKSPACE", "LOOKS_PER_WORKSPACE"):
            with monkeypatch.context() as patched:
                patched.setattr(thing_store, cap, 1)
                with pytest.raises(ThingStoreRefused) as refused:
                    store.keep_creature(dragon, created_by=ACTOR)
            assert refused.value.code == "thing_cap_reached", cap
        assert not _held(store, dragon.sketch_container)
        assert _counts(connection)["body_plan_version"] == 1


def test_a_look_made_elsewhere_is_kept_after_its_intake_s_own_check(
    provisioned, spine_schema, tmp_path, monkeypatch
):
    imported = _imported()
    static = container_of("blocky-traveller")
    sculpted, skinned = _sculpted()
    knight = container_of("blocky-knight")
    workspace_id = provisioned.workspace_id
    seen: list[Look] = []

    def admit(look: Look) -> None:
        seen.append(look)

    def refuse(look: Look) -> None:
        raise ThingStoreRefused("look_not_admitted", "no admitted mapping names it")

    with _runtime(spine_schema, workspace_id) as connection:
        store = _store(connection, workspace_id, tmp_path)
        with pytest.raises(ThingStoreRefused) as refused:
            store.admit_look(imported, static, created_by=ACTOR, admit=refuse)
        assert refused.value.code == "look_not_admitted"
        assert _counts(connection)["look_version"] == 0
        assert not _held(store, static)
        kept = store.admit_look(imported, static, created_by=ACTOR, admit=admit)
        assert [look.look for look in seen] == ["fixture-traveller-own"]
        assert kept.container_profile == "exulanica.static-glb/v1"
        assert _container(store, kept) == static
        row = connection.execute(
            "select spdx, share_alike, attribution, licence_url, distribution, origin_class "
            "from look_version"
        ).fetchone()
        licence = imported["origin"]["licence"]
        assert row == {
            "spdx": "CC-BY-SA-4.0",
            "share_alike": True,
            "attribution": licence["attribution"],
            "licence_url": licence["licence_url"],
            "distribution": "public",
            "origin_class": "imported",
        }
        kept = store.admit_look(sculpted, skinned, created_by=ACTOR, admit=_admit_any)
        assert kept.container_profile == "exulanica.skinned-glb/v1"
        # The same version drawn from other bytes, and a full library: refused before the bytes.
        redrawn = {**imported, "container": _drawn_from(knight)}
        with pytest.raises(ThingStoreRefused) as refused:
            store.admit_look(redrawn, knight, created_by=ACTOR, admit=_admit_any)
        assert refused.value.code == "thing_version_exists"
        monkeypatch.setattr(thing_store, "LOOKS_PER_WORKSPACE", 2)
        with pytest.raises(ThingStoreRefused) as refused:
            store.admit_look(
                {**redrawn, "look": "fixture-traveller-other"},
                knight,
                created_by=ACTOR,
                admit=_admit_any,
            )
        assert refused.value.code == "thing_cap_reached"
        assert not _held(store, knight)
        assert _counts(connection)["look_version"] == 2


def _insert_look(connection, document: dict[str, Any], profile: str) -> None:
    connection.execute(
        "insert into look_version (workspace_id,key,version,sha256,document,container_profile,"
        "admission,created_by) values (current_workspace(),%s,%s,%s,%s,%s,%s,%s)",
        (
            document["look"],
            document["version"],
            sha256_of_canonical(document).hex(),
            Jsonb(document),
            profile,
            Jsonb({}),
            ACTOR,
        ),
    )


@pytest.mark.parametrize(
    ("change", "constraint"),
    [
        ({"attribution": None, "verdict": "SHIP"}, "look_version_credits_what_it_shares"),
        ({"licence_url": None}, "look_version_credits_what_it_shares"),
        ({"authors": []}, "look_version_credits_what_it_shares"),
        ({"profile": "exulanica.skinned-glb/v1"}, "look_version_reads_its_container_by_its_kind"),
        ({"skinned": "exulanica.static-glb/v1"}, "look_version_reads_its_container_by_its_kind"),
    ],
)
def test_the_table_holds_a_look_s_credit_and_profile(provisioned, spine_schema, change, constraint):
    if "skinned" in change:
        document, profile = _sculpted()[0], change["skinned"]
    else:
        document, profile = _imported(), change.get("profile", "exulanica.static-glb/v1")
        for field, value in change.items():
            if field == "authors":
                document["origin"]["authors"] = value
            elif field != "profile":
                document["origin"]["licence"][field] = value
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            _insert_look(connection, document, profile)
        assert refused.value.diag.constraint_name == constraint


def test_the_table_holds_a_kind_s_plan_and_a_withdrawal_s_digest(
    provisioned, spine_schema, tmp_path
):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _store(connection, workspace_id, tmp_path).keep_creature(creature, created_by=ACTOR)
        # A kind whose document names the drafted plan's digest, with no digest in its row.
        kind = {**creature.kind.document, "kind": "unpinned_kind"}
        with pytest.raises(psycopg.errors.CheckViolation) as refused:
            connection.execute(
                "insert into thing_kind_version (workspace_id,key,version,sha256,document,plan,"
                "created_by) values (current_workspace(),%s,1,%s,%s,%s,%s)",
                ("unpinned_kind", "e" * 64, Jsonb(kind), creature.plan.name, ACTOR),
            )
        assert refused.value.diag.constraint_name == "thing_kind_version_names_its_plan"
        # A withdrawal naming the right version at another digest.
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "insert into look_withdrawal (workspace_id,key,version,sha256,reason,"
                "withdrawn_by) values (current_workspace(),%s,%s,%s,'no longer worn',%s)",
                (creature.sketch.look, creature.sketch.version, "e" * 64, ACTOR),
            )


def test_a_withdrawn_look_stays_held_and_is_passed_by(provisioned, spine_schema, tmp_path):
    creature = _creature()
    reference = creature.sketch.reference()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _store(connection, workspace_id, tmp_path)
        with pytest.raises(ThingStoreRefused) as refused:
            store.withdraw_look(creature.sketch.look, 1, "no longer wanted", withdrawn_by=ACTOR)
        assert refused.value.code == "look_unknown"
        store.keep_creature(creature, created_by=ACTOR)
        assert admitted_look(connection, workspace_id, reference) == creature.sketch
        assert admitted_look(connection, workspace_id, {**reference, "sha256": "e" * 64}) is None
        assert admitted_look_by_digest(connection, workspace_id, reference["sha256"]) == (
            creature.sketch
        )
        assert admitted_look_by_digest(connection, workspace_id, "e" * 64) is None
        with pytest.raises(ThingStoreRefused) as refused:
            store.withdraw_look(creature.sketch.look, 1, "no longer\nwanted", withdrawn_by=ACTOR)
        assert refused.value.code == "withdrawal_reason_refused"
        store.withdraw_look(creature.sketch.look, 1, "no longer wanted", withdrawn_by=ACTOR)
        store.withdraw_look(creature.sketch.look, 1, "asked twice", withdrawn_by=ACTOR)
        assert admitted_look(connection, workspace_id, reference) is None
        assert admitted_look_by_digest(connection, workspace_id, reference["sha256"]) is None
        assert store.look(creature.sketch.look, 1) is None
        assert store.look_by_digest(creature.sketch.sha256) is None
        kept = store.look(creature.sketch.look, 1, include_withdrawn=True)
        assert kept is not None and kept.withdrawn
        assert store.look_by_digest(creature.sketch.sha256, include_withdrawn=True) == kept
        # The kind stays what it is, with no look left to draw.
        kind = store.kind(creature.kind.kind, creature.kind.version)
        assert kind is not None and kind.sha256 == creature.kind.sha256
        assert _counts(connection)["look_withdrawal"] == 1
        withdrawal = connection.execute("select reason, sha256 from look_withdrawal").fetchone()
        assert withdrawal == {"reason": "no longer wanted", "sha256": creature.sketch.sha256}
        # A look whose document the reader now refuses is withdrawn by its row.
        unread = _imported()
        unread["look"] = "fixture-unread"
        unread["label"] = "Not Lowercase"
        _insert_look(connection, copy.deepcopy(unread), "exulanica.static-glb/v1")
        assert store.look("fixture-unread", 1, include_withdrawn=True) is None
        unread_sha256 = sha256_of_canonical(unread).hex()
        assert admitted_look_by_digest(connection, workspace_id, unread_sha256) is None
        store.withdraw_look("fixture-unread", 1, "no longer read", withdrawn_by=ACTOR)
        assert _counts(connection)["look_withdrawal"] == 2
