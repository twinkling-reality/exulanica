"""Making the personal-source world from reviewed photographs, through the routes a browser uses.

``GET /worlds/personal-source`` says what composing now would do or names why not, and
``POST /worlds/personal-source`` does exactly that or refuses by name with nothing written. The
application here connects as provisioned runtime roles with row-level security in force, not as
the schema owner the other API fixtures use, so what a stranger can see is what a deployment
shows.
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from dataclasses import dataclass, field

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
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
from exulanica.orchestration.reference_world import compose_reference_sources
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import photo_bytes, scratch_role_database, write_point_map
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres

_OWNER_TOKEN = "personal-world-owner-token-long-enough-to-be-accepted"
_STRANGER_TOKEN = "personal-world-stranger-token-long-enough-to-be-accepted"
_RUNTIME_ROLE = "exulanica_personal_world_suite"
_READER_ROLE = "exulanica_personal_world_reader"
_PATH = "/worlds/personal-source"


@dataclass
class Api:
    client: TestClient
    repository: object
    store: LocalContentAddressedStore
    actor: uuid.UUID
    #: Each photograph's bytes, authorization, review and when they end, by capture.
    receipts: dict = field(default_factory=dict)

    def get(self, path: str, token: str = _OWNER_TOKEN):
        return self.client.get(path, headers={"Authorization": f"Bearer {token}"})

    def post(self, path: str, body: dict, token: str = _OWNER_TOKEN):
        return self.client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})

    def read(self) -> dict:
        response = self.get(_PATH)
        assert response.status_code == 200, response.text
        return response.json()

    def worlds(self) -> list[dict]:
        response = self.get("/worlds")
        assert response.status_code == 200, response.text
        return response.json()["worlds"]


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=_RUNTIME_ROLE)
    provision_runtime_role(repository.connection, role=_READER_ROLE, read_only=True)
    database = scratch_role_database(scratch, _RUNTIME_ROLE)
    with database.session(repository.workspace_id) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    actor = uuid.uuid4()
    grants = {
        _OWNER_TOKEN: {
            "workspace_id": str(repository.workspace_id),
            "actor": str(actor),
            "permissions": EVERY_PERMISSION,
        },
        _STRANGER_TOKEN: {
            "workspace_id": str(uuid.uuid4()),
            "actor": str(uuid.uuid4()),
            "permissions": EVERY_PERMISSION,
        },
    }
    store = LocalContentAddressedStore(tmp_path / "blobs")
    services = Services(
        database=database,
        readonly_database=scratch_role_database(scratch, _READER_ROLE),
        store=store,
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)}),
        executor_shares_the_write_role=False,
        model_client=None,
    )
    with TestClient(create_app(services, verify=False)) as client:
        yield Api(client, repository, store, actor)


def _photograph(
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
        data, filename=f"photo-{minute}.jpg"
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


def _renew(api: Api, capture: uuid.UUID) -> None:
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


def _depth_estimate(api: Api, capture: uuid.UUID) -> uuid.UUID:
    """A point map under the review and a depth right, bound as the depth stage binds it."""
    data, authority, screening, until = api.receipts[capture]
    repository = api.repository
    pin = local_model_role(DEPTH_ROLE).primary
    identity = ModelIdentity.local(str(stage("depth").model_role), pin.repo_id, pin.revision)
    grant_model_right(
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
    return artifact


def _source_media(api: Api, entry: dict) -> list[dict]:
    response = api.get(
        f"/world/source-media?world_id={entry['world_id']}"
        f"&source_snapshot_id={entry['source_snapshot_id']}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wait_until(moment: dt.datetime) -> None:
    left = (moment - dt.datetime.now(dt.UTC)).total_seconds()
    if left > 0:
        time.sleep(left + 0.5)


def _group(api: Api) -> None:
    run_scene_grouping(api.repository)
    api.repository.connection.commit()


def _compose(api: Api, digest: str):
    return api.post(_PATH, {"topology_digest": digest})


def _bootstrap(api: Api, world_id: str, title: str) -> tuple[dict, dict]:
    """Read the style and open the world's first version, as the browser does after composing."""
    state = api.get(f"/world/styles/current?world_id={world_id}")
    assert state.status_code == 200, state.text
    booted = api.post(
        f"/world/versions/bootstrap?world_id={world_id}",
        {"base_topology_digest": state.json()["current_topology_digest"], "title": title},
    )
    assert booted.status_code == 200, booted.text
    return state, booted


def _save_entry(api: Api, world_id: str, title: str = "From my photographs") -> dict:
    """The browser's steps after composing: read the style, bootstrap, save the entry."""
    state, booted = _bootstrap(api, world_id, title)
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


