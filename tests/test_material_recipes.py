"""Migration 0066: a workspace's own material recipes and bakes, and how deletion reaches them.

Four groups, each against real PostgreSQL:

*   **Recipes** are checked against the published maker before they are stored, are immutable,
    are hidden the moment they are withdrawn, and cannot be derived from a photograph yet.
*   **Bakes** move only along their states, are counted against the workspace's quota, and are
    made by :class:`~exulanica.world.material_bakes.MaterialBakeWorker`, which records a bake
    before it writes a byte. The tests that need the real baker say so and skip only when this
    checkout has no ``web/node_modules``; everything else records a synthetic container through
    the worker's own record-and-write path.
*   **Erasure** runs through the one purge machinery: a workspace tombstone destroys every bake,
    a capture tombstone and a person withdrawal destroy the bakes of photo-derived recipes that
    reach them and nothing else, completion waits for the bytes, the purge role holds only the
    columns it needs, and restore replays a bake's purge. A photo-derived recipe cannot exist
    yet, so those tests set aside exactly the two triggers that keep it inert, and put them back.
*   **Withdrawal** of an authored recipe hides it and destroys nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.roles import provision_purge_role
from exulanica.deletion import queue
from exulanica.deletion.restore import RestoreRefused, checkpoint, prepare_restore, replay
from exulanica.deletion.worker import PurgeWorker
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence.blob import BlobId
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.materials import canonical_bytes, sha256_hex, thaw
from exulanica.materials.workspace import (
    WORKSPACE_LICENCE_ID,
    WORKSPACE_LICENCE_SHA256,
    BakeResult,
    bake_receipt,
    bake_request,
)
from exulanica.migrations import migration_directory
from exulanica.store.namespaces import LocalWorkspaceStores
from exulanica.world.material_bakes import (
    BakeLimits,
    BakeRuntime,
    BakeRuntimeUnavailable,
    MaterialBakeWorker,
    _Failed,
)
from exulanica.world.material_recipes import (
    BakeBytesMissing,
    BakeNotReady,
    BakeQuotaExceeded,
    InvalidRecipe,
    MaterialReadOnly,
    MaterialRepository,
    MaterialWithdrawn,
    PhotoDerivedRecipeInert,
    ProposedRecipeInert,
    UnknownMaterial,
    _refusals,
)
from exulanica.world.texture_assets import load_material_catalog

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo
from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged

MIGRATION = migration_directory() / "0066_workspace_material_recipes.sql"
CATALOG = load_material_catalog()
BRICK = "cc0.brick-running-bond"
METAL = "cc0.storefront-metal"
#: The tables 0066 puts under forced row-level security, keyed on the workspace.
FORCED = (
    "material_bake",
    "material_bake_quota",
    "material_bake_request",
    "material_recipe",
    "material_recipe_source",
    "material_recipe_withdrawal",
)
#: The two triggers that keep a photo-derived recipe inert until 0073.
INERT = (
    ("material_recipe", "tg_material_recipe_awaits_model_right"),
    ("material_recipe_source", "tg_material_recipe_source_awaits_model_right"),
)
#: The one that keeps a proposed recipe inert until a proposal records its model.
PROPOSAL_INERT = ("material_recipe", "tg_material_recipe_awaits_proposal_model")


def _code(text: str) -> str:
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _small(set_id: str = BRICK, *, seed: int | None = None) -> dict:
    """A published recipe at the smallest resolution, so a real bake takes a moment."""
    recipe = thaw(CATALOG.sets[set_id].recipe)
    recipe["resolution"] = {"width": 16, "height": 16}
    if seed is not None:
        recipe["seed"] = seed
    return recipe


class Materials:
    """Recipes, bakes and the purge over the `purged` fixture's workspace and photograph."""

    def __init__(self, purged, tmp_path: Path) -> None:
        self.purged = purged
        self.workspace_id = purged.workspace_id
        self.stores = LocalWorkspaceStores(tmp_path / "materials")
        self.actor = uuid.uuid4()
        self.owner = purged.database()
        self._sessions = contextlib.ExitStack()
        self.connection = self._sessions.enter_context(self.owner.session(self.workspace_id))

    def close(self) -> None:
        self._sessions.close()

    def repository(self, connection=None) -> MaterialRepository:
        return MaterialRepository(
            connection or self.connection,
            self.workspace_id,
            self.actor,
            catalog=CATALOG,
            stores=self.stores,
        )

    def rows(self, sql: str, *params):
        return self.connection.execute(sql, params).fetchall()

    def worker(self, runtime: BakeRuntime | None = None, **options) -> MaterialBakeWorker:
        return MaterialBakeWorker(
            self.owner,
            self.stores,
            frozenset({self.workspace_id}),
            runtime=runtime or BakeRuntime(Path("/absent/node"), Path("/absent"), Path("/absent")),
            catalog=CATALOG,
            **options,
        )

    def purge_worker(self) -> PurgeWorker:
        return PurgeWorker(
            self.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
            self.purged.store,
            frozenset({self.workspace_id}),
            name="test-material-purge",
            material_stores=self.stores,
        )

    def record_synthetic_bake(self, recipe_id: uuid.UUID, payload: bytes | None = None) -> bytes:
        """Claim and record a bake through the worker's own path, with made-up container bytes.

        Erasure does not care what the bytes are, only that a recorded bake names them and the
        namespace holds them, so this needs no Node. The receipt is a real one for the recipe.
        """
        worker = self.worker()
        claim = worker._claim(self.connection, self.workspace_id)
        assert claim is not None and claim.recipe_id == recipe_id
        container = payload or b"synthetic container for " + recipe_id.bytes
        assert worker._record_and_write(
            self.connection, self.workspace_id, claim, container, self.receipt(recipe_id, container)
        )
        return container

    def receipt(self, recipe_id: uuid.UUID, container: bytes) -> dict:
        """A real receipt for the recipe, naming made-up container bytes."""
        record = self.repository().recipe(recipe_id)
        request = bake_request(
            recipe_id=recipe_id, recipe=record.recipe, maker_sha256=record.maker_sha256
        )
        return bake_receipt(
            request=request,
            maker_sha256=record.maker_sha256,
            recipe_sha256=record.recipe_sha256,
            result=BakeResult(
                content_sha256=hashlib.sha256(container).hexdigest(),
                byte_size=len(container),
                node="v24.0.0",
                package_sha256="0" * 64,
            ),
        )

    def forget_bakes(self) -> None:
        """Delete every bake row, as a database restored from before the bakes would lack them."""
        with self.connection.transaction():
            for table, trigger in (
                ("material_bake_request", "tg_material_bake_request_append_only"),
                ("material_bake", "tg_material_bake_no_delete"),
            ):
                self.connection.execute(f"alter table {table} disable trigger {trigger}")
            self.connection.execute("delete from material_bake_request")
            self.connection.execute("delete from material_bake")
            for table, trigger in (
                ("material_bake_request", "tg_material_bake_request_append_only"),
                ("material_bake", "tg_material_bake_no_delete"),
            ):
                self.connection.execute(f"alter table {table} enable trigger {trigger}")

    def baked(self, set_id: str = BRICK, **recipe_options) -> tuple[uuid.UUID, bytes]:
        recipe = self.repository().create_recipe(_small(set_id, **recipe_options))
        self.repository().request_bake(recipe.recipe_id)
        return recipe.recipe_id, self.record_synthetic_bake(recipe.recipe_id)

    def in_namespace(self, container: bytes) -> bool:
        return self.stores.for_workspace(self.workspace_id).exists(BlobId.of_bytes(container))

    @contextlib.contextmanager
    def photo_derived_allowed(self):
        """Set aside the two inert triggers, as the migration after 0073 will, and restore them."""
        for table, trigger in INERT:
            self.connection.execute(f"alter table {table} disable trigger {trigger}")
        try:
            yield
        finally:
            for table, trigger in INERT:
                self.connection.execute(f"alter table {table} enable trigger {trigger}")

    def photo_derived(self, captures: list[uuid.UUID], set_id: str = METAL) -> uuid.UUID:
        """A photo-derived recipe naming these photographs, written as 0073's service will."""
        record = CATALOG.sets[set_id]
        raw = canonical_bytes(_small(set_id, seed=len(captures) + 7))
        with self.connection.transaction():
            recipe_id = self.connection.execute(
                "insert into material_recipe (workspace_id, origin, maker_id, maker_version, "
                "  maker_sha256, recipe_canonical, recipe_document, recipe_sha256, "
                "  source_count, created_by) "
                "values (%s, 'photo_derived', %s, %s, %s, %s, convert_from(%s, 'UTF8')::jsonb, "
                "  %s, %s, %s) returning recipe_id",
                (
                    self.workspace_id,
                    record.maker.maker_id,
                    record.maker.version,
                    bytes.fromhex(record.maker.sha256),
                    raw,
                    raw,
                    hashlib.sha256(raw).digest(),
                    len(captures),
                    self.actor,
                ),
            ).fetchone()["recipe_id"]
            for ordinal, capture in enumerate(captures):
                self.connection.execute(
                    "insert into material_recipe_source (workspace_id, recipe_id, capture_id, "
                    "  ordinal) values (%s, %s, %s, %s)",
                    (self.workspace_id, recipe_id, capture, ordinal),
                )
        return recipe_id

    def blocked(self, recipe_id: uuid.UUID) -> bool:
        return self.rows(
            "select tombstone_blocks_material_recipe(%s, %s) as blocked",
            self.workspace_id,
            recipe_id,
        )[0]["blocked"]


