"""Actual PostgreSQL persistence, concurrency, immutable history and current authority."""

import concurrent.futures
import threading
import uuid

import psycopg
import pytest
from exulanica.world.character_appearance import (
    AppearanceUnavailable,
    CharacterSubject,
    StaleAppearance,
)
from exulanica.world.character_appearance_repository import CharacterAppearanceRepository
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society_repository import SocietyRepository

from character_appearance_fixtures import family, recipe
from test_world_objects_postgres import another_connection
from test_world_objects_postgres import world as world

pytestmark = pytest.mark.postgres


@pytest.fixture
def appearance(world, repository):
    objects, snapshot, _ = world
    actor = uuid.uuid4()
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Appearance test", created_by=actor
    )
    repo = CharacterAppearanceRepository(
        repository.connection,
        repository.workspace_id,
        actor,
        families=(family(),),
        authorize_family=lambda definition: True,
    )
    subject = CharacterSubject(kind="avatar", subject_id=actor)
    repository.connection.commit()
    return repo, version.version_id, subject, objects


def test_save_reopen_reset_and_history_are_durable(appearance, spine_schema):
    repo, version, subject, _ = appearance
    assert repo.read(version, subject) == {"revision": 0, "current": None}
    first = repo.save(
        version,
        subject,
        recipe(parameters={"height": 185, "clothing": "coat", "color": "#123456"}),
        base_revision=0,
    )
    assert first["current"]["render_status"] == "no_prepared_representation"
    assert first["current"]["generation_status"] == "not_requested"
    with another_connection(spine_schema, repo.workspace_id) as connection:
        reopened = CharacterAppearanceRepository(
            connection,
            repo.workspace_id,
            repo.actor,
            families=(family(),),
            authorize_family=lambda definition: True,
        )
        assert reopened.read(version, subject) == first
        default = reopened.reset(version, subject, base_revision=1)
        assert default["current"]["document"]["recipe"]["parameters"]["height"] == 175
        restored = reopened.reset(version, subject, base_revision=2, restore_revision=1)
        assert restored["current"]["document"] == first["current"]["document"]
        assert restored["current"]["restored_from_revision"] == 1
        assert [r["revision"] for r in reopened.history(version, subject)] == [3, 2, 1]
        assert [
            r["revision"] for r in reopened.history(version, subject, before_revision=3, limit=1)
        ] == [2]
    with pytest.raises(StaleAppearance):
        repo.save(version, subject, recipe(), base_revision=1)
    assert repo.read(version, subject)["revision"] == 3


def test_concurrent_first_save_has_one_winner(appearance, spine_schema):
    repo, version, subject, _ = appearance
    barrier = threading.Barrier(2)

    def save(height):
        with another_connection(spine_schema, repo.workspace_id) as conn:
            writer = CharacterAppearanceRepository(
                conn,
                repo.workspace_id,
                repo.actor,
                families=(family(),),
                authorize_family=lambda definition: True,
            )
            barrier.wait(timeout=5)
            try:
                return writer.save(
                    version,
                    subject,
                    recipe(parameters={"height": height, "clothing": "coat", "color": "#123456"}),
                    base_revision=0,
                )["revision"]
            except StaleAppearance:
                return "stale"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, (180, 190)))
    assert sorted(results, key=str) == [1, "stale"]
    assert len(repo.history(version, subject)) == 1


