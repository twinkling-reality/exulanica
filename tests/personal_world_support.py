"""The routes a browser uses for a world made from reviewed photographs, as runtime roles.

Shared by ``test_personal_source_world_api.py`` and ``test_personal_world_addition.py``. The
application connects as provisioned runtime roles with row-level security in force, not as the
schema owner the other API fixtures use, so what a stranger can see is what a deployment shows.
Every photograph goes through the intake the upload route runs and the grouping the scene worker
runs; the review is recorded as the drawer records it.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field, replace

from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes.character_appearance import CharacterAppearanceRuntime
from exulanica.api.services import Services
from exulanica.db.roles import provision_runtime_role
from exulanica.evidence.blob import BlobId
from exulanica.ingest.model_rights import bind_point_map, grant_model_right, require_model_right
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import (
    authorize_personal_capture,
    record_human_screening,
    record_person_detection_screening,
)
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.ingest.stages import stage
from exulanica.ingest.stages.segmentation import DEPTH_ROLE, local_model_role
from exulanica.models.handoff import LOCAL_PROCESS, ModelHandoff, ModelIdentity
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from character_appearance_fixtures import family, recipe
from conftest import photo_bytes, scratch_role_database, write_point_map
from tests_support_api import EVERY_PERMISSION

OWNER_TOKEN = "personal-world-owner-token-long-enough-to-be-accepted"
STRANGER_TOKEN = "personal-world-stranger-token-long-enough-to-be-accepted"
RUNTIME_ROLE = "exulanica_personal_world_suite"
READER_ROLE = "exulanica_personal_world_reader"
PATH = "/worlds/personal-source"
#: The reviewed catalog asset migration 0042 installs, by content digest, as an object names it.
CUBE = "b41289ac10548cf698d46a15206caa8e744b0b800f4ac29260c99f18d8b831d9"


@dataclass
class Api:
    client: TestClient
    repository: object
    store: LocalContentAddressedStore
    actor: uuid.UUID
    #: The runtime role's database, for a test that calls a repository as a deployment would.
    database: object
    #: Each photograph's bytes, authorization, review and when they end, by capture.
    receipts: dict = field(default_factory=dict)

    def get(self, path: str, token: str = OWNER_TOKEN):
        return self.client.get(path, headers={"Authorization": f"Bearer {token}"})

    def post(self, path: str, body: dict, token: str = OWNER_TOKEN):
        return self.client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})

    def put(self, path: str, body: dict, token: str = OWNER_TOKEN):
        return self.client.put(path, json=body, headers={"Authorization": f"Bearer {token}"})

    def read(self) -> dict:
        response = self.get(PATH)
        assert response.status_code == 200, response.text
        return response.json()

    def worlds(self) -> list[dict]:
        response = self.get("/worlds")
        assert response.status_code == 200, response.text
        return response.json()["worlds"]

    def entry(self, entry_id: str) -> dict:
        response = self.get(f"/world-entries/{entry_id}")
        assert response.status_code == 200, response.text
        return response.json()

    def version(self, entry: dict, version_id: str | None = None) -> dict:
        response = self.get(
            f"/world/versions/{version_id or entry['authored_version_id']}"
            f"?world_id={entry['world_id']}"
        )
        assert response.status_code == 200, response.text
        return response.json()


def personal_world_api(tmp_path, repository, spine_schema) -> Iterator[Api]:
    """The application as a deployment runs it, with an avatar look family served."""
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=RUNTIME_ROLE)
    provision_runtime_role(repository.connection, role=READER_ROLE, read_only=True)
    database = scratch_role_database(scratch, RUNTIME_ROLE)
    with database.session(repository.workspace_id) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    actor = uuid.uuid4()
    grants = {
        OWNER_TOKEN: {
            "workspace_id": str(repository.workspace_id),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
        STRANGER_TOKEN: {
            "workspace_id": str(uuid.uuid4()),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    store = LocalContentAddressedStore(tmp_path / "blobs")
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, READER_ROLE),
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        served = client.app.state.services
        client.app.state.services = replace(
            served,
            character_appearance=CharacterAppearanceRuntime(
                (family(),), lambda connection, session, definition: True
            ),
        )
        yield Api(client, repository, store, actor, database)


def photograph(
    api: Api,
    *,
    minute: int,
    when: bool = True,
    review: str | None = "human",
    by=None,
    hour: int = 12,
    valid_seconds: float = 3600,
):
    """Intake one photograph, authorize it as personal and screen it as ``review`` says.

    ``"human"`` records a human review, ``"detection"`` a person-detection receipt, which permits
    looking and nothing else, and ``None`` no screening at all.
    """
    data = photo_bytes(when=f"2026:09:20 {hour:02d}:{minute:02d}:00" if when else None)
    repository = api.repository
    intake = PhotoIngestPipeline(repository, api.store).ingest_intake(
        data, filename=f"photo-{hour}-{minute}.jpg"
    )
    assert intake.capture_id is not None, intake.error
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    who = by or api.actor
    authority = authorize_personal_capture(
        repository,
        capture_id=intake.capture_id,
        actor=who,
        account_authority_basis="Synthetic test fixture owned by the test actor",
        authorization_scope={"purpose": "personal-source world test"},
        purpose="personal-source world test",
        authorized_at=now - dt.timedelta(minutes=5),
        valid_until=now + dt.timedelta(seconds=valid_seconds),
    )
    screening = None
    if review == "detection":
        record_person_detection_screening(
            repository,
            authorization_id=authority.authorization_id,
            authorized_by=who,
            purpose="find the people in it so they can be hidden",
            screened_at=now - dt.timedelta(minutes=4),
            valid_until=now + dt.timedelta(hours=1),
        )
    elif review == "human":
        screening = record_human_screening(
            repository,
            authorization_id=authority.authorization_id,
            reviewed_by=who,
            sensitive_regions=[],
            screened_at=now - dt.timedelta(minutes=4),
            valid_until=now + dt.timedelta(seconds=valid_seconds),
        )
    repository.connection.commit()
    until = now + dt.timedelta(seconds=valid_seconds)
    api.receipts[intake.capture_id] = (data, authority, screening, until)
    return intake.capture_id


def renew(api: Api, capture: uuid.UUID) -> None:
    """A new authorization and human review of the same photograph, recorded now."""
    repository = api.repository
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    authority = authorize_personal_capture(
        repository,
        capture_id=capture,
        actor=api.actor,
        account_authority_basis="Synthetic test fixture owned by the test actor",
        authorization_scope={"purpose": "personal-source world renewal"},
        purpose="personal-source world renewal",
        authorized_at=now,
        valid_until=now + dt.timedelta(hours=1),
    )
    record_human_screening(
        repository,
        authorization_id=authority.authorization_id,
        reviewed_by=api.actor,
        sensitive_regions=[],
        screened_at=now,
        valid_until=now + dt.timedelta(hours=1),
    )
    repository.connection.commit()


def depth_estimate(api: Api, capture: uuid.UUID, *, right_seconds: float | None = None):
    """A point map under the review and a depth right, bound as the depth stage binds it.

    Returns the artifact id and the depth right. ``right_seconds`` ends the right that long from
    now instead of when the review ends.
    """
    data, authority, screening, until = api.receipts[capture]
    repository = api.repository
    pin = local_model_role(DEPTH_ROLE).primary
    identity = ModelIdentity.local(str(stage("depth").model_role), pin.repo_id, pin.revision)
    if right_seconds is not None:
        now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
        until = now + dt.timedelta(seconds=right_seconds)
    right = grant_model_right(
        repository,
        capture_id=capture,
        authorization_id=authority.authorization_id,
        identity=identity,
        destination=LOCAL_PROCESS,
        granted_by=api.actor,
        purpose="estimate 3D shape",
        valid_until=until,
    )
    permission = require_model_right(
        repository, capture, screening.screening_id, ModelHandoff.local(identity)
    )
    artifact, _ = write_point_map(
        repository,
        api.store,
        BlobId.of_bytes(data),
        payload=b"GENERATED POINT MAP FIXTURE",
        privacy_screening_id=screening.screening_id,
    )
    bind_point_map(repository, artifact_id=artifact, decision=permission)
    repository.connection.commit()
    return artifact, right


def source_media(api: Api, entry: dict) -> list[dict]:
    response = api.get(
        f"/world/source-media?world_id={entry['world_id']}"
        f"&source_snapshot_id={entry['source_snapshot_id']}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def wait_until(moment: dt.datetime) -> None:
    left = (moment - dt.datetime.now(dt.UTC)).total_seconds()
    if left > 0:
        time.sleep(left + 0.5)


def group(api: Api) -> None:
    run_scene_grouping(api.repository)
    api.repository.connection.commit()


def compose(api: Api, digest: str, preview_sha256: str | None = None):
    body = {"topology_digest": digest}
    if preview_sha256 is not None:
        body["preview_sha256"] = preview_sha256
    return api.post(PATH, body)


def bootstrap(api: Api, world_id: str, title: str) -> tuple[dict, dict]:
    """Read the style and open the world's first version, as the browser does after composing."""
    state = api.get(f"/world/styles/current?world_id={world_id}")
    assert state.status_code == 200, state.text
    booted = api.post(
        f"/world/versions/bootstrap?world_id={world_id}",
        {"base_topology_digest": state.json()["current_topology_digest"], "title": title},
    )
    assert booted.status_code == 200, booted.text
    return state, booted