@pytest.fixture
def materials(purged, tmp_path):
    fixture = Materials(purged, tmp_path)
    try:
        yield fixture
    finally:
        fixture.close()


def _capture(materials) -> uuid.UUID:
    return materials.rows("select capture_id from capture order by created_at")[0]["capture_id"]


def _second_capture(materials, photo_dir) -> uuid.UUID:
    purged = materials.purged
    # A different description too, so no derivative of one photograph shares bytes with the other's
    # and a deletion of one completes without waiting on the other.
    vision = CountingVisionModel(
        payload={**DEFAULT_PAYLOAD, "scene_description": "A second photograph, of something else."}
    )
    pipeline = PhotoIngestPipeline(purged.repository, purged.store, vision=vision)
    # Different bytes from the fixture's photograph, so deleting one never waits on the other.
    photo = write_photo(photo_dir, "b.jpg", when="2026:08:27 10:02:00", size=(120, 90))
    outcome = ingest_observed(pipeline, purged.repository, photo)
    assert outcome.error is None, outcome.error
    return outcome.capture_id


# -- the file ----------------------------------------------------------------------------------


def test_0066_is_one_transaction_and_shaped_like_its_neighbours():
    statements = [line for line in _code(MIGRATION.read_text()).splitlines() if line.strip()]
    assert statements[0] == "begin;"
    assert statements[1] == "select pg_advisory_xact_lock(119622309);"
    assert statements[-1] == "commit;"
    assert "tombstone_scope" not in _code(MIGRATION.read_text()), "no scope is added"


def test_the_inert_triggers_refuse_and_do_nothing_else():
    code = _code(MIGRATION.read_text())
    for _, trigger in (*INERT, PROPOSAL_INERT):
        pattern = (
            rf"create function {trigger}\(\) returns trigger\s+"
            r"language plpgsql as \$fn\$(.*?)\$fn\$"
        )
        body = re.search(pattern, code, re.S)
        assert body is not None, trigger
        statements = [s.strip() for s in body.group(1).split(";") if s.strip()]
        assert any(s.startswith("raise exception") or "raise exception" in s for s in statements)
        assert not re.search(r"\b(insert|update|delete|perform)\b", body.group(1)), trigger


def test_every_material_table_is_forced_and_isolated(materials):
    rows = materials.rows(
        "select c.relname, c.relrowsecurity, c.relforcerowsecurity, "
        "  (select string_agg(p.qual, ' ') from pg_policies p "
        "    where p.schemaname = current_schema() and p.tablename = c.relname "
        "      and p.policyname = 'ws_isolation') as qual "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = current_schema() and c.relname = any(%s) order by c.relname",
        list(FORCED),
    )
    assert [row["relname"] for row in rows] == list(FORCED)
    for row in rows:
        assert row["relrowsecurity"] and row["relforcerowsecurity"], row["relname"]
        assert "current_workspace()" in row["qual"], row["relname"]


def test_writes_that_change_what_may_be_read_wait_for_a_delivery(materials):
    guarded = {
        row["relname"]
        for row in materials.rows(
            "select c.relname from pg_trigger t join pg_class c on c.oid = t.tgrelid "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname = current_schema() and t.tgname = 'aaa_asset_read_mutation' "
            "  and c.relname like 'material%%'"
        )
    }
    assert guarded == {
        "material_bake",
        "material_recipe",
        "material_recipe_source",
        "material_recipe_withdrawal",
    }


def test_the_queue_and_the_dependency_kinds_name_the_new_targets(materials):
    definitions = " ".join(
        row["definition"]
        for row in materials.rows(
            "select pg_get_constraintdef(c.oid) as definition from pg_constraint c "
            "where c.conname in ('purge_job_target_kind_check', "
            "  'person_derivative_dependency_target_kind_check') "
            "  and c.connamespace = current_schema()::regnamespace"
        )
    )
    assert "'material_bake'" in definitions
    assert "'material_recipe'" in definitions


# -- recipes -----------------------------------------------------------------------------------


def test_an_authored_recipe_is_checked_stored_and_read_back(materials):
    document = _small()
    record = materials.repository().create_recipe(document, based_on=(BRICK, 1), label="Mine")
    assert record.origin == "authored"
    assert (record.maker_id, record.maker_version) == ("loom.brick", 1)
    assert record.maker_sha256 == CATALOG.sets[BRICK].maker.sha256
    assert record.recipe_sha256 == sha256_hex(canonical_bytes(document))
    assert thaw(record.recipe) == document
    assert record.label == "Mine" and record.based_on == (BRICK, 1)
    assert [r.recipe_id for r in materials.repository().recipes()] == [record.recipe_id]
    stored = materials.rows(
        "select recipe_document, label from material_recipe where recipe_id = %s",
        record.recipe_id,
    )[0]
    assert stored["recipe_document"] == document and "Mine" not in str(stored["recipe_document"])


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r["parameters"].update(courses=25), "even number"),
        (lambda r: r.update(resolution={"width": 15, "height": 16}), "power of two"),
        (lambda r: r["maker"].update(version=2), "published maker"),
        (lambda r: r["maker"].update(id="loom.unknown"), "published maker"),
        (lambda r: r.update(seed=1.5), "float"),
        (lambda r: r.update(profile="exulanica.texture-recipe/v2"), "profile"),
        (lambda r: r["parameters"].update(mortar_colour="gréy"), "cannot write"),
    ],
)
def test_a_recipe_the_published_maker_refuses_is_never_stored(materials, change, message):
    document = _small()
    change(document)
    with pytest.raises(InvalidRecipe, match=message):
        materials.repository().create_recipe(document)
    assert materials.rows("select recipe_id from material_recipe") == []


