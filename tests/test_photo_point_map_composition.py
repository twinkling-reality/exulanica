"""Placing a depth estimate from your own photograph into your own world.

Every verdict here comes from rows and bytes this file created and then changed underneath the
request, so each assertion is about what the server read rather than about what a body claimed.
The photograph is synthetic and the depth model is a double; what is under test is the resolution,
the placement and what happens to a placed estimate when the permission behind it ends.

The one thing worth naming before the tests: the SOURCE of a request of this kind is a reference
(``entry_id`` and ``attachment_id``), and what is placed is the depth artifact reached through it.
A request naming the same two identifiers with ``kind: source_attachment`` asks for the photograph
itself to become geometry and is always refused. Both are tested here, side by side, because the
difference between them is the whole point of the kind.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.ingest.model_rights import (
    LOCAL_PROCESS,
    ModelHandoff,
    ModelIdentity,
    grant_model_right,
    withdraw_model_right,
)
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.stages.segmentation import DEPTH_ROLE as INGEST_DEPTH_ROLE
from exulanica.reconstruction.testing import FlatDepthModel
from exulanica.world import WorldObjectRepository
from exulanica.world.photo_point_maps import DEPTH_ROLE as WORLD_DEPTH_ROLE

from test_saved_world_entries_api import _attachment_body, _create_starter, _reviewed_source
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres

#: The checkpoint the double stands in for. A real pin is not needed and would be a claim: what
#: matters is that the right names exactly the model that ran.
DEPTH_MODEL = ModelIdentity.local(INGEST_DEPTH_ROLE, "test/plane-depth", "1" * 40)


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


class CountingDepth(FlatDepthModel):
    """The flat depth double, stating the checkpoint a right can name."""

    def __init__(self) -> None:
        super().__init__()
        self.model_handoff = ModelHandoff.local(DEPTH_MODEL)
        self.calls = 0

    def predict(self, image):
        self.calls += 1
        return super().predict(image)


class Placed:
    """A starter world with one reviewed photograph attached and an estimate made from it."""

    def __init__(self, api, repository, entry, source, right) -> None:
        self.api = api
        self.repository = repository
        self.entry = entry
        self.source = source
        self.right = right

    @property
    def version_id(self) -> str:
        return self.entry["authored_version_id"]

    def worlds(self) -> WorldObjectRepository:
        return WorldObjectRepository(
            self.repository.connection,
            self.repository.workspace_id,
            world_id=self.entry["world_id"],
            store=self.api.store,
        )

    def stored_version(self):
        response = self.api.get(
            f"/world/versions/{self.version_id}?world_id={self.entry['world_id']}"
        )
        assert response.status_code == 200, response.text
        return response.json()

    def source_body(self, kind="photo_point_map"):
        return {
            "kind": kind,
            "entry_id": self.entry["entry_id"],
            "attachment_id": self.attachment_id,
        }

    @property
    def attachment_id(self) -> str:
        return self.entry["source_attachments"][0]["attachment_id"]

    @property
    def region_id(self) -> str:
        """The starter world's own region. A starter is not the structural fixture's snapshot."""
        return self.entry["authored_scene"]["region"]["region_id"]

    def placement(self, subject_id="point-map:kitchen", **overrides):
        body = {
            "subject_id": subject_id,
            "region_id": self.region_id,
            "transform": {
                "x_mm": 1200,
                "y_mm": 0,
                "z_mm": -450,
                "yaw_microradians": 785398,
                "scale_milli": 1000,
            },
            "origin_role": "personal",
        }
        body.update(overrides)
        return body

    def request(self, *, placement=True, base=None, kind="photo_point_map", **placement_overrides):
        return {
            "base_state_sha256": base or self.stored_version()["state_sha256"],
            "source": self.source_body(kind),
            "placement": self.placement(**placement_overrides) if placement else None,
        }

    def preview(self, body=None):
        return self.api.post(
            f"/world/versions/{self.version_id}/compositions/preview"
            f"?world_id={self.entry['world_id']}",
            body if body is not None else self.request(),
        )

    def saved_entry_body(self):
        """What a browser sends so the saved world's resume point moves with the placement."""
        current = self.stored_entry()
        return {
            "entry_id": current["entry_id"],
            "base_revision": current["revision"],
            "authored_state_sha256": current["authored_state_sha256"],
            "authored_edit_seq": current["authored_edit_seq"],
        }

    def apply(self, body=None):
        return self.api.post(
            f"/world/versions/{self.version_id}/compositions/apply"
            f"?world_id={self.entry['world_id']}",
            body if body is not None else self.request(),
        )

    def stored_entry(self):
        response = self.api.get(f"/world-entries/{self.entry['entry_id']}")
        assert response.status_code == 200, response.text
        return response.json()

    def detach(self):
        current = self.stored_entry()
        return self.api.post(
            f"/world-entries/{self.entry['entry_id']}/source-detachments",
            {
                "operation_id": str(uuid.uuid4()),
                "base_revision": current["revision"],
                "authored_version_id": current["authored_version_id"],
                "authored_state_sha256": current["authored_state_sha256"],
                "authored_edit_seq": current["authored_edit_seq"],
                "style_version_id": current["style_version_id"],
                "selections": [{"attachment_id": self.attachment_id}],
            },
        )

    def instances(self):
        return self.worlds().version(uuid.UUID(self.version_id)).point_map_instances


