"""A visitor crosses into a society of things through the door and goes home, against PostgreSQL.

Through the real routes, as a world's owner and as a bridge with a channel credential:

*   a grant that lets one visitor in through the version's gate; the bridge sends a player across
    with a sword, the society's next minute takes the arrival, the bridge reads that its visitor
    arrived and which thing its sword became, the visitor wears the shipped look its mapping named,
    and the translation manifest the arrival names is kept;
*   the owner sends the visitor home: the next minute records it leaving with what it held, the
    bridge reads the departure with the game item each held thing travels out as, and reports what
    its game delivered, once;
*   a second visitor waits for room, a resent arrival is the same arrival, and a look the library
    does not ship is refused before anything is written;
*   revoking the grant sends its visitors home, and the bridge reads every departure before it
    reads that the grant ended;
*   a visitor whose player left is not asked again;
*   a thing's card reads what came across with a visitor by its arrival in the world;
*   the society replays from what it stored and bound, with no bridge running.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.door.bridges import BridgeDirectory, load_bridge_directory
from exulanica.door.crossings import DoorCrossings
from exulanica.world.crossings import register_crossing_stream

import door_support
import test_society_authored_world_postgres as helpers
from test_door_postgres import BRIDGE, OWNER, SOMEONE, _frames, _hello
from test_door_postgres import door as door
from test_society_saved_world_api import routes
from test_society_things_postgres import _events, _make_society, _place, _replayed, _step

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres

#: The namespace the door derives a visitor's and a departure's ids in, written out here so the
#: expected ids come from the contract, not from the code under test.
IDS = uuid.UUID("8f1d6a52-3c47-5e09-b4a8-1e7c2d90f6b3")


def _visitor_id(grant_id: str, arrival_id: str) -> str:
    return str(uuid.uuid5(IDS, f"{grant_id}:arrival:{arrival_id}"))


def _departure_id(grant_id: str, thing_id: str, reason: str) -> str:
    return str(uuid.uuid5(IDS, f"{grant_id}:departure:{thing_id}:{reason}"))


@pytest.fixture
def crossings():
    """The door's crossings handed to every society of things this process plays."""
    register_crossing_stream(DoorCrossings())
    try:
        yield
    finally:
        register_crossing_stream(None)


def _world(door) -> tuple[dict[str, Any], dict[str, Any]]:
    """A society of things over the saved world, with a gate its visitors come through."""
    world = door["world"]
    client = door["client"]
    _place(client, world, "well", "well", 2, -4_000, 2_000)
    _place(client, world, "gate", "gate", 1, 0, 6_000)
    return world, _make_society(client, world)


def _grant(door, key: str = "visitors-0001", **change: Any) -> tuple[str, dict[str, str]]:
    """A grant letting one player in through the gate, and its channel credential."""
    world = door["world"]
    body = {
        "idempotency_key": key,
        "bridge": "test-bridge",
        "visitors_maximum": 1,
        "kinds": ["player"],
        "version_id": str(world["binding"].version_id),
        "gate": "gate",
        "may_carry_in": True,
        "may_carry_out": True,
        "channel_credential": True,
        **change,
    }
    issued = door["client"].post(
        "/door/grants",
        headers=OWNER,
        params={"world_id": world["binding"].world_id},
        json=body,
    )
    assert issued.status_code == 201, issued.text
    credential = issued.json()["channel_credential"]["credential"]
    return issued.json()["grant"]["grant_id"], {"Authorization": f"Bearer {credential}"}


def _arrive(client, channel, arrival_id: str, *, carried=None, look_key="otherwise"):
    return client.post(
        "/door/channel/arrivals",
        headers=channel,
        json={
            "arrival_id": arrival_id,
            "game_type": "player",
            "look_key": look_key,
            "carried": [{"game_item": "test:sword", "count": 1}] if carried is None else carried,
        },
    )


def _read(door, channel, cursor: str) -> tuple[list[dict[str, Any]], str]:
    read = _frames(door, channel, cursor)
    assert read.status_code == 200, read.text
    return read.json()["frames"], read.json()["cursor"]


def _visitors(society: dict[str, Any]) -> list[dict[str, Any]]:
    return [p for p in society["state"]["inhabitants"] if p["came_by"] == "crossed"]