def test_actor_workspace_and_version_are_not_interchangeable(appearance, spine_schema):
    repo, version, subject, objects = appearance
    original = repo.save(version, subject, recipe(), base_revision=0)
    other = objects.create_version(
        parent_version_id=version, title="Independent branch", created_by=repo.actor
    )
    repo.connection.commit()
    assert repo.read(other.version_id, subject)["revision"] == 0
    repo.save(
        other.version_id,
        subject,
        recipe(parameters={"height": 190, "clothing": "coat", "color": "#123456"}),
        base_revision=0,
    )
    assert repo.read(version, subject) == original
    stranger = CharacterSubject(kind="avatar", subject_id=uuid.uuid4())
    for action in (
        lambda: repo.read(version, stranger),
        lambda: repo.save(version, stranger, recipe(), base_revision=0),
        lambda: repo.history(version, stranger),
        lambda: repo.reset(version, stranger, base_revision=1),
    ):
        with pytest.raises(UnknownWorldResource):
            action()
    with another_connection(spine_schema, uuid.uuid4()) as conn:
        alien = CharacterAppearanceRepository(
            conn, uuid.uuid4(), repo.actor, families=(family(),), authorize_family=lambda f: True
        )
        with pytest.raises(UnknownWorldResource):
            alien.read(version, subject)


def test_family_withdrawal_preserves_record_but_disables_new_use(appearance):
    repo, version, subject, _ = appearance
    original = repo.save(version, subject, recipe(), base_revision=0)
    repo.authorize_family = lambda f: False
    held = repo.read(version, subject)
    assert held["current"]["document"] == original["current"]["document"]
    assert held["current"]["render_status"] == "family_source_unavailable"
    assert repo.available_families(version, subject) == []
    for action in (
        lambda: repo.save(version, subject, recipe(), base_revision=1),
        lambda: repo.reset(version, subject, base_revision=1),
    ):
        with pytest.raises(AppearanceUnavailable):
            action()
    repo.authorize_family = lambda f: True
    repo.families = {family(family_revision="2").sha256: family(family_revision="2")}
    assert repo.read(version, subject)["current"]["render_status"] == "family_source_unavailable"
    assert repo.history(version, subject)[0]["document"] == original["current"]["document"]


def test_synthetic_subject_uses_existing_population_and_never_rewrites_society(appearance):
    repo, version, _, _ = appearance
    place = uuid.uuid4()
    repo.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (repo.workspace_id, place)
    )
    society = SocietyRepository(repo.connection, repo.workspace_id)
    original = society.create(
        version, place_id=place, region_id="region-a", seed="7a" * 32, actor=repo.actor
    )
    repo.connection.commit()
    subject = CharacterSubject(
        kind="synthetic-inhabitant",
        society_id=original["society_id"],
        subject_id=original["state"]["inhabitants"][0]["id"],
    )
    repo.save(version, subject, recipe(), base_revision=0)
    repo.reset(version, subject, base_revision=1)
    assert society.snapshot(version) == original
    assert society.events(version) == ()
    repo.connection.commit()
    invented = subject.model_copy(update={"subject_id": uuid.uuid4()})
    with pytest.raises(UnknownWorldResource):
        repo.read(version, invented)
    repo.actor = uuid.uuid4()
    with pytest.raises(UnknownWorldResource):
        repo.read(version, subject)
    repo.actor = original["created_by"]
    # Remove presence from current canonical state (test-only administrative mutation).
    from psycopg.types.json import Jsonb

    state = dict(original["state"])
    state["inhabitants"] = state["inhabitants"][1:]
    repo.connection.execute(
        "update world_society set state=%s where workspace_id=%s and society_id=%s",
        (Jsonb(state), repo.workspace_id, original["society_id"]),
    )
    repo.connection.commit()
    with pytest.raises(UnknownWorldResource):
        repo.read(version, subject)


def test_database_refuses_history_rewrite_and_revision_gap(appearance):
    repo, version, subject, _ = appearance
    repo.save(version, subject, recipe(), base_revision=0)
    for statement in (
        "update world_character_appearance_revision set operation='reset'",
        "delete from world_character_appearance_revision",
    ):
        with pytest.raises(psycopg.errors.CheckViolation), repo.connection.transaction():
            repo.connection.execute(statement)
    with pytest.raises(psycopg.errors.CheckViolation), repo.connection.transaction():
        repo.connection.execute(
            "insert into world_character_appearance_revision "
            "select workspace_id,world_id,version_id,subject_kind,subject_id,society_id,"
            "3,operation,restored_from_revision,document,document_sha256,created_by,created_at "
            "from world_character_appearance_revision"
        )
    assert repo.read(version, subject)["revision"] == 1


