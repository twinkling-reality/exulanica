"""A person removes a made town's building, or stands it taller or lower, through the API.

Against PostgreSQL as the runtime role, on a small town made through the API under a fixed
identity, so it is the same town on every run. Through ``POST .../parts/{part_id}/remove`` and
``.../storeys`` and their previews: a kept change is the version's ``part:`` override and queues a
bake of every tile it alters; a storey count outside the lot's range, a move, a building the town
does not have and a stranger's request are refused; with a society of things, a removal is refused
while anybody lives or works in the building, naming them, and so is a lowering that takes away a
premises somebody lives in. Expected figures are read from the town's own records, never retyped.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from typing import Any

import pytest
from exulanica.api.routes import world_parts
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.world import saved_entries
from exulanica.world.composers.city_grammar_town import records_with
from exulanica.world.generated_worlds import town_records
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.town_parts import TownBuilding, town_buildings
from exulanica.world.version_tiles import VERSION_BAKE_JOB_KIND, changed_tiles, version_changes
from psycopg.rows import dict_row

from personal_world_support import OWNER_TOKEN, STRANGER_TOKEN
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

TOWN = "world:generated:00000000-0000-4000-8000-000000000003"
THINGS = "exulanica-society/v7"


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


@dataclasses.dataclass
class Town:
    api: Any
    entry: dict[str, Any]
    snapshot_id: uuid.UUID

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.api.repository.workspace_id  # type: ignore[no-any-return]

    @property
    def version_id(self) -> uuid.UUID:
        return uuid.UUID(self.entry["authored_version_id"])

    def path(self, tail: str = "") -> str:
        return f"/world/versions/{self.version_id}{tail}?world_id={TOWN}"

    def base(self) -> str:
        read = self.api.get(self.path())
        assert read.status_code == 200, read.text
        return str(read.json()["state_sha256"])

    def buildings(self) -> list[TownBuilding]:
        with self.api.database.session(self.workspace_id) as connection:
            made = town_records(connection, self.workspace_id, TOWN, self.snapshot_id)
        return list(town_buildings(made.records))

    def receipt(self) -> Any:
        with self.api.database.session(self.workspace_id) as connection:
            return town_records(connection, self.workspace_id, TOWN, self.snapshot_id).receipt

    def post(self, part_id: str, tail: str, *, preview=False, token=OWNER_TOKEN, **body):  # type: ignore[no-untyped-def]
        path = self.path(f"/parts/{part_id}/{tail}" + ("/preview" if preview else ""))
        return self.api.post(path, {"base_state_sha256": self.base(), **body}, token)

    def overrides(self) -> dict[str, Any]:
        with self.api.database.session(self.workspace_id) as connection:
            changes = WorldObjectRepository(
                connection, self.workspace_id, world_id=TOWN
            ).part_changes(self.version_id)
        return {change.identity: change for change in changes}

    def jobs(self) -> list[dict[str, Any]]:
        """The version's queued tile bakes, read as the owner across every workspace."""
        connection = self.api.repository.connection
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                "select payload from job where kind = %s and payload->>'version_id' = %s",
                (VERSION_BAKE_JOB_KIND, str(self.version_id)),
            ).fetchall()
        connection.commit()
        return [row["payload"] for row in rows]

    def altered(self) -> set[str]:
        """The inputs digest of every tile the version's kept changes alter."""
        with self.api.database.session(self.workspace_id) as connection:
            changes = version_changes(
                connection, self.workspace_id, TOWN, self.snapshot_id, self.version_id
            )
            tiles = changed_tiles(connection, self.workspace_id, TOWN, self.snapshot_id, changes)
        return {tile.tile_inputs_digest for tile in tiles}


def _town(api: Any) -> Town:
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": "Changed"})
    assert response.status_code == 201, response.text
    entry = response.json()
    assert entry["world_id"] == TOWN
    return Town(api, entry, uuid.UUID(api.version(entry)["source_snapshot_id"]))


def _ranged(town: Town, *, lower: bool = False) -> tuple[TownBuilding, list[int]]:
    """A building whose lot allows more than one storey count (with ``lower``, one fewer than it
    stands), with the counts it allows, read from the town's grammar."""
    receipt = town.receipt()
    for building in town.buildings():
        counts = []
        for storeys in range(1, building.storeys + 4):
            try:
                records_with(receipt, {building.identity: BuildingChange(storeys=storeys)})
            except BuildingStoreysRefused:
                continue
            counts.append(storeys)
        if len(counts) > 1 and (not lower or counts[0] < building.storeys):
            return building, counts
    raise AssertionError("no building of the small town has a range of storeys")


