"""An undo or redo of a change to a made town's building queues the version's changed tiles for
baking, as a kept change queues them, through every route that reverses an edit
(:func:`exulanica.api.world_edit.reversal`,
:func:`exulanica.world.version_tiles.queue_version_bakes`).

Against PostgreSQL as the runtime role, on a small town made through the API, its changes written
as the parts routes write them and undone and redone through the routes; the jobs are read as the
owner. Where nothing is drained, every job a step queued is still queued after it. The town is made
under one fixed identity, so every run makes the same town.

*   ``things/undo`` and ``things/redo`` queue the tiles each step leaves changed, and none twice;
*   ``objects/undo`` (the page's Take back and the agent's undo) and ``environment-instances/undo``
    queue them too, found before the edit takes the workspace's lock, and a stale base is refused
    as it always was; a redo finds the tiles of the change it puts back before the lock too;
*   a tile whose bake failed because the version changed again is queued again by the undo that
    brings the version back, and is then baked.
"""

from __future__ import annotations

import pytest
from exulanica.grammar.grammars.city.generation.massing import (
    BuildingChange,
    BuildingStoreysRefused,
)
from exulanica.world import saved_entries, version_tiles
from exulanica.world.generated_worlds import town_records, town_records_with
from exulanica.world.objects import ElementOverride
from exulanica.world.town_parts import town_buildings
from exulanica.world.version_tiles import (
    VERSION_BAKE_JOB_KIND,
    changed_tiles,
    changes_fold,
    forget_changed_tiles,
    version_changes,
)
from psycopg.rows import dict_row

from test_society_made_world import made as imported_made  # noqa: F401
from test_version_tiles_postgres import Town, _town  # noqa: F401

pytestmark = pytest.mark.postgres


#: The small town's identity, so every run makes the same town: one in which a building other than
#: the first stands a storey taller with the first removed, and each change alters tiles. A town
#: made under a fresh identity each run sometimes has no such building.
TOWN = "world:generated:00000000-0000-4000-8000-000000000001"


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _the_same_town_on_every_run(monkeypatch):  # type: ignore[no-untyped-def]
    monkeypatch.setattr(saved_entries, "new_world_id", lambda kind: TOWN)


def _queued(town: Town) -> list[tuple[tuple[int, int], str, str]]:
    """The version's queued bakes, each as its tile, its inputs digest and its payload's fold, in
    the order they were queued."""
    rows = town.owner_rows(
        "select payload from job where kind = %s and state = 'queued' and workspace_id = %s "
        "order by created_at, job_id",
        VERSION_BAKE_JOB_KIND,
        town.workspace_id,
    )
    assert {row["payload"]["version_id"] for row in rows} <= {str(town.version_id)}
    return [
        (
            tuple(row["payload"]["tile"]),
            row["payload"]["tile_inputs_digest"],
            row["payload"]["edit_delta_digest"],
        )
        for row in rows
    ]


def _expected(town: Town, changes: dict[str, BuildingChange]) -> set[tuple]:  # type: ignore[type-arg]
    """The changed tiles these changes give, as :func:`_queued` names a job of each."""
    with town.session() as connection:
        tiles = changed_tiles(
            connection, town.workspace_id, town.world_id, town.snapshot_id, changes
        )
    return {((t.tile_x, t.tile_y), t.tile_inputs_digest, t.edit_delta_digest) for t in tiles}


def _changes(town: Town) -> dict[str, BuildingChange]:
    with town.session() as connection:
        return version_changes(
            connection, town.workspace_id, town.world_id, town.snapshot_id, town.version_id
        )


def _taller(town: Town, removed: str) -> tuple[str, int]:
    """A building other than ``removed`` and one storey more than it stands, within its lot's
    range: the first the town's grammar takes."""
    with town.session() as connection:
        made = town_records(connection, town.workspace_id, town.world_id, town.snapshot_id)
        for building in town_buildings(made.records):
            if building.identity == removed:
                continue
            changes = {
                removed: BuildingChange(removed=True),
                building.identity: BuildingChange(storeys=building.storeys + 1),
            }
            try:
                town_records_with(
                    connection, town.workspace_id, town.world_id, town.snapshot_id, changes
                )
            except BuildingStoreysRefused:
                continue
            return building.identity, building.storeys + 1
    raise AssertionError("no building of the small town stands one storey taller")


def _post(town: Town, path: str, base: str | None = None):  # type: ignore[no-untyped-def]
    """``path`` of the version, posted against ``base`` or the version's state as it stands."""
    state = base or town.api.version(town.entry)["state_sha256"]  # type: ignore[attr-defined]
    return town.api.post(  # type: ignore[attr-defined]
        f"/world/versions/{town.version_id}/{path}?world_id={town.world_id}",
        {"base_state_sha256": state},
    )


def _edit(town: Town, path: str) -> None:
    response = _post(town, path)
    assert response.status_code == 200, response.text


def _remakings_watched(monkeypatch) -> list[int]:  # type: ignore[no-untyped-def]
    """Each remaking of the town with changes from now on, as how many advisory locks the remaking
    connection held then: 0 throughout means none ran under the edit's workspace lock."""
    held: list[int] = []
    made_with = version_tiles.town_records_with

    def watched(connection, *args, **kwargs):  # type: ignore[no-untyped-def]
        with connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                "select count(*) as n from pg_locks where locktype = 'advisory' "
                "and pid = pg_backend_pid() and granted"
            ).fetchone()
        held.append(row["n"])
        return made_with(connection, *args, **kwargs)

    monkeypatch.setattr(version_tiles, "town_records_with", watched)
    return held


