"""What each kind of world supports, read through the application as a deployment runs it.

Every request here is an authenticated HTTP request against the real application, connected as a
provisioned runtime role with row-level security on (``test_society_made_world.made``). Each
capability read is held to the authority it projects: the regions it lists are exactly the
regions an object may be placed in, an arrangement it calls unsupported is one the preview blocks
by the same code, and a model choice is refused with the status the people's own route gives the
same code. A society's input names the authored edit it followed, and an event joins to it. Two
extensions show that an option or a role reaches the reads from its own catalog or registry, with
no second definition in discovery.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from typing import Any

import exulanica.api.role_hosts as role_hosts_module
import exulanica.api.routes.world_models as world_models_module
import pytest
from exulanica.api.authorisation import load_token_directory
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world import action_catalog
from exulanica.world.arrangements import arrangement_catalog
from exulanica.world.assets import reviewed_assets
from exulanica.world.decision_roles import RoleRegistry, decision_roles
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.starter import AUTHORED_SPAWN_X_MM, AUTHORED_SPAWN_Z_MM

import personal_world_support as personal
import test_world_traffic_route as traffic
from test_society_made_world import made as imported_made  # noqa: F401
from test_world_models_route import _signalled
from tests_support_api import EVERY_PERMISSION

pytestmark = pytest.mark.postgres
_presets_try_every_candidate = traffic._presets_try_every_candidate

BENCH = next(asset for asset in reviewed_assets() if asset.asset_key == "cc0.bench")
SQUARE = arrangement_catalog().by_key()["small_square"]
FACING_THE_CENTRE = 3_141_593
V = "/world/versions/{version_id}"
#: A test-only reviewed behaviour, published into the registry for one test and taken out again.
TRIAL_BEHAVIOUR = "motion.capability-trial"


@pytest.fixture
def api(request):
    return request.getfixturevalue("imported_made")


def _in(entry: dict[str, Any], path: str) -> str:
    return f"{path}{'&' if '?' in path else '?'}world_id={entry['world_id']}"


def _version_path(entry: dict[str, Any], suffix: str = "") -> str:
    return _in(entry, f"/world/versions/{entry['authored_version_id']}{suffix}")


def _capabilities(api, entry: dict[str, Any], token: str = personal.OWNER_TOKEN) -> dict[str, Any]:
    response = api.get(_version_path(entry, "/capabilities"), token=token)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["profile"] == "exulanica.world-capabilities/v1"
    assert document["world_id"] == entry["world_id"]
    assert document["version_id"] == entry["authored_version_id"]
    return document


def _operation(document: dict[str, Any], operation: str, **bind: str) -> dict[str, Any]:
    found = [
        row
        for row in document["operations"]
        if row["operation"] == operation
        and all(row["bind"].get(key) == value for key, value in bind.items())
    ]
    assert len(found) == 1, (operation, bind, [row["operation"] for row in document["operations"]])
    return found[0]


def _state(document: dict[str, Any], operation: str, **bind: str) -> tuple[str, str | None]:
    row = _operation(document, operation, **bind)
    return row["state"], row["code"]


def _creation(api, token: str = personal.OWNER_TOKEN) -> dict[str, dict[str, Any]]:
    response = api.get("/worlds/capabilities", token=token)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["profile"] == "exulanica.world-creation/v1"
    assert document["policy"]["policy_id"] == "exulanica.world-count"
    return {row["kind"]: row for row in document["kinds"]}


def _starter(api) -> dict[str, Any]:
    response = api.post("/world-entries/starter", {"title": "Capabilities"})
    assert response.status_code == 200, response.text
    return response.json()


def _place(
    api,
    entry: dict[str, Any],
    region_id: str,
    *,
    object_id: str = "object:bench",
    base: str | None = None,
    x_mm: int = 3_000,
    z_mm: int = 5_000,
):
    version = api.version(entry)
    return api.post(
        _version_path(entry, "/objects"),
        {
            "base_state_sha256": base or version["state_sha256"],
            "object_id": object_id,
            "asset_sha256": BENCH.content_sha256,
            "region_id": region_id,
            "transform": {
                "x_mm": x_mm,
                "y_mm": 0,
                "z_mm": z_mm,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            },
            "origin_role": "fictional",
        },
    )


def _with_grant(api, permissions: list[str]) -> str:
    """A token for the owner's workspace holding only ``permissions``, added to the running app."""
    token = f"capability-reader-{uuid.uuid4().hex}"
    services = api.client.app.state.services
    grants = {
        personal.OWNER_TOKEN: {
            "workspace_id": str(api.repository.workspace_id),
            "actor": str(api.actor),
            "permissions": EVERY_PERMISSION,
        },
        token: {
            "workspace_id": str(api.repository.workspace_id),
            "actor": str(api.actor),
            "permissions": permissions,
        },
    }
    api.client.app.state.services = dataclasses.replace(
        services, tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(grants)})
    )
    return token