def test_a_recipe_for_a_maker_of_a_material_class_is_refused_by_name(materials):
    """A workspace bakes v1 opaque sets only, so a published maker that states its class is
    refused when a recipe names it, before any bake could fail on it."""
    for set_id, material_class in (
        ("cc0.float-glazing", "glazing"),
        ("cc0.broadleaf-foliage", "cutout"),
        ("cc0.tree-bark", "opaque"),
    ):
        record = CATALOG.sets[set_id]
        with pytest.raises(InvalidRecipe, match=f"{record.maker.maker_id} makes {material_class}"):
            materials.repository().create_recipe(thaw(record.recipe))
    assert materials.rows("select recipe_id from material_recipe") == []


def test_a_variant_names_a_pinned_set_and_that_set_s_maker(materials):
    repository = materials.repository()
    with pytest.raises(InvalidRecipe, match="pinned version"):
        repository.create_recipe(_small(), based_on=(BRICK, 2))
    with pytest.raises(InvalidRecipe, match="that set's maker"):
        repository.create_recipe(_small(), based_on=(METAL, 1))
    for label in ("", " padded", "a" * 201, "line\nbreak"):
        with pytest.raises(InvalidRecipe, match="label"):
            repository.create_recipe(_small(), label=label)


def test_a_photo_derived_recipe_is_refused_by_the_repository_and_by_the_schema(materials):
    with pytest.raises(PhotoDerivedRecipeInert):
        materials.repository().create_recipe(_small(), origin="photo_derived")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="personal model right"):
        materials.photo_derived([_capture(materials)])
    authored = materials.repository().create_recipe(_small())
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="personal model right"):
        materials.connection.execute(
            "insert into material_recipe_source (workspace_id, recipe_id, capture_id, ordinal) "
            "values (%s, %s, %s, 0)",
            (materials.workspace_id, authored.recipe_id, _capture(materials)),
        )


def _insert_recipe(materials, origin: str) -> None:
    """A recipe row written straight to the table, as nothing in the product writes one."""
    raw = canonical_bytes(_small())
    materials.connection.execute(
        "insert into material_recipe (workspace_id, origin, maker_id, maker_version, "
        "  maker_sha256, recipe_canonical, recipe_document, recipe_sha256, created_by) "
        "values (%s, %s, 'loom.brick', 1, %s, %s, convert_from(%s, 'UTF8')::jsonb, %s, %s)",
        (
            materials.workspace_id,
            origin,
            bytes.fromhex(CATALOG.sets[BRICK].maker.sha256),
            raw,
            raw,
            hashlib.sha256(raw).digest(),
            materials.actor,
        ),
    )


def test_a_proposed_recipe_is_refused_until_a_proposal_records_its_model(materials):
    with pytest.raises(ProposedRecipeInert, match="the model that proposed it"):
        materials.repository().create_recipe(_small(), origin="proposed")
    # The schema refuses it whatever writes it, and says so in words the repository names.
    with pytest.raises(ProposedRecipeInert), _refusals():
        _insert_recipe(materials, "proposed")
    # Setting aside the photo-derived triggers does not set this one aside.
    with (
        materials.photo_derived_allowed(),
        pytest.raises(psycopg.errors.InsufficientPrivilege, match="the model that proposed it"),
    ):
        _insert_recipe(materials, "proposed")
    assert materials.rows("select count(*) as n from material_recipe")[0]["n"] == 0
    # With the trigger set aside the repository still refuses on its own, and the trigger is all
    # that stands in the schema: the column admits the value, so the migration that records a
    # proposal's model has only to replace the trigger.
    table, trigger = PROPOSAL_INERT
    with materials.connection.transaction(force_rollback=True):
        materials.connection.execute(f"alter table {table} disable trigger {trigger}")
        with pytest.raises(ProposedRecipeInert):
            materials.repository().create_recipe(_small(), origin="proposed")
        _insert_recipe(materials, "proposed")
    assert materials.rows("select count(*) as n from material_recipe")[0]["n"] == 0


def test_with_the_right_in_place_a_source_must_be_a_live_photograph_of_that_recipe(materials):
    authored = materials.repository().create_recipe(_small())
    with materials.photo_derived_allowed():
        with pytest.raises(psycopg.errors.CheckViolation, match="only a photo-derived"):
            materials.connection.execute(
                "insert into material_recipe_source values (%s, %s, %s, 0)",
                (materials.workspace_id, authored.recipe_id, _capture(materials)),
            )
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="names 0 photographs"),
            materials.connection.transaction(),
        ):
            raw = canonical_bytes(_small(METAL))
            materials.connection.execute(
                "insert into material_recipe (workspace_id, origin, maker_id, maker_version, "
                "  maker_sha256, recipe_canonical, recipe_document, recipe_sha256, "
                "  source_count, created_by) values (%s, 'photo_derived', 'loom.metal', 1, "
                "  %s, %s, convert_from(%s, 'UTF8')::jsonb, %s, 1, %s)",
                (
                    materials.workspace_id,
                    bytes.fromhex(CATALOG.sets[METAL].maker.sha256),
                    raw,
                    raw,
                    hashlib.sha256(raw).digest(),
                    materials.actor,
                ),
            )
        derived = materials.photo_derived([_capture(materials)])
        assert not materials.blocked(derived)


def test_a_recipe_is_immutable_and_never_deleted(materials):
    record = materials.repository().create_recipe(_small())
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="immutable"):
        materials.connection.execute(
            "update material_recipe set label = 'changed' where recipe_id = %s",
            (record.recipe_id,),
        )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        materials.connection.execute(
            "delete from material_recipe where recipe_id = %s", (record.recipe_id,)
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        materials.connection.execute(
            "insert into material_recipe (workspace_id, origin, maker_id, maker_version, "
            "  maker_sha256, recipe_canonical, recipe_document, recipe_sha256, created_by) "
            "select workspace_id, origin, maker_id, maker_version, maker_sha256, "
            "  recipe_canonical, recipe_document, sha256('forged'), created_by "
            "from material_recipe where recipe_id = %s",
            (record.recipe_id,),
        )


def test_a_withdrawn_recipe_is_hidden_its_row_kept_and_nothing_destroyed(materials):
    recipe_id, container = materials.baked()
    repository = materials.repository()
    repository.withdraw_recipe(recipe_id)
    assert repository.recipes() == []
    with pytest.raises(MaterialWithdrawn):
        repository.recipe(recipe_id)
    with pytest.raises(MaterialWithdrawn):
        repository.read_bake(recipe_id)
    with pytest.raises(MaterialWithdrawn):
        repository.withdraw_recipe(recipe_id)
    assert materials.rows("select count(*) as n from material_recipe")[0]["n"] == 1
    assert (
        materials.rows("select purge_id from purge_job where target_kind = 'material_bake'") == []
    )
    assert materials.in_namespace(container), "withdrawal hides; the workspace's deletion reclaims"
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="append-only"):
        materials.connection.execute("delete from material_recipe_withdrawal")
    with pytest.raises(UnknownMaterial):
        repository.recipe(uuid.uuid4())


def test_another_workspace_sees_no_recipe_and_cannot_request_its_bake(materials):
    record = materials.repository().create_recipe(_small())
    app = materials.purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with app.session(materials.workspace_id) as own:
        assert [r.recipe_id for r in materials.repository(own).recipes()] == [record.recipe_id]
    other = uuid.uuid4()
    with app.session(other) as foreign:
        repository = MaterialRepository(
            foreign, other, uuid.uuid4(), catalog=CATALOG, stores=materials.stores
        )
        assert repository.recipes() == []
        with pytest.raises(UnknownMaterial):
            repository.request_bake(record.recipe_id)
        assert foreign.execute("select count(*) as n from material_recipe").fetchone()["n"] == 0


