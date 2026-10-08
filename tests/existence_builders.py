"""How the existence sweep makes a real object of each id kind in the owner's workspace.

``tests/route_probes.py`` names each kind by its address and points at a function here. Each
function takes the sweep's owner context from ``tests/test_existence_oracle.py`` and returns the
id it made, or a mapping from address to id when making the object also made the object it lives
in: a society action request exists inside a version whose society can take one, so its builder
makes that version too and says so, and the sweep asks about the pair it made.

The owner context offers ``request`` (an HTTP call with the owner's token), ``real`` (another
kind's id, made once per test), ``repository`` (the owner's repository on an administrative
autocommit connection), ``workspace_id``, ``actor`` (the owner token's actor), ``store`` and
``tiles`` (the application's content and tile stores), ``photo_dir``, ``tmp_path``, ``app``,
``society_inputs`` (the society input the application's adapter hands a version) and ``memo``
(objects several builders share within one test). A builder goes through the API where the API
can make the object, and through the domain where only a worker or an operator can, and says
which.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any, Final

from exulanica.environment import (
    DerivedEnvironmentAsset,
    EnvironmentFeatureInput,
    EnvironmentRepository,
    FeatureIndexPublication,
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
)
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence.blob import BlobId
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository
from exulanica.world.assets import reviewed_assets
from exulanica.world.society_comparison_repository import SocietyComparisonRepository
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_experiments import DEVELOPMENT_SEEDS
from exulanica.world.society_repository import SocietyRepository

import comparison_support
from conftest import (
    DEFAULT_PAYLOAD,
    CountingVisionModel,
    ingest_observed,
    write_photo,
    write_point_map,
)
from retired_society_support import plant_retired_decision, plant_retired_society
from social_society_fixtures import social_input
from society_fixtures import SEED, society_input
from society_living_fixtures import grid_input
from static_glb_builder import cube
from test_material_recipes import _small
from thing_fixtures import kind_body, placeable_kind
from workspace_asset_support import declaration as workspace_asset_declaration
from world_support import FIXTURE_WORLD_ID, registered_world

ROOT = Path(__file__).resolve().parents[1]
#: The owner's world. The stranger's workspace holds a world by the same id, so a world route a
#: stranger is sent to reaches its own lookup rather than stopping at a world the stranger lacks.
WORLD = FIXTURE_WORLD_ID
#: The topology the owner's world is composed over, with one source slot so a source id exists.
TOPOLOGY = "existence-topology"
#: The region every authored thing in the owner's world is placed in.
REGION = "region-a"
#: A society profile each builder asks for by name, because what a society can do depends on it:
#: actions and a comparison of models need v2, a stored model proposal needs v3, which is retired
#: and so is planted as it was stored, and experiments need v4.
PURPOSEFUL = "exulanica-society/v2"
SOCIAL = "exulanica-society/v3"
LIVING = "exulanica-society/v4"


def _ok(response, *expected: int) -> Any:
    assert response.status_code in expected, (response.status_code, response.text)
    return response.json() if response.content else None


def in_world(owner, method: str, path: str, **kwargs):
    """A request to a world route with the owner's token, in the owner's world (API)."""
    return owner.request(method, path, params={"world_id": WORLD}, **kwargs)


# -- the photograph and what ingest makes of it -----------------------------------------------


def photograph(owner) -> dict[str, Any]:
    """One ingested photograph with a person in it, made once per test (domain: ingest)."""
    if "photograph" not in owner.memo:
        payload = copy.deepcopy(DEFAULT_PAYLOAD)
        payload["objects"] = [
            {
                "label": "person",
                "salience": "primary",
                "confidence": "high",
                "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
            }
        ]
        pipeline = PhotoIngestPipeline(
            owner.repository, owner.store, vision=CountingVisionModel(payload=payload)
        )
        outcome = ingest_observed(
            pipeline, owner.repository, write_photo(owner.photo_dir, "existence.jpg")
        )
        assert outcome.error is None, outcome.error
        row = owner.repository.connection.execute(
            "select capture_id, blob_sha256 from capture where capture_id = %s",
            (outcome.capture_id,),
        ).fetchone()
        owner.memo["photograph"] = dict(row)
    return owner.memo["photograph"]


def capture(owner) -> uuid.UUID:
    return photograph(owner)["capture_id"]


def evidence_span(owner) -> uuid.UUID:
    row = owner.repository.connection.execute(
        "select span_id from evidence_span "
        "where workspace_id = %s and blob_sha256 = %s and modality = 'still_image' limit 1",
        (owner.workspace_id, photograph(owner)["blob_sha256"]),
    ).fetchone()
    return row["span_id"]


def point_map(owner) -> uuid.UUID:
    """A depth artifact of the photograph, written as the depth stage writes it (domain)."""
    artifact_id, _ = write_point_map(
        owner.repository, owner.store, BlobId(bytes(photograph(owner)["blob_sha256"]))
    )
    return artifact_id


def intake_batch(owner) -> uuid.UUID:
    """A closed batch: an open one would keep the formation stream waiting (domain)."""
    batch = IntakeBatch.open(owner.repository, label="existence")
    batch.declare_size(1)
    batch.close("succeeded")
    return batch.batch_id


# -- the owner's world --------------------------------------------------------------------------


def world(owner) -> dict[str, Any]:
    """The owner's composed world: a topology with one source slot, bootstrapped (API)."""
    if "world" not in owner.memo:
        source_id = uuid.uuid4()
        registered_world(owner.repository.connection, owner.workspace_id, WORLD, actor=owner.actor)
        WorldStyleRepository(
            owner.repository.connection, owner.workspace_id, world_id=WORLD
        ).register_topology(
            TopologyContract(
                TOPOLOGY,
                (REGION,),
                (
                    TopologySourceSlot(
                        source_id=source_id,
                        slot_key="hero-memory",
                        region_id=REGION,
                        evidence_span_id=None,
                        missing_reason="no evidence was recorded",
                    ),
                ),
                world_id=WORLD,
            )
        )
        booted = _ok(
            in_world(
                owner, "POST", "/world/versions/bootstrap", json={"base_topology_digest": TOPOLOGY}
            ),
            200,
        )
        owner.memo["world"] = {**booted, "source_id": source_id}
    return owner.memo["world"]