# -- making worlds ---------------------------------------------------------------------------------


def test_what_a_workspace_may_make_follows_what_it_holds(api):
    kinds = _creation(api)
    assert set(kinds) == {"authored-starter", "generated", "personal-source"}
    assert kinds["authored-starter"]["create"]["operation"] == "POST /world-entries/starter"
    assert kinds["authored-starter"]["create"]["state"] == "available"
    assert kinds["generated"]["create"]["state"] == "available"
    # The count policy's own figure for a signed-in person's workspace.
    assert kinds["generated"]["limit"] == 24 and kinds["generated"]["held"] == 0
    assert kinds["generated"]["create"]["options"] == [
        "GET /worlds/recipes",
        "GET /worlds/specification",
    ]
    personal_plan = api.read()
    creating = kinds["personal-source"]["create"]
    # The personal-source plan the preview read serves is the state, by its own refusal code.
    assert creating["state"] == "unavailable"
    assert creating["code"] == personal_plan["refusal"]["code"]
    assert creating["preview"] == {
        "operation": "GET /worlds/personal-source",
        "required": True,
        "token": "topology_digest",
    }
    assert kinds["personal-source"]["kind_facts"]["takes_photographs"] is True
    assert kinds["generated"]["kind_facts"]["takes_photographs"] is False

    _starter(api)
    kinds = _creation(api)
    assert kinds["authored-starter"]["held"] == 1
    # The starter's own rule, reported as it behaves: a workspace holding a saved world makes no
    # other starter, whatever the count policy states for starters.
    assert kinds["authored-starter"]["limit"] is None
    assert (
        kinds["authored-starter"]["create"]["state"],
        kinds["authored-starter"]["create"]["code"],
    ) == (
        "unavailable",
        "saved_world_conflict",
    )
    refused = api.post("/world-entries/starter", {"title": "Another"})
    assert refused.status_code == 409 and refused.json()["code"] == "saved_world_conflict"


def test_making_a_town_is_unavailable_by_the_budget_that_refuses_it(api, monkeypatch):
    """The read reports the figure in force, a deployment's own where it states one, and names
    which of the two budgets leaves no room: the worlds held, or the day's tiles."""
    monkeypatch.setenv("EXULANICA_WORLDS_HELD", "5")
    monkeypatch.setenv("EXULANICA_TILES_A_DAY", "2")
    assert _creation(api)["generated"]["limit"] == 5
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "Today's town"})
    assert made.status_code == 201, made.text
    generated = _creation(api)["generated"]
    assert generated["held"] == 1
    # One two-tile town is all of a day's two tiles: no room for even one tile more.
    assert (generated["create"]["state"], generated["create"]["code"]) == (
        "unavailable",
        "tile_budget_reached",
    )
    monkeypatch.setenv("EXULANICA_TILES_A_DAY", "48")
    monkeypatch.setenv("EXULANICA_WORLDS_HELD", "1")
    generated = _creation(api)["generated"]
    assert (generated["limit"], generated["create"]["code"]) == (1, "world_limit_reached")


def test_a_caller_who_may_not_read_admission_is_told_it_is_not_known(api):
    token = _with_grant(api, ["world.read", "world.write"])
    kinds = _creation(api, token=token)
    creating = kinds["personal-source"]["create"]
    assert creating["permitted"] is False
    assert (creating["state"], creating["code"]) == ("unknown", None)
    assert kinds["authored-starter"]["create"]["permitted"] is True


# -- one version of each kind ----------------------------------------------------------------------