# -- bakes -------------------------------------------------------------------------------------


def test_requesting_a_bake_queues_it_once_and_counts_each_request(materials):
    record = materials.repository().create_recipe(_small())
    first = materials.repository().request_bake(record.recipe_id)
    again = materials.repository().request_bake(record.recipe_id)
    assert first.bake_id == again.bake_id
    assert first.state == "requested" and first.set_id == f"ws.{record.recipe_id.hex}"
    assert materials.rows("select count(*) as n from material_bake_request")[0]["n"] == 1
    with pytest.raises(BakeNotReady):
        materials.repository().read_bake(record.recipe_id)


def test_the_daily_quota_and_the_waiting_quota_refuse_past_their_limits(materials):
    materials.connection.execute(
        "insert into material_bake_quota (workspace_id, requests_per_day, pending_at_once, "
        "  declared_by) values (%s, 2, 1, %s)",
        (materials.workspace_id, materials.actor),
    )
    repository = materials.repository()
    first = repository.create_recipe(_small())
    second = repository.create_recipe(_small(seed=5))
    repository.request_bake(first.recipe_id)
    with pytest.raises(BakeQuotaExceeded, match="waiting"):
        repository.request_bake(second.recipe_id)
    assert materials.rows("select count(*) as n from material_bake")[0]["n"] == 1

    worker = materials.worker()
    claim = worker._claim(materials.connection, materials.workspace_id)
    assert worker._finish_failed(
        materials.connection, materials.workspace_id, claim, _Failed("bake_failed", "test")
    )
    assert repository.request_bake(first.recipe_id).state == "requested"
    claim = worker._claim(materials.connection, materials.workspace_id)
    worker._finish_failed(
        materials.connection, materials.workspace_id, claim, _Failed("bake_failed", "test")
    )
    with pytest.raises(BakeQuotaExceeded, match="last day"):
        repository.request_bake(first.recipe_id)


def test_a_bake_never_enters_the_queue_without_a_request_that_counts_it(materials):
    """Whatever writes the queue, the database holds the count: a bare write fails at commit."""
    record = materials.repository().create_recipe(_small())

    def refused_at_commit(sql: str, *params) -> None:
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="without a request that counts it"),
            materials.connection.transaction(),
        ):
            materials.connection.execute(sql, params)

    refused_at_commit(
        "insert into material_bake (workspace_id, recipe_id, set_id, requested_by) "
        "values (%s, %s, %s, %s)",
        materials.workspace_id,
        record.recipe_id,
        f"ws.{record.recipe_id.hex}",
        materials.actor,
    )
    assert materials.rows("select count(*) as n from material_bake")[0]["n"] == 0

    # Entering the queue is what counts: a write that leaves a waiting bake waiting is no request.
    materials.repository().request_bake(record.recipe_id)
    with materials.connection.transaction():
        materials.connection.execute(
            "update material_bake set attempts = attempts where workspace_id = %s",
            (materials.workspace_id,),
        )

    # Back from failed: a bare update commits nothing, and asking through the repository does.
    worker = materials.worker()
    claim = worker._claim(materials.connection, materials.workspace_id)
    assert worker._finish_failed(
        materials.connection, materials.workspace_id, claim, _Failed("bake_failed", "test")
    )
    refused_at_commit(
        "update material_bake set state = 'requested', attempts = 0, failure_class = null, "
        "  failure_message = null where workspace_id = %s",
        materials.workspace_id,
    )
    assert materials.rows("select state from material_bake")[0]["state"] == "failed"
    assert materials.repository().request_bake(record.recipe_id).state == "requested"

    # Back from baked: the same.
    materials.record_synthetic_bake(record.recipe_id)
    refused_at_commit(
        "update material_bake set state = 'requested' where workspace_id = %s",
        materials.workspace_id,
    )
    assert materials.rows("select state from material_bake")[0]["state"] == "baked"
    assert materials.rows("select count(*) as n from material_bake_request")[0]["n"] == 2


def test_a_withdrawal_cancels_a_waiting_bake_and_refuses_a_new_request(materials):
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    materials.repository().withdraw_recipe(record.recipe_id)
    row = materials.rows("select state, failure_class from material_bake")[0]
    assert (row["state"], row["failure_class"]) == ("cancelled", "withdrawn")
    with pytest.raises(MaterialWithdrawn):
        materials.repository().request_bake(record.recipe_id)
    assert materials.worker()._claim(materials.connection, materials.workspace_id) is None


@pytest.mark.parametrize(
    "update",
    [
        "state = 'baked'",
        "state = 'running'",
        "set_id = 'ws.00000000000000000000000000000000'",
        "attempts = 1, state = 'cancelled', failure_class = null",
        "purged_at = now()",
    ],
)
def test_a_bake_moves_only_along_its_states_and_only_the_purger_marks_it_gone(materials, update):
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    with pytest.raises(psycopg.errors.Error):
        materials.connection.execute(f"update material_bake set {update}")


def test_recorded_bytes_never_change_and_the_runtime_never_marks_them_purged(materials):
    recipe_id, _ = materials.baked()
    for update in (
        "content_sha256 = sha256('other')",
        "state = 'failed', failure_class = 'bake_failed'",
        "purged_at = now()",
    ):
        with pytest.raises(psycopg.errors.Error):
            materials.connection.execute(
                f"update material_bake set {update} where recipe_id = %s", (recipe_id,)
            )
    app = materials.purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with app.session(materials.workspace_id) as runtime:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute("update material_bake set purged_at = now()")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            runtime.execute("delete from material_bake")


def test_a_lost_lease_records_nothing(materials):
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    worker = materials.worker(lease_seconds=120)
    claim = worker._claim(materials.connection, materials.workspace_id)
    materials.connection.execute(
        "update material_bake set lease_expires_at = clock_timestamp() - interval '1 second'"
    )
    retaken = worker._claim(materials.connection, materials.workspace_id)
    assert retaken is not None and retaken.claim_token != claim.claim_token
    assert not worker._record_and_write(
        materials.connection, materials.workspace_id, claim, b"late", {"profile": "x"}
    )
    assert not materials.in_namespace(b"late")


def test_a_deletion_before_the_record_refuses_the_bake_and_writes_nothing(materials):
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    worker = materials.worker()
    claim = worker._claim(materials.connection, materials.workspace_id)
    materials.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    row = materials.rows("select state from material_bake")[0]
    assert row["state"] == "cancelled"
    assert not worker._record_and_write(
        materials.connection, materials.workspace_id, claim, b"too late", {"profile": "x"}
    )
    assert not materials.in_namespace(b"too late")


def _real_runtime() -> BakeRuntime:
    try:
        return BakeRuntime.from_checkout()
    except BakeRuntimeUnavailable as missing:
        pytest.skip(
            f"the real baker needs web/node_modules in this checkout ({missing}); run "
            "`pnpm --dir web install` to exercise it"
        )


def test_the_worker_bakes_verifies_records_and_serves_a_recipe(materials):
    runtime = _real_runtime()
    record = materials.repository().create_recipe(_small(METAL), based_on=(METAL, 1))
    materials.repository().request_bake(record.recipe_id)
    outcome = materials.worker(runtime).drain()
    assert (outcome.baked, outcome.failed, outcome.lost) == (1, 0, 0), outcome.failures
    bake = materials.repository().bake(record.recipe_id)
    assert bake is not None and bake.state == "baked"
    receipt = bake.receipt
    assert receipt["profile"] == "exulanica.workspace-texture-bake-receipt/v1"
    assert receipt["recipe_sha256"] == record.recipe_sha256
    assert receipt["maker_sha256"] == record.maker_sha256
    assert receipt["licence_id"] == "LicenseRef-Exulanica-Workspace-Private"
    assert re.fullmatch(r"v\d+\.\d+\.\d+", receipt["runtime"]["node"])
    served = materials.repository().read_bake(record.recipe_id)
    assert hashlib.sha256(served.data).hexdigest() == bake.content_sha256 == served.content_sha256
    assert served.set_id == bake.set_id and served.licence_id == receipt["licence_id"]
    assert not materials.purged.store.exists(BlobId.of_bytes(served.data)), "never a shared blob"


