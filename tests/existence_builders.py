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
from typing import Any

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
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.society_experiments import DEVELOPMENT_SEEDS

from conftest import (
    DEFAULT_PAYLOAD,
    CountingVisionModel,
    ingest_observed,
    write_photo,
    write_point_map,
)
from social_society_fixtures import social_input
from society_fixtures import SEED
from society_living_fixtures import grid_input
from test_material_recipes import _small

ROOT = Path(__file__).resolve().parents[1]
#: The topology the owner's world is composed over, with one source slot so a source id exists.
TOPOLOGY = "existence-topology"
#: The region every authored thing in the owner's world is placed in.
REGION = "region-a"
#: A society profile each builder asks for by name, because what a society can do depends on it:
#: actions need v2 or v3, model decisions need v3 and experiments need v4.
SOCIAL = "exulanica-society/v3"
LIVING = "exulanica-society/v4"


def _ok(response, *expected: int) -> Any:
    assert response.status_code in expected, (response.status_code, response.text)
    return response.json() if response.content else None


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
        WorldStyleRepository(owner.repository.connection, owner.workspace_id).register_topology(
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
            )
        )
        booted = _ok(
            owner.request(
                "POST", "/world/versions/bootstrap", json={"base_topology_digest": TOPOLOGY}
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
        owner.request(
            "POST",
            "/world/versions",
            json={"title": f"existence {profile}", "source_snapshot_id": snapshot},
        ),
        201,
    )
    version_id = uuid.UUID(version["version_id"])
    owner.society_inputs[version_id] = document(version_id)
    society = _ok(
        owner.request(
            "POST",
            f"/world/versions/{version_id}/society",
            json={
                "place_id": str(_place(owner)),
                "region_id": REGION,
                "seed": SEED,
                "profile": profile,
            },
        ),
        200,
    )
    return {"version_id": version_id, "society": society}


def _plain_version(owner) -> uuid.UUID:
    """A new version of the owner's world with no society in it (API)."""
    version = _ok(
        owner.request(
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
        owner.request(
            "PUT",
            f"/world/versions/{version_id}/characters/avatar/{owner.actor}/appearance",
            params={"world_id": DEFAULT_WORLD_ID},
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
    current = _ok(owner.request("GET", f"/world/versions/{version_id}"), 200)
    object_id = "object:existence"
    _ok(
        owner.request(
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


def declared_place(owner) -> str:
    """A place whose frame a provider declared (API)."""
    made = _ok(
        owner.request(
            "POST",
            "/environment-resources/places",
            json={
                "provider_key": "nyc-open-data",
                "provider_frame_statement": "The provider publishes these bounds in this frame.",
                "geographic_frame": _frame().model_dump(mode="json"),
                "geographic_bounds": _bounds().model_dump(mode="json"),
            },
        ),
        201,
    )
    return made["place_id"]


def environment_instance(owner) -> dict[str, Any]:
    """An admitted render placed whole in a version of its own, with no society (API)."""
    version_id = _plain_version(owner)
    current = _ok(owner.request("GET", f"/world/versions/{version_id}"), 200)
    admitted = environment(owner)
    instance_id = "environment:existence"
    _ok(
        owner.request(
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


def _interaction_preview(owner) -> dict[str, Any]:
    if "interaction" not in owner.memo:
        world(owner)
        base = _ok(owner.request("GET", "/world/interactions/current"), 200)
        proposal_id = str(uuid.uuid4())
        preview = _ok(
            owner.request(
                "POST",
                "/world/interactions/previews",
                json={
                    "proposal_id": proposal_id,
                    "origin": "settings",
                    "origin_reference": "existence-panel",
                    "base_policy_version_id": None,
                    "base_structure_snapshot_id": base["base_structure_snapshot_id"],
                    "base_topology_sha256": base["base_topology_sha256"],
                    "capability_patch": {"comfort.field-of-view-degrees": 82},
                    "proposal_input": {"control_ids": ["fieldOfView"]},
                    "explanation": "Apply the field-of-view choice made in Settings.",
                },
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


def _style_preview(owner) -> dict[str, Any]:
    if "style" not in owner.memo:
        world(owner)
        current = _ok(owner.request("GET", "/world/styles/current"), 200)
        proposal_id = str(uuid.uuid4())
        preview = _ok(
            owner.request(
                "POST",
                "/world/styles/previews",
                json={
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
    """A user action in a social society, with the version that holds it (API)."""
    made = _version_with_society(owner, SOCIAL, social_input)
    version_id, state = made["version_id"], made["society"]
    targets = owner.society_inputs[version_id]["targets"]
    target = next(row for row in targets if row["affordance"] == "rest")
    action = _ok(
        owner.request(
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
    """A model decision request in a social society, with its version (API).

    The application has no decision provider, so the request is recorded with the reason it
    was not answered, which is a real request all the same.
    """
    made = _version_with_society(owner, SOCIAL, social_input)
    version_id, state = made["version_id"], made["society"]
    key = str(uuid.uuid4())
    _ok(
        owner.request(
            "POST",
            f"/world/versions/{version_id}/society/decisions",
            json={
                "idempotency_key": key,
                "subject_id": state["state"]["social"]["cast_ids"][0],
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
            },
        ),
        200,
        201,
    )
    return {
        "/world/versions/{version_id}": version_id,
        "/world/versions/{version_id}/society/decisions/{request_id}": key,
    }


def experiment(owner) -> str:
    """A no-op experiment over the default version's living society (API)."""
    version_id = owner.real("/world/versions/{version_id}")
    experiment_id = str(uuid.uuid4())
    _ok(
        owner.request(
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
        owner.request(
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


def district_version(owner) -> uuid.UUID:
    """A version whose district the host registered over two admitted city sources (domain).

    A district is host configuration: an operator admits the committed Flatiron sources and
    registers the binding, which no request can do, so the society runtime is rebuilt with it.
    """
    from exulanica.api.society_runtime import SocietyRuntime, SocietyRuntimeBinding

    base = ROOT / "assets/owned-world/flatiron/flatiron-owned-district.json"
    reading = ROOT / "assets/owned-world/flatiron-interpretation-v1/district-interpretation.json"
    version_id = _plain_version(owner)
    version = _ok(owner.request("GET", f"/world/versions/{version_id}"), 200)
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
    current = _ok(owner.request("GET", "/world/styles/current"), 200)
    return {
        "json": {
            "base_style_version_id": current["current"]["version_id"],
            "base_topology_digest": current["current_topology_digest"],
        }
    }
