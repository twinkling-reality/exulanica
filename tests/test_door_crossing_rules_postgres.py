"""The rules a crossing is held to, against PostgreSQL, through the real routes.

*   An arrival is named by a random version 4 UUID and a departure by the id the door derives, so a
    bridge cannot send an arrival under the id one of its visitors' departures will be written
    under: such an arrival is refused, the table refuses one written past the door, and the owner's
    send-away, a revocation and a grant's end all still send the visitors home.
*   A visitors grant stored before a grant had to name its version is still read, listed, opened
    and revoked; it takes no arrival, and a grant of that shape is no longer issued.
*   A grant for visitors is issued only for a version holding a society of things: a version with
    no society, or with a society of people, is refused by name and nothing is issued, while its
    people may still be handed to a bridge.
*   A grant takes a bounded number of arrivals in any hour, refused ones included, answered with
    when to try again; a resent arrival is not counted again.
*   A visitor carries its shipped look's own licence and may be shown where the look may, whatever
    a mapping says of the look.
*   A second-profile mapping may name a look a workspace keeps: a visitor arrives in it, with its
    licence, once its own workspace keeps it at the key and version the mapping names, and the
    minute records it by its digest; while only another workspace keeps it, or its workspace keeps
    that digest under another key, the arrival is refused by name and nothing is written.
*   Arrivals the grant or mapping does not admit are refused by name before anything is written:
    things carried in under a grant that lets none in, too many things, an item that does not cross,
    a kind the library does not ship, a grant for no visitors, and an arrival id reused for another
    arrival.
*   Two grants' visitors in one society are each their own grant's.
*   A grant's end is not told while a crossing waits for the society's minute.
*   A visitor sent home is still asked for until the minute that takes its departure.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import uuid
from typing import Any

import psycopg
import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.door import crossings as door_crossings
from exulanica.door.bridges import load_bridge_directory
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.authored import container_of
from exulanica.world.thing_library import shipped_looks
from exulanica.world.thing_store import ThingStore
from psycopg.types.json import Jsonb

import door_support
import test_society_authored_world_postgres as helpers
from test_door_crossings_postgres import (
    _arrive,
    _departure_id,
    _grant,
    _read,
    _visitor_id,
    _visitors,
    _world,
)
from test_door_crossings_postgres import crossings as crossings
from test_door_postgres import OWNER, _credential, _grant_for, _hello, _person_request
from test_door_postgres import door as door
from test_society_saved_world_api import routes
from test_society_things_postgres import _step
from test_thing_store_admission import _imported

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres


def _scoped(world):
    """The world's own connection, in a transaction scoped to its workspace."""
    connection = world["connection"]
    connection.commit()
    transaction = connection.transaction()
    transaction.__enter__()
    connection.execute(
        "select set_config('exulanica.workspace_id', %s, true)", (str(world["workspace"]),)
    )
    return connection, transaction


def _expire(world, grant_id: str) -> None:
    """End a grant by its own end: a revision after its last whose end has passed."""
    connection, transaction = _scoped(world)
    try:
        latest = connection.execute(
            "select grant_seq, document, recorded_by from door_grant_revision "
            "where workspace_id = %s and grant_id = %s order by grant_seq desc limit 1",
            (world["workspace"], uuid.UUID(grant_id)),
        ).fetchone()
        ended = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        document = {
            **latest["document"],
            "grant_seq": latest["grant_seq"] + 1,
            "expires_at": ended.isoformat(timespec="microseconds"),
        }
        connection.execute(
            "insert into door_grant_revision (workspace_id, grant_id, grant_seq, document, "
            "document_sha256, recorded_by) values (%s, %s, %s, %s, %s, %s)",
            (
                world["workspace"],
                uuid.UUID(grant_id),
                document["grant_seq"],
                Jsonb(document),
                sha256_of_canonical(document).hex(),
                latest["recorded_by"],
            ),
        )
    finally:
        transaction.__exit__(None, None, None)


