"""Searches for a route home are bounded: how many a flyer makes an episode, and how far each goes.

Unbounded, a flyer the guard holds again and again searches every ten held steps of the homing
minute, and a search that finds no route settles every cell of its band, about a third of a second
on the largest grid the module admits. Both bounds are the flight module's named parameters.
"""

from __future__ import annotations

import heapq
from collections import Counter
from dataclasses import replace

from exulanica.movement import flight as flight_module
from exulanica.movement.air import AirVolume, PartBox, Placement, Solid, build_occupancy
from exulanica.movement.flight import FLIGHT_MODULE, state_at

from flight_support import DEVELOPMENT_SEEDS, crowded_flight, seeded, square_flight

EPISODE = FLIGHT_MODULE.value("episode_steps")
ROUTE_SEARCHES = FLIGHT_MODULE.value("route_searches")
ROUTE_CELLS = FLIGHT_MODULE.value("route_cells")


def _solid_centre(flight):
    """The centre of some solid cell that is no perch's own."""
    own = {cell for perch in flight.perches for c in perch.columns.values() for cell in c.own_cells}
    nx, ny, nz = flight.volume.shape
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                cell = (ix, iy, iz)
                if flight.occupancy.is_solid(cell) and cell not in own:
                    low, high = flight.volume.cell_bounds(cell)
                    return [(a + b) // 2 for a, b in zip(low, high, strict=True)]
    raise AssertionError("the world has no solid cell")


def _taken(monkeypatch) -> list[int]:
    """For each search, how many entries it takes off its queue: every cell it settles, and
    entries a cheaper way to the same cell made stale. A cell is queued at most once from each of
    its six neighbours and once more as the start, so a search takes at most 6 * settled + 1."""
    counts: list[int] = []
    real = heapq.heappop

    def counting(queue):
        counts[-1] += 1
        return real(queue)

    route = flight_module._route

    def search(*arguments):
        counts.append(0)
        monkeypatch.setattr(flight_module.heapq, "heappop", counting)
        try:
            return route(*arguments)
        finally:
            monkeypatch.setattr(flight_module.heapq, "heappop", real)

    monkeypatch.setattr(flight_module, "_route", search)
    return counts


def test_a_flyer_held_again_and_again_searches_at_most_route_searches_times_an_episode(
    monkeypatch,
):
    """Break steering: every flyer flies at a crown, so the guard holds it again and again on its
    way home. Each still searches for its way home exactly the bounded number of times; without the
    bound the same flyers search 32, 35 and 61 times."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[4])
    centre = _solid_centre(flight)

    def into_the_crown(flight_input, kind, flyer_state, step):
        position = tuple(flyer_state["position_mm"])
        offset = tuple(c - p for c, p in zip(centre, position, strict=True))
        return flight_module.scale_to(offset, kind.max_speed_mm_s), False

    monkeypatch.setattr(flight_module, "_desired", into_the_crown)
    searches: Counter[tuple[int, ...]] = Counter()
    route = flight_module._route

    def counted(flight_input, kind, start, goal):
        searches[tuple(goal)] += 1
        return route(flight_input, kind, start, goal)

    monkeypatch.setattr(flight_module, "_route", counted)
    state_at(flight, EPISODE - 1)
    homes = {tuple(flight.column(f.home_perch_id, f.kind).approach_mm) for f in flight.flyers}
    assert set(searches) == homes
    assert set(searches.values()) == {ROUTE_SEARCHES}
    # The same episode unbounded: the counts the route_searches parameter's reason quotes.
    searches.clear()
    monkeypatch.setattr(flight_module, "_ROUTE_SEARCHES", 10**6)
    state_at(flight, EPISODE - 1)
    assert sorted(searches.values()) == [32, 35, 61]


def test_a_search_ends_with_no_route_once_it_has_settled_route_cells_cells(monkeypatch):
    """A route among the crowded crowns: found when a search may settle the cells it needs, and
    not found when it may settle one fewer."""
    flight = seeded(crowded_flight(), DEVELOPMENT_SEEDS[4])
    flyer = flight.flyers[0]
    kind = flight.kinds[flyer.kind]
    goal = flight.column(flyer.home_perch_id, flyer.kind).approach_mm
    volume = flight.volume
    start = (volume.min_x_mm + 1_250, volume.ground_mm + 6_250, volume.max_z_mm - 1_250)
    route = flight_module._route(flight, kind, start, goal)
    assert route

    def found(cells: int) -> bool:
        monkeypatch.setattr(flight_module, "_ROUTE_CELLS", cells)
        return flight_module._route(flight, kind, start, goal) == route

    # The fewest cells that find it: a search allowed more finds it, one allowed fewer does not.
    low, high = 1, ROUTE_CELLS
    assert found(high)
    while low < high:
        middle = (low + high) // 2
        low, high = (low, middle) if found(middle) else (middle + 1, high)
    assert low > 1 and found(low)
    monkeypatch.setattr(flight_module, "_ROUTE_CELLS", low - 1)
    assert flight_module._route(flight, kind, start, goal) is None


def test_a_search_for_a_sealed_goal_on_the_largest_grid_settles_route_cells_and_stops(monkeypatch):
    """The largest grid the module admits, with a goal sealed inside a box of parts: a search
    finds no route once it has settled the bounded number of cells; unbounded, it settles the
    whole band first."""
    half = 26_000
    volume = AirVolume("declared", -half, half, -half, half, 0, 12_000, 500)
    nx, ny, nz = volume.shape
    assert nx * ny * nz <= FLIGHT_MODULE.value("max_cells")
    at = Placement(20_250, 5_000, 20_250, 0, 1000)
    walls = (
        PartBox(-1_500, 1_500, -1_500, 1_500, 0, 400),
        PartBox(-1_500, 1_500, -1_500, 1_500, 2_200, 2_600),
        PartBox(-1_500, -1_100, -1_500, 1_500, 0, 2_600),
        PartBox(1_100, 1_500, -1_500, 1_500, 0, 2_600),
        PartBox(-1_500, 1_500, -1_500, -1_100, 0, 2_600),
        PartBox(-1_500, 1_500, 1_100, 1_500, 0, 2_600),
    )
    solids = [Solid("box", wall, at) for wall in walls]
    occupancy = build_occupancy(volume, solids, clearance_mm=140)
    goal = (20_250, 6_250, 20_250)
    assert not occupancy.is_solid(volume.cell_of(goal))
    flight = replace(square_flight(), volume=volume, occupancy=occupancy)
    kind = next(iter(flight.kinds.values()))
    taken = _taken(monkeypatch)
    far = (-20_000, 6_250, -20_000)
    assert flight_module._route(flight, kind, far, goal) is None
    monkeypatch.setattr(flight_module, "_ROUTE_CELLS", nx * ny * nz)
    assert flight_module._route(flight, kind, far, goal) is None
    bounded, unbounded = taken
    assert bounded <= 6 * ROUTE_CELLS + 1 < unbounded