def test_missing_bytes_are_re_baked_to_the_digest_already_recorded(materials):
    runtime = _real_runtime()
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    assert materials.worker(runtime).drain().baked == 1
    first = materials.repository().bake(record.recipe_id)
    path = materials.stores.for_workspace(materials.workspace_id)._path_for(
        BlobId.from_hex(first.content_sha256)
    )
    path.chmod(0o644)
    path.unlink()
    with pytest.raises(BakeBytesMissing):
        materials.repository().read_bake(record.recipe_id)
    assert materials.repository().request_bake(record.recipe_id).state == "requested"
    assert materials.worker(runtime).drain().baked == 1
    healed = materials.repository().bake(record.recipe_id)
    assert healed.content_sha256 == first.content_sha256 and healed.receipt == first.receipt
    assert materials.repository().read_bake(record.recipe_id).content_sha256 == first.content_sha256


def test_a_bake_the_worker_cannot_verify_or_finish_in_time_stores_nothing(materials, tmp_path):
    runtime = _real_runtime()
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    tight = BakeLimits(timeout_seconds=0.05)
    outcome = materials.worker(runtime, limits=tight, lease_seconds=120).drain()
    assert outcome.failed == 1
    row = materials.rows("select state, failure_class, content_sha256 from material_bake")[0]
    assert (row["state"], row["failure_class"], row["content_sha256"]) == (
        "failed",
        "timed_out",
        None,
    )
    liar = tmp_path / "liar"
    liar.mkdir()
    fake = liar / "node"
    fake.write_text(
        "#!/bin/sh\n"
        'while [ "$1" != "--out" ]; do shift; done\n'
        'printf "not a container" > "$2"\n'
        'printf \'%s\' \'{"byte_size":15,"content_sha256":"'
        + hashlib.sha256(b"not a container").hexdigest()
        + '","profile":"exulanica.texture-bake-result/v1","runtime":'
        '{"node":"v1.0.0","package_sha256":"' + "0" * 64 + "\"}}'\n",
        encoding="ascii",
    )
    fake.chmod(0o755)
    materials.repository().request_bake(record.recipe_id)
    lying = BakeRuntime(node=fake, loader=runtime.loader, package=runtime.package)
    outcome = materials.worker(lying).drain()
    assert outcome.failed == 1, outcome
    row = materials.rows("select state, failure_class, content_sha256 from material_bake")[0]
    assert (row["state"], row["failure_class"], row["content_sha256"]) == (
        "failed",
        "unverified_output",
        None,
    )
    assert not materials.in_namespace(b"not a container")


# -- erasure -----------------------------------------------------------------------------------


def test_a_workspace_tombstone_destroys_every_bake_and_completion_waits_for_it(materials):
    _, first_bytes = materials.baked()
    _, second_bytes = materials.baked(METAL)
    waiting = materials.repository().create_recipe(_small(seed=9))
    materials.repository().request_bake(waiting.recipe_id)
    tombstone = materials.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    jobs = materials.rows(
        "select target_ref from purge_job where tombstone_id = %s and target_kind = "
        "'material_bake' order by target_ref",
        tombstone,
    )
    assert [job["target_ref"] for job in jobs] == sorted(
        hashlib.sha256(payload).hexdigest() for payload in (first_bytes, second_bytes)
    )
    states = {row["state"] for row in materials.rows("select state from material_bake")}
    assert states == {"baked", "cancelled"}
    assert not queue.is_purge_complete(materials.connection, tombstone)

    outcome = materials.purge_worker().drain()
    assert outcome.failed == 0 and outcome.blocked is None, outcome
    assert not materials.in_namespace(first_bytes) and not materials.in_namespace(second_bytes)
    assert all(
        row["purged_at"] is not None
        for row in materials.rows(
            "select purged_at from material_bake where content_sha256 is not null"
        )
    )
    assert queue.is_purge_complete(materials.connection, tombstone)
    assert tombstone in outcome.completed_tombstones


def test_a_worker_without_the_namespaces_leaves_a_bake_job_and_the_tombstone_open(materials):
    _, container = materials.baked()
    tombstone = materials.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    blind = PurgeWorker(
        materials.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD),
        materials.purged.store,
        frozenset({materials.workspace_id}),
    )
    blind.drain()
    assert materials.in_namespace(container)
    assert not queue.is_purge_complete(materials.connection, tombstone)
    materials.purge_worker().drain()
    assert queue.is_purge_complete(materials.connection, tombstone)


def test_a_capture_tombstone_destroys_only_bakes_of_recipes_that_name_it(materials, photo_dir):
    kept_capture = _second_capture(materials, photo_dir)
    deleted_capture = _capture(materials)
    authored, authored_bytes = materials.baked()
    with materials.photo_derived_allowed():
        doomed = materials.photo_derived([deleted_capture, kept_capture])
        spared = materials.photo_derived([kept_capture])
    materials.repository().request_bake(doomed)
    doomed_bytes = materials.record_synthetic_bake(doomed)
    materials.repository().request_bake(spared)
    spared_bytes = materials.record_synthetic_bake(spared)

    tombstone = materials.purged.tombstone_the_capture(deleted_capture)
    assert materials.blocked(doomed)
    assert not materials.blocked(spared) and not materials.blocked(authored)
    material_jobs = materials.rows(
        "select target_ref from purge_job where tombstone_id = %s and target_kind = "
        "'material_bake'",
        tombstone,
    )
    assert [job["target_ref"] for job in material_jobs] == [
        hashlib.sha256(doomed_bytes).hexdigest()
    ]
    outcome = materials.purge_worker().drain()
    assert (outcome.failed, outcome.skipped) == (0, 0), outcome
    assert not materials.in_namespace(doomed_bytes)
    assert materials.in_namespace(spared_bytes) and materials.in_namespace(authored_bytes)
    assert queue.is_purge_complete(materials.connection, tombstone)
    with pytest.raises(MaterialWithdrawn):
        materials.repository().read_bake(doomed)
    assert materials.repository().read_bake(spared).data == spared_bytes


def _name_a_person(materials, capture: uuid.UUID) -> uuid.UUID:
    connection = materials.purged.repository.connection
    workspace = materials.workspace_id
    span = materials.rows(
        "select s.span_id from evidence_span s join capture c "
        "  on c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256 "
        "where c.capture_id = %s order by s.span_id limit 1",
        capture,
    )[0]["span_id"]
    run_id = materials.rows("select run_id from pipeline_run order by started_at limit 1")[0][
        "run_id"
    ]
    occurrence = connection.execute(
        "insert into occurrence (workspace_id,capture_id,class,primary_span_id,span_ids,presence,"
        "produced_by_run,detector_version,identity_key,emit_key) values "
        "(%s,%s,'person',%s,array[%s]::uuid[],'{[0,1)}'::int8multirange,%s,'test',%s,%s) "
        "returning occurrence_id",
        (workspace, capture, span, span, run_id, uuid.uuid4().bytes * 2, f"person:{uuid.uuid4()}"),
    ).fetchone()
    occurrence_id = occurrence["occurrence_id"] if isinstance(occurrence, dict) else occurrence[0]
    named = name_occurrence(
        IdentityRepository(connection, workspace),
        AssertionWriter(connection, workspace),
        occurrence_id=occurrence_id,
        display_name="A Person",
        actor=uuid.uuid4(),
    )
    return named.entity_id