def test_a_starter_world_lists_its_region_and_takes_an_edit_there_and_nowhere_else(api):
    entry = _starter(api)
    document = _capabilities(api, entry)
    assert document["kind"] == "authored-starter"
    assert document["regions"] == {
        "state": "listed",
        "code": None,
        "region_ids": ["region:starter"],
    }
    assert document["society"] == {"held": False, "engine": "exulanica-society/v2"}
    placing = _operation(document, "POST /world/versions/{version_id}/objects")
    assert placing["state"] == "available" and placing["permitted"] is True
    assert placing["base"] == [
        {
            "field": "base_state_sha256",
            "read": "GET /world/versions/{version_id}",
            "value": "state_sha256",
        }
    ]
    assert placing["effects"] == [{"on": "society", "state": "available", "code": None}]
    assert _state(document, "POST /world/versions/{version_id}/society/presence") == (
        "unavailable",
        "society_unavailable",
    )
    assert _state(document, "GET /world/versions/{version_id}/traffic") == (
        "unavailable",
        "roads_not_stated",
    )

    # Every region the read lists is one the validator accepts, and any other is refused.
    refused = _place(api, entry, "region-nowhere")
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_object_data"
    before = api.version(entry)["state_sha256"]
    placed = _place(api, entry, document["regions"]["region_ids"][0])
    assert placed.status_code == 201, placed.text
    # The base the read named, reread; the old one is refused by name and nothing changes.
    stale = _place(api, entry, "region:starter", object_id="object:second", base=before)
    assert stale.status_code == 409 and stale.json()["code"] == "stale_object_base"
    reread = api.version(entry)
    assert reread["state_sha256"] == placed.json()["state_sha256"]
    assert [obj["object_id"] for obj in reread["objects"]] == ["object:bench"]


def test_the_read_lists_every_offered_action_by_its_id_with_its_operation_s_state(api):
    """The action catalog as the version's read serves it: every offered id once, each with the
    state, code, permissions and holding of the one operation of this same read that projects its
    route and bind, and an action no operation projects saying so with no state."""
    entry = _starter(api)
    document = _capabilities(api, entry)
    actions = {action["id"]: action for action in document["actions"]}
    assert list(actions) == [action.id for action in action_catalog.offered()]
    unprojected = set()
    for ident, action in actions.items():
        run = action["runs_by"]
        rows = [
            row
            for row in document["operations"]
            if row["operation"] == run["route"]
            and all(row["bind"].get(key) == value for key, value in run["bind"].items())
        ]
        if not rows:
            unprojected.add(ident)
            assert (action["projected"], action["state"], action["code"]) == (False, None, None)
            continue
        # One operation, and the action says what it says.
        [row] = rows
        assert action["projected"] is True, ident
        assert (action["state"], action["code"]) == (row["state"], row["code"]), ident
        assert (action["requires"], action["permitted"]) == (row["requires"], row["permitted"])
    # The four whose subject is one being, or the world apart from any version: "ask where its
    # subject is read", never "not permitted" (the owner here holds every permission).
    assert unprojected == {
        "pieces.request",
        "beings.play",
        "beings.give-back",
        "world.make",
    }
    assert all(actions[ident]["permitted"] for ident in unprojected)
    # A starter world holds no society: the clock's three actions share one operation's refusal.
    states = {actions[ident]["state"] for ident in ("clock.play", "clock.pause", "clock.speed")}
    assert len(states) == 1 and states != {"available"}
    # No reserved id is served, and none of a later version's.
    assert not {a.id for a in action_catalog.actions() if a.status != "offered"} & set(actions)

    # A caller who may only read is shown the same list, permitted nothing.
    reader = _capabilities(api, entry, token=_with_grant(api, ["world.read"]))
    assert [action["id"] for action in reader["actions"]] == list(actions)
    assert not any(action["permitted"] for action in reader["actions"])
    assert [action["state"] for action in reader["actions"]] == [
        action["state"] for action in actions.values()
    ]