def test_a_visitor_crosses_in_through_the_door_and_goes_home(door, crossings):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    hello = _hello(door, channel)
    assert hello.status_code == 200, hello.text
    _frames_read, cursor = _read(door, channel, hello.json()["cursor"])
    arrival_id = str(uuid.uuid4())
    sent = _arrive(client, channel, arrival_id)
    assert sent.status_code == 201, sent.text
    thing_id = sent.json()["thing_id"]
    assert thing_id == _visitor_id(grant_id, arrival_id)
    again = _arrive(client, channel, arrival_id)
    assert (again.status_code, again.json()["thing_id"]) == (200, thing_id)

    society = _step(client, world, society)
    [visitor] = _visitors(society)
    assert visitor["id"] == thing_id
    [sword] = [t for t in society["state"]["things"] if t.get("held_by") == thing_id]
    frames, cursor = _read(door, channel, cursor)
    [arrived] = [frame for frame in frames if frame["kind"] == "arrived"]
    assert arrived == {
        "kind": "arrived",
        "arrival_id": arrival_id,
        "thing_id": thing_id,
        "carried": [{"thing_id": sword["id"], "game_item": "test:sword"}],
    }
    # The world's models read names the visitor among those decided for from outside, with no
    # decision of its program yet.
    scope, _, society_route = routes(world)
    models = client.get(society_route + "/models", headers=OWNER, params=scope).json()
    assert models["outside"] == [
        {
            "subject_id": thing_id,
            "came": "crossed",
            "grant_id": grant_id,
            "bridge": "test-bridge",
            "bridge_label": "A test bridge",
            "run_by": "server",
            "ai": False,
            "connected": True,
            "declared": None,
            "latest": None,
        }
    ]
    # The visitor wears the shipped look its mapping named, chosen by its crossing.
    looks = client.get(
        f"/world/versions/{world['binding'].version_id}/thing-looks",
        headers=OWNER,
        params={"world_id": world["binding"].world_id},
    ).json()["looks"]
    [worn] = [look for look in looks if look["thing_id"] == thing_id]
    assert (worn["chosen_by"], worn["look"]) == (
        "crossing",
        {"look": "blocky-traveller", "version": 1, "sha256": door_support.BLOCKY_TRAVELLER_SHA256},
    )
    # The manifest the arrival names is kept by its digest and says what came across.
    connection = world["connection"]
    stored = connection.execute(
        "select m.manifest_sha256, m.document from door_crossing c join door_manifest m "
        "  on m.workspace_id = c.workspace_id "
        " and m.manifest_sha256 = c.document->>'translation_manifest_sha256' "
        "where c.workspace_id = %s and c.crossing_id = %s",
        (world["workspace"], uuid.UUID(arrival_id)),
    ).fetchone()
    connection.commit()
    assert stored["manifest_sha256"] == sha256_of_canonical(stored["document"]).hex()
    assert stored["document"]["profile"] == "exulanica.translation-manifest/v2"
    assert {"/player", "/test:sword", "/player name"} <= {
        field["path"] for field in stored["document"]["fields"]
    }

    # Its owner sends it home: the next minute records it leaving with what it held.
    sent_away = client.post(
        f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id}
    )
    assert sent_away.status_code == 202, sent_away.text
    society = _step(client, world, society)
    assert _visitors(society) == []
    [left] = [e for e in _events(client, world) if e["event_kind"] == "thing_departed"]
    assert left["document"]["reason"] == "sent_home"
    frames, cursor = _read(door, channel, cursor)
    [departed] = [frame for frame in frames if frame["kind"] == "departed"]
    leaving = _departure_id(grant_id, thing_id, "sent_away")
    assert departed == {
        "kind": "departed",
        "departure_id": leaving,
        "thing_id": thing_id,
        "why": "sent_home",
        "carried": [{"thing_id": sword["id"], "kind": sword["kind"], "game_item": "test:sword"}],
    }
    # A bridge that says hello again reads every departure it has not reported delivered again.
    again = _hello(door, channel)
    frames, _after = _read(door, channel, again.json()["cursor"])
    assert [frame for frame in frames if frame["kind"] == "departed"] == [departed]
    report = {"delivered": [{"thing_id": sword["id"], "game_item": "test:sword"}]}
    first = client.post(
        f"/door/channel/departures/{leaving}/delivered", headers=channel, json=report
    )
    assert (first.status_code, first.json()) == (202, {"recorded": True})
    second = client.post(
        f"/door/channel/departures/{leaving}/delivered", headers=channel, json=report
    )
    assert (second.status_code, second.json()) == (202, {"recorded": False})
    # Once delivered, a hello starts after it.
    frames, _after = _read(door, channel, _hello(door, channel).json()["cursor"])
    assert [frame for frame in frames if frame["kind"] == "departed"] == []
    wrong = client.post(
        f"/door/channel/departures/{leaving}/delivered", headers=channel, json={"delivered": []}
    )
    assert (wrong.status_code, wrong.json()["code"]) == (422, "delivery_not_this_departure")
    unknown = client.post(
        f"/door/channel/departures/{uuid.uuid4()}/delivered", headers=channel, json=report
    )
    assert (unknown.status_code, unknown.json()["code"]) == (404, "unknown_reference")
    # The society replays from what it stored and bound, with no bridge running.
    assert _replayed(client, world)


