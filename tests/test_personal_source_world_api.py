"""Making the personal-source world from reviewed photographs, through the routes a browser uses.

``GET /worlds/personal-source`` says what composing now would do or names why not, and
``POST /worlds/personal-source`` does exactly that or refuses by name with nothing written. The
application here connects as provisioned runtime roles with row-level security in force, not as
the schema owner the other API fixtures use, so what a stranger can see is what a deployment
shows.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.orchestration.reference_world import compose_reference_sources

from personal_world_support import (
    PATH,
    STRANGER_TOKEN,
    bootstrap,
    compose,
    depth_estimate,
    group,
    personal_world_api,
    photograph,
    renew,
    save_entry,
    source_media,
    wait_until,
)

pytestmark = pytest.mark.postgres


@pytest.fixture
def api(tmp_path, repository, spine_schema):
    yield from personal_world_api(tmp_path, repository, spine_schema)


def test_no_reviewed_photograph_is_refused_by_name_and_writes_nothing(api):
    # Authorized but never screened, screened only for person detection, and reviewed by
    # somebody else: none is the account holder's human review, so none counts.
    photograph(api, minute=0, review=None)
    photograph(api, minute=1, review="detection")
    photograph(api, minute=2, by=uuid.uuid4())
    group(api)
    read = api.read()
    assert read["action"] is None
    assert read["refusal"]["code"] == "no_reviewed_personal_sources"
    assert "Review your photographs first" in read["refusal"]["detail"]
    assert read["photographs"] == {"reviewed": 0, "composed": 0, "outside_scene_groups": 0}
    assert read["topology_digest"] is None
    refused = compose(api, "0" * 64)
    assert refused.status_code == 409
    assert refused.json() == {"code": read["refusal"]["code"], "detail": read["refusal"]["detail"]}
    assert api.worlds() == []


def test_a_reviewed_photograph_in_no_scene_group_is_left_out_and_counted(api):
    photograph(api, minute=0, when=False)
    group(api)
    read = api.read()
    assert read["refusal"]["code"] == "no_grouped_personal_sources"
    assert read["photographs"] == {"reviewed": 1, "composed": 0, "outside_scene_groups": 1}
    assert read["regions"] == 0
    # A grouped one beside it is composed; the ungrouped one stays out and is still counted.
    photograph(api, minute=2)
    group(api)
    read = api.read()
    assert read["action"] == "create_world"
    assert read["photographs"] == {"reviewed": 2, "composed": 1, "outside_scene_groups": 1}
    assert read["regions"] == 1


def test_composing_makes_the_world_the_browser_then_saves_and_names(api):
    first = photograph(api, minute=0)
    second = photograph(api, minute=3)
    group(api)
    read = api.read()
    assert read["action"] == "create_world"
    assert read["refusal"] is None and read["world_id"] is None
    assert read["photographs"] == {"reviewed": 2, "composed": 2, "outside_scene_groups": 0}
    assert read["regions"] == 1

    composed = compose(api, read["topology_digest"])
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
    bootstrap(api, body["world_id"], "From my photographs")
    assert api.read()["action"] == "save_entry"
    entry = save_entry(api, body["world_id"])
    assert entry["world_id"] == body["world_id"]
    after = api.read()
    assert after["action"] is None
    assert after["refusal"]["code"] == "personal_world_current"
    assert after["saved_entry_id"] == entry["entry_id"]
    assert compose(api, after["topology_digest"]).json()["code"] == "personal_world_current"


def test_a_digest_the_person_was_not_shown_is_refused_and_writes_nothing(api):
    photograph(api, minute=0)
    group(api)
    shown = api.read()["topology_digest"]
    # Another reviewed photograph arrives between the read and the write.
    photograph(api, minute=4)
    group(api)
    refused = compose(api, shown)
    assert refused.status_code == 409
    assert refused.json()["code"] == "personal_sources_changed"
    assert api.worlds() == []
    assert compose(api, api.read()["topology_digest"]).status_code == 200


def test_the_route_and_the_operator_script_are_one_writer_of_one_world(api):
    capture = photograph(api, minute=0)
    record = compose_reference_sources(
        api.repository,
        region_id="operator-region",
        captures=[(capture, api.repository.capture(capture).blob_id.hex, "operator.jpg")],
        source_manifest_sha256="ab" * 32,
        actor=api.actor,
    )
    api.repository.connection.commit()
    group(api)
    read = api.read()
    # The script made the world; the route composes into it rather than making a second one.
    assert read["world_id"] == record["world_id"]
    assert read["action"] == "update_world"
    assert compose(api, read["topology_digest"]).json()["world_id"] == record["world_id"]
    assert [world["world_id"] for world in api.worlds()] == [record["world_id"]]


def test_a_stranger_sees_none_of_the_owners_photographs_or_world(api):
    photograph(api, minute=0)
    group(api)
    compose(api, api.read()["topology_digest"])
    stranger = api.get(PATH, token=STRANGER_TOKEN)
    assert stranger.status_code == 200, stranger.text
    assert stranger.json()["refusal"]["code"] == "no_reviewed_personal_sources"
    assert stranger.json()["world_id"] is None
    assert stranger.json()["photographs"]["reviewed"] == 0


#: The reason a world's source slot gives when its personal photograph is no longer allowed.
_LAPSED = "its personal authorization or human review is no longer current"


def test_a_made_world_stops_drawing_a_photograph_whose_review_lapsed_until_reviewed_again(api):
    capture = photograph(api, minute=0, valid_seconds=6)
    artifact, _right = depth_estimate(api, capture)
    group(api)
    created = compose(api, api.read()["topology_digest"]).json()
    entry = save_entry(api, created["world_id"])
    [slot] = source_media(api, entry)
    assert slot["state"] == "available"
    assert slot["evidence_path"] == f"/evidence/{slot['evidence_span_id']}/masked"
    assert str(artifact) in {row["artifact_id"] for row in api.get("/geometry").json()}
    assert api.get(f"/geometry/{artifact}").status_code == 200

    wait_until(api.receipts[capture][3])
    [slot] = source_media(api, entry)
    # The world stops drawing it: no viewer, no evidence path, and a reason that says why.
    assert slot["state"] == "unavailable_asset"
    assert slot["reason"] == _LAPSED
    assert slot["evidence_path"] is None and slot["asset_reference"] is None
    # Its depth estimate was bound to the review and the right, and is refused with them.
    assert str(artifact) not in {row["artifact_id"] for row in api.get("/geometry").json()}
    assert api.get(f"/geometry/{artifact}").status_code == 404
    # The library keeps the photograph: it stays the account holder's to see.
    assert api.get(f"/evidence/{slot['evidence_span_id']}/masked").status_code == 200

    renew(api, capture)
    [slot] = source_media(api, entry)
    assert slot["state"] == "available" and slot["reason"] is None
    assert slot["evidence_path"] == f"/evidence/{slot['evidence_span_id']}/masked"