def _run_depth(repository, store, capture_id, screening_id):
    depth = CountingDepth()
    outcome = PhotoIngestPipeline(repository, store, depth=depth).ingest_derivatives(
        capture_id, privacy_screening_id=screening_id
    )
    assert outcome.error is None, outcome.error
    return depth, outcome


@pytest.fixture
def placed(repository, objects_api):
    """One photograph, reviewed, attached to a starter world, with a depth estimate published."""
    entry = _create_starter(objects_api)
    source = _reviewed_source(repository, objects_api)
    attached = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments",
        _attachment_body(entry, source),
    )
    assert attached.status_code == 200, attached.text
    entry = attached.json()

    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    right = grant_model_right(
        repository,
        capture_id=uuid.UUID(source["capture_id"]),
        authorization_id=uuid.UUID(entry["source_attachments"][0]["authorization_id"]),
        identity=DEPTH_MODEL,
        destination=LOCAL_PROCESS,
        granted_by=objects_api.actor,
        purpose="place a 3D estimate of my own photograph in my own world",
        valid_until=now + dt.timedelta(hours=1),
        granted_at=now,
    )
    depth, _ = _run_depth(
        repository,
        objects_api.store,
        uuid.UUID(source["capture_id"]),
        uuid.UUID(entry["source_attachments"][0]["screening_id"]),
    )
    assert depth.calls == 1, "the fixture's estimate must have actually been made"
    repository.connection.commit()
    return Placed(objects_api, repository, entry, source, right)


# -- the two layers spell the depth role the same way ---------------------------------------------


def test_the_world_layer_and_the_pipeline_name_the_same_role():
    """Two spellings of one string in two layers that may not import each other.

    If this fails, nothing crashes: every resolution simply answers "no current permission" for
    every photograph, which reads as a person having permission problems rather than as a rename.
    """
    assert WORLD_DEPTH_ROLE == INGEST_DEPTH_ROLE


# -- a ready preview, and the apply that matches it -----------------------------------------------


def test_a_ready_preview_names_the_estimate_and_what_permitted_it(placed):
    response = placed.preview()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["availability"] == "ready", (body["blocked_reason"], body["blocked_detail"])
    assert body["blocked_reason"] is None
    assert body["would_change"]["kind"] == "add_point_map"
    assert body["source"]["kind"] == "photo_point_map"
    assert body["source"]["bytes"] == "available"
    assert body["source"]["capture_id"] == placed.source["capture_id"]
    assert body["source"]["model"] == {
        "destination": LOCAL_PROCESS,
        "identifier": DEPTH_MODEL.model_id,
        "provider": "local",
        "revision": DEPTH_MODEL.revision,
        "role": INGEST_DEPTH_ROLE,
    }
    assert body["source"]["rung"] == 3
    document = body["would_change"]["document"]
    assert document["instance_id"] == "point-map:kitchen"
    assert document["origin"] == {"kind": "authored", "role": "personal"}
    assert document["source"]["right"]["right_id"] == str(placed.right.right_id)
    assert document["source"]["attachment"]["attachment_id"] == placed.attachment_id
    assert document["source"]["artifact"]["container"] == "opm/2"
    assert document["source"]["artifact"]["content_sha256"] == body["source"]["content_sha256"]