def _place(owner) -> uuid.UUID:
    place = uuid.uuid4()
    owner.repository.connection.execute(
        "insert into place(workspace_id, place_id) values (%s, %s)", (owner.workspace_id, place)
    )
    return place


def _version_with_society(owner, profile: str, document) -> dict[str, Any]:
    """A new version of the owner's world holding a society of ``profile`` (API)."""
    snapshot = world(owner)["snapshot_id"]
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": f"existence {profile}", "source_snapshot_id": snapshot},
        ),
        201,
    )
    version_id = uuid.UUID(version["version_id"])
    owner.society_inputs[version_id] = document(version_id)
    society = _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society",
            json={"place_id": str(_place(owner)), "region_id": REGION, "profile": profile},
        ),
        200,
    )
    return {"version_id": version_id, "society": society}


def _plain_version(owner) -> uuid.UUID:
    """A new version of the owner's world with no society in it (API)."""
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": "existence", "source_snapshot_id": world(owner)["snapshot_id"]},
        ),
        201,
    )
    return uuid.UUID(version["version_id"])


def world_version(owner) -> uuid.UUID:
    """A version with a living society, the profile the most society routes can answer."""
    return _version_with_society(
        owner, LIVING, lambda version_id: grid_input(version_id=version_id)
    )["version_id"]


def source_media(owner) -> uuid.UUID:
    return world(owner)["source_id"]


def avatar(owner) -> uuid.UUID:
    """The owner's avatar, with one saved look (API).

    An avatar's subject id is the actor it belongs to. The look is saved so the owner's writes
    and resets are answered by its revision, which a stranger's never reach.
    """
    from character_appearance_fixtures import recipe

    version_id = owner.real("/world/versions/{version_id}")
    _ok(
        in_world(
            owner,
            "PUT",
            f"/world/versions/{version_id}/characters/avatar/{owner.actor}/appearance",
            json={"base_revision": 0, "recipe": recipe().model_dump(mode="json")},
        ),
        200,
    )
    return owner.actor


_TRANSFORM = {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0, "scale_milli": 1000}
#: The reviewed asset an object is made of, read from the registry migration 0042 installs for
#: every workspace; an object names its asset by content digest.
CUBE = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-cube")


def world_object(owner) -> dict[str, Any]:
    """An authored object placed in a version of its own, with no society (API).

    A version holding a living society takes an authored edit only through the society runtime's
    authored-input adapter, which this application is built without, so the object goes where an
    edit is an edit.
    """
    version_id = _plain_version(owner)
    current = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    object_id = "object:existence"
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/objects",
            json={
                "base_state_sha256": current["state_sha256"],
                "object_id": object_id,
                "asset_sha256": CUBE.content_sha256,
                "region_id": REGION,
                "transform": _TRANSFORM,
                "origin_role": "fictional",
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/objects/{object_id}": object_id,
    }


def invented_object() -> str:
    return f"object:{uuid.uuid4().hex}"


def placed_thing(owner) -> dict[str, Any]:
    """A thing placed by a shipped kind in a version of its own, with no society (API)."""
    version_id = _plain_version(owner)
    current = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    thing_id = "thing:existence"
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/things",
            json={
                "base_state_sha256": current["state_sha256"],
                "thing_id": thing_id,
                "kind": kind_body(placeable_kind()),
                "region_id": REGION,
                "pose": {"x_mm": 0, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0},
                "origin_role": "fictional",
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/things/{thing_id}": thing_id,
    }


def invented_thing() -> str:
    return f"thing:{uuid.uuid4().hex}"


# -- admitted environment sources --------------------------------------------------------------


def _frame() -> GeographicFrame:
    return GeographicFrame(
        name="nyc-grid",
        crs="EPSG:6539",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="NAVD88",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="nyc-grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 100_000, 100_000, 10_000),
    )


def _rights() -> OperationRights:
    return OperationRights(
        display=True,
        extract=True,
        index=True,
        persist=True,
        modify=True,
        compose=True,
        export=False,
        model_processing=False,
    )