def test_a_visitor_s_card_reads_what_came_across_by_its_arrival_in_its_world(door, crossings):
    """The manifest the door kept for an arrival, read by the arrival's id in its world: the
    stored document and its digest, and the bridge in the words the deployment declares for it.
    An id that names no arrival into that world is answered as one nobody sent."""
    world, _society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    assert _hello(door, channel).status_code == 200
    arrival_id = str(uuid.uuid4())
    sent = _arrive(client, channel, arrival_id)
    assert sent.status_code == 201, sent.text
    scope = {"world_id": world["binding"].world_id}
    read = client.get(f"/door/crossings/{arrival_id}/manifest", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    body = read.json()
    connection = world["connection"]
    stored = connection.execute(
        "select m.manifest_sha256, m.document from door_crossing c join door_manifest m "
        "  on m.workspace_id = c.workspace_id "
        " and m.manifest_sha256 = c.document->>'translation_manifest_sha256' "
        "where c.workspace_id = %s and c.crossing_id = %s",
        (world["workspace"], uuid.UUID(arrival_id)),
    ).fetchone()
    connection.commit()
    assert (body["manifest_sha256"], body["manifest"]) == (
        stored["manifest_sha256"],
        stored["document"],
    )
    assert sha256_of_canonical(body["manifest"]).hex() == body["manifest_sha256"]
    assert body["from"] == {"bridge": "test-bridge", "label": "A test bridge", "ai": False}
    # The card's words are the mapping's own: what the sword is, and why the name stayed behind.
    fields = {field["path"]: field for field in body["manifest"]["fields"]}
    assert fields["/test:sword"]["words"] == "A sword, which arrives as a sword"
    assert (fields["/player name"]["disposition"], fields["/player name"]["reason"]) == (
        "dropped",
        "a person's name never crosses",
    )

    # Sent home, the visitor's departure is written under an id that names no arrival, and what
    # came across with it does not change.
    thing_id = sent.json()["thing_id"]
    sent_away = client.post(
        f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id}
    )
    assert sent_away.status_code == 202, sent_away.text
    nothing = {"code": "unknown_reference", "detail": "nothing at this address is available"}
    for asked, params in (
        (str(uuid.uuid4()), scope),
        (_departure_id(grant_id, thing_id, "sent_away"), scope),
        (arrival_id, {"world_id": "another-world"}),
    ):
        refused = client.get(f"/door/crossings/{asked}/manifest", headers=OWNER, params=params)
        assert (refused.status_code, refused.json()) == (404, nothing), asked
    again = client.get(f"/door/crossings/{arrival_id}/manifest", headers=OWNER, params=scope)
    assert (again.status_code, again.json()) == (200, body)

    # A deployment that no longer declares the bridge still shows what came across, and states
    # nothing it does not know about the bridge.
    bare, _runtime = door["application"](BridgeDirectory())
    with bare:
        undeclared = bare.get(f"/door/crossings/{arrival_id}/manifest", headers=OWNER, params=scope)
    assert undeclared.status_code == 200, undeclared.text
    assert undeclared.json() == {
        **body,
        "from": {"bridge": "test-bridge", "label": None, "ai": None},
    }


