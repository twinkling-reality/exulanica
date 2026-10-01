"""Published character catalogs on PostgreSQL: publication, withdrawal, what a saved look reads."""

import copy
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.db.roles import provision_runtime_role
from exulanica.evidence.blob import BlobId
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.character_appearance import (
    AppearanceUnavailable,
    CharacterRecipe,
    CharacterSubject,
    designed_looks,
    recipe_from_look,
)
from exulanica.world.character_appearance_repository import CharacterAppearanceRepository
from exulanica.world.character_catalog_publication import (
    catalog_documents,
    catalog_imports,
    publish_catalogs,
    withdraw_catalog,
)
from exulanica.world.character_catalogs import (
    CatalogRegistry,
    PublicationRefused,
    read_publication_document,
)
from exulanica.world.character_parametric import declared_family
from psycopg import sql
from psycopg.types.json import Jsonb

from test_character_catalogs import catalog_b
from test_world_objects_postgres import world as world

pytestmark = pytest.mark.postgres

ROOT = Path(__file__).parents[1]
CHARACTERS = ROOT / "assets/characters"
CATALOG = json.loads((CHARACTERS / "catalog.json").read_text())
LOOKS = json.loads((CHARACTERS / "looks.json").read_text())


@pytest.fixture(scope="module")
def documents():
    layered, parametric = catalog_documents(CHARACTERS)
    return SimpleNamespace(a=layered, parametric=parametric, b=catalog_b())


@pytest.fixture
def catalogs(repository, tmp_path):
    """Publish for one test, and take the reviewed containers back out afterwards.

    ``world_reviewed_asset`` is preserved between tests, so every key this imports is removed
    again, as ``publish_reviewed`` in ``test_character_appearance_postgres`` does. The publication
    tables themselves are emptied with every other spine table.
    """
    store = LocalContentAddressedStore(tmp_path / "character-blobs")
    imported: set[str] = set()
    registry = CatalogRegistry()

    def publish(*documents):
        for document in documents:
            imported.update(item.manifest.asset_key for item in catalog_imports(document))
        with repository.connection.transaction():
            outcomes = publish_catalogs(repository.connection, store, documents)
        repository.connection.commit()
        return outcomes

    def withdraw(document, reason="test_withdrawal"):
        digest = read_publication_document(document).catalog_sha256
        with repository.connection.transaction():
            state = withdraw_catalog(repository.connection, digest, reason)
        repository.connection.commit()
        return state

    yield SimpleNamespace(store=store, publish=publish, withdraw=withdraw, registry=registry)
    if imported:
        with repository.connection.transaction():
            repository.connection.execute(
                "delete from world_reviewed_asset where asset_key = any(%s)", (sorted(imported),)
            )
        repository.connection.commit()


@pytest.fixture
def looks(world, repository, catalogs):
    """A saved look's repository as a request builds it, with the served catalogs read afresh."""
    objects, snapshot, _ = world
    actor = uuid.uuid4()
    versions = [
        objects.create_version(
            source_snapshot_id=snapshot.snapshot_id, title=f"Catalog world {n}", created_by=actor
        ).version_id
        for n in (1, 2)
    ]
    repository.connection.commit()

    def repo():
        return CharacterAppearanceRepository(
            repository.connection,
            repository.workspace_id,
            actor,
            store=catalogs.store,
            world_id=objects.world_id,
            served=catalogs.registry.served(repository.connection),
        )

    return SimpleNamespace(
        repo=repo, versions=versions, subject=CharacterSubject(kind="avatar", subject_id=actor)
    )


def _family(publication, family_id):
    return next(f for f in publication.families if f.family_id == family_id)


def _feminine_look(hair):
    look = copy.deepcopy(designed_looks(CATALOG, LOOKS)["tailored-feminine"]["look"])
    look["parts"]["hair"] = hair
    return look


# -- publication ------------------------------------------------------------------------------