def test_apply_stores_exactly_what_preview_showed_and_a_new_read_sees_it(placed):
    previewed = placed.preview().json()["would_change"]["document"]
    applied = placed.apply()
    assert applied.status_code == 201, applied.text

    (stored,) = placed.instances()
    assert stored.instance_id == "point-map:kitchen"
    assert stored.availability == "available"
    assert stored.source.artifact_id is not None
    from exulanica.world import point_map_instance_document

    assert point_map_instance_document(stored) == previewed
    # The version's own token moved, and the returned body is the token for what it holds.
    assert applied.json()["state_sha256"] == placed.stored_version()["state_sha256"]
    assert applied.json()["state_sha256"] != previewed and applied.json()["edit_seq"] == 1


def test_a_second_apply_with_the_same_id_is_refused_and_the_first_stays(placed):
    assert placed.apply().status_code == 201
    again = placed.apply()
    assert again.status_code == 409, again.text
    assert again.json() == {
        "code": "composition_blocked",
        "detail": "subject_already_present",
    }
    assert len(placed.instances()) == 1


def test_undo_takes_the_placement_back(placed):
    assert placed.apply().status_code == 201
    version = placed.stored_version()
    undone = placed.api.post(
        f"/world/versions/{placed.version_id}/objects/undo?world_id={placed.entry['world_id']}",
        {"base_state_sha256": version["state_sha256"]},
    )
    assert undone.status_code == 200, undone.text
    assert placed.instances() == ()
    # An undone addition frees its id, which is what makes undo usable rather than final.
    assert placed.apply().status_code == 201
    assert len(placed.instances()) == 1


# -- the refusals ---------------------------------------------------------------------------------


def _blocked(response, reason):
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["availability"] == "blocked"
    assert body["blocked_reason"] == reason, body["blocked_detail"]
    assert body["would_change"]["document"] is None
    return body


def test_the_same_reference_as_an_attachment_is_still_never_geometry(placed):
    """The kind is the whole difference: one asks for the photograph, the other for the estimate."""
    _blocked(
        placed.preview(placed.request(kind="source_attachment")),
        "attachment_is_not_composition",
    )
    assert placed.preview().json()["availability"] == "ready"


def test_stopping_the_estimate_refuses_the_composition(placed):
    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    placed.repository.connection.commit()
    _blocked(placed.preview(), "depth_not_permitted")
    refused = placed.apply()
    assert refused.status_code == 409
    assert refused.json()["detail"] == "depth_not_permitted"
    assert placed.instances() == ()


def test_a_photograph_with_no_estimate_yet_says_so(repository, objects_api):
    entry = _create_starter(objects_api)
    source = _reviewed_source(repository, objects_api, minute=5)
    entry = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments", _attachment_body(entry, source)
    ).json()
    now = repository.connection.execute("select clock_timestamp() as at").fetchone()["at"]
    grant_model_right(
        repository,
        capture_id=uuid.UUID(source["capture_id"]),
        authorization_id=uuid.UUID(entry["source_attachments"][0]["authorization_id"]),
        identity=DEPTH_MODEL,
        destination=LOCAL_PROCESS,
        granted_by=objects_api.actor,
        purpose="place a 3D estimate",
        valid_until=now + dt.timedelta(hours=1),
        granted_at=now,
    )
    repository.connection.commit()
    waiting = Placed(objects_api, repository, entry, source, None)
    _blocked(waiting.preview(), "depth_not_produced")


def test_a_photograph_nobody_allowed_says_permission_rather_than_absence(repository, objects_api):
    """Which of the two a person reads decides what they do next, so the order is a decision."""
    entry = _create_starter(objects_api)
    source = _reviewed_source(repository, objects_api, minute=6)
    entry = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments", _attachment_body(entry, source)
    ).json()
    repository.connection.commit()
    unpermitted = Placed(objects_api, repository, entry, source, None)
    _blocked(unpermitted.preview(), "depth_not_permitted")


def test_removing_the_photograph_from_the_world_refuses_a_new_placement(placed):
    assert placed.detach().status_code == 200
    _blocked(placed.preview(), "membership_not_current")