def test_a_town_s_building_is_removed_or_stood_taller_and_its_tiles_queued(made):
    town = _town(made)
    building, counts = _ranged(town)
    gone = next(b for b in town.buildings() if b.identity != building.identity)
    assert town.jobs() == []

    listed = made.get(town.path("/parts"))
    assert listed.status_code == 200, listed.text
    assert listed.json()["profile"] == "exulanica.town-parts/v1"
    assert {part["part_id"] for part in listed.json()["parts"]} == {
        b.identity for b in town.buildings()
    }

    preview = town.post(gone.identity, "remove", preview=True)
    assert preview.status_code == 200, preview.text
    assert preview.json()["availability"] == "ready"
    assert preview.json()["would_change"]["subject_id"] == f"part:{gone.identity}"
    removed = town.post(gone.identity, "remove")
    assert removed.status_code == 200, removed.text
    assert town.overrides()[gone.identity].removed
    queued = {job["tile_inputs_digest"] for job in town.jobs()}
    assert queued and queued == town.altered()
    listed = made.get(town.path("/parts")).json()
    assert gone.identity not in {part["part_id"] for part in listed["parts"]}
    # Removed once, it is brought back by undo, not removed again.
    again = town.post(gone.identity, "remove")
    assert again.status_code == 409, again.text

    other = counts[-1] if counts[-1] != building.storeys else counts[0]
    said = town.post(building.identity, "storeys", preview=True, storeys=other)
    assert said.status_code == 200, said.text
    if other > building.storeys:
        expected = f"Taller: {other} storeys. Nobody lives in the new homes yet."
    else:
        expected = f"Lower: {other} {'storey' if other == 1 else 'storeys'}."
    assert said.json()["landing"]["said"] == expected
    kept = town.post(building.identity, "storeys", storeys=other)
    assert kept.status_code == 200, kept.text
    assert town.overrides()[building.identity].storeys == other
    assert not town.overrides()[building.identity].removed
    # Every tile the two changes alter together is queued, once.
    payloads = town.jobs()
    digests = [job["tile_inputs_digest"] for job in payloads]
    assert set(digests) >= town.altered() and len(digests) == len(set(digests))
    assert all(
        building.identity not in str(job) and gone.identity not in str(job) for job in payloads
    )


def test_a_town_s_building_is_refused_in_words_and_a_stranger_is_not_told_of_it(made):
    town = _town(made)
    building, counts = _ranged(town)
    base = town.base()

    tall = town.post(building.identity, "storeys", storeys=counts[-1] + 1)
    assert tall.status_code == 422, tall.text
    body = tall.json()
    assert body["code"] == "part_storeys_refused"
    assert body["detail"] == (
        f"Not taller: a {building.label.lower()} here has at most {counts[-1]} storeys."
    )
    assert body["where"] == {
        "part_id": building.identity,
        "storeys": counts[-1] + 1,
        "fewest": counts[0],
        "most": counts[-1],
    }
    if counts[0] > 1:
        low = town.post(building.identity, "storeys", storeys=counts[0] - 1)
        assert low.status_code == 422, low.text
        assert low.json()["detail"].startswith(f"Not lower: a {building.label.lower()} here ")
    blocked = town.post(building.identity, "storeys", preview=True, storeys=counts[-1] + 1)
    assert blocked.json()["blocked_reason"] == "part_storeys_refused"
    assert "said" not in blocked.json()["landing"]

    moved = made.post(
        town.path(f"/parts/{building.identity}/move"),
        {
            "base_state_sha256": base,
            "pose": {"x_mm": 1_000, "y_mm": 0, "z_mm": 0, "yaw_microradians": 0},
        },
    )
    assert moved.status_code == 422, moved.text
    assert moved.json()["code"] == "part_not_changeable"
    assert moved.json()["detail"] == "A town's building stands on its lot: it is not moved."

    nowhere = town.post(str(uuid.uuid4()), "remove")
    assert nowhere.status_code == 422, nowhere.text
    assert nowhere.json()["code"] == "part_unknown"

    stranger = town.post(building.identity, "remove", token=STRANGER_TOKEN)
    assert stranger.status_code == 404, stranger.text
    assert town.post(
        building.identity, "remove", preview=True, token=STRANGER_TOKEN
    ).status_code == (404)
    # Nothing was kept and nothing queued.
    assert town.base() == base and town.overrides() == {} and town.jobs() == []


def _homes(society: dict[str, Any]) -> dict[str, list[str]]:
    """Who lives in each premises, by its record subject, by name."""
    state = society["state"]
    premises = state["people"]["premises"]
    found: dict[str, list[str]] = {}
    for person in state["inhabitants"]:
        resident = person.get("resident")
        if resident and resident.get("home") and person.get("display_name"):
            subject = premises[resident["home"]["premises"]]["subject_id"]
            found.setdefault(subject, []).append(str(person["display_name"]))
    return found