def test_publishing_is_idempotent_and_a_changed_catalog_is_a_new_revision(catalogs, documents):
    first = catalogs.publish(documents.a, documents.parametric)
    assert [(o.catalog_id, o.revision, o.state) for o in first] == [
        ("exulanica-characters", 2, "published"),
        ("exulanica-parametric-characters", 1, "published"),
    ]
    again = catalogs.publish(documents.a, documents.parametric)
    assert [o.state for o in again] == ["unchanged", "unchanged"]
    relabelled = copy.deepcopy(documents.a)
    relabelled["catalog"]["families"][0]["label"] = "Relabelled"
    with pytest.raises(PublicationRefused, match="a changed catalog is a new revision"):
        catalogs.publish(relabelled)
    (b,) = catalogs.publish(documents.b)
    assert (b.revision, b.state) == (3, "published")
    older = copy.deepcopy(relabelled)
    older["catalog"]["revision"] = 1
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="not newer"):
        catalogs.publish(older)


def test_only_the_host_writes_a_publication_and_nothing_is_ever_rewritten(
    repository, catalogs, documents
):
    catalogs.publish(documents.a)
    connection = repository.connection
    table = "character_catalog_publication"
    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="never rewritten"),
        connection.transaction(),
    ):
        connection.execute(f"update {table} set producer = 'someone else'")
    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="never rewritten"),
        connection.transaction(),
    ):
        connection.execute(f"delete from {table}")
    role = f"catalog_app_{uuid.uuid4().hex[:12]}"
    try:
        provision_runtime_role(connection, role=role)
        for name in (table, "character_catalog_withdrawal"):
            granted = connection.execute(
                "select has_table_privilege(%(r)s, %(t)s, 'SELECT') as s,"
                " has_table_privilege(%(r)s, %(t)s, 'INSERT') as i,"
                " has_table_privilege(%(r)s, %(t)s, 'UPDATE') as u,"
                " has_table_privilege(%(r)s, %(t)s, 'DELETE') as d",
                {"r": role, "t": name},
            ).fetchone()
            assert granted == {"s": True, "i": False, "u": False, "d": False}
        connection.execute(
            sql.SQL("grant insert on {} to {}").format(sql.Identifier(table), sql.Identifier(role))
        )
        connection.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
        try:
            with (
                pytest.raises(psycopg.errors.InsufficientPrivilege, match="administration"),
                connection.transaction(),
            ):
                connection.execute(
                    f"insert into {table}(catalog_sha256,catalog_id,profile,kind,revision,"
                    "document,producer) values(%s,'x-catalog',"
                    "'exulanica.character-catalog-bundle/v1','layered-people',9,'{}','me')",
                    ("f" * 64,),
                )
        finally:
            connection.execute("reset role")
    finally:
        connection.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(role)))
        connection.commit()


def test_a_stored_document_that_disagrees_with_its_key_is_never_served(
    repository, catalogs, documents
):
    connection = repository.connection
    with connection.transaction():
        connection.execute(
            "insert into character_catalog_publication"
            "(catalog_sha256,catalog_id,profile,kind,revision,document,producer) "
            "values(%s,'exulanica-characters','exulanica.character-catalog-bundle/v1',"
            "'layered-people',2,%s,'test')",
            ("0" * 64, Jsonb(documents.a)),
        )
    connection.commit()
    assert catalogs.registry.served(connection).publications == ()
    publication, withdrawn = catalogs.registry.document(connection, "0" * 64)
    assert (publication, withdrawn) == (None, False)


def test_withdrawal_is_final_and_stops_serving(repository, catalogs, documents):
    catalogs.publish(documents.a, documents.b)
    served = catalogs.registry.served(repository.connection)
    assert [p.revision for p in served.publications] == [2, 3]
    assert catalogs.withdraw(documents.a) == "withdrawn"
    assert catalogs.withdraw(documents.a) == "unchanged"
    served = catalogs.registry.served(repository.connection)
    assert [p.revision for p in served.publications] == [3]
    digest = read_publication_document(documents.a).catalog_sha256
    publication, withdrawn = catalogs.registry.document(repository.connection, digest)
    assert withdrawn and publication is not None
    with (
        pytest.raises(PublicationRefused, match="no such published catalog"),
        repository.connection.transaction(),
    ):
        withdraw_catalog(repository.connection, "e" * 64, "test")