def _forget(town: Town) -> None:
    """Forget, in this process, the tiles any change of the town alters, as a process that never
    found them starts."""
    with town.session() as connection:
        made = town_records(connection, town.workspace_id, town.world_id, town.snapshot_id)
    forget_changed_tiles(frozenset({made.receipt_sha256}))


def test_an_undo_and_a_redo_of_town_changes_queue_their_tiles_where_none_is_queued(town):
    removed = town.buildings()[0]
    taller, storeys = _taller(town, removed)
    town.change(ElementOverride(f"part:{taller}", suppressed=False, storeys=storeys), taller)
    both = _changes(town)
    assert both == {removed: BuildingChange(removed=True), taller: BuildingChange(storeys=storeys)}
    alone = {removed: both[removed]}
    removed_set, both_set = _expected(town, alone), _expected(town, both)
    assert removed_set and both_set and not removed_set & both_set
    # The changes were written without the parts routes, so nothing is queued yet.
    assert _queued(town) == []

    _edit(town, "things/undo")
    assert _changes(town) == alone
    after_undo = _queued(town)
    assert len(after_undo) == len(removed_set)
    assert set(after_undo) == removed_set
    assert {fold for _tile, _inputs, fold in after_undo} == {changes_fold(alone)}
    # Exactly what a kept change queues: nothing is left for the version to queue.
    assert town.queue() == ()

    _edit(town, "things/redo")
    assert _changes(town) == both
    after_redo = _queued(town)
    assert after_redo[: len(after_undo)] == after_undo
    assert set(after_redo[len(after_undo) :]) == both_set
    assert len(after_redo) == len(removed_set) + len(both_set)
    assert {fold for _tile, _inputs, fold in after_redo[len(after_undo) :]} == {changes_fold(both)}
    assert town.queue() == ()

    # A tile already queued is not queued again, whichever way the version steps.
    _edit(town, "things/undo")
    assert _queued(town) == after_redo
    _edit(town, "things/redo")
    assert _queued(town) == after_redo


def test_an_undo_of_the_only_change_queues_nothing(town):
    assert len(_changes(town)) == 1
    _edit(town, "things/undo")
    assert _changes(town) == {}
    # Every tile is the public bake again.
    assert _queued(town) == []
    assert {t.state for t in town.tiles()} == {"baked"}


@pytest.mark.parametrize("route", ["objects/undo", "environment-instances/undo"])
def test_every_undo_route_queues_a_town_change_s_tiles_found_before_the_edit_s_lock(
    town, route, monkeypatch
):
    removed = town.buildings()[0]
    taller, storeys = _taller(town, removed)
    town.change(ElementOverride(f"part:{taller}", suppressed=False, storeys=storeys), taller)
    alone = {removed: BuildingChange(removed=True)}
    removed_set = _expected(town, alone)
    # A stale base is refused as it always was, and queues nothing.
    stale = _post(town, route, "0" * 64)
    assert stale.status_code == 409, stale.text
    assert stale.json()["code"] == "stale_object_base"
    assert _queued(town) == []

    _forget(town)
    held = _remakings_watched(monkeypatch)
    _edit(town, route)
    assert _changes(town) == alone
    assert set(_queued(town)) == removed_set
    # The town was made again with the undo's changes, and never while the edit held its lock.
    assert held
    assert set(held) == {0}


def test_an_undo_queues_again_the_tiles_whose_bakes_failed_on_a_later_change(town):
    removed = town.buildings()[0]
    alone = _changes(town)
    first = town.queue()
    assert first
    taller, storeys = _taller(town, removed)
    town.change(ElementOverride(f"part:{taller}", suppressed=False, storeys=storeys), taller)
    # The worker finds the version's changes are no longer the ones its bakes were queued for.
    failed = town.baker.drain([town.workspace_id])
    assert len(failed) == len(first)
    assert {o.status for o in failed} == {"failed"}
    assert all("no longer the ones" in o.detail for o in failed)

    _edit(town, "objects/undo")
    assert _changes(town) == alone
    expected = _expected(town, alone)
    assert set(_queued(town)) == expected
    digests = {inputs for _tile, inputs, _fold in expected}
    assert {t.state for t in town.tiles() if t.tile_inputs_digest in digests} == {"baking"}

    baked = town.baker.drain([town.workspace_id])
    assert len(baked) == len(first)
    assert {o.status for o in baked} == {"baked"}
    assert {t.state for t in town.tiles()} == {"baked"}


def test_a_redo_queues_the_tiles_of_the_change_it_puts_back_found_before_the_edit_s_lock(
    town, monkeypatch
):
    removed = town.buildings()[0]
    taller, storeys = _taller(town, removed)
    town.change(ElementOverride(f"part:{taller}", suppressed=False, storeys=storeys), taller)
    both = _changes(town)
    _edit(town, "things/undo")
    assert _changes(town) == {removed: BuildingChange(removed=True)}
    both_set = _expected(town, both)

    _forget(town)
    held = _remakings_watched(monkeypatch)
    _edit(town, "things/redo")
    assert _changes(town) == both
    assert both_set <= set(_queued(town))
    # The town was made again with the change the redo restores, never while the edit held its lock.
    assert held
    assert set(held) == {0}
