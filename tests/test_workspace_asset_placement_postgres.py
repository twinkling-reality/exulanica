"""Placing a person's own prepared asset: preview, apply, reopen, undo, withdrawal and isolation.

Every test drives the real application as a provisioned runtime role (neither owner nor
BYPASSRLS) against a private PostgreSQL, through the composition routes with the
``workspace_asset`` source kind, and reads back what was stored. The society and flight readers
are asked about a starter world holding a placed asset, as their runtimes read it.
"""

from __future__ import annotations

import json
import uuid
from urllib.parse import urlencode

import psycopg
import pytest
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.evidence.blob import BlobId
from exulanica.selection.validation import Session
from exulanica.world import WorldObjectRepository, WorldStructureRepository, flight_input
from exulanica.world.flight_input import saved_world_flight
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID, create_starter_authorities

from static_glb_builder import cube, png
from workspace_asset_support import AssetsApi, assets_api, declaration
from world_structure_fixtures import structural_candidate
from world_support import registered_world

pytestmark = pytest.mark.postgres

PARAMETERS = {"axis": "x", "travel_mm": 1_000, "cycle_ticks": 40}


@pytest.fixture
def api(repository, spine_schema, tmp_path):
    yield from assets_api(repository, spine_schema, tmp_path)


def in_world(api: AssetsApi, path: str, world_id: str | None = None) -> str:
    return f"{path}?{urlencode({'world_id': world_id or api.world_id})}"


def transform(**overrides) -> dict[str, int]:
    return {
        "x_mm": 1_200,
        "y_mm": 0,
        "z_mm": -450,
        "yaw_microradians": 785_398,
        "scale_milli": 1_000,
        **overrides,
    }


def new_version(api: AssetsApi, world_id: str | None = None, **body) -> dict:
    if "parent_version_id" not in body:
        body.setdefault("source_snapshot_id", str(api.snapshot_id))
    response = api.post(in_world(api, "/world/versions", world_id), {"title": "My square", **body})
    assert response.status_code == 201, response.text
    return response.json()


def read(api: AssetsApi, version_id: str, world_id: str | None = None) -> dict:
    response = api.get(in_world(api, f"/world/versions/{version_id}", world_id))
    assert response.status_code == 200, response.text
    return response.json()


def body(
    version: dict,
    asset_id: str,
    *,
    digest: str | None = None,
    subject_id: str = "object:bench",
    region_id: str = "region-a",
) -> dict:
    source = {"kind": "workspace_asset", "asset_id": asset_id}
    if digest is not None:
        source["prepared_sha256"] = digest
    return {
        "base_state_sha256": version["state_sha256"],
        "source": source,
        "placement": {
            "subject_id": subject_id,
            "region_id": region_id,
            "transform": transform(),
            "origin_role": "fictional",
        },
    }


def preview(api: AssetsApi, version_id: str, request: dict, world_id: str | None = None, **who):
    return api.post(
        in_world(api, f"/world/versions/{version_id}/compositions/preview", world_id),
        request,
        **who,
    )


def apply(api: AssetsApi, version_id: str, request: dict, world_id: str | None = None, **who):
    return api.post(
        in_world(api, f"/world/versions/{version_id}/compositions/apply", world_id), request, **who
    )


def assert_refused(response, reason: str) -> None:
    assert response.status_code == 409, response.text
    assert response.json() == {"code": "composition_blocked", "detail": reason}


def prepared(api: AssetsApi, payload: bytes | None = None, **overrides) -> tuple[str, str, dict]:
    """Admit and prepare an asset; its id, its prepared digest and its view."""
    view = api.admitted(payload or bench(), **overrides)
    return view["asset_id"], view["preparation"]["output"]["content_sha256"], view


def bench() -> bytes:
    return cube(offset=(0.0, 0.0, 0.0), texture=png(4, 4)).build()


def placed(api: AssetsApi, asset_id: str, digest: str, **place) -> tuple[dict, dict]:
    version = new_version(api)
    applied = apply(api, version["version_id"], body(version, asset_id, digest=digest, **place))
    assert applied.status_code == 201, applied.text
    return version, applied.json()


# -- preview, apply, reopen, undo ---------------------------------------------------------------