def _crossings(world) -> list[dict[str, Any]]:
    connection = world["connection"]
    rows = connection.execute(
        "select crossing_id, kind, thing_id, document from door_crossing "
        "where workspace_id = %s order by society_id, crossing_seq",
        (world["workspace"],),
    ).fetchall()
    connection.commit()
    return rows


def _decider(grant_id: str) -> dict[str, str]:
    return {"kind": "external", "bridge": "test-bridge", "grant_id": grant_id}


def test_an_arrival_never_takes_the_id_a_departure_is_written_under(door, crossings):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door, visitors_maximum=2)
    assert _hello(door, channel).status_code == 200
    first = str(uuid.uuid4())
    sent = _arrive(client, channel, first)
    assert sent.status_code == 201, sent.text
    thing_id = sent.json()["thing_id"]
    assert thing_id == _visitor_id(grant_id, first)
    # Every id the door will write this visitor's departures under is known to its bridge, and
    # none of them names an arrival: the route refuses each before anything is written.
    for reason in ("sent_away", "grant_ended"):
        taken = _arrive(client, channel, _departure_id(grant_id, thing_id, reason))
        assert taken.status_code == 422, taken.text
    assert len(_crossings(world)) == 1
    # Past the door, the table refuses an arrival named by a version 5 id, and takes the same row
    # under a random one (the arm before: the copy is otherwise a crossing the table accepts).
    connection, transaction = _scoped(world)
    copy_row = (
        "insert into door_crossing (workspace_id, society_id, crossing_id, crossing_seq, "
        "grant_id, kind, thing_id, document, document_sha256, game_items, look, recorded_by) "
        "select workspace_id, society_id, %(id)s, crossing_seq + 1, grant_id, kind, thing_id, "
        "jsonb_set(document, '{arrival_id}', to_jsonb(%(id)s::text)), document_sha256, "
        "game_items, look, recorded_by from door_crossing "
        "where workspace_id = %(w)s and crossing_id = %(first)s"
    )
    try:
        with connection.transaction(force_rollback=True):
            connection.execute(
                copy_row, {"id": uuid.uuid4(), "w": world["workspace"], "first": uuid.UUID(first)}
            )
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                copy_row,
                {
                    "id": uuid.UUID(_departure_id(grant_id, thing_id, "sent_away")),
                    "w": world["workspace"],
                    "first": uuid.UUID(first),
                },
            )
    finally:
        transaction.__exit__(None, None, None)
    second = _arrive(client, channel, str(uuid.uuid4())).json()["thing_id"]
    society = _step(client, world, society)
    assert {visitor["id"] for visitor in _visitors(society)} == {thing_id, second}

    # The owner sends the first home, and revoking the grant sends the second.
    sent_away = client.post(
        f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id}
    )
    assert sent_away.status_code == 202, sent_away.text
    revoked = client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    assert revoked.status_code == 200, revoked.text
    society = _step(client, world, society)
    assert _visitors(society) == []
    departures = {row["crossing_id"] for row in _crossings(world) if row["kind"] == "departure"}
    assert departures == {
        uuid.UUID(_departure_id(grant_id, thing_id, "sent_away")),
        uuid.UUID(_departure_id(grant_id, second, "grant_ended")),
    }

    # A grant that runs out sends its visitor home too.
    later_id, later = _grant(door, key="visitors-0003")
    assert _hello(door, later).status_code == 200
    arrival = str(uuid.uuid4())
    staying = _arrive(client, later, arrival).json()["thing_id"]
    refused = _arrive(client, later, _departure_id(later_id, staying, "grant_ended"))
    assert refused.status_code == 422
    society = _step(client, world, society)
    _expire(world, later_id)
    asker = door["runtime"].asker()
    workspace, world_id = world["workspace"], world["binding"].world_id
    assert asker.configuration(workspace, world_id, staying, _decider(later_id))[1] == (
        "grant_expired"
    )
    society = _step(client, world, society)
    assert _visitors(society) == []
    assert uuid.UUID(_departure_id(later_id, staying, "grant_ended")) in {
        row["crossing_id"] for row in _crossings(world)
    }