@pytest.mark.parametrize("named_first", [True, False], ids=["named-then-read", "read-then-named"])
def test_a_person_withdrawal_destroys_bakes_read_from_their_photographs(
    materials, photo_dir, named_first
):
    capture = _capture(materials)
    other_capture = _second_capture(materials, photo_dir)
    person = _name_a_person(materials, capture) if named_first else None
    with materials.photo_derived_allowed():
        theirs = materials.photo_derived([capture])
        others = materials.photo_derived([other_capture])
    if person is None:
        person = _name_a_person(materials, capture)
    dependencies = materials.rows(
        "select target_id from person_derivative_dependency "
        "where entity_id = %s and target_kind = 'material_recipe'",
        person,
    )
    assert [row["target_id"] for row in dependencies] == [theirs]
    for recipe in (theirs, others):
        materials.repository().request_bake(recipe)
    their_bytes = materials.record_synthetic_bake(theirs)
    other_bytes = materials.record_synthetic_bake(others)

    tombstone = materials.purged.repository.insert_tombstone(
        scope="entity", entity_id=person, requested_by=uuid.uuid4(), reason="withdrew"
    )
    assert materials.blocked(theirs) and not materials.blocked(others)
    receipt = materials.rows(
        "select record from person_withdrawal_receipt where tombstone_id = %s", tombstone
    )[0]["record"]
    assert receipt["purge_job_count"] >= 1
    materials.purge_worker().drain()
    assert not materials.in_namespace(their_bytes)
    assert materials.in_namespace(other_bytes)
    assert queue.is_purge_complete(materials.connection, tombstone)