def test_a_building_people_live_in_is_not_removed_or_lowered_from_under_them(made, monkeypatch):
    town = _town(made)
    made.client.app.state.services = dataclasses.replace(
        made.client.app.state.services, societies_of_things=True
    )
    created = made.post(
        town.path("/society"),
        {"region_id": town.entry["generated_ground"]["region_id"], "profile": THINGS},
    )
    assert created.status_code in (200, 201), created.text
    homes = _homes(created.json())
    lived_in = next(
        b
        for b in town.buildings()
        if any(f"city.premises:{premises}" in homes for premises in b.premises)
    )
    residents = [
        name
        for premises in lived_in.premises
        for name in homes.get(f"city.premises:{premises}", [])
    ]

    verdict = town.post(lived_in.identity, "remove", preview=True)
    assert verdict.json()["blocked_reason"] == "part_houses_people"
    refused = town.post(lived_in.identity, "remove")
    assert refused.status_code == 422, refused.text
    body = refused.json()
    assert body["code"] == "part_houses_people"
    assert body["detail"].startswith("Not removed: ") and body["detail"].endswith(" there.")
    assert residents[0] in body["detail"]
    assert "can be moved" not in body["detail"]
    assert set(residents) <= set(body["where"]["people"])
    assert body["where"]["part_id"] == lived_in.identity

    # No storey count the small town's lots allow takes a premises away (each lot keeps its
    # premises down to its fewest storeys), so what lowering takes is stood in for: the premises
    # somebody lives in.
    building, _counts = _ranged(town, lower=True)
    lowered = building.storeys - 1
    taken = next(premises for premises in lived_in.premises if f"city.premises:{premises}" in homes)
    with monkeypatch.context() as patched:
        patched.setattr(world_parts, "premises_taken", lambda before, after, identity: (taken,))
        lower = town.post(building.identity, "storeys", storeys=lowered)
        assert lower.status_code == 422, lower.text
        assert lower.json()["code"] == "part_houses_people"
        assert lower.json()["detail"].startswith("Not lower: ")
        assert lower.json()["detail"].endswith(" there, in the storeys it would lose.")
        assert lower.json()["where"]["storeys"] == lowered
        preview = town.post(building.identity, "storeys", preview=True, storeys=lowered)
        assert preview.json()["blocked_reason"] == "part_houses_people"

    # A change that takes nobody's premises is kept with the society standing.
    kept = town.post(building.identity, "storeys", storeys=lowered)
    assert kept.status_code == 200, kept.text
    assert town.overrides()[building.identity].storeys == lowered
    assert town.jobs()


def _kept(town: Town) -> tuple[dict[str, Any], list[str]]:
    """The version's kept overrides and its queued bakes, in an order that compares."""
    return town.overrides(), sorted(json.dumps(job, sort_keys=True) for job in town.jobs())


def test_a_change_on_a_stale_base_or_with_a_saved_world_that_cannot_advance_keeps_nothing(
    made, monkeypatch
):
    """A change whose saved world cannot advance with it is rolled back with it, and one posted on
    a base the version has moved past is refused (409 ``stale_object_base``): neither keeps an
    override nor queues a bake."""
    town = _town(made)
    building, counts = _ranged(town)
    gone = next(b for b in town.buildings() if b.identity != building.identity)
    other = counts[-1] if counts[-1] != building.storeys else counts[0]
    storeys = town.path(f"/parts/{building.identity}/storeys")
    before = _kept(town)

    def cannot_advance(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("the saved world did not advance")

    entry = made.get(f"/world-entries/{town.entry['entry_id']}")
    assert entry.status_code == 200, entry.text
    saved = entry.json()
    with monkeypatch.context() as patched:
        repository = saved_entries.SavedWorldEntryRepository
        patched.setattr(repository, "advance_authored_locked", cannot_advance)
        body = {
            "base_state_sha256": town.base(),
            "storeys": other,
            "saved_entry": {
                "entry_id": saved["entry_id"],
                "base_revision": saved["revision"],
                "authored_state_sha256": saved["authored_state_sha256"],
                "authored_edit_seq": saved["authored_edit_seq"],
            },
        }
        try:
            failed = made.post(storeys, body)
        except RuntimeError as exc:
            assert "did not advance" in str(exc)
        else:
            assert failed.status_code == 500, failed.text
    assert _kept(town) == before

    old = town.base()
    assert town.post(gone.identity, "remove").status_code == 200
    removed = _kept(town)
    assert removed != before
    stale = made.post(storeys, {"base_state_sha256": old, "storeys": other})
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_object_base"
    assert _kept(town) == removed