def test_a_withdrawal_stands_for_a_digest_before_its_publication(repository, catalogs, documents):
    """A restore carries a withdrawal even when the backup never held its publication (0135): the
    row names the digest alone, and publishing that document then records it, answers withdrawn
    and leaves the catalog's older revision current."""
    withdrawn = read_publication_document(documents.b).catalog_sha256
    with repository.connection.transaction():
        repository.connection.execute(
            "insert into character_catalog_withdrawal(catalog_sha256,reason) values(%s,%s)",
            (withdrawn, "carried_by_restore"),
        )
    repository.connection.commit()
    with (
        pytest.raises(psycopg.errors.CheckViolation),
        repository.connection.transaction(),
    ):
        repository.connection.execute(
            "insert into character_catalog_withdrawal(catalog_sha256,reason) values(%s,%s)",
            ("not-a-digest", "test"),
        )
    outcomes = catalogs.publish(documents.a, documents.b)
    assert [(o.revision, o.state) for o in outcomes] == [(2, "published"), (3, "withdrawn")]
    served = catalogs.registry.served(repository.connection)
    assert [p.revision for p in served.publications] == [2]
    assert [p.revision for p in served.current()] == [2]
    publication, is_withdrawn = catalogs.registry.document(repository.connection, withdrawn)
    assert is_withdrawn and publication is not None
    assert [o.state for o in catalogs.publish(documents.a, documents.b)] == [
        "unchanged",
        "withdrawn",
    ]


# -- what a saved look reads ------------------------------------------------------------------


def test_a_saved_look_keeps_its_catalog_and_is_unavailable_by_name_once_withdrawn(
    catalogs, documents, looks
):
    catalogs.publish(documents.a, documents.parametric)
    a = read_publication_document(documents.a)
    b = read_publication_document(documents.b)
    first, second = looks.versions
    feminine_a = _family(a, "makehuman-people/v1/feminine")
    masculine = _family(a, "makehuman-people/v1/masculine")

    worn = _feminine_look("feminine/hair/long01")
    saved = looks.repo().save(
        first, looks.subject, recipe_from_look(worn, feminine_a), base_revision=0
    )
    assert saved["current"]["render_status"] == "available"
    assert saved["current"]["render"]["catalog_sha256"] == a.catalog_sha256
    assert saved["current"]["render"]["resolution"] == "authored"
    assert saved["current"]["document"]["publication"]["revision"] == 2

    suit = designed_looks(CATALOG, LOOKS)["suit-masculine"]["look"]
    looks.repo().save(second, looks.subject, recipe_from_look(suit, masculine), base_revision=0)

    # Catalog B removes that hairstyle and narrows the feminine height bound.
    catalogs.publish(documents.b)
    read = looks.repo().read(first, looks.subject)["current"]
    assert read["render_status"] == "available"
    assert (read["render"]["catalog_sha256"], read["render"]["resolution"]) == (
        a.catalog_sha256,
        "authored",
    )
    masculine_read = looks.repo().read(second, looks.subject)["current"]
    assert masculine_read["render"]["catalog_sha256"] == b.catalog_sha256
    assert masculine_read["render"]["resolution"] == "compatible"

    # A look saved now over B's feminine family sits beside the A look in another version.
    feminine_b = _family(b, "makehuman-people/v1/feminine")
    looks.repo().save(
        second,
        looks.subject,
        recipe_from_look(_feminine_look("feminine/hair/bob01"), feminine_b),
        base_revision=1,
    )
    assert looks.repo().read(second, looks.subject)["current"]["render"]["catalog_sha256"] == (
        b.catalog_sha256
    )
    assert looks.repo().read(first, looks.subject)["current"]["render_status"] == "available"

    # Withdrawing A leaves nothing that derives the first look's family: unavailable, by name.
    catalogs.withdraw(documents.a)
    after = looks.repo().read(first, looks.subject)["current"]
    assert after["render_status"] == "family_source_unavailable"
    assert after["render"] is None
    assert after["document"]["recipe"]["parameters"]["hair"] == "feminine/hair/long01"
    assert [row["revision"] for row in looks.repo().history(first, looks.subject)] == [1]
    with pytest.raises(AppearanceUnavailable):
        looks.repo().reset(first, looks.subject, base_revision=1)
    with pytest.raises(AppearanceUnavailable):
        looks.repo().save(first, looks.subject, recipe_from_look(worn, feminine_a), base_revision=1)
    assert looks.repo().read(second, looks.subject)["current"]["render_status"] == "available"