def test_a_prepared_asset_previews_without_writing_and_applies_exactly_what_it_previewed(
    api: AssetsApi,
) -> None:
    asset_id, digest, view = prepared(api)
    version = new_version(api)
    before = read(api, version["version_id"])
    edits_before = api.sql("select count(*) as n from world_alternate_version_edit")[0]["n"]

    verdict = preview(api, version["version_id"], body(before, asset_id))
    assert verdict.status_code == 200, verdict.text
    document = verdict.json()
    assert document["availability"] == "ready", document
    assert document["source"] == {
        "kind": "workspace_asset",
        "asset_id": asset_id,
        "preparation_id": view["preparation"]["preparation_id"],
        "content_sha256": digest,
        "bytes": "available",
        "title": "Oak bench",
        "dimensions_mm": {"width": 1000, "height": 1000, "depth": 1000},
        "licence_id": None,
        "attribution": None,
    }
    change = document["would_change"]
    assert change["kind"] == "add_object"
    assert change["document"]["asset_sha256"] == digest
    assert change["document"]["workspace_preparation_id"] == view["preparation"]["preparation_id"]
    assert change["document"]["behaviour"] is None
    # A preview reads and writes nothing, down to the edit log.
    assert read(api, version["version_id"]) == before
    assert api.sql("select count(*) as n from world_alternate_version_edit")[0]["n"] == edits_before

    # An apply names the bytes it expects to place; the transport refuses one that does not.
    unnamed = apply(api, version["version_id"], body(before, asset_id))
    assert unnamed.status_code == 422, unnamed.text
    applied = apply(api, version["version_id"], body(before, asset_id, digest=digest))
    assert applied.status_code == 201, applied.text
    after = applied.json()
    assert after["schema_version"] == 4
    [obj] = after["objects"]
    assert obj["asset"] is None
    assert obj["workspace_asset"] == {
        "asset_id": asset_id,
        "preparation_id": view["preparation"]["preparation_id"],
        "title": "Oak bench",
        "content_sha256": digest,
        "byte_size": view["preparation"]["output"]["byte_size"],
        "media_type": "model/gltf-binary",
        "licence_id": None,
        "attribution": None,
        "availability": "available",
    }
    [stored] = api.sql(
        "select after_document from world_alternate_version_edit where edit_id = %s",
        uuid.UUID(after["edits"][-1]["edit_id"]),
    )
    assert stored["after_document"] == change["document"]

    # Reopened, it is the version apply answered with.
    assert read(api, version["version_id"]) == after

    undone = api.post(
        in_world(api, f"/world/versions/{version['version_id']}/objects/undo"),
        {"base_state_sha256": after["state_sha256"]},
    )
    assert undone.status_code == 200, undone.text
    assert undone.json()["objects"] == []
    assert undone.json()["state_sha256"] == before["state_sha256"]


def test_apply_places_only_the_published_bytes_of_a_current_version(api: AssetsApi) -> None:
    asset_id, digest, _ = prepared(api)
    version = new_version(api)
    # Another digest is a changed asset, never a substitute for the one published.
    assert_refused(
        apply(api, version["version_id"], body(version, asset_id, digest="0" * 64)),
        "workspace_asset_changed",
    )
    first = apply(
        api,
        version["version_id"],
        body(version, asset_id, digest=digest, subject_id="object:bench-a"),
    )
    assert first.status_code == 201, first.text
    # The preview was of a state the version has moved past.
    assert_refused(
        apply(
            api,
            version["version_id"],
            body(version, asset_id, digest=digest, subject_id="object:bench-b"),
        ),
        "stale_base",
    )
    current = first.json()
    assert_refused(
        apply(
            api,
            version["version_id"],
            body(current, asset_id, digest=digest, subject_id="object:bench-a"),
        ),
        "subject_already_present",
    )
    # The same preparation placed twice is two objects drawing one output.
    second = apply(
        api,
        version["version_id"],
        body(current, asset_id, digest=digest, subject_id="object:bench-b"),
    )
    assert second.status_code == 201, second.text
    assert [o["workspace_asset"]["content_sha256"] for o in second.json()["objects"]] == [
        digest,
        digest,
    ]