def environment(owner) -> dict[str, Any]:
    """An admitted source, a render derived from it and a published feature index (domain).

    Admission is an operator's act on a file already on the machine, so the domain makes it; the
    application's own store receives the bytes, which is what its routes read.
    """
    if "environment" not in owner.memo:
        repository = EnvironmentRepository(
            owner.repository.connection, owner.workspace_id, owner.store
        )
        source_bytes = b"existence sweep source"
        source_path = owner.tmp_path / "existence-source.bin"
        source_path.write_bytes(source_bytes)
        source = SourceAdmission(
            place_id=_place(owner),
            provider_key="nyc-open-data",
            provider_original_id="existence",
            provider_revision="2026-09-23",
            expected_sha256=hashlib.sha256(source_bytes).hexdigest(),
            expected_byte_size=len(source_bytes),
            source_path="fixture/existence-source.bin",
            media_type="application/octet-stream",
            geographic_frame=_frame(),
            geographic_bounds=_bounds(),
            operation_rights=_rights(),
            attribution="Synthetic fixture",
            modification_notice="Synthetic fixture is unchanged",
            local_path=source_path,
        )
        repository.admit_source(source, actor=owner.actor)
        render_bytes = b"existence sweep render"
        render_path = owner.tmp_path / "existence-render.glb"
        render_path.write_bytes(render_bytes)
        render = DerivedEnvironmentAsset(
            admission_id=source.admission_id,
            expected_sha256=hashlib.sha256(render_bytes).hexdigest(),
            expected_byte_size=len(render_bytes),
            media_type="model/gltf-binary",
            derivation_kind="fixture-render",
            derivation_lineage={"method": "fixture/v1", "input_sha256": [source.expected_sha256]},
            geographic_frame=_frame(),
            geographic_bounds=_bounds(),
            operation_rights=_rights(),
            attribution="Synthetic fixture",
            modification_notice="Synthetic render fixture",
            local_path=render_path,
        )
        repository.register_derived(render, actor=owner.actor)
        repository.publish_feature_index(
            source.admission_id,
            FeatureIndexPublication(
                render_asset_id=render.asset_id,
                features=(
                    EnvironmentFeatureInput(
                        provider_feature_id="doitt_id:1",
                        kind="building",
                        bbox=(0, 0, 0, 100, 100, 100),
                        label="Fixture building",
                        render_batch_id=7,
                    ),
                ),
            ),
            actor=owner.actor,
        )
        owner.memo["environment"] = {
            "admission_id": source.admission_id,
            "render_asset_id": render.asset_id,
        }
    return owner.memo["environment"]


def environment_source(owner) -> uuid.UUID:
    return environment(owner)["admission_id"]


def place_declaration(caller, place_id: str | None = None) -> dict[str, Any]:
    """A request declaring a place's frame, under ``place_id`` when one is given.

    Each request states its frame in words of its own, so two requests are two different frames:
    a caller declaring an id it already declared is a conflict, never a retry of the same thing.
    """
    body: dict[str, Any] = {
        "provider_key": "nyc-open-data",
        "provider_frame_statement": (
            f"The provider publishes these bounds in this frame, statement {uuid.uuid4().hex}."
        ),
        "geographic_frame": _frame().model_dump(mode="json"),
        "geographic_bounds": _bounds().model_dump(mode="json"),
    }
    if place_id is not None:
        body["place_id"] = place_id
    return {"json": body}


def declared_place(owner) -> str:
    """A place whose frame a provider declared (API)."""
    made = _ok(
        owner.request("POST", "/environment-resources/places", **place_declaration(owner)), 201
    )
    return made["place_id"]


def environment_instance(owner) -> dict[str, Any]:
    """An admitted render placed whole in a version of its own, with no society (API)."""
    version_id = _plain_version(owner)
    current = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    admitted = environment(owner)
    instance_id = "environment:existence"
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/environment-instances",
            json={
                "base_state_sha256": current["state_sha256"],
                "instance_id": instance_id,
                "admission_id": str(admitted["admission_id"]),
                "render_asset_id": str(admitted["render_asset_id"]),
                "publication_id": None,
                "selection": {"kind": "whole_asset"},
                "source_anchor": {
                    "frame_name": "nyc-grid",
                    "coordinate_scale": 1000,
                    "coordinates": [10, 20, 0],
                },
                "region_id": REGION,
                "transform": _TRANSFORM,
                "origin_role": "fictional",
            },
        ),
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/environment-instances/{instance_id}": instance_id,
    }


def invented_environment_instance() -> str:
    return f"environment:{uuid.uuid4().hex}"


# -- the owner's settings: interaction policy and style -----------------------------------------


def interaction_preview_request(caller, proposal_id: str) -> dict[str, Any]:
    """A request previewing a field-of-view choice under ``proposal_id``, made against the
    caller's own current interaction policy and structural world."""
    base = _ok(
        caller.request("GET", "/world/interactions/current", params={"world_id": WORLD}), 200
    )
    return {
        "params": {"world_id": WORLD},
        "json": {
            "proposal_id": proposal_id,
            "origin": "settings",
            "origin_reference": "existence-panel",
            "base_policy_version_id": (base.get("current") or {}).get("version_id"),
            "base_structure_snapshot_id": base["base_structure_snapshot_id"],
            "base_topology_sha256": base["base_topology_sha256"],
            "capability_patch": {"comfort.field-of-view-degrees": 82},
            "proposal_input": {"control_ids": ["fieldOfView"]},
            "explanation": "Apply the field-of-view choice made in Settings.",
        },
    }


def _interaction_preview(owner) -> dict[str, Any]:
    if "interaction" not in owner.memo:
        world(owner)
        proposal_id = str(uuid.uuid4())
        preview = _ok(
            owner.request(
                "POST",
                "/world/interactions/previews",
                **interaction_preview_request(owner, proposal_id),
            ),
            201,
        )
        owner.memo["interaction"] = {
            "proposal_id": proposal_id,
            "preview_id": preview["preview_id"],
        }
    return owner.memo["interaction"]


def interaction_preview(owner) -> str:
    return _interaction_preview(owner)["preview_id"]


def interaction_proposal(owner) -> str:
    return _interaction_preview(owner)["proposal_id"]


def style_preview_request(caller, proposal_id: str) -> dict[str, Any]:
    """A request previewing a style under ``proposal_id``, made against the caller's own
    current style and topology."""
    current = _ok(caller.request("GET", "/world/styles/current", params={"world_id": WORLD}), 200)
    return {
        "params": {"world_id": WORLD},
        "json": {
            "proposal_id": proposal_id,
            "origin": "settings",
            "origin_reference": "appearance-panel",
            "scope": {"kind": "global"},
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
            "profile": {
                "profile_id": "origin-landscape",
                "profile_version": 1,
                "parameters": {"vitality": 0.25},
            },
        },
    }