def test_a_starter_arrangement_is_previewed_then_applied_as_the_read_says(api):
    entry = _starter(api)
    document = _capabilities(api, entry)
    applying = _operation(document, "POST /world/versions/{version_id}/arrangements/apply")
    assert applying["state"] == "available"
    assert (
        applying["preview"]["operation"] == "POST /world/versions/{version_id}/arrangements/preview"
    )
    catalog = api.get("/world/arrangements")
    assert catalog.status_code == 200, catalog.text
    assert applying["options"] == ["GET /world/arrangements"]
    assert {
        "key": SQUARE.key,
        "version": SQUARE.version,
        "title": SQUARE.title,
        "summary": SQUARE.summary,
    } in catalog.json()["arrangements"]
    body = {
        "base_state_sha256": api.version(entry)["state_sha256"],
        "arrangement_key": SQUARE.key,
        "arrangement_version": SQUARE.version,
        "viewer": {
            "x_mm": AUTHORED_SPAWN_X_MM,
            "z_mm": AUTHORED_SPAWN_Z_MM,
            "yaw_microradians": FACING_THE_CENTRE,
        },
        "origin_role": "fictional",
    }
    preview = api.post(_version_path(entry, "/arrangements/preview"), body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["availability"] == "ready"
    applied = api.post(_version_path(entry, "/arrangements/apply"), body)
    assert applied.status_code == 201, applied.text
    stale = api.post(_version_path(entry, "/arrangements/apply"), body)
    assert stale.status_code == 409
    assert stale.json() == {"code": "arrangement_refused", "detail": "stale_base"}


def test_a_generated_town_states_what_its_ground_and_engine_never_do(api, monkeypatch):
    traffic._identity(monkeypatch, _signalled())
    entry = traffic._made(api, "A town")
    document = _capabilities(api, entry)
    assert document["kind"] == "generated"
    assert document["kind_facts"] == {
        "takes_photographs": False,
        "draws_generated_tiles": True,
        "source_independent": True,
    }
    assert document["regions"]["region_ids"] == [entry["generated_ground"]["region_id"]]
    assert document["society"] == {"held": False, "engine": "exulanica-society/v5"}
    blocked = _state(document, "POST /world/versions/{version_id}/arrangements/preview")
    assert blocked == ("unsupported", "arrangement_needs_authored_ground")
    # The preview the read names answers the same code for this world.
    body = {
        "base_state_sha256": api.version(entry)["state_sha256"],
        "arrangement_key": SQUARE.key,
        "arrangement_version": SQUARE.version,
        "viewer": {"x_mm": 0, "z_mm": 0, "yaw_microradians": 0},
        "origin_role": "fictional",
    }
    preview = api.post(_version_path(entry, "/arrangements/preview"), body)
    assert preview.status_code == 200, preview.text
    assert preview.json()["blocked_reason"] == "arrangement_needs_authored_ground"
    placing = _operation(document, "POST /world/versions/{version_id}/objects")
    assert placing["effects"] == [
        {"on": "society", "state": "unsupported", "code": "authored_affordance_unreachable"}
    ]
    assert _state(document, "POST /world/versions/{version_id}/society/presence") == (
        "unsupported",
        "engine_keeps_its_people",
    )
    assert _state(document, "POST /world/versions/{version_id}/society/actions") == (
        "unsupported",
        "engine_takes_no_directed_actions",
    )
    assert _state(document, "GET /world/versions/{version_id}/traffic") == ("available", None)
    person = _state(
        document, "POST /world/versions/{version_id}/models/{role_key}", role_key="society_decision"
    )
    assert person == ("unavailable", "society_unavailable")
    signal = _operation(
        document, "POST /world/versions/{version_id}/models/{role_key}", role_key="junction_signal"
    )
    assert signal["state"] == "available"
    assert signal["effects"] == [
        {"on": "decisions", "state": "unavailable", "code": "models_not_run_here"}
    ]

    models = api.get(_version_path(entry, "/models"))
    assert models.status_code == 200, models.text
    roles = {role["key"]: role for role in models.json()["roles"]}
    for role in roles.values():
        # One set of declared semantics on every role, beside what only that role has.
        assert {"host_refusal", "model_subjects_maximum", "contract", "capability"} <= set(role)
        assert (
            role["capability"]["operation"] == "POST /world/versions/{version_id}/models/{role_key}"
        )
        assert role["capability"]["bind"]["role_key"] == role["key"]
        assert role["host_refusal"] == "models_not_run_here"
        assert len(role["contract"]["sha256"]) == 64
    assert roles["society_decision"]["view"] is None
    assert roles["society_decision"]["reason"] == "society_unavailable"
    assert roles["junction_signal"]["subjects"]
    policy = signal_actuation()
    assert roles["junction_signal"]["timing"] == {
        "segment_seconds": policy.segment_seconds,
        "target_preparation_seconds": policy.preparation_lead_seconds,
    }
    for model in roles["junction_signal"]["models"]:
        assert {"provider_description", "usd_per_mtok"} <= set(model)

    # A refused choice is answered with the status its code has on the people's own route.
    signal_id = roles["junction_signal"]["subjects"][0]["signal_id"]
    unknown_light = api.post(
        _version_path(entry, "/models/junction_signal"),
        {"idempotency_key": str(uuid.uuid4()), "subjects": ["signal:nowhere"], "model": None},
    )
    assert unknown_light.status_code == 422
    assert unknown_light.json()["code"] == "signal_not_in_world"
    unoffered = {"provider": "nebius", "model_id": "no/such-model"}
    choice = api.post(
        _version_path(entry, "/models/junction_signal"),
        {"idempotency_key": str(uuid.uuid4()), "subjects": [signal_id], "model": unoffered},
    )
    assert choice.status_code == 422 and choice.json()["code"] == "model_not_offered"

    society = api.post(
        _version_path(entry, "/society"),
        {"region_id": entry["generated_ground"]["region_id"], "profile": "exulanica-society/v5"},
    )
    assert society.status_code == 200, society.text
    held = _capabilities(api, entry)
    assert held["society"] == {"held": True, "engine": "exulanica-society/v5"}
    person = _operation(
        held, "POST /world/versions/{version_id}/models/{role_key}", role_key="society_decision"
    )
    assert person["state"] == "available"
    assert person["subjects"] == {
        "read": "GET /world/versions/{version_id}/society",
        "field": "state.inhabitants",
    }
    people = society.json()["state"]["inhabitants"]
    answers = []
    for route in ("/models/society_decision", "/society/models"):
        field = "subjects" if route.startswith("/models") else "people"
        refused = api.post(
            _version_path(entry, route),
            {"idempotency_key": str(uuid.uuid4()), field: [people[0]["id"]], "model": unoffered},
        )
        answers.append((refused.status_code, refused.json()["code"]))
    # One refusal, one status, whichever route records the people's choice. (The people's
    # repository names a model the manifest does not hold model_not_declared; the signals' names
    # it model_not_offered. That difference is the two repositories', reported, not changed here.)
    assert answers == [(422, "model_not_declared"), (422, "model_not_declared")]


def test_a_world_from_photographs_lists_every_region_its_source_holds(api):
    personal.photograph(api, minute=0)
    personal.photograph(api, minute=0, hour=15)
    personal.group(api)
    entry = personal.make_world(api)
    # The gap as it was: neither the saved world nor its fresh version names a region, and the
    # photographs' media read gives one only as a field of each photograph's slot.
    saved = api.entry(entry["entry_id"])
    assert saved["authored_scene"] is None and saved["generated_ground"] is None
    assert api.version(entry)["objects"] == []
    document = _capabilities(api, entry)
    assert document["kind"] == "personal-source"
    listed = document["regions"]["region_ids"]
    assert len(listed) == 2
    assert set(listed) == {source["region_id"] for source in personal.source_media(api, entry)}
    for index, region in enumerate(listed):
        placed = _place(api, entry, region, object_id=f"object:bench-{index}")
        assert placed.status_code == 201, placed.text
    assert _state(document, "POST /world/versions/{version_id}/society/actions") == (
        "unavailable",
        "society_unavailable",
    )
    assert document["society"] == {"held": False, "engine": "exulanica-society/v2"}

    # A photograph withdrawn: the deletion invalidates the source, and the read says what each
    # operation then answers, by the operation's own code.
    capture = api.repository.connection.execute(
        "select capture_id from capture where workspace_id=%s order by capture_id limit 1",
        (api.repository.workspace_id,),
    ).fetchone()["capture_id"]
    api.repository.insert_tombstone(
        scope="capture", capture_id=capture, requested_by=api.actor, reason="withdrawn in a test"
    )
    api.repository.connection.commit()
    withdrawn = _capabilities(api, entry)
    assert withdrawn["regions"] == {
        "state": "unavailable",
        "code": "invalidated_source_version",
        "region_ids": [],
    }
    placing = _operation(withdrawn, "POST /world/versions/{version_id}/objects")
    assert (placing["state"], placing["code"], placing["effects"]) == (
        "unavailable",
        "invalidated_source_version",
        [],
    )
    refused = _place(api, entry, listed[0], object_id="object:after")
    assert refused.status_code == 409 and refused.json()["code"] == "invalidated_source_version"
    assert _state(withdrawn, "POST /world/versions/{version_id}/society") == (
        "unavailable",
        "unavailable_society_input",
    )
    bringing = api.post(
        _version_path(entry, "/society"),
        {"region_id": listed[0], "profile": "exulanica-society/v2"},
    )
    assert bringing.status_code == 424
    assert bringing.json()["code"] == "unavailable_society_input"


def test_the_people_role_names_why_its_read_is_unavailable(api, monkeypatch):
    entry = _starter(api)
    placed = _place(api, entry, "region:starter")
    assert placed.status_code == 201, placed.text
    created = api.post(
        _version_path(entry, "/society"),
        {"region_id": "region:starter", "profile": "exulanica-society/v2"},
    )
    assert created.status_code == 200, created.text

    def withdrawn(_connection, _session, _document) -> None:
        raise UnavailableSocietyInput("a source this society depends on was withdrawn")

    # The rights check a society's reads ask, answering as it does once a source is withdrawn.
    monkeypatch.setattr(api.client.app.state, "society_input_authorizer", withdrawn)
    models = api.get(_version_path(entry, "/models"))
    assert models.status_code == 200, models.text
    people = next(role for role in models.json()["roles"] if role["subject"] == "person")
    # Its read cannot be served, and it says why by code rather than by a null.
    assert (people["available"], people["reason"], people["view"]) == (
        False,
        "unavailable_society_input",
        None,
    )
    # A choice is recorded without reading the society's inputs, so it stays available.
    assert people["capability"]["state"] == "available"


# -- a society's input names the edit it followed ----------------------------------------------


def test_a_version_the_caller_does_not_hold_is_unknown_to_both_reads(api, monkeypatch):
    """A stranger asking for this workspace's town, and anyone asking for an invented version, get
    404 unknown_reference from the capability and models reads, also where the version holds a
    society whose snapshot the models read authorizes once and reads its decisions under."""
    traffic._identity(monkeypatch, _signalled())
    town = traffic._made(api, "A town with its people")
    created = api.post(
        _version_path(town, "/society"),
        {"region_id": town["generated_ground"]["region_id"], "profile": "exulanica-society/v5"},
    )
    assert created.status_code == 200, created.text
    invented = {**town, "authored_version_id": str(uuid.uuid4())}
    for suffix in ("/capabilities", "/models"):
        assert api.get(_version_path(town, suffix)).status_code == 200, suffix
        for answer in (
            api.get(_version_path(town, suffix), token=personal.STRANGER_TOKEN),
            api.get(_version_path(invented, suffix)),
        ):
            assert answer.status_code == 404, (suffix, answer.text)
            assert answer.json()["code"] == "unknown_reference", (suffix, answer.text)


def test_the_models_read_authorizes_a_societys_inputs_as_reading_the_society_does(api, monkeypatch):
    """The people's view reads the society's decisions under the one snapshot it read, so a models
    read authorizes the society's inputs exactly as often as reading the society does."""
    traffic._identity(monkeypatch, _signalled())
    town = traffic._made(api, "A town with its people")
    created = api.post(
        _version_path(town, "/society"),
        {"region_id": town["generated_ground"]["region_id"], "profile": "exulanica-society/v5"},
    )
    assert created.status_code == 200, created.text
    calls: list[object] = []
    authorize = api.client.app.state.society_input_authorizer

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return authorize(*args, **kwargs)

    monkeypatch.setattr(api.client.app.state, "society_input_authorizer", counted)
    assert api.get(_version_path(town, "/society")).status_code == 200
    reading = len(calls)
    calls.clear()
    assert api.get(_version_path(town, "/models")).status_code == 200
    assert reading > 0
    assert len(calls) == reading


def test_an_event_joins_to_the_authored_edit_its_input_followed(api):
    entry = _starter(api)
    placed = _place(api, entry, "region:starter")
    assert placed.status_code == 201, placed.text
    created = api.post(
        _version_path(entry, "/society"),
        {"region_id": "region:starter", "profile": "exulanica-society/v2"},
    )
    assert created.status_code == 200, created.text
    snapshot = created.json()
    for _ in range(5):
        stepped = api.post(
            _version_path(entry, "/society/steps"),
            {"base_tick": snapshot["current_tick"], "base_state_sha256": snapshot["state_sha256"]},
        )
        assert stepped.status_code == 200, stepped.text
        snapshot = stepped.json()
    events = api.get(_version_path(entry, "/society/events"))
    assert events.status_code == 200, events.text
    sequences = {event["document"]["input_seq"] for event in events.json()["events"]}
    assert sequences, events.json()
    version = api.version(entry)
    edits = {edit["edit_seq"]: edit for edit in version["edits"]}
    for sequence in sorted(sequences):
        provenance = api.get(_version_path(entry, f"/society/inputs/{sequence}"))
        assert provenance.status_code == 200, provenance.text
        document = provenance.json()
        assert document["profile"] == "exulanica.society-input-provenance/v1"
        assert document["input_seq"] == sequence
        authored = document["authored_state"]
        edit = edits[authored["edit_seq"]]
        # The input followed exactly this edit: the state it records is the edit's result.
        assert authored["delta_sha256"] == edit["result_state_sha256"]
        assert edit["object_id"] == "object:bench"
    unknown = api.get(_version_path(entry, "/society/inputs/999"))
    assert unknown.status_code == 404 and unknown.json()["code"] == "unknown_reference"
    stranger = api.get(_version_path(entry, "/society/inputs/1"), token=personal.STRANGER_TOKEN)
    assert stranger.status_code == 404 and stranger.json()["code"] == "unknown_reference"


# -- extensions reach the reads from their own data ---------------------------------------------


@pytest.fixture
def trial_behaviour(api):
    """A reviewed behaviour published for this test alone, and taken out again whatever happens."""
    connection = api.repository.connection
    connection.execute(
        "insert into world_object_behaviour_registry "
        "(behaviour_key,behaviour_version,summary,parameters) values (%s,1,%s,%s)",
        (
            TRIAL_BEHAVIOUR,
            "A test-only reviewed sway.",
            json.dumps(
                {"sway_mm": {"kind": "integer", "minimum": 10, "maximum": 500, "default": 50}}
            ),
        ),
    )
    connection.commit()
    try:
        yield TRIAL_BEHAVIOUR
    finally:
        connection.rollback()
        connection.execute(
            "update world_alternate_object set behaviour_key=null,behaviour_version=null,"
            "behaviour_parameters=null where behaviour_key=%s",
            (TRIAL_BEHAVIOUR,),
        )
        connection.execute(
            "delete from world_object_behaviour_registry where behaviour_key=%s", (TRIAL_BEHAVIOUR,)
        )
        connection.commit()


def test_a_reviewed_behaviour_added_to_its_catalog_is_offered_with_no_second_definition(
    api, request
):
    entry = _starter(api)
    placed = _place(api, entry, "region:starter")
    assert placed.status_code == 201, placed.text
    operation = "POST /world/versions/{version_id}/objects/{object_id}/behaviour"
    before = _operation(_capabilities(api, entry), operation)
    request.getfixturevalue("trial_behaviour")
    after = _operation(_capabilities(api, entry), operation)
    # Discovery names the read that lists behaviours, not the behaviours: nothing in it changed.
    assert before == after and after["options"] == ["GET /world/behaviours"]
    listed = api.get("/world/behaviours").json()
    assert TRIAL_BEHAVIOUR in {row["behaviour_key"] for row in listed}
    path = _version_path(entry, "/objects/object:bench/behaviour")
    base = api.version(entry)["state_sha256"]
    out_of_range = api.post(
        path,
        {
            "base_state_sha256": base,
            "behaviour": {
                "behaviour_key": TRIAL_BEHAVIOUR,
                "behaviour_version": 1,
                "parameters": {"sway_mm": 9_999},
            },
        },
    )
    assert out_of_range.status_code == 422 and out_of_range.json()["code"] == "invalid_object_data"
    given = api.post(
        path,
        {
            "base_state_sha256": base,
            "behaviour": {
                "behaviour_key": TRIAL_BEHAVIOUR,
                "behaviour_version": 1,
                "parameters": {"sway_mm": 80},
            },
        },
    )
    assert given.status_code == 200, given.text
    [bench] = given.json()["objects"]
    assert bench["behaviour"]["behaviour_key"] == TRIAL_BEHAVIOUR


def test_a_role_the_registry_adds_is_listed_and_refused_until_its_host_is_written(api, monkeypatch):
    entry = _starter(api)
    signal = decision_roles().role("junction_signal")
    crossing = dataclasses.replace(signal, key="test_crossing", subject="crossing")
    registry = decision_roles()
    extended = RoleRegistry(registry.version, {**registry.roles, crossing.key: crossing})
    monkeypatch.setattr(world_models_module, "decision_roles", lambda: extended)
    models = api.get(_version_path(entry, "/models"))
    assert models.status_code == 200, models.text
    listed = next(role for role in models.json()["roles"] if role["key"] == "test_crossing")
    assert (listed["available"], listed["reason"]) == (False, "role_subject_unsupported")
    assert listed["capability"]["state"] == "unsupported"
    assert listed["capability"]["code"] == "role_subject_unsupported"
    refused = api.post(
        _version_path(entry, "/models/test_crossing"),
        {"idempotency_key": str(uuid.uuid4()), "subjects": ["x"], "model": None},
    )
    assert refused.status_code == 409 and refused.json()["code"] == "role_subject_unsupported"
    in_capabilities = _operation(
        _capabilities(api, entry),
        "POST /world/versions/{version_id}/models/{role_key}",
        role_key="test_crossing",
    )
    assert in_capabilities["state"] == "unsupported"
    # Its host is written in code and named for its subject: then it is served like any role.
    hosts = {**role_hosts_module.ROLE_HOSTS, "crossing": role_hosts_module.ROLE_HOSTS["signal"]}
    monkeypatch.setattr(world_models_module, "ROLE_HOSTS", hosts)
    hosted = next(
        role
        for role in api.get(_version_path(entry, "/models")).json()["roles"]
        if role["key"] == "test_crossing"
    )
    assert hosted["capability"]["state"] == "unavailable"
    assert hosted["capability"]["code"] == "roads_not_stated"
    assert hosted["label"] == "Traffic lights"


def test_nothing_this_file_publishes_is_left_in_a_registry(api):
    """A guard at the end of the file: the trial behaviour is gone once its test ends."""
    rows = api.repository.connection.execute(
        "select 1 from world_object_behaviour_registry where behaviour_key=%s", (TRIAL_BEHAVIOUR,)
    ).fetchall()
    assert rows == []


def test_a_societys_events_are_read_back_page_by_page_in_one_order(api):
    entry = _starter(api)
    assert _place(api, entry, "region:starter").status_code == 201
    created = api.post(
        _version_path(entry, "/society"),
        {"region_id": "region:starter", "profile": "exulanica-society/v2"},
    )
    assert created.status_code == 200, created.text
    snapshot = created.json()
    for _ in range(6):
        stepped = api.post(
            _version_path(entry, "/society/steps"),
            {"base_tick": snapshot["current_tick"], "base_state_sha256": snapshot["state_sha256"]},
        )
        assert stepped.status_code == 200, stepped.text
        snapshot = stepped.json()
    whole = api.get(_version_path(entry, "/society/events"))
    assert whole.status_code == 200, whole.text
    everything = whole.json()["events"]
    assert whole.json()["next"] is None
    assert len(everything) > 5, "too few events to page through"
    pages, cursor = [], None
    while True:
        suffix = "/society/events?limit=5" + (f"&before={cursor}" if cursor else "")
        page = api.get(_version_path(entry, suffix))
        assert page.status_code == 200, page.text
        pages.extend(page.json()["events"])
        cursor = page.json()["next"]
        if cursor is None:
            break
        assert len(page.json()["events"]) == 5
    assert pages == everything
    for refused in ("not-a-cursor", f"1::{uuid.uuid4()}"):
        answer = api.get(_version_path(entry, f"/society/events?before={refused}"))
        assert answer.status_code == 422, answer.text
        assert answer.json()["code"] == "invalid_event_cursor"