def test_the_purge_role_holds_exactly_the_bake_privileges_it_needs(materials):
    columns = materials.rows(
        "select privilege_type, column_name from information_schema.column_privileges "
        "where grantee = %s and table_schema = current_schema() and table_name = 'material_bake' "
        "order by privilege_type, column_name",
        _PURGE_ROLE,
    )
    assert [(row["privilege_type"], row["column_name"]) for row in columns] == [
        ("SELECT", "content_sha256"),
        ("SELECT", "purged_at"),
        ("SELECT", "workspace_id"),
        ("UPDATE", "purged_at"),
    ]
    tables = materials.rows(
        "select table_name, privilege_type from information_schema.table_privileges "
        "where grantee = %s and table_schema = current_schema() and table_name like 'material%%'",
        _PURGE_ROLE,
    )
    assert tables == []
    executable = materials.rows(
        "select has_function_privilege(%s, "
        "  'material_bake_purge_is_authorized(uuid,uuid,bytea)', 'execute') as allowed",
        _PURGE_ROLE,
    )[0]["allowed"]
    assert executable
    public = materials.rows(
        "select has_function_privilege('public', "
        "  'material_bake_purge_is_authorized(uuid,uuid,bytea)', 'execute') as allowed"
    )[0]["allowed"]
    assert not public
    # Reprovisioning is idempotent and grants nothing wider.
    with materials.owner.unscoped() as admin:
        admin.execute(f"set search_path to {materials.purged.scratch}, public")
        provision_purge_role(admin, role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    assert (
        materials.rows(
            "select count(*) as n from information_schema.column_privileges "
            "where grantee = %s and table_schema = current_schema() "
            "  and table_name = 'material_bake'",
            _PURGE_ROLE,
        )[0]["n"]
        == 4
    )


def test_the_destroy_question_refuses_a_bake_its_tombstone_does_not_reach(materials):
    _, container = materials.baked()
    capture_tombstone = materials.purged.tombstone_the_capture(_capture(materials))
    digest = hashlib.sha256(container).digest()
    assert not materials.rows(
        "select material_bake_purge_is_authorized(%s, %s, %s) as allowed",
        materials.workspace_id,
        capture_tombstone,
        digest,
    )[0]["allowed"]
    # A forged job for an authored bake under a capture tombstone is never claimed.
    materials.connection.execute(
        "insert into purge_job (tombstone_id, workspace_id, target_kind, target_ref) "
        "values (%s, %s, 'material_bake', %s)",
        (capture_tombstone, materials.workspace_id, digest.hex()),
    )
    materials.purge_worker().drain()
    assert materials.in_namespace(container)
    other = uuid.uuid4()
    with materials.owner.session(other) as foreign:
        assert not foreign.execute(
            "select material_bake_purge_is_authorized(%s, %s, %s) as allowed",
            (materials.workspace_id, capture_tombstone, digest),
        ).fetchone()["allowed"]


def test_restore_replays_a_bake_s_purge_over_restored_bytes(materials, tmp_path):
    _, container = materials.baked()
    materials.purged.repository.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    purge_database = materials.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    PurgeWorker(
        purge_database,
        materials.purged.store,
        frozenset({materials.workspace_id}),
        material_stores=materials.stores,
    ).drain()
    assert not materials.in_namespace(container)
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(materials.owner, source)
    prepare_restore(source, marker)
    # An object-store backup older than the deletion brings the bytes back.
    materials.stores.for_workspace(materials.workspace_id).put_bytes(container)
    with pytest.raises(RestoreRefused, match="no material store"):
        replay(materials.owner, purge_database, materials.purged.store, source, marker)
    replay(
        materials.owner,
        purge_database,
        materials.purged.store,
        source,
        marker,
        materials=materials.stores,
    )
    assert not materials.in_namespace(container)
    assert len(materials.rows("select * from restore_replay_receipt")) == 1


# -- redistribution paths that need a database -------------------------------------------------


def test_a_judge_seed_refuses_a_workspace_holding_private_bakes(materials, tmp_path):
    from exulanica.orchestration.judge_seed import SeedRefused, export_seed

    materials.baked()
    with pytest.raises(SeedRefused, match="LicenseRef-Exulanica-Workspace-Private"):
        export_seed(
            materials.connection,
            materials.purged.store,
            workspace_id=materials.workspace_id,
            destination=tmp_path / "seed",
            created_at="2026-09-16T00:00:00Z",
        )
    assert not (tmp_path / "seed").exists()


@pytest.mark.parametrize("table", ["world_reviewed_asset", "world_texture_set"])
def test_the_global_registries_refuse_a_private_licence(materials, table):
    """The two catalogs anything may serve across workspaces hold CC0 bytes and nothing else."""
    with pytest.raises(psycopg.errors.CheckViolation, match="licence_id"):
        if table == "world_reviewed_asset":
            materials.connection.execute(
                "insert into world_reviewed_asset (asset_key, title, summary, media_type, "
                "  content_sha256, byte_size, licence_id, licence_sha256) values "
                "('ws.private', 'Private', 'Private', 'model/gltf-binary', %s, 1, %s, %s)",
                ("1" * 64, WORKSPACE_LICENCE_ID, WORKSPACE_LICENCE_SHA256),
            )
        else:
            materials.connection.execute(
                "insert into world_texture_set (set_id, version, title, summary, media_type, "
                "  truth, content_sha256, byte_size, width, height, extent_u_mm, extent_v_mm, "
                "  channels, licence_id, licence_sha256) values "
                "('ws.private', 1, 'Private', 'Private', 'application/vnd.exulanica.texture-set', "
                "  'invented', %s, 1, 16, 16, 1000, 1000, '[]'::jsonb, %s, %s)",
                ("1" * 64, WORKSPACE_LICENCE_ID, WORKSPACE_LICENCE_SHA256),
            )


# -- lock order --------------------------------------------------------------------------------


def _rows_free(connection, workspace_id: uuid.UUID) -> bool:
    """Whether every recipe and bake row of the workspace can be locked here without waiting."""
    try:
        with connection.transaction():
            for table in ("material_recipe", "material_bake"):
                connection.execute(
                    f"select 1 from {table} where workspace_id = %s for update nowait",
                    (workspace_id,),
                ).fetchall()
    except psycopg.errors.LockNotAvailable:
        return False
    return True


def _holding_the_lifecycle_lock(materials, work, write=None):
    """Run ``work`` on another thread while this connection holds the workspace's lifecycle lock.

    A tombstone takes that lock and then updates bake rows. So while it is held here, the other
    thread must be waiting on the lock itself, holding no row, and that is asked directly: this
    connection locks every recipe and bake row of the workspace without waiting. Only then does it
    write, by default what a tombstone writes next, or ``write``. Taking a row first and the
    lifecycle lock second, the order a bare guard would give, deadlocks here, and every writer
    retries past a deadlock, so a test that looked only at the outcome would pass the wrong order.
    The wait is observed on the other thread's own backend, so another session on a shared server
    cannot stand in for it, and it is given as long as a loaded machine needs.
    """
    import threading
    import time

    outcome: dict[str, object] = {}
    started = threading.Event()

    def run() -> None:
        with materials.owner.session(materials.workspace_id) as connection:
            outcome["pid"] = connection.info.backend_pid
            started.set()
            try:
                outcome["value"] = work(connection)
            except Exception as error:  # the assertion below names it
                outcome["error"] = error

    with materials.owner.session(materials.workspace_id) as holder:
        holder.execute("set lock_timeout = '30s'")
        with holder.transaction():
            holder.execute("select material_bake_lifecycle_lock(%s)", (materials.workspace_id,))
            thread = threading.Thread(target=run)
            thread.start()
            assert started.wait(timeout=30), "the other thread never connected"
            deadline = time.monotonic() + 30
            waiting = 0
            while not waiting and time.monotonic() < deadline:
                waiting = holder.execute(
                    "select count(*) as n from pg_locks "
                    "where pid = %s and locktype = 'advisory' and not granted",
                    (outcome["pid"],),
                ).fetchone()["n"]
                if not waiting:
                    time.sleep(0.02)
            assert waiting, "the other thread never waited on the lifecycle lock"
            free = _rows_free(holder, materials.workspace_id)
            # Writing past a row the other thread holds would deadlock; the assertion below names
            # the order instead.
            if free and write is not None:
                write(holder)
            elif free:
                holder.execute(
                    "update material_bake set state = 'cancelled', claim_token = null, "
                    "  claimed_by = null, lease_expires_at = null, failure_class = 'withdrawn' "
                    "where workspace_id = %s and state in ('requested', 'running', 'failed')",
                    (materials.workspace_id,),
                )
        thread.join(timeout=30)
    assert not thread.is_alive()
    assert free, "the other thread locked a row before it waited for the lifecycle lock"
    outcome.pop("pid")
    return outcome


def test_a_bake_request_waits_for_a_deletion_before_it_locks_a_bake(materials):
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    worker = materials.worker()
    claim = worker._claim(materials.connection, materials.workspace_id)
    assert worker._finish_failed(
        materials.connection, materials.workspace_id, claim, _Failed("bake_failed", "test")
    )
    outcome = _holding_the_lifecycle_lock(
        materials,
        lambda connection: materials.repository(connection).request_bake(record.recipe_id),
    )
    assert isinstance(outcome.get("error"), MaterialWithdrawn), outcome
    assert materials.rows("select state from material_bake")[0]["state"] == "cancelled"


def test_a_claim_waits_for_a_deletion_before_it_locks_a_bake(materials):
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    worker = materials.worker()
    outcome = _holding_the_lifecycle_lock(
        materials, lambda connection: worker._claim(connection, materials.workspace_id)
    )
    assert outcome == {"value": None}, outcome
    assert materials.rows("select state from material_bake")[0]["state"] == "cancelled"


def test_a_withdrawal_waits_for_the_lifecycle_lock_before_it_reads_the_recipe(materials):
    """Two withdrawals at once answer as two in turn: the second finds the recipe withdrawn.

    A withdrawal locks no row, so what holds it to the order is when it reads the recipe. Read
    before the lock, the recipe is still live, and the second withdrawal's row meets the first's
    and says nothing.
    """
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    outcome = _holding_the_lifecycle_lock(
        materials,
        lambda connection: materials.repository(connection).withdraw_recipe(record.recipe_id),
        write=lambda holder: materials.repository(holder).withdraw_recipe(record.recipe_id),
    )
    assert isinstance(outcome.get("error"), MaterialWithdrawn), outcome
    assert materials.rows("select count(*) as n from material_recipe_withdrawal")[0]["n"] == 1
    assert materials.rows("select state from material_bake")[0]["state"] == "cancelled"


# -- what the review of this migration found -------------------------------------------------------


@pytest.mark.parametrize("scope", ["workspace", "capture"])
def test_restore_finishes_when_the_restored_database_predates_the_bake(materials, tmp_path, scope):
    """A Monday database, a Tuesday bake, a Wednesday deletion: the bytes still go."""
    if scope == "workspace":
        _, container = materials.baked()
    else:
        with materials.photo_derived_allowed():
            recipe_id = materials.photo_derived([_capture(materials)])
        materials.repository().request_bake(recipe_id)
        container = materials.record_synthetic_bake(recipe_id)
    if scope == "workspace":
        materials.purged.repository.insert_tombstone(
            scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
        )
    else:
        materials.purged.tombstone_the_capture(_capture(materials))
    purge_database = materials.purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    materials.purge_worker().drain()
    assert not materials.in_namespace(container)
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(materials.owner, source)
    prepare_restore(source, marker)
    materials.stores.for_workspace(materials.workspace_id).put_bytes(container)
    materials.forget_bakes()
    replay(
        materials.owner,
        purge_database,
        materials.purged.store,
        source,
        marker,
        materials=materials.stores,
    )
    assert not materials.in_namespace(container)
    assert len(materials.rows("select * from restore_replay_receipt")) == 1


def test_a_bake_being_written_is_waited_for_and_never_re_requested(materials):
    import threading
    import time

    from exulanica.canonical import canonical_json

    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    worker = materials.worker()
    claim = worker._claim(materials.connection, materials.workspace_id)
    container = b"bytes the worker has recorded and not yet written"
    digest = hashlib.sha256(container).digest()
    raw_receipt = canonical_json(materials.receipt(record.recipe_id, container))
    outcome: dict[str, object] = {}
    with materials.owner.session(materials.workspace_id) as writer:
        writer.execute("select pg_advisory_lock(hashtextextended(%s, 0))", (digest.hex(),))
        assert worker._record(writer, materials.workspace_id, claim, digest, container, raw_receipt)
        # Recorded and not written: asking again must not queue it, and reading must wait.
        assert materials.repository().request_bake(record.recipe_id).state == "baked"
        assert materials.rows("select count(*) as n from material_bake_request")[0]["n"] == 1

        def read() -> None:
            with materials.owner.session(materials.workspace_id) as reader:
                outcome["pid"] = reader.info.backend_pid
                try:
                    outcome["data"] = materials.repository(reader).read_bake(record.recipe_id).data
                except Exception as error:  # the assertion below names it
                    outcome["error"] = error

        thread = threading.Thread(target=read)
        thread.start()
        deadline = time.monotonic() + 30
        waiting = 0
        while not waiting and time.monotonic() < deadline:
            if "pid" in outcome:
                waiting = writer.execute(
                    "select count(*) as n from pg_locks "
                    "where pid = %s and locktype = 'advisory' and not granted",
                    (outcome["pid"],),
                ).fetchone()["n"]
            if not waiting:
                time.sleep(0.02)
        assert waiting, outcome
        materials.stores.for_workspace(materials.workspace_id).put_bytes(container)
        writer.execute("select pg_advisory_unlock(hashtextextended(%s, 0))", (digest.hex(),))
        thread.join(timeout=30)
    assert outcome.get("data") == container, outcome


def _fake_node(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    fake = directory / "node"
    fake.write_text("#!/bin/sh\n" + body, encoding="ascii")
    fake.chmod(0o755)
    return fake


@pytest.mark.parametrize(
    ("status", "failure_class", "stored"),
    [
        (1, "bake_failed", "the baker exited 1"),
        (2, "invalid_recipe", "the baker refused the request: at /srv/secret"),
    ],
)
def test_what_the_baker_prints_never_reaches_the_workspace_verbatim(
    materials, tmp_path, status, failure_class, stored
):
    runtime = _real_runtime()
    record = materials.repository().create_recipe(_small())
    materials.repository().request_bake(record.recipe_id)
    fake = _fake_node(
        tmp_path / f"node-{status}",
        f"printf 'at /srv/secret\\001\\303\\251\\n' >&2\nexit {status}\n",
    )
    lying = BakeRuntime(node=fake, loader=runtime.loader, package=runtime.package)
    outcome = materials.worker(lying).drain()
    assert outcome.failed == 1, outcome
    row = materials.rows("select failure_class, failure_message from material_bake")[0]
    assert (row["failure_class"], row["failure_message"]) == (failure_class, stored)
    assert all(" " <= character <= "~" for character in row["failure_message"])


def test_a_pass_serves_workspaces_in_turn_and_outlives_one_that_breaks(materials, monkeypatch):
    other = uuid.uuid4()
    with materials.owner.session(other) as connection:
        foreign = MaterialRepository(
            connection, other, uuid.uuid4(), catalog=CATALOG, stores=materials.stores
        )
        for seed in (1, 2):
            foreign.request_bake(foreign.create_recipe(_small(seed=seed)).recipe_id)
    for seed in (3, 4):
        repository = materials.repository()
        repository.request_bake(repository.create_recipe(_small(seed=seed)).recipe_id)
    seen: list[uuid.UUID] = []
    broken: set[uuid.UUID] = set()

    def stub(self, connection, workspace_id, claim, outcome):
        seen.append(workspace_id)
        if workspace_id in broken:
            raise RuntimeError("a bake that breaks unexpectedly")
        self._finish_failed(connection, workspace_id, claim, _Failed("bake_failed", "stub"))
        outcome.failed += 1

    monkeypatch.setattr(MaterialBakeWorker, "_bake_one", stub)
    both = frozenset({materials.workspace_id, other})
    runtime = BakeRuntime(Path("/absent/node"), Path("/absent"), Path("/absent"))
    worker = MaterialBakeWorker(
        materials.owner,
        materials.stores,
        both,
        runtime=runtime,
        catalog=CATALOG,
        limit_per_pass=2,
    )
    worker.drain()
    assert sorted(seen) == sorted(both), "one bake from each workspace, not two from the first"

    seen.clear()
    broken.add(min(both))
    outcome = worker.drain()
    assert seen == [min(both), max(both)]
    assert outcome.failed == 1 and len(outcome.errors) == 1
    assert "a bake that breaks unexpectedly" in outcome.errors[0]


def _read_only_database(materials):
    import secrets

    from exulanica.orchestration.judge_seed import provision_judge_role

    role, password = "exulanica_judge_materials", secrets.token_urlsafe(24)
    with materials.owner.unscoped() as admin:
        admin.execute(f"set search_path to {materials.purged.scratch}, public")
        provision_judge_role(admin, role=role, password=password)
    return materials.purged.database(role=role, password=password)


def test_a_read_only_deployment_refuses_material_writes_by_name(materials):
    materials.repository().create_recipe(_small())
    with _read_only_database(materials).session(materials.workspace_id) as connection:
        repository = materials.repository(connection)
        [existing] = repository.recipes()
        for write in (
            lambda: repository.create_recipe(_small(seed=11)),
            lambda: repository.request_bake(existing.recipe_id),
            lambda: repository.withdraw_recipe(existing.recipe_id),
        ):
            with pytest.raises(MaterialReadOnly):
                write()
    assert materials.rows("select count(*) as n from material_recipe")[0]["n"] == 1


def test_the_runtime_role_makes_every_material_write_the_product_makes(materials):
    """Recipes, bake requests, claims, records, failures and withdrawals, as the provisioned writer.

    Every other material test writes as the database owner, who holds every privilege, so none of
    them would notice provisioning take away one the product needs. The writer may only append
    recipes, their sources and withdrawals, and bake requests. This takes every path the product
    takes on those tables and on bakes, as that writer, ending with a deletion whose trigger reads
    recipes and the photographs they name to find the bakes it reaches.
    """
    capture = _capture(materials)
    worker = materials.worker()
    app = materials.purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with app.session(materials.workspace_id) as runtime:
        assert runtime.execute("select current_user as role").fetchone()["role"] == _APP_ROLE
        for table in (
            "material_recipe",
            "material_recipe_source",
            "material_recipe_withdrawal",
            "material_bake_request",
        ):
            held = runtime.execute(
                "select has_table_privilege(%s, 'INSERT') as appends, "
                "  has_table_privilege(%s, 'UPDATE') as updates",
                (table, table),
            ).fetchone()
            assert (held["appends"], held["updates"]) == (True, False), table
        repository = materials.repository(runtime)

        kept = repository.create_recipe(_small())
        assert repository.request_bake(kept.recipe_id).state == "requested"
        claim = worker._claim(runtime, materials.workspace_id)
        assert claim is not None and claim.recipe_id == kept.recipe_id
        assert worker._finish_failed(
            runtime, materials.workspace_id, claim, _Failed("bake_failed", "test")
        )
        assert repository.request_bake(kept.recipe_id).state == "requested"
        claim = worker._claim(runtime, materials.workspace_id)
        assert claim is not None
        container = b"synthetic container for " + kept.recipe_id.bytes
        assert worker._record_and_write(
            runtime,
            materials.workspace_id,
            claim,
            container,
            materials.receipt(kept.recipe_id, container),
        )
        assert repository.read_bake(kept.recipe_id).data == container

        waiting = repository.create_recipe(_small(seed=5))
        repository.request_bake(waiting.recipe_id)
        repository.withdraw_recipe(waiting.recipe_id)
        repository.withdraw_recipe(kept.recipe_id)
        assert repository.recipes() == []

        IngestRepository(runtime, materials.workspace_id).insert_tombstone(
            scope="capture",
            capture_id=capture,
            requested_by=materials.actor,
            reason="the person deleted this photograph",
        )

    bakes = {
        row["recipe_id"]: row["state"]
        for row in materials.rows("select recipe_id, state from material_bake")
    }
    assert bakes == {kept.recipe_id: "baked", waiting.recipe_id: "cancelled"}
    assert materials.rows("select count(*) as n from material_bake_request")[0]["n"] == 3
    assert materials.rows("select count(*) as n from material_recipe_withdrawal")[0]["n"] == 2
    assert (
        materials.rows("select purge_id from purge_job where target_kind = 'material_bake'") == []
    ), "both recipes were authored, so a photograph's deletion reaches neither bake"