def test_an_expired_review_refuses_the_composition(repository, objects_api):
    """The receipts are append-only, so the fixture waits out a short term rather than edits one."""
    entry = _create_starter(objects_api)
    source = _reviewed_source(repository, objects_api, minute=7, valid_for_seconds=2)
    entry = objects_api.post(
        f"/world-entries/{entry['entry_id']}/source-attachments", _attachment_body(entry, source)
    ).json()
    repository.connection.commit()
    expiring = Placed(objects_api, repository, entry, source, None)
    # The control: while the review stands, this reference fails on the permission behind the
    # estimate, which is a later check. Only the wait moves it to the expiry.
    _blocked(expiring.preview(), "depth_not_permitted")
    expiry = repository.connection.execute(
        "select valid_until from reconstruction_privacy_screening "
        "where workspace_id=%s and screening_id=%s",
        (repository.workspace_id, uuid.UUID(entry["source_attachments"][0]["screening_id"])),
    ).fetchone()["valid_until"]
    repository.connection.execute(
        "select pg_sleep(greatest(0,extract(epoch from (%s-clock_timestamp())))+0.05)", (expiry,)
    )
    repository.connection.commit()
    _blocked(expiring.preview(), "expired_source_not_composable")


def test_a_fictional_role_is_an_invalid_placement(placed):
    body = placed.request()
    body["placement"]["origin_role"] = "fictional"
    blocked = _blocked(placed.preview(body), "invalid_placement")
    assert "personal" in blocked["blocked_detail"]


def test_a_region_of_another_snapshot_is_an_invalid_placement(placed):
    _blocked(placed.preview(placed.request(region_id="region:not-here")), "invalid_placement")


def test_a_stale_base_is_reported_with_the_current_state(placed):
    body = placed.request(base="0" * 64)
    blocked = _blocked(placed.preview(body), "stale_base")
    assert blocked["version"]["state_sha256"] == placed.stored_version()["state_sha256"]
    refused = placed.apply(body)
    assert refused.status_code == 409
    assert refused.json()["detail"] == "stale_base"


def test_an_attachment_of_another_world_is_not_found(placed):
    body = placed.request()
    body["source"]["attachment_id"] = str(uuid.uuid4())
    _blocked(placed.preview(body), "unknown_attachment")


# -- what happens to an estimate already placed ---------------------------------------------------


def test_stopping_the_estimate_stops_it_being_drawn_and_leaves_the_placement(placed):
    assert placed.apply().status_code == 201
    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    (stored,) = placed.instances()
    assert stored.availability == "withdrawn"
    assert stored.unavailable_reason == "model_right_withdrawn"
    # The edit is still there. Taking permission back is not editing somebody's world for them,
    # and Undo and Remove both stay available on a placement nobody may currently see.
    assert stored.instance_id == "point-map:kitchen"
    assert not stored.removed


def test_removing_the_photograph_from_the_world_detaches_what_it_produced(placed):
    assert placed.apply().status_code == 201
    assert placed.detach().status_code == 200
    (stored,) = placed.instances()
    assert stored.availability == "detached"
    assert stored.unavailable_reason is None


def test_deleting_the_photograph_withdraws_the_placed_estimate(placed):
    assert placed.apply().status_code == 201
    placed.repository.connection.execute(
        "update capture set deleted_at=clock_timestamp() where workspace_id=%s and capture_id=%s",
        (placed.repository.workspace_id, uuid.UUID(placed.source["capture_id"])),
    )
    (stored,) = placed.instances()
    assert stored.availability == "withdrawn"
    assert stored.unavailable_reason == "source_deleted"


def test_a_removal_works_even_after_the_permission_ended(placed):
    """The person most likely to want this is the one whose right has just ended."""
    assert placed.apply().status_code == 201
    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    placed.repository.connection.commit()
    worlds = placed.worlds()
    version = worlds.version(uuid.UUID(placed.version_id))
    worlds.remove_point_map(
        uuid.UUID(placed.version_id),
        "point-map:kitchen",
        base_state_sha256=version.state_sha256,
        actor=placed.api.actor,
    )
    (stored,) = placed.instances()
    assert stored.removed


def test_a_move_is_refused_while_it_may_not_be_drawn(placed):
    from exulanica.world import Transform
    from exulanica.world.errors import PointMapNotPermitted

    assert placed.apply().status_code == 201
    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    placed.repository.connection.commit()
    worlds = placed.worlds()
    version = worlds.version(uuid.UUID(placed.version_id))
    with pytest.raises(PointMapNotPermitted):
        worlds.move_point_map(
            uuid.UUID(placed.version_id),
            "point-map:kitchen",
            Transform(0, 0, 0, 0, 1000),
            base_state_sha256=version.state_sha256,
            actor=placed.api.actor,
        )