def test_the_families_read_names_each_family_s_kind_and_publication(catalogs, documents, looks):
    catalogs.publish(documents.a, documents.parametric)
    listed = looks.repo().available_families(looks.versions[0], looks.subject)
    kinds = {entry["family"]["family_id"]: entry["kind"] for entry in listed}
    assert kinds == {
        "makehuman-people/v1/feminine": "layered-people",
        "makehuman-people/v1/masculine": "layered-people",
        "makehuman-parametric/v1": "parametric-body",
    }
    assert {entry["publication"]["state"] for entry in listed} == {"current"}


def test_a_parametric_look_saves_with_its_reviewed_body_and_never_with_another_recipe(
    catalogs, documents, looks
):
    catalogs.publish(documents.a, documents.parametric)
    parametric = read_publication_document(documents.parametric)
    (family,) = parametric.families
    (body,) = declared_family(documents.parametric, family.family_id).representations
    version = looks.versions[0]
    recipe = CharacterRecipe(
        family_id=family.family_id,
        family_sha256=family.sha256,
        parameters=body.values,
        seed=0,
        representation_id=body.representationId,
    )
    saved = looks.repo().save(version, looks.subject, recipe, base_revision=0)["current"]
    assert saved["render_status"] == "available"
    assert saved["render"]["kind"] == "parametric-body"
    assert saved["render"]["dependencies"] == [
        {
            "asset_key": "makehuman.parametric.default.v1",
            "content_sha256": body.asset.contentSha256,
            "byte_size": body.asset.byteSize,
            "state": "available",
        }
    ]
    taller = {**body.values, "heightCm": 176}
    with pytest.raises(ValueError, match="not prepared for these exact recipe inputs"):
        looks.repo().save(
            version,
            looks.subject,
            recipe.model_copy(update={"parameters": taller}),
            base_revision=1,
        )
    unprepared = looks.repo().save(
        version,
        looks.subject,
        recipe.model_copy(update={"parameters": taller, "representation_id": None}),
        base_revision=1,
    )["current"]
    assert unprepared["render_status"] == "no_prepared_representation"
    with pytest.raises(ValueError, match="not prepared"):
        looks.repo().save(
            version,
            looks.subject,
            recipe.model_copy(
                update={"parameters": taller, "representation_id": f"preparation:{uuid.uuid4()}"}
            ),
            base_revision=2,
        )
    reset = looks.repo().reset(version, looks.subject, base_revision=2)["current"]
    assert reset["document"]["recipe"]["representation_id"] == body.representationId
    assert reset["render_status"] == "available"

    # The body's bytes gone from the store: unavailable by name, recipe intact.
    blob = catalogs.store.root / catalogs.store.key_for(BlobId.from_hex(body.asset.contentSha256))
    blob.unlink()
    gone = looks.repo().read(version, looks.subject)["current"]
    assert gone["render_status"] == "asset_bytes_unavailable"
    assert gone["document"]["recipe"]["parameters"] == body.values