def _not_prepared(api: AssetsApi) -> tuple[str, str | None]:
    response = api.admit(bench())
    assert response.status_code == 201, response.text
    return response.json()["asset_id"], None


def _incompatible(api: AssetsApi) -> tuple[str, str | None]:
    asset_id, digest, _ = prepared(api, unit="millimetre")
    return asset_id, digest


def _bytes_missing(api: AssetsApi) -> tuple[str, str | None]:
    asset_id, digest, _ = prepared(api)
    store = api.stores.for_workspace(api.owner)
    (store.root / store.key_for(BlobId.from_hex(digest))).unlink()
    return asset_id, digest


def _never_admitted(api: AssetsApi) -> tuple[str, str | None]:
    return str(uuid.uuid4()), None


@pytest.mark.parametrize(
    ("make", "reason"),
    [
        (_never_admitted, "unknown_workspace_asset"),
        (_not_prepared, "workspace_asset_not_prepared"),
        (_incompatible, "workspace_asset_incompatible"),
        (_bytes_missing, "workspace_asset_bytes_unavailable"),
    ],
    ids=["unknown", "not-prepared", "incompatible", "bytes-missing"],
)
def test_preview_and_apply_give_the_same_reason_and_write_nothing(api: AssetsApi, make, reason):
    asset_id, digest = make(api)
    version = new_version(api)
    verdict = preview(api, version["version_id"], body(version, asset_id, digest=digest))
    assert verdict.status_code == 200, verdict.text
    assert (verdict.json()["availability"], verdict.json()["blocked_reason"]) == (
        "blocked",
        reason,
    )
    assert_refused(
        apply(api, version["version_id"], body(version, asset_id, digest=digest or "1" * 64)),
        reason,
    )
    assert read(api, version["version_id"])["objects"] == []