#: A visitors grant's scope as revisions were stored before grants named their version.
_STORED_SCOPE: dict[str, Any] = {
    "visitors_maximum": 1,
    "kinds": ["player"],
    "things": [],
    "version_id": None,
    "gate": None,
    "may_carry_in": False,
    "may_carry_out": False,
    "may_speak": True,
    "world_words": None,
}


def _stored_grant(world, scope: dict[str, Any]) -> uuid.UUID:
    """A grant written straight into the tables, as a revision stored before a rule it would now
    break: the rules a grant is read under still hold for it."""
    grant_id = uuid.uuid4()
    connection, transaction = _scoped(world)
    try:
        connection.execute(
            "insert into door_grant (workspace_id, grant_id, world_id, bridge, issued_by) "
            "values (%s, %s, %s, 'test-bridge', %s)",
            (world["workspace"], grant_id, world["binding"].world_id, world["session"].actor),
        )
        document = {
            "profile": "exulanica.door-grant/v1",
            "grant_id": str(grant_id),
            "grant_seq": 1,
            "world_id": world["binding"].world_id,
            "bridge": "test-bridge",
            "scope": scope,
            "mapping_sha256": sorted(
                [
                    door_support.mapping_sha256(),
                    door_support.mapping_sha256(door_support.mapping(2)),
                ]
            ),
            "expires_at": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(
                timespec="microseconds"
            ),
        }
        connection.execute(
            "insert into door_grant_revision (workspace_id, grant_id, grant_seq, document, "
            "document_sha256, recorded_by) values (%s, %s, 1, %s, %s, %s)",
            (
                world["workspace"],
                grant_id,
                Jsonb(document),
                sha256_of_canonical(document).hex(),
                world["session"].actor,
            ),
        )
    finally:
        transaction.__exit__(None, None, None)
    return grant_id


def test_a_visitors_grant_stored_before_grants_named_their_version_is_still_read(door):
    world = door["world"]
    client = door["client"]
    scope = _STORED_SCOPE
    grant_id = _stored_grant(world, scope)
    params = {"world_id": world["binding"].world_id}
    listed = client.get("/door/grants", headers=OWNER, params=params)
    assert listed.status_code == 200, listed.text
    [stored] = [g for g in listed.json()["grants"] if g["grant_id"] == str(grant_id)]
    assert stored["scope"] == scope
    one = client.get(f"/door/grants/{grant_id}", headers=OWNER)
    assert (one.status_code, one.json()["grant"]["scope"]) == (200, scope)
    opened = client.post(f"/door/grants/{grant_id}/channel-credentials", headers=OWNER)
    assert opened.status_code == 201, opened.text
    channel = {"Authorization": f"Bearer {opened.json()['credential']}"}
    assert _hello(door, channel).status_code == 200
    taken = _arrive(client, channel, str(uuid.uuid4()), carried=[])
    assert (taken.status_code, taken.json()["code"]) == (409, "world_not_open_to_visitors")
    revoked = client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER)
    assert (revoked.status_code, revoked.json()["grant"]["state"]) == (200, "revoked")
    # Issued now, the same shape is refused: a grant for visitors names their version.
    issued = client.post(
        "/door/grants",
        headers=OWNER,
        params=params,
        json={
            "idempotency_key": "visitors-no-version",
            "bridge": "test-bridge",
            "visitors_maximum": 1,
            "kinds": ["player"],
        },
    )
    assert (issued.status_code, issued.json()["code"]) == (422, "invalid_scope")