def test_prepared_asset_missing_or_withdrawn_does_not_erase_recipe(appearance, tmp_path):
    import json
    import struct

    from exulanica.store.local import LocalContentAddressedStore
    from exulanica.world.asset_import import ReviewedAssetImport, import_reviewed_asset
    from exulanica.world.character_appearance import RepresentationBinding

    from character_appearance_fixtures import sha

    repo, version, subject, _ = appearance
    store = LocalContentAddressedStore(tmp_path / "reviewed-test-assets")
    doc = json.dumps({"asset": {"version": "2.0", "generator": "explicit-test-fixture"}}).encode()
    doc += b" " * (-len(doc) % 4)
    payload = struct.pack("<IIIII", 0x46546C67, 2, 20 + len(doc), len(doc), 0x4E4F534A) + doc
    licence = b"CC0 synthetic test fixture license"
    manifest = ReviewedAssetImport(
        profile="exulanica.reviewed-asset-import/v1",
        asset_key="test.character",
        title="Test-only prepared asset",
        summary="Container authority test, not rig quality evidence",
        content_sha256=sha(payload),
        byte_size=len(payload),
        licence_id="CC0-1.0",
        licence_sha256=sha(licence),
        source_url="https://example.invalid/test-only",
        source_revision="1",
        producer="test",
    )
    with repo.connection.transaction():
        receipt_sha = import_reviewed_asset(repo.connection, store, manifest, payload, licence)
    preparation = store.put_bytes(b"explicit test preparation receipt")
    binding = RepresentationBinding(
        binding_id="prepared-test",
        recipe_input_sha256=recipe().input_sha256,
        asset=dict(
            asset_key=manifest.asset_key,
            content_sha256=manifest.content_sha256,
            receipt_sha256=receipt_sha,
            byte_size=len(payload),
        ),
        rig_id="test-rig",
        rig_revision="1",
        rig_sha256="1" * 64,
        producer="test",
        producer_revision="1",
        preparation_receipt_sha256=preparation.blob_id.hex,
    )
    definition = family(representations=[binding])
    repo.families = {definition.sha256: definition}
    repo.store = store
    bound = recipe(definition, representation_id=binding.binding_id)
    first = repo.save(version, subject, bound, base_revision=0)
    assert first["current"]["render_status"] == "available"
    # Even a configured binding must not label edited input as already generated.
    with pytest.raises(ValueError):
        repo.save(
            version,
            subject,
            recipe(
                definition,
                representation_id=binding.binding_id,
                parameters={"height": 190, "clothing": "shirt", "color": "#eeeeee"},
            ),
            base_revision=1,
        )
    repo.store = LocalContentAddressedStore(tmp_path / "empty-assets")
    assert repo.read(version, subject)["current"]["render_status"] == "asset_bytes_unavailable"
    saved_without_bytes = repo.save(version, subject, bound, base_revision=1)
    assert saved_without_bytes["current"]["document"] == first["current"]["document"]
    repo.store = store
    # Administrative registry withdrawal; receipt and bytes deliberately retained.
    repo.connection.execute(
        "delete from world_reviewed_asset where asset_key=%s", (manifest.asset_key,)
    )
    repo.connection.commit()
    held = repo.read(version, subject)
    assert held["current"]["render_status"] == "asset_withdrawn_or_unreviewed"
    assert held["current"]["document"] == first["current"]["document"]
    assert store.exists(preparation.blob_id)