def test_the_bytes_going_missing_is_its_own_state(placed):
    assert placed.apply().status_code == 201
    (stored,) = placed.instances()
    # The store has no delete: removing the file is what "the bytes went missing" IS, and a
    # store method for it would be a capability the product does not want.
    Path(placed.api.store.root, placed.api.store.key_for(
        BlobId.from_hex(stored.source.point_map_sha256)
    )).unlink()
    (after,) = placed.instances()
    assert after.availability == "unavailable_bytes"


def test_re_adding_after_an_undo_needs_the_permission_that_stands_then(placed):
    """An undone row is retained and a same-id re-add replaces it, which is a NEW placement.

    Migration 0088 introduced that path for environment instances. Here it has to carry the extra
    condition this kind exists for: a person who stopped their estimates between the undo and the
    re-add must not get the placement back by re-using its id.
    """
    assert placed.apply().status_code == 201
    undone = placed.api.post(
        f"/world/versions/{placed.version_id}/objects/undo?world_id={placed.entry['world_id']}",
        {"base_state_sha256": placed.stored_version()["state_sha256"]},
    )
    assert undone.status_code == 200, undone.text
    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    placed.repository.connection.commit()
    refused = placed.apply()
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"] == "depth_not_permitted"
    assert placed.instances() == ()


def test_adding_the_photograph_back_never_reactivates_what_it_produced(placed):
    """A rebind is a new membership under a new review; the old placement stays detached."""
    # Applied with the saved-world cursor, as a browser does, so the entry moves with the
    # placement and the membership change below is not refused for an unrelated reason.
    request = placed.request()
    request["base_state_sha256"] = placed.stored_entry()["authored_state_sha256"]
    request["saved_entry"] = placed.saved_entry_body()
    assert placed.apply(request).status_code == 201
    assert placed.detach().status_code == 200
    (detached,) = placed.instances()
    assert detached.availability == "detached"

    from test_saved_world_entries_api import _renew_reviewed_source

    renewed = _renew_reviewed_source(placed.repository, placed.api, placed.source)
    placed.repository.connection.commit()
    current = placed.stored_entry()
    rebound = placed.api.post(
        f"/world-entries/{placed.entry['entry_id']}/source-rebinds",
        {
            "operation_id": str(uuid.uuid4()),
            "base_revision": current["revision"],
            "authored_version_id": current["authored_version_id"],
            "authored_state_sha256": current["authored_state_sha256"],
            "authored_edit_seq": current["authored_edit_seq"],
            "style_version_id": current["style_version_id"],
            "sources": [
                {
                    "capture_id": renewed["capture_id"],
                    "evidence_span_id": renewed["evidence_span_id"],
                }
            ],
        },
    )
    assert rebound.status_code == 200, rebound.text
    (still,) = placed.instances()
    assert still.availability == "detached"


def test_a_branch_copies_only_the_estimates_it_may_still_draw(placed):
    assert placed.apply().status_code == 201
    worlds = placed.worlds()
    kept = worlds.create_version(
        title="Branch with the estimate",
        parent_version_id=uuid.UUID(placed.version_id),
        created_by=placed.api.actor,
    )
    assert [i.instance_id for i in kept.point_map_instances] == ["point-map:kitchen"]

    withdraw_model_right(
        placed.repository, right_id=placed.right.right_id, withdrawn_by=placed.api.actor
    )
    dropped = worlds.create_version(
        title="Branch after stopping it",
        parent_version_id=uuid.UUID(placed.version_id),
        created_by=placed.api.actor,
    )
    assert dropped.point_map_instances == ()
    # The parent keeps its placement; only the copy declines to repeat it.
    assert len(placed.instances()) == 1


def test_a_package_export_withholds_a_world_holding_a_placed_estimate(placed):
    """A crate leaves this machine, and a withdrawal here cannot reach it there."""
    from exulanica.world_package.environments import ExportVersion, partition_export_versions

    kept_id, withheld_id = uuid.uuid4(), uuid.uuid4()
    authored, environment, authored_withheld, environment_withheld = partition_export_versions(
        (
            ExportVersion(kept_id, None, environment_bearing=False, source_invalidated=False),
            ExportVersion(
                withheld_id,
                None,
                environment_bearing=False,
                source_invalidated=False,
                point_map_bearing=True,
            ),
        )
    )
    assert authored == (kept_id,)
    assert withheld_id not in authored and withheld_id not in environment
    assert (authored_withheld, environment_withheld) == (1, 0)