def test_a_visitors_grant_is_issued_only_for_a_version_holding_a_society_of_things(door):
    world = door["world"]
    client = door["client"]
    params = {"world_id": world["binding"].world_id}
    body = {
        "bridge": "test-bridge",
        "visitors_maximum": 1,
        "kinds": ["player"],
        "version_id": str(world["binding"].version_id),
    }
    # The version holds no society: there is nowhere for a visitor to arrive.
    empty = client.post(
        "/door/grants",
        headers=OWNER,
        params=params,
        json={**body, "idempotency_key": "nobody-lives-here"},
    )
    assert (empty.status_code, empty.json()["code"]) == (409, "world_not_open_to_visitors")
    # Its society is one of people (exulanica-society/v2), whose engine holds no things.
    _request, person = _person_request(door)
    peopled = client.post(
        "/door/grants",
        headers=OWNER,
        params=params,
        json={**body, "idempotency_key": "people-live-here"},
    )
    assert (peopled.status_code, peopled.json()["code"]) == (409, "world_not_open_to_visitors")
    assert client.get("/door/grants", headers=OWNER, params=params).json()["grants"] == []
    # Its people may still be handed to the bridge: the rule is the visitors'.
    named = client.post(
        "/door/grants",
        headers=OWNER,
        params=params,
        json={
            "idempotency_key": "one-of-its-people",
            "bridge": "test-bridge",
            "things": [person],
            "version_id": str(world["binding"].version_id),
        },
    )
    assert named.status_code == 201, named.text


def test_an_arrival_under_a_stored_grant_into_a_society_of_people_is_refused(door):
    """A grant stored before issuing read its version's society, naming a version whose society is
    one of people (exulanica-society/v2): its arrivals are refused by the rule issuing now keeps."""
    world = door["world"]
    client = door["client"]
    _person_request(door)  # the version's society is one of people
    grant_id = _stored_grant(
        world, {**_STORED_SCOPE, "version_id": str(world["binding"].version_id)}
    )
    opened = client.post(f"/door/grants/{grant_id}/channel-credentials", headers=OWNER)
    assert opened.status_code == 201, opened.text
    channel = {"Authorization": f"Bearer {opened.json()['credential']}"}
    assert _hello(door, channel).status_code == 200
    taken = _arrive(client, channel, str(uuid.uuid4()), carried=[])
    assert (taken.status_code, taken.json()["code"]) == (409, "world_not_open_to_visitors")


def test_a_grant_takes_a_bounded_number_of_arrivals_an_hour(door, crossings, monkeypatch):
    world, _society = _world(door)
    client = door["client"]
    monkeypatch.setattr(door_crossings, "ARRIVALS_PER_HOUR_MAXIMUM", 2)
    _grant_id, channel = _grant(door, visitors_maximum=4)
    assert _hello(door, channel).status_code == 200
    first = str(uuid.uuid4())
    assert _arrive(client, channel, first).status_code == 201
    assert _arrive(client, channel, str(uuid.uuid4())).status_code == 201
    # A resent arrival is the same one, not another.
    assert _arrive(client, channel, first).status_code == 200
    third = _arrive(client, channel, str(uuid.uuid4()))
    assert (third.status_code, third.json()["code"]) == (429, "too_many_arrivals")
    assert 1 <= third.json()["retry_after_s"] <= 3600
    assert len(_crossings(world)) == 2


def test_a_visitor_carries_its_look_s_own_licence_whatever_its_mapping_says(door, crossings):
    world, _society = _world(door)
    claimed = door_support.mapping_v2()
    claimed["visitors"][0]["looks"][0]["licence"] = {
        "spdx": "CC-BY-4.0",
        "attribution": "Somebody else",
    }
    entries = json.loads(
        door_support.bridges_setting(listed=False, workspaces=[str(world["workspace"])])
    )
    entries[0]["mapping_sha256"] = [door_support.mapping_sha256(claimed)]
    admitted = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})
    other_client, _runtime = door["application"](admitted)
    look = shipped_looks()[("blocky-traveller", 1)].document["origin"]
    # The arm before: the mapping's words and the look's own licence differ.
    assert look["licence"]["spdx"] != "CC-BY-4.0"
    with other_client:
        _grant_id, channel = _grant(door, key="visitors-licence")
        said = other_client.post(
            "/door/channel/hello",
            headers=channel,
            json={
                "adapter_version": door_support.ADAPTER_VERSION,
                "mapping": claimed,
                "reads": door_support.READS,
            },
        )
        assert said.status_code == 200, said.text
        arrival = str(uuid.uuid4())
        assert _arrive(other_client, channel, arrival).status_code == 201
    [crossing] = [row for row in _crossings(world) if row["crossing_id"] == uuid.UUID(arrival)]
    origin = crossing["document"]["origin"]
    assert origin["licence"] == look["licence"]
    assert origin["distribution"] == look["distribution"]