def test_source_tombstone_denies_subject_without_erasing_history(repository, tmp_path, photo_dir):
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore
    from exulanica.world.object_repository import WorldObjectRepository
    from exulanica.world.structure_repository import WorldStructureRepository

    from conftest import write_photo
    from test_world_objects_postgres import apply_candidate
    from world_structure_fixtures import structural_candidate

    structures = WorldStructureRepository(repository.connection, repository.workspace_id)
    apply_candidate(structures, structural_candidate())
    outcome = PhotoIngestPipeline(
        repository, LocalContentAddressedStore(tmp_path / "sources"), vision=None
    ).ingest_file(write_photo(photo_dir, "appearance-source.jpg"))
    assert outcome.error is None
    evidence = repository.connection.execute(
        "select s.span_id,c.capture_id from evidence_span s join capture c "
        "on c.workspace_id=s.workspace_id and c.blob_sha256=s.blob_sha256 "
        "where s.workspace_id=%s limit 1",
        (repository.workspace_id,),
    ).fetchone()
    snapshot = apply_candidate(
        structures,
        structural_candidate(graph="appearance-source", evidence_span_id=evidence["span_id"]),
    )
    actor = uuid.uuid4()
    version = WorldObjectRepository(repository.connection, repository.workspace_id).create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Source-bound avatar", created_by=actor
    )
    repo = CharacterAppearanceRepository(
        repository.connection,
        repository.workspace_id,
        actor,
        families=(family(),),
        authorize_family=lambda f: True,
    )
    subject = CharacterSubject(kind="avatar", subject_id=actor)
    repo.save(version.version_id, subject, recipe(), base_revision=0)
    repository.insert_tombstone(
        scope="capture",
        capture_id=evidence["capture_id"],
        requested_by=actor,
        reason="test source withdrawal",
    )
    repository.connection.commit()
    for operation in (
        lambda: repo.read(version.version_id, subject),
        lambda: repo.history(version.version_id, subject),
        lambda: repo.save(version.version_id, subject, recipe(), base_revision=1),
    ):
        with pytest.raises(AppearanceUnavailable):
            operation()
    assert (
        repository.connection.execute(
            "select count(*) n from world_character_appearance_revision"
        ).fetchone()["n"]
        == 1
    )
    repository.connection.commit()


def test_non_owner_role_cannot_read_another_workspace(appearance):
    from exulanica.db.roles import provision_runtime_role
    from psycopg import sql

    repo, version, subject, _ = appearance
    repo.save(version, subject, recipe(), base_revision=0)
    role = "appearance_test_" + uuid.uuid4().hex[:16]
    conn = repo.connection
    # Transaction rollback removes this test role and its scratch-only grants.
    try:
        conn.execute("begin")
        provision_runtime_role(conn, role=role)
        conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
        assert (
            conn.execute("select count(*) n from world_character_appearance_revision").fetchone()[
                "n"
            ]
            == 1
        )
        conn.execute("select set_config('exulanica.workspace_id',%s,true)", (str(uuid.uuid4()),))
        assert (
            conn.execute("select count(*) n from world_character_appearance_revision").fetchone()[
                "n"
            ]
            == 0
        )
    finally:
        conn.rollback()


def test_current_v2_source_authority_is_required_for_every_subject_operation(appearance):
    from exulanica.world.society import UnavailableSocietyInput

    from society_fixtures import SEED, society_input

    repo, version, _, _ = appearance
    place = uuid.uuid4()
    repo.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)", (repo.workspace_id, place)
    )
    current = {"allowed": True}

    def authorize(document):
        if not current["allowed"]:
            raise UnavailableSocietyInput("test source withdrawn")

    societies = SocietyRepository(repo.connection, repo.workspace_id, input_authorizer=authorize)
    snapshot = societies.create(
        version,
        place_id=place,
        region_id="region-a",
        seed=SEED,
        actor=repo.actor,
        profile="exulanica-society/v2",
        initial_input=society_input(version),
    )
    repo.connection.commit()
    repo.societies = societies
    subject = CharacterSubject(
        kind="synthetic-inhabitant",
        society_id=snapshot["society_id"],
        subject_id=snapshot["state"]["inhabitants"][0]["id"],
    )
    repo.save(version, subject, recipe(), base_revision=0)
    state_before = societies.snapshot(version)
    event_before = societies.events(version)
    repo.connection.commit()
    repo.reset(version, subject, base_revision=1)
    assert societies.snapshot(version) == state_before
    assert societies.events(version) == event_before
    repo.connection.commit()
    current["allowed"] = False
    for operation in (
        lambda: repo.read(version, subject),
        lambda: repo.history(version, subject),
        lambda: repo.available_families(version, subject),
        lambda: repo.save(version, subject, recipe(), base_revision=2),
        lambda: repo.reset(version, subject, base_revision=2),
    ):
        with pytest.raises(UnavailableSocietyInput):
            operation()
    assert (
        repo.connection.execute(
            "select count(*) n from world_character_appearance_revision"
        ).fetchone()["n"]
        == 2
    )
    repo.connection.commit()