def _stored_manifest(world, society_id: str, arrival_id: str) -> str:
    """The digest of the manifest an arrival into one society names, read from the door's rows."""
    row = (
        world["connection"]
        .execute(
            "select c.document->>'translation_manifest_sha256' as digest from door_crossing c "
            "where c.workspace_id = %s and c.society_id = %s and c.crossing_id = %s",
            (world["workspace"], uuid.UUID(society_id), uuid.UUID(arrival_id)),
        )
        .fetchone()
    )
    world["connection"].commit()
    return row["digest"]


def test_an_arrival_id_sent_into_two_versions_is_read_by_its_version(door, crossings):
    """A bridge chooses its arrival ids and each society holds an id once, so one id sent into two
    versions' societies of a world names two arrivals: a card names its version and reads its own;
    with no version, an arrival its minute took answers before one it refused, though newer."""
    world, society = _world(door)
    client = door["client"]
    scope = {"world_id": world["binding"].world_id}
    _first_grant, channel = _grant(door)
    assert _hello(door, channel).status_code == 200
    arrival_id = str(uuid.uuid4())
    assert _arrive(client, channel, arrival_id).status_code == 201
    society = _step(client, world, society)
    assert len(_visitors(society)) == 1

    # A second version of the same world, holding a society of things and no gate: the same id
    # sent there arrives in its society's crossings and its minute refuses it (no arrival place).
    made = client.post(
        "/world/versions",
        headers=OWNER,
        params=scope,
        json={
            "title": "the same world again",
            "source_snapshot_id": str(world["binding"].source_snapshot_id),
        },
    )
    assert made.status_code == 201, made.text
    second = {
        **world,
        "binding": world["binding"].model_copy(
            update={"version_id": uuid.UUID(made.json()["version_id"])}
        ),
    }
    _place(client, second, "well", "well", 2, -4_000, 2_000)
    other_society = _make_society(client, second)
    _second_grant, other_channel = _grant(
        {**door, "world": second}, key="visitors-0002", may_carry_in=False
    )
    assert _hello(door, other_channel).status_code == 200
    assert _arrive(client, other_channel, arrival_id, carried=[]).status_code == 201
    other_society = _step(client, second, other_society)
    assert _visitors(other_society) == []
    bound = (
        world["connection"]
        .execute(
            "select disposition, reason from door_crossing_binding "
            "where workspace_id = %s and society_id = %s and crossing_id = %s",
            (world["workspace"], uuid.UUID(other_society["society_id"]), uuid.UUID(arrival_id)),
        )
        .fetchone()
    )
    world["connection"].commit()
    assert (bound["disposition"], bound["reason"]) == ("refused", "no_arrival_place")

    first = _stored_manifest(world, society["society_id"], arrival_id)
    other = _stored_manifest(world, other_society["society_id"], arrival_id)
    assert first != other  # the first carried a sword, the second nothing

    def read(**version: str) -> Any:
        answer = client.get(
            f"/door/crossings/{arrival_id}/manifest", headers=OWNER, params={**scope, **version}
        )
        assert answer.status_code == 200, answer.text
        return answer.json()["manifest_sha256"]

    assert read(version_id=str(world["binding"].version_id)) == first
    assert read(version_id=str(second["binding"].version_id)) == other
    assert read() == first
    elsewhere = client.get(
        f"/door/crossings/{arrival_id}/manifest",
        headers=OWNER,
        params={**scope, "version_id": str(uuid.uuid4())},
    )
    assert (elsewhere.status_code, elsewhere.json()["code"]) == (404, "unknown_reference")


