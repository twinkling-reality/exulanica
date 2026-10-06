"""World kinds through the application: kept in a workspace, made into worlds, lived in, drawn.

The application as a deployment runs it (the runtime role under row-level security, with the
society runtime every instance builds). The kinds are the hand-written fixtures in
``tests/fixtures/world-kinds`` (test fixtures, not kinds a person or a model made), sent as a
creator would send them, with the origin ``uploaded``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import psycopg
import pytest
from exulanica.api.routes import world_kinds as kinds_route
from exulanica.world.generated_worlds import (
    SiteRecordsElsewhere,
    generation_receipt,
    town_records,
)
from exulanica.world.kinds import repository as kinds_repository
from exulanica.world.kinds.worker import JobOutcome, Kept, kind_worker
from exulanica.world.society_engines import CREATES
from exulanica.world.world_recipes import town_recipe

from personal_world_support import OWNER_TOKEN, STRANGER_TOKEN
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
LIVING = CREATES["town"]


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


def _uploaded(name: str) -> dict[str, Any]:
    document = json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8"))
    document["origin"] = "uploaded"
    document["provenance"] = {"by": "a test creator"}
    return document


def _keep(api, name: str) -> dict[str, Any]:
    response = api.post("/worlds/kinds", {"document": _uploaded(name)})
    assert response.status_code == 201, response.text
    return response.json()


def _world(api, kind: str, preset: str, title: str) -> dict[str, Any]:
    response = api.post(f"/worlds/kinds/{kind}/worlds", {"preset": preset, "title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_a_creator_s_kind_is_kept_listed_made_into_a_world_and_drawn_for_its_world(made):
    api = made
    kept = _keep(api, "farm")
    assert kept["kind"]["kind"] == "fixture_farm" and kept["kind"]["source"] == "workspace"
    assert kept["validation"]["verdict"] == "passed"
    library = api.get("/worlds/kinds").json()
    listed = {(kind["kind"], kind["source"]) for kind in library["kinds"]}
    assert ("town", "shipped") in listed and ("fixture_farm", "workspace") in listed
    entry = _world(api, "fixture_farm", "small_farm", "Our farm")
    assert entry["source_kind"] == "generated" and entry["generated_ground"] is None
    site = entry["generated_site"]
    assert (site["kind"], site["kind_version"], site["region_id"]) == (
        "fixture_farm",
        1,
        "region:generated",
    )
    listed_entry = next(
        e for e in api.get("/world-entries").json() if e["entry_id"] == entry["entry_id"]
    )
    assert listed_entry["generated_site"] == site
    path = f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    served = api.get(path)
    assert served.status_code == 200, served.text
    drawing = served.json()
    assert drawing["kind"]["kind"] == "fixture_farm" and drawing["world_id"] == entry["world_id"]
    assert drawing["slots"] and drawing["walk"]["blockersMm"]
    canonical = json.dumps(drawing, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert served.headers["etag"] == f'"{hashlib.sha256(canonical.encode()).hexdigest()}"'
    # A stranger is told the world does not exist, as for every world route.
    assert api.get(path, token=STRANGER_TOKEN).status_code == 404
    # The receipt the snapshot names carries the kind document the world was made from.
    with api.database.session(api.repository.workspace_id) as connection:
        _digest, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    assert receipt["kind"]["sha256"] == kept["kind"]["sha256"]
    assert "tiles" not in receipt


def test_a_kind_is_kept_once_and_a_refused_kind_writes_nothing(made):
    api = made
    _keep(api, "cafe")
    again = api.post("/worlds/kinds", {"document": _uploaded("cafe")})
    assert again.status_code == 409 and again.json()["code"] == "kind_version_exists"
    closed = _uploaded("farm")
    closed["zones"][0]["access"] = "closed"
    refused = api.post("/worlds/kinds", {"document": closed})
    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["code"] == "kind_unreachable" and body["report"]["verdict"] == "refused"
    authored = _uploaded("farm")
    authored["origin"] = "authored"
    authored["provenance"] = {"by": "someone"}
    not_uploaded = api.post("/worlds/kinds", {"document": authored})
    assert not_uploaded.status_code == 422 and not_uploaded.json()["where"] == "origin"
    kinds = {kind["kind"] for kind in api.get("/worlds/kinds").json()["kinds"]}
    assert "fixture_farm" not in kinds and "fixture_cafe" in kinds


def test_a_value_the_kind_does_not_offer_and_an_unknown_kind_are_refused_by_name(made):
    api = made
    _keep(api, "site")
    outside = api.post(
        "/worlds/kinds/fixture_building_site/worlds",
        {"preset": "small_job", "title": "Our site", "values": {"workers": 41}},
    )
    assert (
        outside.status_code == 422 and outside.json()["code"] == "specification_value_out_of_range"
    )
    unknown = api.post("/worlds/kinds/windmill/worlds", {"preset": "x", "title": "x"})
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_world_kind"
    no_preset = api.post(
        "/worlds/kinds/fixture_building_site/worlds", {"preset": "big_job", "title": "x"}
    )
    assert no_preset.status_code == 404 and no_preset.json()["code"] == "unknown_world_recipe"


def test_the_town_made_from_its_kind_is_the_town_made_from_its_preset(made):
    api = made
    entry = _world(api, "town", "small_town", "Our town")
    assert (
        entry["generated_site"] is None and entry["generated_ground"]["recipe_key"] == "small_town"
    )
    with api.database.session(api.repository.workspace_id) as connection:
        _digest, receipt = generation_receipt(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
        )
    # The same gate's reference, read from the recipe catalog here, not from the route.
    assert receipt["recipe"] == town_recipe("small_town", {}).reference()


def test_people_live_in_a_site_world_on_its_own_surfaces_under_its_own_routine(made):
    api = made
    _keep(api, "cafe")
    entry = _world(api, "fixture_cafe", "quiet_cafe", "Our cafe")
    society = f"/world/versions/{entry['authored_version_id']}/society?world_id={entry['world_id']}"
    created = api.post(society, {"region_id": "region:generated", "profile": LIVING})
    assert created.status_code in (200, 201), created.text
    body = created.json()
    with api.database.session(api.repository.workspace_id) as connection:
        document = connection.execute(
            "select i.document from world_society_input i join world_society s on "
            "s.workspace_id=i.workspace_id and s.society_id=i.society_id where "
            "s.workspace_id=%s and s.world_id=%s and i.input_seq=1",
            (api.repository.workspace_id, entry["world_id"]),
        ).fetchone()["document"]
    assert document["profile"] == "exulanica.society-input/walking-surfaces-v2"
    assert document["navigation"]["profile"] == "site-walking-surfaces/v1"
    routine = document["living"]["routine"]
    assert routine["overlay"]["profile"] == "exulanica.routine-overlay/v1"
    place = document["living"]["place"]
    # Everybody here comes in from a home off the site: the kind's preset says ten.
    residents = sum(d["resident_capacity"] for d in place["destinations"])
    assert residents == document["population"]["size"] == 10
    assert len(body["state"]["inhabitants"]) == residents
    assert {ref["kind"] for ref in document["dependency_refs"]} >= {"site_place"}
    assert "city_place" not in {ref["kind"] for ref in document["dependency_refs"]}


def test_a_kind_version_is_append_only_and_stays_in_its_workspace(made):
    api = made
    _keep(api, "farm")
    workspace = api.repository.workspace_id
    with (
        api.database.session(workspace) as connection,
        pytest.raises(psycopg.Error),
        connection.transaction(),
    ):
        connection.execute(
            "update world_kind_version set origin='authored' where kind='fixture_farm'"
        )
    with api.database.session(uuid.uuid4()) as other:
        assert other.execute("select count(*) as n from world_kind_version").fetchone()["n"] == 0


def test_a_site_receipt_with_tiles_or_without_its_kind_is_refused_by_the_schema(made):
    api = made
    _keep(api, "farm")
    entry = _world(api, "fixture_farm", "small_farm", "Our farm")
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        _digest, receipt = generation_receipt(
            connection, workspace, entry["world_id"], uuid.UUID(entry["source_snapshot_id"])
        )
        for broken in (
            {**copy.deepcopy(dict(receipt)), "tiles": [[0, 0]]},
            {key: value for key, value in receipt.items() if key != "kind"},
        ):
            with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
                connection.execute(
                    "insert into world_generation_receipt (workspace_id,world_id,"
                    "receipt_sha256,receipt,created_by) values (%s,%s,%s,%s,%s)",
                    (
                        workspace,
                        entry["world_id"],
                        "a" * 64,
                        psycopg.types.json.Jsonb(broken),
                        uuid.uuid4(),
                    ),
                )


def test_an_upload_is_held_to_its_size_first_and_kept_with_its_uploader_not_its_words(made):
    api = made
    huge = _uploaded("cafe")
    huge["summary"] = "x" * 150_000
    # A body over the route's own bound is refused before it is read or parsed.
    refused = api.post("/worlds/kinds", {"document": huge})
    assert refused.status_code == 413 and refused.json()["code"] == "body_too_large"
    assert "131072" in refused.json()["detail"]
    big = _uploaded("cafe")
    big["summary"] = "x" * 70_000
    refused = api.post("/worlds/kinds", {"document": big})
    assert refused.status_code == 422 and "at most 65536 bytes" in refused.json()["detail"]
    kept = _keep(api, "cafe")
    library = {k["kind"]: k for k in api.get("/worlds/kinds").json()["kinds"]}
    assert "fixture_cafe" in library
    with api.database.session(api.repository.workspace_id) as connection:
        row = connection.execute(
            "select document->'provenance' as p, created_by from world_kind_version "
            "where kind='fixture_cafe'"
        ).fetchone()
    # The words the creator sent ("a test creator") are not kept, and the document names no
    # account: the row's own column records who uploaded it.
    assert row["p"] == {"by": "an upload to its workspace"}
    assert row["created_by"] == api.actor and str(api.actor) not in json.dumps(row["p"])
    assert kept["kind"]["kind"] == "fixture_cafe"


def test_a_value_that_is_not_a_number_is_refused_in_words_not_with_a_500(made):
    api = made
    _keep(api, "site")
    # Sent as raw JSON: a client's encoder refuses to write NaN, and Python's reader accepts it.
    refused = api.client.post(
        "/worlds/kinds/fixture_building_site/worlds",
        content=b'{"preset": "small_job", "title": "x", "values": {"workers": NaN}}',
        headers={"Authorization": f"Bearer {OWNER_TOKEN}", "Content-Type": "application/json"},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["value"] == "nan"


class _WorkerThatMustNotRun:
    checks = drawings = places = Kept(1)

    def run(self, *args: Any, **kwargs: Any) -> JobOutcome:
        raise AssertionError("the kind worker was asked to build something")


def test_a_workspace_keeps_no_more_kind_versions_than_its_cap(made, monkeypatch):
    api = made
    monkeypatch.setattr(kinds_repository, "KINDS_PER_WORKSPACE", 1)
    _keep(api, "farm")
    # Refused before any sample world is built for it, as a kept version is.
    monkeypatch.setattr(kinds_route, "kind_worker", _WorkerThatMustNotRun)
    refused = api.post("/worlds/kinds", {"document": _uploaded("cafe")})
    assert refused.status_code == 409 and refused.json()["code"] == "kind_cap_reached"
    again = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    assert again.status_code == 409 and again.json()["code"] == "kind_version_exists"


def test_work_the_kind_worker_cannot_take_is_answered_503_with_when_to_ask_again(made, monkeypatch):
    api = made

    class Busy:
        checks = drawings = Kept(1)

        def run(self, *args: Any, **kwargs: Any) -> JobOutcome:
            return JobOutcome("busy", reason="workspace")

    monkeypatch.setattr(kinds_route, "kind_worker", Busy)
    refused = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    assert refused.status_code == 503 and refused.json()["code"] == "kind_work_busy"
    assert refused.headers["retry-after"] == "2"
    assert "This workspace" in refused.json()["detail"]


def test_a_site_world_is_never_generated_on_a_request_s_thread(made, monkeypatch):
    api = made
    _keep(api, "farm")
    entry = _world(api, "fixture_farm", "small_farm", "Our farm")
    # From here, generating a site's records in this process fails the request that does it.
    from exulanica.world.composers import site_plan

    def generated_here(receipt: Any) -> tuple[object, ...]:
        raise AssertionError("a site's records were generated on a request's thread")

    monkeypatch.setattr(site_plan, "records", generated_here)
    worker = kind_worker()
    # Nothing kept: the drawing and the place are generated again, in the worker.
    monkeypatch.setattr(worker, "drawings", Kept(16))
    monkeypatch.setattr(worker, "places", Kept(16))
    version, world = entry["authored_version_id"], entry["world_id"]
    served = api.get(f"/world/versions/{version}/site?world_id={world}")
    assert served.status_code == 200, served.text
    assert served.json()["world_id"] == world
    # The reads that ask a world for its roads say a site world states none, generating nothing.
    capabilities = api.get(f"/world/versions/{version}/capabilities?world_id={world}")
    assert capabilities.status_code == 200, capabilities.text
    traffic = api.get(f"/world/versions/{version}/traffic?world_id={world}")
    assert traffic.status_code != 500, traffic.text
    with (
        api.database.session(api.repository.workspace_id) as connection,
        pytest.raises(SiteRecordsElsewhere),
    ):
        town_records(
            connection, api.repository.workspace_id, world, uuid.UUID(entry["source_snapshot_id"])
        )

    # People brought in walk the place the worker makes; none of it is made on this thread.
    def placed_here(*args: Any) -> dict[str, Any]:
        raise AssertionError("a site's place was made on a request's thread")

    monkeypatch.setattr(site_plan, "society_place", placed_here)
    society = f"/world/versions/{version}/society?world_id={world}"
    created = api.post(society, {"region_id": "region:generated", "profile": LIVING})
    assert created.status_code in (200, 201), created.text
    assert created.json()["state"]["inhabitants"]


def test_a_lone_surrogate_a_client_sends_is_said_back_escaped_not_with_a_500(made):
    api = made
    _keep(api, "site")
    headers = {"Authorization": f"Bearer {OWNER_TOKEN}", "Content-Type": "application/json"}
    for values, code in (
        (b'{"workers": "\\ud800"}', "specification_value_out_of_range"),
        (b'{"\\ud800": 1}', "specification_value_unknown"),
    ):
        refused = api.client.post(
            "/worlds/kinds/fixture_building_site/worlds",
            content=b'{"preset": "small_job", "title": "x", "values": ' + values + b"}",
            headers=headers,
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == code
        assert "\\ud800" in refused.text


def test_the_library_reads_each_kept_document_once(made, monkeypatch):
    api = made
    _keep(api, "farm")
    _keep(api, "cafe")
    read: list[str] = []
    original = kinds_repository.read_kind

    def counted(document: Any) -> Any:
        read.append(document["kind"])
        return original(document)

    monkeypatch.setattr(kinds_repository, "read_kind", counted)
    monkeypatch.setattr(kinds_repository, "_read", type(kinds_repository._read)())
    for _ in range(3):
        listed = api.get("/worlds/kinds")
        assert listed.status_code == 200
    assert sorted(read) == ["fixture_cafe", "fixture_farm"]


def test_a_kept_kind_that_no_longer_reads_is_left_out_and_refused_by_name(made):
    api = made
    kept = _keep(api, "farm")
    workspace = api.repository.workspace_id
    with api.database.session(workspace) as connection:
        document = connection.execute(
            "select document from world_kind_version where kind='fixture_farm'"
        ).fetchone()["document"]
        # As a later catalog edit could leave it: a look family no catalog states any more.
        document = {**document, "kind": "fixture_old", "version": 1}
        document["site"] = {**document["site"], "ground": "nowhere.grass"}
        connection.execute(
            "insert into world_kind_version (workspace_id,kind,version,document_sha256,document,"
            "origin,validation,created_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                workspace,
                "fixture_old",
                1,
                "b" * 64,
                psycopg.types.json.Jsonb(document),
                "uploaded",
                psycopg.types.json.Jsonb(
                    {
                        **kept["validation"],
                        "kind": {**kept["validation"]["kind"], "sha256": "b" * 64},
                    }
                ),
                api.actor,
            ),
        )
    listed = api.get("/worlds/kinds")
    assert listed.status_code == 200
    assert {k["kind"] for k in listed.json()["kinds"]} >= {"fixture_farm"}
    assert "fixture_old" not in {k["kind"] for k in listed.json()["kinds"]}
    refused = api.post("/worlds/kinds/fixture_old/worlds", {"preset": "small_farm", "title": "x"})
    assert refused.status_code == 409 and refused.json()["code"] == "kind_unreadable"


def test_the_site_route_says_a_starter_world_is_not_made_from_a_kind(made):
    api = made
    starter = api.post("/world-entries/starter", {"title": "Our square"})
    assert starter.status_code in (200, 201), starter.text
    entry = starter.json()
    path = f"/world/versions/{entry['authored_version_id']}/site?world_id={entry['world_id']}"
    answered = api.get(path)
    assert answered.status_code == 404 and answered.json()["code"] == "unknown_reference"


def test_a_stranger_cannot_tell_a_kind_another_workspace_keeps_from_an_invented_one(made):
    # The route takes {kind}, which the generic existence-oracle sweep (it reads *_id placeholders)
    # does not ask about; this asks for it.
    api = made
    _keep(api, "farm")
    body = {"preset": "small_farm", "title": "Theirs"}
    theirs = api.post("/worlds/kinds/fixture_farm/worlds", body, token=STRANGER_TOKEN)
    invented = api.post("/worlds/kinds/fixture_nowhere/worlds", body, token=STRANGER_TOKEN)
    assert theirs.status_code == invented.status_code == 404
    assert theirs.json()["code"] == invented.json()["code"] == "unknown_world_kind"


def test_a_kind_key_another_workspace_chose_is_a_fresh_kind_of_ones_own(made):
    # A kind's key is an id the caller chooses (CHOSEN_IDS asks this of *_id fields); the table is
    # keyed by workspace, so another workspace's key is answered as a fresh one is.
    api = made
    _keep(api, "cafe")
    again = api.post("/worlds/kinds", {"document": _uploaded("cafe")}, token=STRANGER_TOKEN)
    assert again.status_code == 201, again.text


def test_two_workspaces_sending_one_kind_are_told_nothing_of_each_other_s_check(made, monkeypatch):
    api = made
    asked: list[str] = []

    class Recording:
        checks = drawings = places = Kept(1)

        def run(self, key: str, *args: Any, **kwargs: Any) -> JobOutcome:
            asked.append(key)
            return JobOutcome("busy")

    monkeypatch.setattr(kinds_route, "kind_worker", Recording)
    for token in (OWNER_TOKEN, STRANGER_TOKEN):
        answered = api.post("/worlds/kinds", {"document": _uploaded("cafe")}, token=token)
        assert answered.status_code == 503
    # One document, two workspaces, two checks kept apart by workspace.
    assert len(asked) == 2 and len(set(asked)) == 2
    assert str(api.repository.workspace_id) in asked[0]
    assert asked[0].split(":")[-1] == asked[1].split(":")[-1]


@pytest.mark.parametrize(
    "path", ["/worlds/kinds/town/worlds", "/worlds/generated"], ids=["kinds", "generated"]
)
def test_a_town_value_json_cannot_say_back_is_refused_in_words_not_with_a_500(made, path):
    api = made
    headers = {"Authorization": f"Bearer {OWNER_TOKEN}", "Content-Type": "application/json"}
    preset = "preset" if path.startswith("/worlds/kinds") else "recipe"
    for values in (b'{"x": NaN}', b'{"x": Infinity}', b'{"\\ud800": 1}'):
        refused = api.client.post(
            path,
            content=b'{"'
            + preset.encode()
            + b'": "small_town", "title": "x", "values": '
            + values
            + b"}",
            headers=headers,
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "specification_value_unknown"


def test_a_title_holding_a_control_or_format_character_is_refused_before_anything_is_made(
    made, monkeypatch
):
    api = made
    _keep(api, "farm")
    monkeypatch.setattr(kinds_route, "kind_worker", _WorkerThatMustNotRun)
    for title in ("a\u0000b", "a​b", "a‮b"):
        refused = api.post(
            "/worlds/kinds/fixture_farm/worlds", {"preset": "small_farm", "title": title}
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["code"] == "invalid_saved_world_entry"