def save_entry(api: Api, world_id: str, title: str = "From my photographs") -> dict:
    """The browser's steps after composing: read the style, bootstrap, save the entry."""
    state, booted = bootstrap(api, world_id, title)
    saved = api.post(
        "/world-entries",
        {
            "world_id": world_id,
            "title": title,
            "source_kind": "personal",
            "authored_version_id": booted.json()["version_id"],
            "style_version_id": state.json()["current"]["version_id"],
        },
    )
    assert saved.status_code == 201, saved.text
    return saved.json()


def make_world(api: Api) -> dict:
    """Compose what the read offers, then bootstrap and save it; returns the saved entry."""
    read = api.read()
    assert read["action"] == "create_world", read
    composed = compose(api, read["topology_digest"])
    assert composed.status_code == 200, composed.text
    return save_entry(api, composed.json()["world_id"])


def binding(entry: dict) -> dict:
    """The saved-entry cursor an authored edit names, so the saved world advances with it."""
    return {
        "entry_id": entry["entry_id"],
        "base_revision": entry["revision"],
        "authored_state_sha256": entry["authored_state_sha256"],
        "authored_edit_seq": entry["authored_edit_seq"],
    }


def place_object(api: Api, entry: dict, region_id: str, object_id: str = "object:lantern") -> dict:
    """Place the reviewed cube in ``region_id`` as the object surface does; returns the entry."""
    version = api.version(entry)
    placed = api.post(
        f"/world/versions/{entry['authored_version_id']}/objects?world_id={entry['world_id']}",
        {
            "base_state_sha256": version["state_sha256"],
            "object_id": object_id,
            "asset_sha256": CUBE,
            "region_id": region_id,
            "transform": {
                "x_mm": 1_200,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
            "saved_entry": binding(entry),
        },
    )
    assert placed.status_code == 201, placed.text
    return api.entry(entry["entry_id"])


def region_appearance(api: Api, entry: dict, region_id: str, vitality: float = 0.25) -> dict:
    """Give one place its own appearance, saved to the entry as Settings saves it."""
    return _appearance(api, entry, {"kind": "region", "region_id": region_id}, vitality)


def world_appearance(api: Api, entry: dict, vitality: float = 0.5) -> dict:
    """Change the whole world's appearance, saved to the entry as Settings saves it."""
    return _appearance(api, entry, {"kind": "global"}, vitality)


def _appearance(api: Api, entry: dict, scope: dict, vitality: float) -> dict:
    world = entry["world_id"]
    state = api.get(f"/world/styles/current?world_id={world}").json()
    preview = api.post(
        f"/world/styles/previews?world_id={world}",
        {
            "proposal_id": str(uuid.uuid4()),
            "origin": "settings",
            "origin_reference": "appearance-panel",
            "scope": scope,
            "base_style_version_id": state["current"]["version_id"],
            "base_topology_digest": state["current_topology_digest"],
            "profile": {
                "profile_id": "origin-landscape",
                "profile_version": 1,
                "parameters": {"vitality": vitality},
            },
        },
    )
    assert preview.status_code == 201, preview.text
    applied = api.post(
        f"/world/styles/previews/{preview.json()['preview_id']}/apply?world_id={world}",
        {
            "base_style_version_id": state["current"]["version_id"],
            "base_topology_digest": state["current_topology_digest"],
            "saved_entry": {**binding(entry), "style_version_id": entry["style_version_id"]},
        },
    )
    assert applied.status_code == 200, applied.text
    return api.entry(entry["entry_id"])


def avatar_look(api: Api, entry: dict) -> dict:
    """Save the avatar's look in the entry's version, as the appearance panel does."""
    response = api.put(
        f"/world/versions/{entry['authored_version_id']}/characters/avatar/{api.actor}/appearance"
        f"?world_id={entry['world_id']}",
        {"base_revision": 0, "recipe": recipe().model_dump(mode="json")},
    )
    assert response.status_code == 200, response.text
    return response.json()