def test_a_second_visitor_waits_for_room_and_an_unshipped_look_is_refused(door, crossings):
    world, society = _world(door)
    client = door["client"]
    _grant_id, channel = _grant(door)
    assert _hello(door, channel).status_code == 200
    assert _arrive(client, channel, str(uuid.uuid4())).status_code == 201
    full = _arrive(client, channel, str(uuid.uuid4()))
    assert (full.status_code, full.json()["code"]) == (409, "visitors_full")
    offered = _arrive(client, channel, str(uuid.uuid4()), look_key="default-skin")
    assert (offered.status_code, offered.json()["code"]) == (422, "look_not_offered")
    # A mapping naming a look the library does not ship is refused at the arrival, by its code:
    # a first-profile digest the library ships no look at, here. A second-profile mapping names
    # its look by the library's own reference, and its visitor arrives in it.
    unshipped = door_support.mapping()
    unshipped["visitors"][0]["looks"][0]["look"] = "sha256:" + "0" * 64
    entries = json.loads(
        door_support.bridges_setting(
            listed=False, workspaces=[str(world["workspace"])], hold_seconds=1
        )
    )
    entries[0]["mapping_sha256"] = [
        door_support.mapping_sha256(unshipped),
        door_support.mapping_sha256(door_support.mapping_v2()),
    ]
    narrowed = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})
    other_client, _runtime = door["application"](narrowed)
    with other_client:
        _second_grant, other = _grant(door, key="visitors-0002")

        def hello(mapping):
            said = other_client.post(
                "/door/channel/hello",
                headers=other,
                json={
                    "adapter_version": door_support.ADAPTER_VERSION,
                    "mapping": mapping,
                    "reads": door_support.READS,
                },
            )
            assert said.status_code == 200, said.text

        hello(unshipped)
        refused = _arrive(other_client, other, str(uuid.uuid4()))
        assert (refused.status_code, refused.json()["code"]) == (422, "look_not_shipped")
        hello(door_support.mapping_v2())
        assert _arrive(other_client, other, str(uuid.uuid4())).status_code == 201
    written = (
        world["connection"]
        .execute(
            "select count(*) as n from door_crossing where workspace_id = %s", (world["workspace"],)
        )
        .fetchone()
    )
    world["connection"].commit()
    assert written["n"] == 2
    society = _step(client, world, society)
    assert len(_visitors(society)) == 2


def test_revoking_a_grant_sends_its_visitors_home_before_its_end_is_read(door, crossings):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    hello = _hello(door, channel)
    _frames_read, cursor = _read(door, channel, hello.json()["cursor"])
    thing_id = _arrive(client, channel, str(uuid.uuid4())).json()["thing_id"]
    society = _step(client, world, society)
    frames, cursor = _read(door, channel, cursor)
    assert [frame["kind"] for frame in frames] == ["arrived"]
    revoked = client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    assert revoked.status_code == 200, revoked.text
    # The departure waits for the next minute, and so does the grant's end: nothing to read yet.
    frames, cursor = _read(door, channel, cursor)
    assert frames == []
    society = _step(client, world, society)
    assert _visitors(society) == []
    frames, cursor = _read(door, channel, cursor)
    assert [frame["kind"] for frame in frames] == ["departed", "grant_ended"]
    assert (frames[0]["thing_id"], frames[0]["why"]) == (thing_id, "grant_ended")
    assert _frames(door, channel, cursor).json()["code"] == "grant_ended"
    assert _replayed(client, world)


def test_a_visitor_whose_player_left_is_not_asked(door, crossings):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    assert _hello(door, channel).status_code == 200
    thing_id = _arrive(client, channel, str(uuid.uuid4())).json()["thing_id"]
    society = _step(client, world, society)
    asker = door["runtime"].asker()
    decider = {"kind": "external", "bridge": "test-bridge", "grant_id": grant_id}
    workspace, world_id = world["workspace"], world["binding"].world_id
    assert asker.configuration(workspace, world_id, thing_id, decider)[1] is None
    gone = client.post("/door/channel/gone", headers=channel, json={"thing_id": thing_id})
    assert (gone.status_code, gone.json()) == (202, {"recorded": True})
    assert asker.configuration(workspace, world_id, thing_id, decider)[1] == (
        "decider_disconnected"
    )
    stranger = client.post("/door/channel/gone", headers=channel, json={"thing_id": SOMEONE[:8]})
    assert stranger.status_code == 422
    nobody = client.post(
        "/door/channel/gone", headers=channel, json={"thing_id": str(uuid.uuid4())}
    )
    assert (nobody.status_code, nobody.json()["code"]) == (404, "unknown_reference")
    # A credential that is not the grant's opens none of this.
    assert _arrive(client, BRIDGE, str(uuid.uuid4())).status_code == 401