def _style_preview(owner) -> dict[str, Any]:
    if "style" not in owner.memo:
        world(owner)
        proposal_id = str(uuid.uuid4())
        preview = _ok(
            owner.request(
                "POST", "/world/styles/previews", **style_preview_request(owner, proposal_id)
            ),
            201,
        )
        owner.memo["style"] = {"proposal_id": proposal_id, "preview_id": preview["preview_id"]}
    return owner.memo["style"]


def style_preview(owner) -> str:
    return _style_preview(owner)["preview_id"]


def style_proposal(owner) -> str:
    return _style_preview(owner)["proposal_id"]


# -- societies ----------------------------------------------------------------------------------


def action_request(owner) -> dict[str, Any]:
    """A user action in a purposeful society, with the version that holds it (API)."""
    made = _version_with_society(owner, PURPOSEFUL, society_input)
    version_id, state = made["version_id"], made["society"]
    targets = owner.society_inputs[version_id]["targets"]
    target = next(row for row in targets if row["affordance"] == "rest")
    action = _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/actions",
            json={
                "idempotency_key": str(uuid.uuid4()),
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
                "subject_id": state["state"]["inhabitants"][0]["id"],
                "intent": {"kind": "go_to", "target_id": target["target_id"]},
            },
        ),
        200,
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/actions/{request_id}": action["request"][
            "request_id"
        ],
    }


def decision_request(owner) -> dict[str, Any]:
    """A stored model decision request in a social society, with its version (domain).

    The social engine and its proposal route are retired, so no request makes either one: the
    society is planted as its creation stored it, and the request as that route recorded one with
    no provider configured, which is how every such request was recorded. A stored one still reads.
    """
    snapshot = world(owner)["snapshot_id"]
    version = _ok(
        in_world(
            owner,
            "POST",
            "/world/versions",
            json={"title": f"existence {SOCIAL}", "source_snapshot_id": snapshot},
        ),
        201,
    )
    version_id = uuid.UUID(version["version_id"])
    document = social_input(version_id)
    owner.society_inputs[version_id] = document
    connection = owner.repository.connection
    society = SocietyRepository(
        connection, owner.workspace_id, world_id=WORLD, input_authorizer=lambda _document: None
    )
    state = plant_retired_society(
        society,
        version_id,
        place_id=_place(owner),
        region_id=REGION,
        seed=SEED,
        actor=owner.actor,
        profile=SOCIAL,
        initial_input=document,
    )
    key = uuid.uuid4()
    with connection.transaction():
        plant_retired_decision(
            SocietyDecisionRepository(society),
            version_id,
            request_id=key,
            subject_id=state["state"]["social"]["cast_ids"][0],
            result={
                "status": "unavailable",
                "reason": "provider_not_configured",
                "proposal": None,
                "provider": None,
            },
        )
    connection.commit()
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/decisions/{request_id}": str(key),
    }


def _comparison(owner) -> dict[str, Any]:
    """A development comparison over a version's purposeful society (domain: only the local
    command defines one, and runs are reserved by its runner)."""
    if "comparison" not in owner.memo:
        made = _version_with_society(owner, PURPOSEFUL, society_input)
        version_id = made["version_id"]
        comparisons = SocietyComparisonRepository(
            SocietyRepository(
                owner.repository.connection,
                owner.workspace_id,
                world_id=WORLD,
                input_authorizer=lambda _document: None,
            )
        )
        # The district society holds more people than a saved world's, so the test catalogs
        # raise the bound as well as committing the tests' seeds.
        catalogs = comparison_support.seeded_catalogs(population_maximum=512)
        comparison_id = uuid.uuid4()
        comparisons.define(
            version_id,
            comparison_id=comparison_id,
            body=comparison_support.development_body(catalogs),
            created_by=owner.actor,
            role=comparison_support.PEOPLE_ROLE,
            catalogs=catalogs,
        )
        run_id = comparisons.reserve(
            comparison_id, arm="routine", seed=comparison_support.SEEDS[0], created_by=owner.actor
        )
        owner.memo["comparison"] = {
            "/world/versions/{version_id}": version_id,
            "/world/versions/{version_id}/society/comparisons/{comparison_id}": comparison_id,
            "/world/versions/{version_id}/society/comparisons/{comparison_id}/runs/{run_id}": (
                run_id
            ),
        }
    return owner.memo["comparison"]


def comparison(owner) -> dict[str, Any]:
    made = _comparison(owner)
    return {
        address: made[address]
        for address in (
            "/world/versions/{version_id}",
            "/world/versions/{version_id}/society/comparisons/{comparison_id}",
        )
    }


def comparison_run(owner) -> dict[str, Any]:
    return _comparison(owner)


def society_input_seq(owner) -> int:
    """The genesis input of the default version's living society: every society holds input 1."""
    owner.real("/world/versions/{version_id}")
    return 1


def invented_input_seq() -> str:
    """An input sequence no society reaches, inside the bound the route's path accepts."""
    return "2147483000"


def experiment(owner) -> str:
    """A no-op experiment over the default version's living society (API)."""
    version_id = owner.real("/world/versions/{version_id}")
    experiment_id = str(uuid.uuid4())
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/experiments",
            json={
                "experiment_id": experiment_id,
                "baseline_input_seq": 1,
                "treatment_input_seq": 1,
                "intervention": {"kind": "noop"},
                "population": 3,
                "warmup_ticks": 2,
                "followup_ticks": 3,
            },
        ),
        200,
        201,
    )
    return experiment_id