def test_catalog_look_saves_resets_and_reports_its_published_containers(appearance, tmp_path):
    import sys
    from pathlib import Path

    from exulanica.store.local import LocalContentAddressedStore
    from exulanica.world.asset_import import import_reviewed_asset
    from exulanica.world.character_appearance import (
        CharacterRecipe,
        catalog_recipe_families,
        designed_looks,
        load_character_catalog,
        look_containers,
        look_from_recipe,
        recipe_from_look,
    )

    sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
    import prepare_character_people as people

    repo, version, subject, _ = appearance
    catalog, looks = load_character_catalog()
    feminine, masculine = catalog_recipe_families(catalog, looks)
    designed = designed_looks(catalog, looks)
    repo.families = {family.sha256: family for family in (feminine, masculine)}
    store = LocalContentAddressedStore(tmp_path / "character-assets")
    repo.store = store

    athletic = designed["athletic-feminine"]["look"]
    saved = repo.save(version, subject, recipe_from_look(athletic, feminine), base_revision=0)
    assert saved["current"]["render_status"] == "catalog_unavailable"
    repo.catalog = catalog
    assert repo.read(version, subject)["current"]["render_status"] == (
        "asset_withdrawn_or_unreviewed"
    )

    needed = {ref["assetKey"] for ref in look_containers(catalog, athletic)}
    assert 10 <= len(needed) <= 14
    imports = [entry for entry in people.catalog_imports(catalog) if entry[0].asset_key in needed]
    with repo.connection.transaction():
        for manifest, payload, licence in imports[:-1]:
            import_reviewed_asset(repo.connection, store, manifest, payload, licence)
    assert repo.read(version, subject)["current"]["render_status"] == (
        "asset_withdrawn_or_unreviewed"
    )
    with repo.connection.transaction():
        import_reviewed_asset(repo.connection, store, *imports[-1])
    current = repo.read(version, subject)["current"]
    assert current["render_status"] == "available"
    assert (
        look_from_recipe(
            catalog, CharacterRecipe.model_validate(current["document"]["recipe"]), feminine
        )
        == athletic
    )
    repo.store = LocalContentAddressedStore(tmp_path / "empty-assets")
    assert repo.read(version, subject)["current"]["render_status"] == "asset_bytes_unavailable"
    repo.store = store

    # Changing the body is choosing the other body's family; reset returns that body's default.
    suit = designed["suit-masculine"]["look"]
    changed = repo.save(version, subject, recipe_from_look(suit, masculine), base_revision=1)
    assert changed["current"]["render_status"] == "asset_withdrawn_or_unreviewed"
    reset = repo.reset(version, subject, base_revision=2)
    default = designed[looks["defaults"]["bases"]["masculine"]]["look"]
    assert reset["current"]["document"]["recipe"] == recipe_from_look(
        default, masculine
    ).model_dump(mode="json")
    restored = repo.reset(version, subject, base_revision=3, restore_revision=1)
    assert restored["current"]["document"]["recipe"] == saved["current"]["document"]["recipe"]
    assert restored["current"]["render_status"] == "available"
    assert [row["revision"] for row in repo.history(version, subject)] == [4, 3, 2, 1]

    # A recipe over a catalog revision this host no longer serves keeps its history.
    repo.families = {masculine.sha256: masculine}
    assert repo.read(version, subject)["current"]["render_status"] == "family_source_unavailable"