def test_a_custom_object_takes_no_behaviour(api: AssetsApi) -> None:
    asset_id, digest, _ = prepared(api)
    version, after = placed(api, asset_id, digest)
    behaviour = {
        "behaviour_key": "motion.bounded-path",
        "behaviour_version": 1,
        "parameters": PARAMETERS,
    }
    refused = api.post(
        in_world(api, f"/world/versions/{version['version_id']}/objects/object:bench/behaviour"),
        {"base_state_sha256": after["state_sha256"], "behaviour": behaviour},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "invalid_object_data"
    # The table refuses it too, whoever writes.
    with pytest.raises(psycopg.errors.CheckViolation) as violation:
        api.sql(
            "update world_alternate_object set behaviour_key = 'motion.bounded-path', "
            "behaviour_version = 1, behaviour_parameters = %s::jsonb "
            "where object_id = 'object:bench'",
            '{"axis": "x", "travel_mm": 1000, "cycle_ticks": 40}',
        )
    assert violation.value.diag.constraint_name == (
        "world_alternate_object_workspace_asset_behaviour"
    )


def test_a_placed_binding_is_immutable_and_a_new_pin_must_be_placeable(api: AssetsApi) -> None:
    asset_id, digest, _ = prepared(api)
    other_id, other_digest, other = prepared(
        api, cube(offset=(0.0, 0.0, 0.0), texture=png(8, 8)).build()
    )
    placed(api, asset_id, digest)
    with pytest.raises(psycopg.errors.CheckViolation, match="binding is immutable"):
        api.sql(
            "update world_alternate_object set asset_sha256 = %s, workspace_preparation_id = %s "
            "where object_id = 'object:bench'",
            other_digest,
            uuid.UUID(other["preparation"]["preparation_id"]),
        )
    withdrawn = api.post(f"/workspace-assets/{other_id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    # The repository asks first; the binding trigger answers alike for a writer that did not.
    assert api.sql(
        "select workspace_asset_placeable(%s, %s, %s) as placeable",
        api.owner,
        uuid.UUID(other["preparation"]["preparation_id"]),
        other_digest,
    ) == [{"placeable": False}]


# -- withdrawal after placement -----------------------------------------------------------------


def test_a_withdrawn_asset_stays_placed_undrawn_and_is_never_placed_again(api: AssetsApi) -> None:
    asset_id, digest, _ = prepared(api)
    version, after = placed(api, asset_id, digest)
    version_id = version["version_id"]

    withdrawn = api.post(f"/workspace-assets/{asset_id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    reread = read(api, version_id)
    # The version is what it was: withdrawal removes the source, not the person's history.
    assert reread["state_sha256"] == after["state_sha256"]
    [obj] = reread["objects"]
    assert obj["workspace_asset"]["availability"] == "withdrawn"
    assert api.get(f"/workspace-assets/{asset_id}/prepared/bytes").status_code == 410

    # Moving it is placing it again.
    moved = api.post(
        in_world(api, f"/world/versions/{version_id}/objects/object:bench/move"),
        {"base_state_sha256": reread["state_sha256"], "transform": transform(x_mm=0)},
    )
    assert moved.status_code == 410, moved.text
    assert moved.json()["code"] == "withdrawn"
    verdict = preview(api, version_id, body(reread, asset_id, subject_id="object:bench-2"))
    assert verdict.json()["blocked_reason"] == "workspace_asset_withdrawn"
    assert_refused(
        apply(api, version_id, body(reread, asset_id, digest=digest, subject_id="object:bench-2")),
        "workspace_asset_withdrawn",
    )

    # A branch is a new placement, so the object stays in the parent and is named.
    branch = new_version(api, parent_version_id=version_id, title="My square, again")
    assert branch["objects"] == []
    assert branch["left_behind"] == [
        {
            "subject": "object",
            "subject_id": "object:bench",
            "removed": False,
            "reason": "source_withdrawn",
        }
    ]

    # Removing it and taking the removal back write no new binding, so both are allowed.
    removed = api.post(
        in_world(api, f"/world/versions/{version_id}/objects/object:bench/remove"),
        {"base_state_sha256": reread["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    restored = api.post(
        in_world(api, f"/world/versions/{version_id}/objects/undo"),
        {"base_state_sha256": removed.json()["state_sha256"]},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["state_sha256"] == after["state_sha256"]
    [back] = restored.json()["objects"]
    assert back["workspace_asset"]["availability"] == "withdrawn"


# -- isolation ----------------------------------------------------------------------------------


def _stranger_world(api: AssetsApi, repository) -> tuple[str, str]:
    admin = repository.connection
    world_id = registered_world(admin, api.stranger)
    structures = WorldStructureRepository(admin, api.stranger, world_id=world_id)
    candidate = structures.preview(structural_candidate(), proposed_by=api.actor)
    snapshot = structures.apply(
        candidate.preview_id,
        base_snapshot_id=candidate.base_snapshot_id,
        base_graph_sha256=candidate.base_graph_sha256,
        base_reconstruction_sha256=candidate.base_reconstruction_sha256,
        committed_by=api.actor,
    )
    admin.commit()
    return world_id, str(snapshot.snapshot_id)


def test_another_workspace_cannot_place_or_probe_an_asset(api: AssetsApi, repository) -> None:
    asset_id, digest, view = prepared(api)
    world_id, snapshot_id = _stranger_world(api, repository)
    made = api.post(
        in_world(api, "/world/versions", world_id),
        {"title": "Theirs", "source_snapshot_id": snapshot_id},
        who="stranger",
    )
    assert made.status_code == 201, made.text
    theirs = made.json()

    def verdict(asset: str, pinned: str | None) -> dict:
        response = preview(
            api, theirs["version_id"], body(theirs, asset, digest=pinned), world_id, who="stranger"
        )
        assert response.status_code == 200, response.text
        # Each verdict echoes the id it was asked about; everything else must be the same.
        return json.loads(response.text.replace(asset, "<asset>"))

    # The owner's id, with or without its digest, reads exactly as an id never admitted.
    unknown = verdict(str(uuid.uuid4()), None)
    assert verdict(asset_id, None) == unknown
    assert verdict(asset_id, digest)["blocked_reason"] == "unknown_workspace_asset"
    assert_refused(
        apply(
            api,
            theirs["version_id"],
            body(theirs, asset_id, digest=digest),
            world_id,
            who="stranger",
        ),
        "unknown_workspace_asset",
    )
    # The same bytes admitted there are their own admission and their own preparation.
    response = api.admit(bench(), declaration(bench()), who="stranger")
    assert response.status_code == 201, response.text
    assert response.json()["asset_id"] != asset_id
    # The binding question is asked in the asking workspace only.
    assert api.sql(
        "select workspace_asset_placeable(%s, %s, %s) as placeable",
        api.owner,
        uuid.UUID(view["preparation"]["preparation_id"]),
        digest,
        workspace=api.stranger,
    ) == [{"placeable": False}]


# -- society and flight -------------------------------------------------------------------------


def test_a_placed_asset_is_an_obstacle_to_people_and_birds_withdrawn_or_not(
    api: AssetsApi, repository
) -> None:
    admin = repository.connection
    world_id = f"world:authored:{uuid.uuid4()}"
    snapshot_id, _, version_id = create_starter_authorities(
        admin, workspace_id=api.owner, actor=api.actor, title="A world of my own", world_id=world_id
    )
    place = uuid.uuid4()
    admin.execute("insert into place(workspace_id,place_id) values(%s,%s)", (api.owner, place))
    admin.commit()
    asset_id, digest, view = prepared(api)
    preparation_id = view["preparation"]["preparation_id"]
    before = read(api, str(version_id), world_id)
    applied = apply(
        api,
        str(version_id),
        {
            **body(before, asset_id, digest=digest, region_id=AUTHORED_STARTER_REGION_ID),
            "placement": {
                "subject_id": "object:bench",
                "region_id": AUTHORED_STARTER_REGION_ID,
                "transform": transform(x_mm=4_000, z_mm=4_000, yaw_microradians=0),
                "origin_role": "fictional",
            },
        },
        world_id,
    )
    assert applied.status_code == 201, applied.text

    binding = AuthoredWorldSocietyBinding(
        binding_id="workspace-asset-obstacle-v1",
        workspace_id=api.owner,
        world_id=world_id,
        version_id=version_id,
        source_snapshot_id=snapshot_id,
        place_id=place,
        region_id=AUTHORED_STARTER_REGION_ID,
    )
    session = Session(workspace_id=api.owner, actor=api.actor)

    def society_input() -> dict:
        runtime = SocietyRuntime(
            store=api.store,
            authored_bindings=[binding],
            reviewed_affordances=reviewed_affordance_registry(),
        )
        document = runtime.initial_input(
            admin, session, version_id, place, AUTHORED_STARTER_REGION_ID
        )
        admin.rollback()
        return document

    def flight():
        # Composed afresh each time: a kept input would answer for the state without reading.
        flight_input._inputs.clear()
        objects = WorldObjectRepository(
            admin, api.owner, world_id=world_id, store=api.store, workspace_assets=api.stores
        )
        made = saved_world_flight(objects, version_id, {}).flight
        admin.rollback()
        return made

    document = society_input()
    assert document["availability"] == "available", document["unavailable_reason"]
    assert {"kind": "workspace_asset", "identity": preparation_id, "sha256": digest} in document[
        "dependency_refs"
    ]
    assert "ground:+00004000:+00004000" not in {
        node["node_id"] for node in document["navigation"]["nodes"]
    }
    assert document["targets"] == []
    [solid] = [solid for solid in flight().solids if solid.object_id == "object:bench"]
    assert (solid.box.min_x_mm, solid.box.max_x_mm, solid.box.max_z_mm) == (-500, 500, 1000)

    withdrawn = api.post(f"/workspace-assets/{asset_id}/withdraw")
    assert withdrawn.status_code == 200, withdrawn.text
    # Still placed, so still in the way, until the person removes it.
    assert society_input() == document
    assert [s.box for s in flight().solids if s.object_id == "object:bench"] == [solid.box]


def test_a_versions_composition_descriptors_name_the_workspace_assets(api: AssetsApi) -> None:
    version = new_version(api)
    read = api.get(in_world(api, f"/world/versions/{version['version_id']}/capabilities"))
    assert read.status_code == 200, read.text
    described = {item["operation"]: item for item in read.json()["operations"]}
    for route in ("preview", "apply"):
        options = described[f"POST /world/versions/{{version_id}}/compositions/{route}"]["options"]
        assert options == ["GET /world/assets", "GET /workspace-assets"]


# -- the independent review's cases (deliveries/A2/delivery-2/schema-review-0126.txt) --------------


def test_a_placed_object_is_kept_and_movable_while_its_bytes_are_prepared_again(
    api: AssetsApi,
) -> None:
    """Missing bytes are a store's state, not a withdrawal: the object is carried and moves."""
    asset_id, digest, _ = prepared(api)
    version, _ = placed(api, asset_id, digest)
    version_id = version["version_id"]
    store = api.stores.for_workspace(api.owner)
    path = store.root / store.key_for(BlobId.from_hex(digest))
    path.chmod(0o644)
    path.unlink()
    assert api.post(f"/workspace-assets/{asset_id}/preparation").status_code == 202
    waiting = read(api, version_id)
    [obj] = waiting["objects"]
    assert obj["workspace_asset"]["availability"] == "unavailable_bytes"
    moved = api.post(
        in_world(api, f"/world/versions/{version_id}/objects/object:bench/move"),
        {"base_state_sha256": waiting["state_sha256"], "transform": transform(x_mm=0)},
    )
    assert moved.status_code == 200, moved.text
    branch = new_version(api, parent_version_id=version_id, title="My square, again")
    assert branch["left_behind"] == []
    assert [o["object_id"] for o in branch["objects"]] == ["object:bench"]
    assert not api.drain().errors
    for kept in (read(api, version_id), read(api, branch["version_id"])):
        assert kept["objects"][0]["workspace_asset"]["availability"] == "available"


_COPY = (
    "insert into world_alternate_object (workspace_id, world_id, version_id, object_id, "
    "asset_sha256, region_id, x_mm, y_mm, z_mm, yaw_microradians, scale_milli, origin_kind, "
    "origin_role, behaviour_key, behaviour_version, behaviour_parameters, removed, "
    "created_edit_id, last_edit_id, addition_undone, workspace_preparation_id) "
    "select workspace_id, world_id, version_id, %s, asset_sha256, region_id, x_mm, y_mm, z_mm, "
    "yaw_microradians, scale_milli, origin_kind, origin_role, behaviour_key, behaviour_version, "
    "behaviour_parameters, removed, created_edit_id, last_edit_id, addition_undone, "
    "workspace_preparation_id from world_alternate_object where object_id = 'object:bench'"
)


def test_a_pin_written_with_no_workspace_named_is_refused(api: AssetsApi) -> None:
    asset_id, digest, _ = prepared(api)
    placed(api, asset_id, digest)
    # The control: in its workspace, the same pin is one the binding question allows.
    api.sql(_COPY, "object:copy")
    with (
        api.owner_database.unscoped() as connection,
        pytest.raises(psycopg.errors.CheckViolation, match="not placeable"),
    ):
        connection.execute(_COPY, ("object:copy-2",))


def test_a_move_preview_refuses_a_withdrawn_objects_move_as_the_move_does(api: AssetsApi) -> None:
    """One shared check (``_checked_move``): the preview's reason is the move's code."""
    asset_id, digest, _ = prepared(api)
    version, after = placed(api, asset_id, digest)
    version_id = version["version_id"]
    move = {"base_state_sha256": after["state_sha256"], "transform": transform(x_mm=0)}
    preview_path = in_world(api, f"/world/versions/{version_id}/objects/object:bench/move/preview")
    ready = api.post(preview_path, move)
    assert ready.status_code == 200, ready.text
    assert (ready.json()["availability"], ready.json()["blocked_reason"]) == ("ready", None)

    assert api.post(f"/workspace-assets/{asset_id}/withdraw").status_code == 200
    blocked = api.post(preview_path, move)
    assert blocked.status_code == 200, blocked.text
    assert (blocked.json()["availability"], blocked.json()["blocked_reason"]) == (
        "blocked",
        "withdrawn",
    )
    moved = api.post(in_world(api, f"/world/versions/{version_id}/objects/object:bench/move"), move)
    assert (moved.status_code, moved.json()["code"]) == (410, "withdrawn")
    assert read(api, version_id)["state_sha256"] == after["state_sha256"]