def experiment_attempt(owner) -> str:
    version_id = owner.real("/world/versions/{version_id}")
    experiment_id = owner.real("/world/versions/{version_id}/society/experiments/{experiment_id}")
    attempt_id = str(uuid.uuid4())
    _ok(
        in_world(
            owner,
            "POST",
            f"/world/versions/{version_id}/society/experiments/{experiment_id}/attempts",
            json={"attempt_id": attempt_id, "seed_sha256": DEVELOPMENT_SEEDS[0]},
        ),
        200,
        201,
        202,
    )
    return attempt_id


# -- materials and saved worlds ------------------------------------------------------------------


def material_recipe(owner) -> str:
    """A recipe varied from a published set (API)."""
    made = _ok(owner.request("POST", "/materials/recipes", json={"recipe": _small()}), 201)
    return made["recipe_id"]


def workspace_asset_request() -> dict[str, Any]:
    """The multipart request that admits a one-metre cube as the caller's own work."""
    payload = cube().build()
    return {
        "data": {"declaration": json.dumps(workspace_asset_declaration(payload))},
        "files": {"content": ("object.glb", payload, "model/gltf-binary")},
    }


def workspace_asset(owner) -> str:
    """A person's own admitted asset, not yet prepared (API)."""
    return _ok(owner.request("POST", "/workspace-assets", **workspace_asset_request()), 201)[
        "asset_id"
    ]


def door_grant(owner) -> str:
    """A grant letting the sweep's test bridge bring one visitor into the owner's world (API)."""
    registered_world(owner.repository.connection, owner.workspace_id, WORLD, actor=owner.actor)
    made = _ok(
        in_world(
            owner,
            "POST",
            "/door/grants",
            json={
                "idempotency_key": "existence-sweep-grant",
                "bridge": "test-bridge",
                "visitors_maximum": 1,
                "kinds": ["player"],
                # The version visitors would arrive in; a grant records it and asks for no society
                # until one crosses.
                "version_id": "6f2b9b7e-0d5c-5b8e-9a51-3c4d2e1f0a77",
            },
        ),
        200,
        201,
    )
    return made["grant"]["grant_id"]


def world_entry(owner) -> str:
    """The workspace's starter world (API)."""
    return _ok(owner.request("POST", "/world-entries/starter", json={"title": "My world"}), 200)[
        "entry_id"
    ]


# -- the recorded library ------------------------------------------------------------------------


