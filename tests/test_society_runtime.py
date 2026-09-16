"""Real PostgreSQL 18 authorization for explicitly registered living-world inputs."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from exulanica.api.society_runtime import SocietyRuntime, SocietyRuntimeBinding
from exulanica.environment.admission import SourceAdmission
from exulanica.environment.repository import EnvironmentRepository
from exulanica.evidence.blob import BlobId
from exulanica.selection.validation import Session
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.assets import reviewed_assets, seed_reviewed_assets
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_planner import input_sha256
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.structure_repository import WorldStructureRepository

from world_structure_fixtures import structural_candidate

pytestmark = pytest.mark.postgres
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
INTERPRETATION = ROOT / "assets/owned-world/flatiron-interpretation-v1/district-interpretation.json"


@pytest.fixture
def runtime_world(repository, tmp_path, request):
    connection = repository.connection
    workspace = repository.workspace_id
    session = Session(workspace_id=workspace, actor=uuid.uuid4())
    assert (
        int(connection.execute("show server_version_num").fetchone()["server_version_num"])
        >= 180000
    )
    store = LocalContentAddressedStore(tmp_path / "blobs")
    seed_reviewed_assets(store)
    structs = WorldStructureRepository(connection, workspace)
    preview = structs.preview(structural_candidate(), proposed_by=session.actor)
    snapshot = structs.apply(
        preview.preview_id,
        base_snapshot_id=preview.base_snapshot_id,
        base_graph_sha256=preview.base_graph_sha256,
        base_reconstruction_sha256=preview.base_reconstruction_sha256,
        committed_by=session.actor,
    )
    objects = WorldObjectRepository(connection, workspace, store=store)
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id,
        title="Explicit authored fixture",
        created_by=session.actor,
    )
    place = uuid.uuid4()
    connection.execute("insert into place(workspace_id,place_id) values(%s,%s)", (workspace, place))
    admissions = EnvironmentRepository(connection, workspace, store)
    plan = json.loads((BASE.parent / "admission-plan.json").read_bytes())
    source_bindings = []
    for declaration in plan["sources"]:
        supplied = {
            **declaration,
            "admission_id": uuid.uuid4(),
            "place_id": place,
            "local_path": BASE.parent / declaration["local_path"],
        }
        supplied["operation_rights"] = {
            **supplied["operation_rights"],
            **getattr(request, "param", {}),
        }
        source = SourceAdmission.model_validate(supplied)
        saved = admissions.admit_source(source, actor=session.actor)
        source_bindings.append(
            dict(
                dataset_id=source.provider_original_id,
                admission_id=source.admission_id,
                source_sha256=source.expected_sha256,
                receipt_sha256=saved.receipt_sha256,
            )
        )
    base_blob = store.put_file(BASE).blob_id.hex
    interpretation_blob = store.put_file(INTERPRETATION).blob_id.hex
    interpreted = json.loads(INTERPRETATION.read_bytes())
    binding = SocietyRuntimeBinding(
        binding_id="reviewed-flatiron-fixture-registration-v1",
        workspace_id=workspace,
        world_id=version.world_id,
        version_id=version.version_id,
        source_snapshot_id=snapshot.snapshot_id,
        place_id=place,
        region_id="region-a",
        district_id=interpreted["district_id"],
        frame=interpreted["frame"],
        translation_mm=(0, 0, 0),
        yaw_microradians=0,
        scale_milli=1000,
        base_artifact_sha256=base_blob,
        interpretation_artifact_sha256=interpretation_blob,
        interpretation_document_sha256=interpreted["document_sha256"],
        sources=source_bindings,
    )
    plate = next(a for a in reviewed_assets() if a.asset_key == "cc0.marker-plate")
    registry = {
        plate.content_sha256: dict(
            asset_key=plate.asset_key,
            affordance="rest",
            duration_ticks=3,
            footprint_half_extents_mm=[500, 500],
            blocks_navigation=False,
            reach_mm=1500,
        )
    }
    runtime = SocietyRuntime(store=store, bindings=[binding], reviewed_affordances=registry)
    objects = WorldObjectRepository(
        connection,
        workspace,
        store=store,
        on_edit=lambda version_id: runtime.authored_edit(connection, session, version_id),
    )
    return dict(
        connection=connection,
        workspace=workspace,
        session=session,
        store=store,
        objects=objects,
        version=version,
        binding=binding,
        registry=registry,
        runtime=runtime,
        admissions=admissions,
        plate=plate,
    )


def initial(world):
    b = world["binding"]
    return world["runtime"].initial_input(
        world["connection"], world["session"], b.version_id, b.place_id, b.region_id
    )


def society(world):
    return SocietyRepository(
        world["connection"],
        world["workspace"],
        input_authorizer=lambda doc: world["runtime"].authorize(
            world["connection"], world["session"], doc
        ),
    )


def create(world):
    b = world["binding"]
    return society(world).create(
        b.version_id,
        place_id=b.place_id,
        region_id=b.region_id,
        seed="7a" * 32,
        actor=world["session"].actor,
        profile="exulanica-society/v2",
        initial_input=initial(world),
    )


def add_plate(world):
    v = world["objects"].version(world["binding"].version_id)
    return world["objects"].add_object(
        v.version_id,
        AuthoredObject(
            object_id="object:rest-fixture",
            asset_sha256=world["plate"].content_sha256,
            region_id="region-a",
            transform=Transform(
                x_mm=40000, y_mm=0, z_mm=64000, yaw_microradians=0, scale_milli=1000
            ),
            origin=ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=v.state_sha256,
        actor=world["session"].actor,
    )


def test_configured_scope_and_reload_do_not_infer_new_registration(runtime_world):
    w = runtime_world
    document = initial(w)
    assert document["availability"] == "available"
    w["runtime"].authorize(w["connection"], w["session"], document)
    state = create(w)
    rebuilt = SocietyRuntime(
        store=w["store"], bindings=[w["binding"]], reviewed_affordances=w["registry"]
    )
    rebuilt.authorize(w["connection"], w["session"], document)
    assert state["profile"] == "exulanica-society/v2"
    assert initial(w) == document
    absent = SocietyRuntime(store=w["store"], bindings=[], reviewed_affordances=w["registry"])
    with pytest.raises(UnavailableSocietyInput):
        absent.authorize(w["connection"], w["session"], document)
    with pytest.raises(UnavailableSocietyInput):
        rebuilt.initial_input(
            w["connection"],
            w["session"],
            w["binding"].version_id,
            w["binding"].place_id,
            "region-b",
        )
    changed = w["binding"].model_copy(update={"translation_mm": (1000, 0, 0)})
    drifted = SocietyRuntime(
        store=w["store"], bindings=[changed], reviewed_affordances=w["registry"]
    )
    with pytest.raises(UnavailableSocietyInput, match="registration"):
        drifted.authorize(w["connection"], w["session"], document)


def test_foreign_workspace_and_authored_version_fail_closed(runtime_world):
    w = runtime_world
    document = initial(w)
    other = Session(workspace_id=uuid.uuid4(), actor=uuid.uuid4())
    with pytest.raises(UnavailableSocietyInput):
        w["runtime"].authorize(w["connection"], other, document)
    with pytest.raises(UnavailableSocietyInput):
        w["runtime"].initial_input(
            w["connection"], w["session"], uuid.uuid4(), w["binding"].place_id, "region-a"
        )


@pytest.mark.parametrize("mutation", ["node", "target", "asset-ref", "origin", "authored-digest"])
def test_self_signed_input_cannot_grant_spatial_or_authored_authority(runtime_world, mutation):
    w = runtime_world
    doc = initial(w)
    if mutation == "node":
        for node in doc["navigation"]["nodes"]:
            node["position_mm"][0] += 10
    elif mutation == "target":
        doc["targets"][0]["enabled"] = False
    elif mutation == "asset-ref":
        doc["dependency_refs"].append(
            {"kind": "reviewed_asset", "identity": "fake", "sha256": "a" * 64}
        )
        doc["dependency_refs"].sort(key=lambda r: (r["kind"], r["identity"], r["sha256"]))
    elif mutation == "origin":
        doc["targets"][0].update(origin="authored", object_id="object:invented")
    else:
        doc["authored_state"]["delta_sha256"] = "a" * 64
    doc["document_sha256"] = input_sha256(doc)
    with pytest.raises(UnavailableSocietyInput):
        w["runtime"].authorize(w["connection"], w["session"], doc)


def test_withdrawal_denies_historical_input_and_unavailable_input_has_no_geometry(runtime_world):
    w = runtime_world
    doc = initial(w)
    create(w)
    source = w["binding"].sources[0]
    w["admissions"].withdraw("source", source.admission_id)
    with pytest.raises(UnavailableSocietyInput):
        w["runtime"].authorize(w["connection"], w["session"], doc)
    unavailable = initial(w)
    assert unavailable["availability"] == "unavailable"
    assert not unavailable["navigation"]["nodes"] and not unavailable["targets"]
    # Ordered refresh can pause a society without authorizing its former geometry.
    w["runtime"].authored_edit(w["connection"], w["session"], w["binding"].version_id)
    latest = (
        w["connection"]
        .execute(
            "select document from world_society_input where workspace_id=%s "
            "order by input_seq desc limit 1",
            (w["workspace"],),
        )
        .fetchone()["document"]
    )
    w["runtime"].authorize(w["connection"], w["session"], latest)
    assert latest["availability"] == "unavailable"


@pytest.mark.parametrize("runtime_world", [{"compose": False}], indirect=True)
def test_denied_source_operation_cannot_be_granted_by_artifact_rights(runtime_world):
    w = runtime_world
    # Artifact metadata still says compose=true. Current admitted rights are authoritative.
    doc = initial(w)
    assert doc["availability"] == "unavailable"
    assert not doc["navigation"]["nodes"]
    with pytest.raises(ValueError, match="initial district unavailable"):
        create(w)


def test_missing_base_or_source_bytes_do_not_fall_back_to_fixtures(runtime_world):
    w = runtime_world
    source = w["binding"].sources[0]
    # Purging through the explicit test authority, never deleting a provider file.
    purge = privileged_purger(
        w["store"],
        PurgeAuthorization(tombstone_id="test", actor="test", reason="isolated missing bytes"),
    )
    purge.purge(BlobId.from_hex(source.source_sha256))
    assert initial(w)["availability"] == "unavailable"


def test_removed_object_history_keeps_current_asset_dependencies(runtime_world):
    w = runtime_world
    create(w)
    with w["connection"].transaction():
        add_plate(w)
    historic = (
        w["connection"]
        .execute(
            "select document from world_society_input where workspace_id=%s "
            "order by input_seq desc limit 1",
            (w["workspace"],),
        )
        .fetchone()["document"]
    )
    assert any(t["origin"] == "authored" for t in historic["targets"])
    assert any(r["kind"] == "reviewed_asset" for r in historic["dependency_refs"])
    with w["connection"].transaction():
        current = w["objects"].version(w["binding"].version_id)
        w["objects"].undo(
            current.version_id, base_state_sha256=current.state_sha256, actor=w["session"].actor
        )
    assert not w["objects"].version(w["binding"].version_id).objects
    w["runtime"].authorize(w["connection"], w["session"], historic)
    purge = privileged_purger(
        w["store"],
        PurgeAuthorization(tombstone_id="test", actor="test", reason="isolated missing bytes"),
    )
    purge.purge(BlobId.from_hex(w["plate"].content_sha256))
    with pytest.raises(UnavailableSocietyInput):
        w["runtime"].authorize(w["connection"], w["session"], historic)


def test_failed_edit_observer_rolls_back_authored_edit_and_input_together(runtime_world):
    w = runtime_world
    create(w)
    before = w["objects"].version(w["binding"].version_id)
    missing = SocietyRuntime(store=w["store"], bindings=[], reviewed_affordances=w["registry"])
    w["objects"] = WorldObjectRepository(
        w["connection"],
        w["workspace"],
        store=w["store"],
        on_edit=lambda version_id: missing.authored_edit(w["connection"], w["session"], version_id),
    )
    with pytest.raises(UnavailableSocietyInput):
        add_plate(w)
    assert w["objects"].version(before.version_id).state_sha256 == before.state_sha256
    assert (
        w["connection"]
        .execute(
            "select count(*) as n from world_society_input where workspace_id=%s", (w["workspace"],)
        )
        .fetchone()["n"]
        == 1
    )


def test_source_withdrawal_cannot_race_outer_authorization_transaction(runtime_world, spine_schema):
    import psycopg
    from exulanica.ingest.spine.scope import WorkspaceScope

    from pg_harness import open_scratch_connection

    w = runtime_world
    doc = initial(w)
    driver, schema = spine_schema
    other = open_scratch_connection(driver, schema)
    WorkspaceScope(other, w["workspace"])
    foreign_repo = EnvironmentRepository(other, w["workspace"], w["store"])
    try:
        with w["connection"].transaction():
            w["runtime"].authorize(w["connection"], w["session"], doc)
            # Existing barrier returns retryable 40001; it never lets withdrawal commit here.
            with pytest.raises(psycopg.errors.SerializationFailure):
                foreign_repo.withdraw("source", w["binding"].sources[0].admission_id)
        foreign_repo.withdraw("source", w["binding"].sources[0].admission_id)
        with pytest.raises(UnavailableSocietyInput):
            w["runtime"].authorize(w["connection"], w["session"], doc)
    finally:
        other.close()


def test_authorization_works_on_readonly_materialization_transaction(runtime_world):
    w = runtime_world
    doc = initial(w)
    create(w)
    with w["connection"].transaction():
        w["connection"].execute("set transaction read only")
        w["runtime"].authorize(w["connection"], w["session"], doc)


def test_foreign_database_rows_do_not_resolve_even_with_bad_host_registration(runtime_world):
    w = runtime_world
    other = Session(workspace_id=uuid.uuid4(), actor=uuid.uuid4())
    binding = w["binding"].model_copy(update={"workspace_id": other.workspace_id})
    runtime = SocietyRuntime(
        store=w["store"], bindings=[binding], reviewed_affordances=w["registry"]
    )
    with pytest.raises(UnavailableSocietyInput, match="authored version"):
        runtime.initial_input(
            w["connection"], other, binding.version_id, binding.place_id, binding.region_id
        )


def test_pinned_admission_digest_drift_and_source_missing_are_explicit(runtime_world):
    w = runtime_world
    for fields in (
        {"source_sha256": "a" * 64},
        {"receipt_sha256": "b" * 64},
        {"admission_id": uuid.uuid4()},
    ):
        sources = (w["binding"].sources[0].model_copy(update=fields), w["binding"].sources[1])
        binding = w["binding"].model_copy(update={"sources": sources})
        runtime = SocietyRuntime(
            store=w["store"], bindings=[binding], reviewed_affordances=w["registry"]
        )
        doc = runtime.initial_input(
            w["connection"], w["session"], binding.version_id, binding.place_id, binding.region_id
        )
        assert doc["availability"] == "unavailable"
        assert not doc["navigation"]["nodes"]


def test_reviewed_registry_mutation_uses_same_delivery_barrier(runtime_world, spine_schema):
    import psycopg
    from exulanica.ingest.spine.scope import WorkspaceScope

    from pg_harness import open_scratch_connection

    w = runtime_world
    doc = initial(w)
    driver, schema = spine_schema
    other = open_scratch_connection(driver, schema)
    WorkspaceScope(other, w["workspace"])
    try:
        with w["connection"].transaction():
            w["runtime"].authorize(w["connection"], w["session"], doc)
            with pytest.raises(psycopg.errors.SerializationFailure):
                other.execute(
                    "update world_reviewed_asset set title=title where asset_key=%s",
                    (w["plate"].asset_key,),
                )
        other.execute(
            "update world_reviewed_asset set title=title where asset_key=%s",
            (w["plate"].asset_key,),
        )
    finally:
        other.close()


def test_rehashing_persisted_history_or_inventing_input_sequence_does_not_authorize(runtime_world):
    w = runtime_world
    doc = initial(w)
    create(w)
    doc["targets"][0]["enabled"] = False
    doc["document_sha256"] = input_sha256(doc)
    with pytest.raises(UnavailableSocietyInput, match="historical"):
        w["runtime"].authorize(w["connection"], w["session"], doc)
    doc = initial(w)
    doc["input_seq"] = 999
    doc["document_sha256"] = input_sha256(doc)
    with pytest.raises(UnavailableSocietyInput, match="sequence"):
        w["runtime"].authorize(w["connection"], w["session"], doc)