def test_no_reviewed_photograph_is_refused_by_name_and_writes_nothing(api):
    # Authorized but never screened, screened only for person detection, and reviewed by
    # somebody else: none is the account holder's human review, so none counts.
    _photograph(api, minute=0, review=None)
    _photograph(api, minute=1, review="detection")
    _photograph(api, minute=2, by=uuid.uuid4())
    _group(api)
    read = api.read()
    assert read["action"] is None
    assert read["refusal"]["code"] == "no_reviewed_personal_sources"
    assert "Review your photographs first" in read["refusal"]["detail"]
    assert read["photographs"] == {"reviewed": 0, "composed": 0, "outside_scene_groups": 0}
    assert read["topology_digest"] is None
    refused = _compose(api, "0" * 64)
    assert refused.status_code == 409
    assert refused.json() == {"code": read["refusal"]["code"], "detail": read["refusal"]["detail"]}
    assert api.worlds() == []


def test_a_reviewed_photograph_in_no_scene_group_is_left_out_and_counted(api):
    _photograph(api, minute=0, when=False)
    _group(api)
    read = api.read()
    assert read["refusal"]["code"] == "no_grouped_personal_sources"
    assert read["photographs"] == {"reviewed": 1, "composed": 0, "outside_scene_groups": 1}
    assert read["regions"] == 0
    # A grouped one beside it is composed; the ungrouped one stays out and is still counted.
    _photograph(api, minute=2)
    _group(api)
    read = api.read()
    assert read["action"] == "create_world"
    assert read["photographs"] == {"reviewed": 2, "composed": 1, "outside_scene_groups": 1}
    assert read["regions"] == 1


def test_composing_makes_the_world_the_browser_then_saves_and_names(api):
    first = _photograph(api, minute=0)
    second = _photograph(api, minute=3)
    _group(api)
    read = api.read()
    assert read["action"] == "create_world"
    assert read["refusal"] is None and read["world_id"] is None
    assert read["photographs"] == {"reviewed": 2, "composed": 2, "outside_scene_groups": 0}
    assert read["regions"] == 1

    composed = _compose(api, read["topology_digest"])
    assert composed.status_code == 200, composed.text
    body = composed.json()
    assert body["action"] == "create_world"
    assert body["topology_digest"] == read["topology_digest"]
    assert body["saved_entry_id"] is None
    [world] = api.worlds()
    assert world == {**world, "world_id": body["world_id"], "kind": "personal-source"}
    assert world["provenance"]["reason"] == "reviewed photographs composed into their scene groups"
    state = api.get(f"/world/styles/current?world_id={body['world_id']}").json()
    assert state["current_topology_digest"] == body["topology_digest"]
    media = api.get(f"/world/source-media?world_id={body['world_id']}")
    assert media.status_code == 200, media.text
    assert sorted(capture for row in media.json() for capture in row["capture_ids"]) == sorted(
        str(capture) for capture in (first, second)
    )

    # The world has a topology and no saved entry yet: nothing to compose, save one. Both before
    # it is made and once the bootstrap has made it, with the same photographs.
    assert api.read()["action"] == "save_entry"
    _bootstrap(api, body["world_id"], "From my photographs")
    assert api.read()["action"] == "save_entry"
    entry = _save_entry(api, body["world_id"])
    assert entry["world_id"] == body["world_id"]
    after = api.read()
    assert after["action"] is None
    assert after["refusal"]["code"] == "personal_world_current"
    assert after["saved_entry_id"] == entry["entry_id"]
    assert _compose(api, after["topology_digest"]).json()["code"] == "personal_world_current"


def test_a_digest_the_person_was_not_shown_is_refused_and_writes_nothing(api):
    _photograph(api, minute=0)
    _group(api)
    shown = api.read()["topology_digest"]
    # Another reviewed photograph arrives between the read and the write.
    _photograph(api, minute=4)
    _group(api)
    refused = _compose(api, shown)
    assert refused.status_code == 409
    assert refused.json()["code"] == "personal_sources_changed"
    assert api.worlds() == []
    assert _compose(api, api.read()["topology_digest"]).status_code == 200


def test_a_made_world_is_refused_by_name_rather_than_changed_where_nobody_sees_it(api):
    _photograph(api, minute=0)
    _group(api)
    created = _compose(api, api.read()["topology_digest"]).json()
    entry = _save_entry(api, created["world_id"])
    _photograph(api, minute=5)
    _group(api)
    read = api.read()
    # A new review would change a topology the saved world never opens, so it is refused, in
    # words saying what the world holds and what the app does not do for it.
    assert read["action"] is None
    assert read["refusal"]["code"] == "personal_world_already_made"
    assert read["refusal"]["detail"] == (
        "Your world from your photographs was made with 1 photograph. 1 photograph you reviewed "
        "since is not in it. This app does not add photographs to a world once it is made, or "
        "move them in it."
    )
    assert read["saved_entry_id"] == entry["entry_id"]
    assert read["photographs"]["composed"] == 2
    before = api.get(f"/world/styles/current?world_id={created['world_id']}").json()
    refused = _compose(api, read["topology_digest"])
    assert refused.status_code == 409
    assert refused.json() == {"code": read["refusal"]["code"], "detail": read["refusal"]["detail"]}
    after = api.get(f"/world/styles/current?world_id={created['world_id']}").json()
    assert after["current_topology_digest"] == before["current_topology_digest"]