def test_a_visitor_arrives_in_a_look_its_own_workspace_keeps_never_another_s(
    door, crossings, tmp_path
):
    world, society = _world(door)
    imported = _imported()

    def admit(workspace_id: uuid.UUID, root: Any) -> Any:
        """The workspace admits the imported traveller's look, as a deployment's intake does."""
        with door["database"].session(workspace_id) as connection:
            store = ThingStore(connection, workspace_id, LocalContentAddressedStore(root))
            kept = store.admit_look(
                copy.deepcopy(imported),
                container_of("blocky-traveller"),
                created_by=world["session"].actor,
                admit=lambda _look: None,
            )
        return kept.look

    theirs = admit(uuid.uuid4(), tmp_path / "theirs")
    named = {"look": theirs.look, "version": theirs.version, "sha256": theirs.sha256}
    assert (theirs.look, theirs.version) not in shipped_looks()
    mapping = door_support.mapping_v2()
    [offered] = mapping["visitors"][0]["looks"]
    licence = {"spdx": imported["origin"]["licence"]["spdx"], "share_alike": True}
    mapping["visitors"][0]["looks"] = [
        {**offered, "look": named, "licence": licence},
        {**offered, "look_key": "renamed", "look": {**named, "look": "renamed-look"}},
    ]
    entries = json.loads(
        door_support.bridges_setting(listed=False, workspaces=[str(world["workspace"])])
    )
    entries[0]["mapping_sha256"] = [door_support.mapping_sha256(mapping)]
    admitted = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})
    other_client, _runtime = door["application"](admitted)
    arrival = str(uuid.uuid4())
    with other_client:
        _grant_id, channel = _grant(door, key="visitors-own-look")
        said = other_client.post(
            "/door/channel/hello",
            headers=channel,
            json={
                "adapter_version": door_support.ADAPTER_VERSION,
                "mapping": mapping,
                "reads": door_support.READS,
            },
        )
        assert said.status_code == 200, said.text
        # Only another workspace keeps it: refused as a look nobody keeps.
        elsewhere = _arrive(other_client, channel, str(uuid.uuid4()))
        assert (elsewhere.status_code, elsewhere.json()["code"]) == (422, "look_not_shipped")
        mine = admit(world["workspace"], tmp_path / "mine")
        assert mine.sha256 == theirs.sha256
        # Kept here, but named under another key: refused by name too.
        renamed = _arrive(other_client, channel, str(uuid.uuid4()), look_key="renamed")
        assert (renamed.status_code, renamed.json()["code"]) == (422, "look_not_shipped")
        sent = _arrive(other_client, channel, arrival)
        assert sent.status_code == 201, sent.text
    # The refused arrivals wrote nothing; the visitor carries the kept look's own licence.
    [crossing] = _crossings(world)
    assert crossing["crossing_id"] == uuid.UUID(arrival)
    origin = crossing["document"]["origin"]
    assert origin["licence"] == imported["origin"]["licence"]
    assert origin["distribution"] == imported["origin"]["distribution"]
    society = _step(door["client"], world, society)
    [visitor] = _visitors(society)
    scope, root, _ = routes(world)
    read = door["client"].get(f"{root}/thing-looks", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    assert [
        (entry["thing_id"], entry["look"], entry["chosen_by"])
        for entry in read.json().get("workspace_looks", [])
    ] == [(visitor["id"], {"sha256": mine.sha256, "source": "workspace"}, "crossing")]


def test_arrivals_a_grant_or_mapping_does_not_admit_are_refused_by_name(door, crossings):
    world, _society = _world(door)
    client = door["client"]
    _grant_id, channel = _grant(door, visitors_maximum=2, may_carry_in=False)
    assert _hello(door, channel).status_code == 200
    carried = _arrive(client, channel, str(uuid.uuid4()))
    assert (carried.status_code, carried.json()["code"]) == (403, "carrying_not_allowed")

    _grant_id, laden = _grant(door, key="visitors-laden", visitors_maximum=2)
    assert _hello(door, laden).status_code == 200
    heavy = _arrive(
        client,
        laden,
        str(uuid.uuid4()),
        carried=[{"game_item": "test:sword", "count": 9}, {"game_item": "test:torch", "count": 8}],
    )
    assert (heavy.status_code, heavy.json()["code"]) == (422, "too_much_carried")
    unmapped = _arrive(
        client, laden, str(uuid.uuid4()), carried=[{"game_item": "test:apple", "count": 1}]
    )
    assert (unmapped.status_code, unmapped.json()["code"]) == (422, "item_not_mapped")
    arrival = str(uuid.uuid4())
    assert _arrive(client, laden, arrival).status_code == 201
    other = _arrive(client, laden, arrival, carried=[])
    assert (other.status_code, other.json()["code"]) == (409, "crossing_id_reused")
    assert len(_crossings(world)) == 1

    # A mapping naming a kind this release does not ship is refused at the arrival, by name.
    unshipped = door_support.mapping()
    unshipped["visitors"][0]["kind"] = {"key": "nosuchkind", "version": 1}
    entries = json.loads(
        door_support.bridges_setting(listed=False, workspaces=[str(world["workspace"])])
    )
    entries[0]["mapping_sha256"] = [door_support.mapping_sha256(unshipped)]
    admitted = load_bridge_directory({"EXULANICA_DOOR_BRIDGES": json.dumps(entries)})
    other_client, _runtime = door["application"](admitted)
    with other_client:
        _grant_id, strange = _grant(door, key="visitors-strange")
        said = other_client.post(
            "/door/channel/hello",
            headers=strange,
            json={
                "adapter_version": door_support.ADAPTER_VERSION,
                "mapping": unshipped,
                "reads": door_support.READS,
            },
        )
        assert said.status_code == 200, said.text
        refused = _arrive(other_client, strange, str(uuid.uuid4()), carried=[])
        assert (refused.status_code, refused.json()["code"]) == (422, "kind_not_shipped")
    assert len(_crossings(world)) == 1


def test_a_grant_for_no_visitors_takes_no_arrival(door):
    _request, person = _person_request(door)
    channel = _credential(door, _grant_for(door, person))
    assert _hello(door, channel).status_code == 200
    refused = _arrive(door["client"], channel, str(uuid.uuid4()), carried=[])
    assert (refused.status_code, refused.json()["code"]) == (403, "no_visitors_allowed")


def test_two_grants_visitors_in_one_society_are_each_their_own_grant_s(door, crossings):
    world, society = _world(door)
    client = door["client"]
    first_id, first = _grant(door, key="visitors-first")
    second_id, second = _grant(door, key="visitors-second")
    cursors = {}
    for name, channel in (("first", first), ("second", second)):
        _frames_read, cursors[name] = _read(door, channel, _hello(door, channel).json()["cursor"])
    mine = _arrive(client, first, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    theirs = _arrive(client, second, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    assert {visitor["id"] for visitor in _visitors(society)} == {mine, theirs}
    frames, cursors["first"] = _read(door, first, cursors["first"])
    assert [(f["kind"], f.get("thing_id")) for f in frames] == [("arrived", mine)]
    frames, cursors["second"] = _read(door, second, cursors["second"])
    assert [(f["kind"], f.get("thing_id")) for f in frames] == [("arrived", theirs)]
    # One grant's owner route names only its own visitors.
    stranger = client.post(
        f"/door/grants/{first_id}/send-away", headers=OWNER, json={"thing_id": theirs}
    )
    assert stranger.status_code == 404
    assert (
        client.post(
            f"/door/grants/{second_id}/send-away", headers=OWNER, json={"thing_id": theirs}
        ).status_code
        == 202
    )
    society = _step(client, world, society)
    assert [visitor["id"] for visitor in _visitors(society)] == [mine]
    frames, cursors["first"] = _read(door, first, cursors["first"])
    assert frames == []
    frames, cursors["second"] = _read(door, second, cursors["second"])
    assert [(f["kind"], f.get("thing_id")) for f in frames] == [("departed", theirs)]
    # A grant reports the deliveries of its own visitors' departures only.
    leaving = frames[0]["departure_id"]
    report = {"delivered": [], "not_delivered": []}
    foreign = client.post(
        f"/door/channel/departures/{leaving}/delivered", headers=first, json=report
    )
    assert (foreign.status_code, foreign.json()["code"]) == (404, "unknown_reference")
    own = client.post(f"/door/channel/departures/{leaving}/delivered", headers=second, json=report)
    assert (own.status_code, own.json()) == (202, {"recorded": True})


def test_a_grant_s_end_waits_for_a_crossing_the_minute_has_not_taken(door, crossings):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    _frames_read, cursor = _read(door, channel, _hello(door, channel).json()["cursor"])
    assert _arrive(client, channel, str(uuid.uuid4()), carried=[]).status_code == 201
    assert client.post(f"/door/grants/{grant_id}/revoke", headers=OWNER).status_code == 200
    # Nobody has arrived or departed yet, but the arrival and its departure wait for a minute.
    frames, cursor = _read(door, channel, cursor)
    assert frames == []
    society = _step(client, world, society)
    frames, cursor = _read(door, channel, cursor)
    assert [frame["kind"] for frame in frames] == ["arrived", "departed", "grant_ended"]


def test_a_visitor_sent_home_is_asked_for_until_the_minute_takes_it(door, crossings):
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    assert _hello(door, channel).status_code == 200
    thing_id = _arrive(client, channel, str(uuid.uuid4()), carried=[]).json()["thing_id"]
    society = _step(client, world, society)
    asker = door["runtime"].asker()
    workspace, world_id = world["workspace"], world["binding"].world_id
    sent = client.post(
        f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id}
    )
    assert sent.status_code == 202
    # Its grant stands and it is still in the world: its program decides for it until it leaves.
    assert asker.configuration(workspace, world_id, thing_id, _decider(grant_id))[1] is None
    society = _step(client, world, society)
    assert _visitors(society) == []
    assert asker.configuration(workspace, world_id, thing_id, _decider(grant_id))[1] == (
        "grant_revoked"
    )


def test_the_departure_ids_the_door_writes_are_the_contract_s(door, crossings):
    """The expected ids are derived here from the namespace the contract states, so a change to how
    the door derives them fails rather than agreeing with itself."""
    world, society = _world(door)
    client = door["client"]
    grant_id, channel = _grant(door)
    assert _hello(door, channel).status_code == 200
    arrival = str(uuid.uuid4())
    thing_id = _arrive(client, channel, arrival, carried=[]).json()["thing_id"]
    assert thing_id == _visitor_id(grant_id, arrival)
    society = _step(client, world, society)
    client.post(f"/door/grants/{grant_id}/send-away", headers=OWNER, json={"thing_id": thing_id})
    written = [row for row in _crossings(world) if row["kind"] == "departure"]
    assert [str(row["crossing_id"]) for row in written] == [
        _departure_id(grant_id, thing_id, "sent_away")
    ]
    assert copy.deepcopy(written[0]["document"])["thing_id"] == thing_id


def test_the_table_refuses_a_mapping_that_states_no_profile(door):
    world = door["world"]
    connection, transaction = _scoped(world)
    write = "insert into door_mapping (workspace_id, mapping_sha256, document) values (%s, %s, %s)"
    try:
        # The arm before: the same row with a profile is taken.
        stated = door_support.mapping()
        with connection.transaction(force_rollback=True):
            connection.execute(
                write,
                (world["workspace"], door_support.mapping_sha256(stated), Jsonb(stated)),
            )
        unstated = {key: value for key, value in stated.items() if key != "profile"}
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                write,
                (world["workspace"], sha256_of_canonical(unstated).hex(), Jsonb(unstated)),
            )
    finally:
        transaction.__exit__(None, None, None)