def named_place(owner) -> uuid.UUID:
    """The place the photograph's vision pass proposed, named by the owner's actor (domain).

    The actor matters: only the account holder who stated a place's name may allow it to go
    anywhere, so a place named by anybody else could not show the owner's answer on its routes.
    """
    occurrence = owner.repository.connection.execute(
        "select occurrence_id from occurrence where class = 'place' and capture_id = %s limit 1",
        (capture(owner),),
    ).fetchone()
    assert occurrence is not None, "the vision payload proposes a place"
    named = name_occurrence(
        IdentityRepository(owner.repository.connection, owner.workspace_id),
        AssertionWriter(owner.repository.connection, owner.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name="Gullfoss",
        actor=owner.actor,
    )
    return named.entity_id


def place_bridge(owner) -> str:
    """A confirmed bridge from a canonical place to the owner's named place (API)."""
    made = _ok(
        owner.request(
            "POST",
            "/selection/place-bridges",
            json={
                "canonical_place_id": str(_place(owner)),
                "memory_place_entity_id": str(named_place(owner)),
            },
        ),
        201,
    )
    return made["decision_id"]


def world_read_place(owner) -> uuid.UUID:
    """A place with no anchor, which its owner is told about and a stranger is not (domain)."""
    return _place(owner)


def companion_answer(owner) -> str:
    """A remembered companion answer (API)."""
    made = _ok(
        owner.request(
            "POST",
            "/companion/memory/answers",
            json={
                "question": "When were these photographs taken?",
                "answer_text": "These photographs were taken on 2026-02-01.",
                "prompt_version": "selection-3",
                "latency_ms": 1,
                "composed": "none",
                "used_fallback": False,
                "unanswered_attempts": 0,
                "unanswered_cost_unknown": False,
            },
        ),
        201,
    )
    return made["answer_id"]


def person_subject(owner) -> str:
    """A person subject, the thing consent is recorded for (API)."""
    return _ok(owner.request("POST", "/person-subjects", json={}), 200, 201)["subject_id"]


def model_right(owner) -> uuid.UUID:
    """A hosted vision right over a personal photograph its account holder admitted (domain)."""
    from conftest import photo_bytes
    from test_personal_model_right import HOSTED, admit_personal, grant

    personal = admit_personal(owner.repository, owner.store, photo_bytes(), "personal.jpg")
    return grant(personal, HOSTED.identities[0], HOSTED.destination).right_id


def derivative_job(owner) -> uuid.UUID:
    """A queued derivative job a worker has claimed, which records its first event (domain)."""
    from exulanica.ingest import derivative_queue

    job_id = derivative_queue.enqueue(
        owner.repository.connection,
        owner.workspace_id,
        batch_id=intake_batch(owner),
        capture_ids=[capture(owner)],
    )
    claimed = derivative_queue.claim(
        owner.repository.connection, owner.workspace_id, worker="existence", lease_seconds=60
    )
    assert claimed is not None
    return job_id


def reference_request(owner) -> uuid.UUID:
    """A queued reference request and its job (domain: the API asks for web notes only where an
    installation configures a source and lists the workspace)."""
    from exulanica.references import store
    from exulanica.references.drafting import reference_prompts

    made, _ = store.create_request(
        owner.repository.connection,
        owner.workspace_id,
        offered_to=(owner.workspace_id,),
        owner_actor_id=owner.actor,
        purpose="kind",
        web=True,
        description="a harbour town with whitewashed houses",
        withheld_words=(),
        prompts_sha256=reference_prompts().sha256,
    )
    return made.reference_id


def piece_request(owner) -> uuid.UUID:
    """A requested piece of the owner's world's look, a well in the default pack (domain: the
    API asks only within the workspace's GPU allowance)."""
    from exulanica.generation import store
    from exulanica.generation.requests import (
        GPU_PROVIDER,
        LookReference,
        generation_catalogs,
        plan_requests,
    )
    from exulanica.world.style_pack_library import style_pack_library

    world(owner)
    library = style_pack_library()
    pack = library.default_pack
    look = LookReference(pack.pack_id, pack.version, pack.manifest_sha256)
    planned = plan_requests([("well", 1)], look, library=library)
    compute = generation_catalogs().compute.for_provider(GPU_PROVIDER)
    made, _ = store.create_piece_requests(
        owner.repository.connection,
        owner.workspace_id,
        requested_by=owner.actor,
        world_id=WORLD,
        look=look,
        planned=planned,
        worst_cases=[compute.worst_case_usd(plan.variants) for plan in planned],
    )
    return made[0].piece_request_id


def reconstruction_job(owner) -> uuid.UUID:
    """A queued scene reconstruction over three admitted captures (domain)."""
    from test_reconstruction_scene_jobs import _captures, _enqueue

    job_id, _ = _enqueue(owner.repository, _captures(owner.repository))
    return job_id


def reconstruction_scene(owner) -> uuid.UUID:
    """A published scene every scene route can read for its owner (domain: the scene worker)."""
    from test_world_read_route import _scene_in

    return _scene_in(owner, owner.repository, owner.tmp_path)


def trained_scene(owner) -> str:
    """A trained Gaussian scene, its blobs copied into the application's store (domain)."""
    from exulanica.store.local import LocalContentAddressedStore

    from test_training_inputs import scene_sample

    root = owner.tmp_path / "trained"
    root.mkdir()
    _, materials = scene_sample(owner.repository, root)
    trained_store = LocalContentAddressedStore(root / "store")
    for blob in trained_store.iter_blob_ids():
        owner.store.put_bytes(trained_store.get(blob))
    return next(
        asset["artifact_id"]
        for material in materials
        for asset in material["assets"]
        if asset["role"] == "trained_geometry"
    )


def baked_tile(owner) -> str:
    """A tile an offline bake recorded, in the application's tile store (domain: the bake)."""
    from exulanica.world.baked_tiles import BakedTileRepository

    from test_corridor_tile_route import _record

    key = uuid.uuid4()
    _record(
        BakedTileRepository(connection=owner.repository.connection, store=owner.tiles),
        key,
        2,
        b"an existence sweep tile",
    )
    return str(key)


def reviewed_asset(owner) -> str:
    """The reviewed cube, which migration 0042 registers for every workspace."""
    return CUBE.asset_key


def character_catalog(owner) -> str:
    """A character catalog the host published (domain: host administration, owner connection).

    Written as the publication row alone: the read serves the document, and the containers a
    catalog names are the reviewed registry's concern, which this sweep leaves alone.
    """
    from exulanica.world.character_catalogs import layered_bundle, read_publication_document
    from psycopg.types.json import Jsonb

    characters = ROOT / "assets/characters"
    publication = read_publication_document(
        layered_bundle(
            json.loads((characters / "catalog.json").read_text()),
            json.loads((characters / "looks.json").read_text()),
        )
    )
    connection = owner.repository.connection
    connection.execute(
        "insert into character_catalog_publication"
        "(catalog_sha256,catalog_id,profile,kind,revision,document,producer) "
        "values(%s,%s,%s,%s,%s,%s,'existence sweep')",
        (
            publication.catalog_sha256,
            publication.catalog_id,
            publication.profile,
            publication.kind,
            publication.revision,
            Jsonb(publication.document),
        ),
    )
    connection.commit()
    return publication.catalog_sha256


def style_pack_content(owner) -> str:
    """A committed style pack's manifest, which the host serves every workspace by its digest."""
    from exulanica.world.style_pack_library import style_pack_library

    return style_pack_library().packs[0].manifest_sha256


def thing_library_content(owner) -> str:
    """A shipped thing kind, which the host serves every workspace by its digest."""
    from exulanica.world.thing_library import thing_library

    return thing_library().listing()["kinds"][0]["sha256"]


def invented_digest() -> str:
    return uuid.uuid4().hex * 2


def _held_creature(owner):
    """A creature drafted in the test fixtures and kept in the owner's own thing store, its sketch's
    container in the application's looks namespace (domain: the creature route comes later)."""
    if "held_creature" not in owner.memo:
        from exulanica.things.creatures import assemble_creature
        from exulanica.world.thing_store import ThingStore

        from test_creature_bodies import BY, _form, _recipe

        creature = assemble_creature(_form(_recipe("ten_legs"), label="swept ten legs"), by=BY)
        looks = owner.app.state.services.content_stores.looks.for_workspace(owner.workspace_id)
        ThingStore(owner.repository.connection, owner.workspace_id, looks).keep_creature(
            creature, created_by=owner.actor
        )
        owner.memo["held_creature"] = creature
    return owner.memo["held_creature"]


def held_look(owner) -> str:
    """The sketch look of a creature the owner's workspace holds, by its document's digest."""
    return _held_creature(owner).sketch.sha256


def held_kind(owner) -> str:
    """The kind of a creature the owner's workspace holds, by its document's digest."""
    return _held_creature(owner).kind.sha256


def district_version(owner) -> uuid.UUID:
    """A version whose district the host registered over two admitted city sources (domain).

    A district is host configuration: an operator admits the committed Flatiron sources and
    registers the binding, which no request can do, so the society runtime is rebuilt with it.
    """
    from exulanica.api.society_runtime import SocietyRuntime, SocietyRuntimeBinding

    base = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
    reading = ROOT / "assets/owned-world/flatiron-interpretation-v1/district-interpretation.json"
    version_id = _plain_version(owner)
    version = _ok(in_world(owner, "GET", f"/world/versions/{version_id}"), 200)
    place = _place(owner)
    admissions = EnvironmentRepository(owner.repository.connection, owner.workspace_id, owner.store)
    sources = []
    for declaration in json.loads((base.parent / "admission-plan.json").read_bytes())["sources"]:
        source = SourceAdmission.model_validate(
            {
                **declaration,
                "admission_id": uuid.uuid4(),
                "place_id": place,
                "local_path": base.parent / declaration["local_path"],
            }
        )
        saved = admissions.admit_source(source, actor=owner.actor)
        sources.append(
            {
                "dataset_id": source.provider_original_id,
                "admission_id": source.admission_id,
                "source_sha256": source.expected_sha256,
                "receipt_sha256": saved.receipt_sha256,
            }
        )
    interpreted = json.loads(reading.read_bytes())
    binding = SocietyRuntimeBinding(
        binding_id="existence-district",
        workspace_id=owner.workspace_id,
        world_id=version["world_id"],
        version_id=version_id,
        source_snapshot_id=world(owner)["snapshot_id"],
        place_id=place,
        region_id=REGION,
        district_id=interpreted["district_id"],
        frame=interpreted["frame"],
        translation_mm=(0, 0, 0),
        yaw_microradians=0,
        scale_milli=1000,
        base_artifact_sha256=owner.store.put_file(base).blob_id.hex,
        interpretation_artifact_sha256=owner.store.put_file(reading).blob_id.hex,
        interpretation_document_sha256=interpreted["document_sha256"],
        sources=sources,
    )
    plate = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.marker-plate")
    registry = {
        plate.content_sha256: {
            "asset_key": plate.asset_key,
            "affordance": "rest",
            "duration_ticks": 3,
            "footprint_half_extents_mm": [500, 500],
            "blocks_navigation": False,
            "reach_mm": 1500,
        }
    }
    runtime = SocietyRuntime(store=owner.store, bindings=[binding], reviewed_affordances=registry)
    owner.app.state.services = dataclasses.replace(
        owner.app.state.services, society_runtime=runtime
    )
    return version_id


# -- world projects -------------------------------------------------------------------------------


def _world_project(owner) -> dict[str, Any]:
    """A project in the owner's world with one goal, the goal shared (API)."""
    if "world_project" not in owner.memo:
        version_id = _plain_version(owner)
        project = _ok(
            in_world(
                owner,
                "POST",
                "/world/projects",
                json={"title": "existence", "version_id": str(version_id)},
            ),
            201,
        )
        route = f"/world/projects/{project['project_id']}"
        item = _ok(
            in_world(
                owner,
                "POST",
                f"{route}/items",
                json={
                    "base_revision": project["revision"],
                    "kind": "goal",
                    "basis": "user_statement",
                    "text": "a quiet square",
                },
            ),
            201,
        )
        shared = _ok(
            in_world(
                owner,
                "POST",
                f"{route}/shares",
                json={"base_revision": item["project_revision"], "item_ids": [item["item_id"]]},
            ),
            200,
        )
        owner.memo["world_project"] = {
            "/world/projects/{project_id}": project["project_id"],
            "/world/projects/{project_id}/items/{item_id}": item["item_id"],
            "/world/projects/{project_id}/shares/{share_id}": shared["shares"][0]["share_id"],
        }
    return owner.memo["world_project"]


def world_project(owner) -> str:
    return _world_project(owner)["/world/projects/{project_id}"]


def world_project_item(owner) -> dict[str, Any]:
    made = _world_project(owner)
    return {
        "/world/projects/{project_id}": made["/world/projects/{project_id}"],
        "/world/projects/{project_id}/items/{item_id}": made[
            "/world/projects/{project_id}/items/{item_id}"
        ],
    }


def world_project_share(owner) -> dict[str, Any]:
    made = _world_project(owner)
    return {
        "/world/projects/{project_id}": made["/world/projects/{project_id}"],
        "/world/projects/{project_id}/shares/{share_id}": made[
            "/world/projects/{project_id}/shares/{share_id}"
        ],
    }


# -- requests made from the owner's own objects ----------------------------------------------------


def feature_index_request(owner) -> dict[str, Any]:
    """A publication naming the owner's own render, so the owner's answer turns on the source."""
    return {
        "json": {
            "render_asset_id": str(environment(owner)["render_asset_id"]),
            "features": [
                {"provider_feature_id": "feature", "kind": "terrain", "bbox": [0, 0, 10, 10]}
            ],
        }
    }


def _generated(owner) -> dict[str, Any]:
    """A world generated from the small-town recipe, made once per test (API)."""
    if "generated" not in owner.memo:
        owner.memo["generated"] = _ok(
            owner.request(
                "POST", "/worlds/generated", json={"recipe": "small_town", "title": "A town"}
            ),
            201,
        )
    return owner.memo["generated"]


def generated_tile(owner) -> dict[str, Any]:
    """A world generated from the small-town recipe (API), and the key its first tile's bake is
    stored under. No test bakes it, so the owner is answered that the world names no such baked
    tile, where a stranger is answered that the world does not exist."""
    from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
    from exulanica.grammar.grammars.city.generation.tiles import tile_record
    from exulanica.grammar.grammars.specified import GENERATED_LOD
    from exulanica.ingest.stages import STAGES, baked_tile_id
    from exulanica.world.generated_worlds import generation_receipt

    entry = _generated(owner)
    _, receipt = generation_receipt(
        owner.repository.connection,
        owner.workspace_id,
        entry["world_id"],
        uuid.UUID(entry["source_snapshot_id"]),
    )
    tile_x, tile_y = receipt["tiles"][0]
    record = tile_record(
        seed=receipt["seed"],
        catalogs=load_city_catalogs(),
        tile_x=tile_x,
        tile_y=tile_y,
        lod=GENERATED_LOD,
    )
    return {
        "/world/versions/{version_id}": entry["authored_version_id"],
        "/world/versions/{version_id}/tiles/{baked_tile_id}": baked_tile_id(
            STAGES["baked_tile"], record
        ),
    }


def generated_tile_request(owner) -> dict[str, Any]:
    """A request in the generated world the tile belongs to."""
    generated_tile(owner)
    return {"params": {"world_id": owner.memo["generated"]["world_id"]}}


#: The signal a fixture comparison's group names. No read of a comparison or its runs compiles the
#: roads, so the town need not be one whose roads the traffic drives.
_FIXTURE_SIGNAL: Final = {"signal_id": "fixture-signal", "junction_id": "fixture-junction"}


def _signal_comparison(owner) -> dict[str, Any]:
    """A development signal comparison over the generated town's roads, assembled as the runner
    assembles one over a fixture signal, with its fixed-timing run reserved (domain)."""
    from exulanica.api.signal_comparison_runner import SignalComparisonRunner
    from exulanica.api.society_comparison_runner import ComparisonArm
    from exulanica.models.manifest import load_manifest
    from exulanica.world.decision_roles import decision_roles
    from exulanica.world.signal_comparison_repository import SignalComparisonRepository

    if "signal_comparison" not in owner.memo:
        entry = _generated(owner)
        version_id = uuid.UUID(entry["authored_version_id"])
        repository = SignalComparisonRepository(
            owner.repository.connection, owner.workspace_id, entry["world_id"]
        )
        runner = SignalComparisonRunner(
            database=None,
            client=None,
            policy_for=lambda _workspace: None,
            manifest=load_manifest(),
            manifest_sha256="a" * 64,
            workspace_id=owner.workspace_id,
            world_id=entry["world_id"],
            actor=owner.actor,
        )
        model = load_manifest().offered_models(decision_roles().deciding_for("signal").chosen)[0]
        seed = runner.catalogs.development_seeds()[0]
        body = runner.body(
            [ComparisonArm(model.provider, model.model_id)], [seed], control=False, group=None
        )
        comparison_id = uuid.uuid4()
        repository.define(
            comparison_id,
            runner.definition(
                version_id, repository.roads(version_id), [_FIXTURE_SIGNAL], body=body
            ),
            created_by=owner.actor,
        )
        run_id = repository.reserve(comparison_id, arm="fixed", seed=seed, created_by=owner.actor)
        owner.repository.connection.commit()
        owner.memo["signal_comparison"] = {
            "/world/versions/{version_id}": str(version_id),
            "/world/versions/{version_id}/traffic/comparisons/{comparison_id}": comparison_id,
            "/world/versions/{version_id}/traffic/comparisons/{comparison_id}/runs/{run_id}": (
                run_id
            ),
        }
    return owner.memo["signal_comparison"]


def signal_comparison(owner) -> dict[str, Any]:
    made = _signal_comparison(owner)
    return {
        address: made[address]
        for address in (
            "/world/versions/{version_id}",
            "/world/versions/{version_id}/traffic/comparisons/{comparison_id}",
        )
    }


def signal_comparison_run(owner) -> dict[str, Any]:
    return _signal_comparison(owner)


def signal_comparison_request(owner) -> dict[str, Any]:
    """A request in the generated world the signal comparison belongs to."""
    _signal_comparison(owner)
    return {"params": {"world_id": owner.memo["generated"]["world_id"]}}


def entry_update_request(owner) -> dict[str, Any]:
    """The owner's saved world, saved again at the cursor it was read at."""
    entry_id = owner.real("/world-entries/{entry_id}")
    entry = _ok(owner.request("GET", f"/world-entries/{entry_id}"), 200)
    return {
        "json": {
            "base_revision": entry["revision"],
            "authored_version_id": entry["authored_version_id"],
            "expected_authored_state_sha256": entry["current_authored_state_sha256"],
            "expected_authored_edit_seq": entry["current_authored_edit_seq"],
            "style_version_id": entry["style_version_id"],
        }
    }


def style_apply_request(owner) -> dict[str, Any]:
    """The owner's style preview applied over the style and topology it was made against."""
    style_preview(owner)
    current = _ok(in_world(owner, "GET", "/world/styles/current"), 200)
    return {
        "params": {"world_id": WORLD},
        "json": {
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
        },
    }


def character_preparation(owner) -> uuid.UUID:
    """A body the owner asked to prepare, still waiting for a preparer (domain: the queue).

    Requested as the character routes request one, and left requested: the sweep asks who may
    read and cancel a preparation, not what a preparer makes of it.
    """
    from exulanica.store.namespaces import LocalWorkspaceStores
    from exulanica.world.character_parametric import PREPARER_ID, PREPARER_VERSION
    from exulanica.world.workspace_preparations import WorkspacePreparationRepository

    queue = WorkspacePreparationRepository(
        owner.repository.connection,
        owner.workspace_id,
        owner.actor,
        stores=LocalWorkspaceStores(owner.tmp_path / "workspace-assets"),
    )
    zero = "0" * 64
    record = queue.request(
        input_kind="character_recipe",
        preparer_id=PREPARER_ID,
        preparer_version=PREPARER_VERSION,
        parameters={
            "family_id": "makehuman-parametric/v1",
            "family_sha256": zero,
            "values": {},
            "seed": 0,
        },
        inputs={"catalog_sha256": zero, "family": {}, "identity_sha256": zero},
    )
    return record.preparation_id