def test_the_route_and_the_operator_script_are_one_writer_of_one_world(api):
    capture = _photograph(api, minute=0)
    record = compose_reference_sources(
        api.repository,
        region_id="operator-region",
        captures=[(capture, api.repository.capture(capture).blob_id.hex, "operator.jpg")],
        source_manifest_sha256="ab" * 32,
        actor=api.actor,
    )
    api.repository.connection.commit()
    _group(api)
    read = api.read()
    # The script made the world; the route composes into it rather than making a second one.
    assert read["world_id"] == record["world_id"]
    assert read["action"] == "update_world"
    assert _compose(api, read["topology_digest"]).json()["world_id"] == record["world_id"]
    assert [world["world_id"] for world in api.worlds()] == [record["world_id"]]


def test_a_stranger_sees_none_of_the_owners_photographs_or_world(api):
    _photograph(api, minute=0)
    _group(api)
    _compose(api, api.read()["topology_digest"])
    stranger = api.get(_PATH, token=_STRANGER_TOKEN)
    assert stranger.status_code == 200, stranger.text
    assert stranger.json()["refusal"]["code"] == "no_reviewed_personal_sources"
    assert stranger.json()["world_id"] is None
    assert stranger.json()["photographs"]["reviewed"] == 0


#: The reason a world's source slot gives when its personal photograph is no longer allowed.
_LAPSED = "its personal authorization or human review is no longer current"


def test_a_made_world_stops_drawing_a_photograph_whose_review_lapsed_until_reviewed_again(api):
    capture = _photograph(api, minute=0, valid_seconds=6)
    artifact = _depth_estimate(api, capture)
    _group(api)
    created = _compose(api, api.read()["topology_digest"]).json()
    entry = _save_entry(api, created["world_id"])
    [slot] = _source_media(api, entry)
    assert slot["state"] == "available"
    assert slot["evidence_path"] == f"/evidence/{slot['evidence_span_id']}/masked"
    assert str(artifact) in {row["artifact_id"] for row in api.get("/geometry").json()}
    assert api.get(f"/geometry/{artifact}").status_code == 200

    _wait_until(api.receipts[capture][3])
    [slot] = _source_media(api, entry)
    # The world stops drawing it: no viewer, no evidence path, and a reason that says why.
    assert slot["state"] == "unavailable_asset"
    assert slot["reason"] == _LAPSED
    assert slot["evidence_path"] is None and slot["asset_reference"] is None
    # Its depth estimate was bound to the review and the right, and is refused with them.
    assert str(artifact) not in {row["artifact_id"] for row in api.get("/geometry").json()}
    assert api.get(f"/geometry/{artifact}").status_code == 404
    # The library keeps the photograph: it stays the account holder's to see.
    assert api.get(f"/evidence/{slot['evidence_span_id']}/masked").status_code == 200

    _renew(api, capture)
    [slot] = _source_media(api, entry)
    assert slot["state"] == "available" and slot["reason"] is None
    assert slot["evidence_path"] == f"/evidence/{slot['evidence_span_id']}/masked"


def test_a_made_world_says_what_it_shows_of_every_photograph_that_changed(api):
    lapsing = _photograph(api, minute=0, valid_seconds=6)
    kept = _photograph(api, minute=1)
    later_place = _photograph(api, minute=0, hour=15)
    _group(api)
    created = _compose(api, api.read()["topology_digest"]).json()
    entry = _save_entry(api, created["world_id"])
    assert len(_source_media(api, entry)) == 3

    # One photograph's review lapses, one more is reviewed, and the later place's group goes
    # stale, as a grouping whose inputs changed does, so that photograph is in no live place.
    _wait_until(api.receipts[lapsing][3])
    _photograph(api, minute=2)
    _group(api)
    api.repository.connection.execute(
        "update derived_artifact set stale=true where workspace_id=%s and kind='scene_group' "
        "and %s=any(source_ids)",
        (api.repository.workspace_id, later_place),
    )
    api.repository.connection.commit()
    read = api.read()
    assert read["refusal"]["code"] == "personal_world_already_made"
    assert read["refusal"]["detail"] == (
        "Your world from your photographs was made with 3 photographs. 1 photograph you "
        "reviewed since is not in it. 1 of its photographs is no longer allowed in it (deleted, "
        "withdrawn or without a current review from you), so the world no longer shows it. "
        "1 of its photographs is no longer in any place, and the world still shows it where it "
        "was placed. This app does not add photographs to a world once it is made, or move "
        "them in it."
    )
    # Each clause is what the world's read path does with those photographs.
    shown = {
        slot["capture_ids"][0]: (slot["state"], slot["reason"])
        for slot in _source_media(api, entry)
    }
    assert shown == {
        str(lapsing): ("unavailable_asset", _LAPSED),
        str(kept): ("available", None),
        str(later_place): ("available", None),
    }
