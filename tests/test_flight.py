"""Flight: bounds and solids over every seed run, choices refused by name, exact replay.

The worlds are composed as the flight route composes them (``flight_support``). The checker
(``exulanica.movement.flight_checks``) reads only what a renderer is handed, and asks the exact
question the step's guard answers conservatively; its positive controls come first, so a check that
could pass by finding nothing is shown to find something.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import itertools
import threading

import pytest
from exulanica.canonical import canonical_json
from exulanica.movement import flight as flight_module
from exulanica.movement.air import _solid_bounds, build_occupancy, segment_meets_cell
from exulanica.movement.fixed import ONE, ceil_div, turn
from exulanica.movement.flight import (
    FLIGHT_MODULE,
    FlightRefused,
    advance_flight,
    allowed_choices,
    flight_input,
    flight_window,
    genesis,
    state_at,
    validate_choice,
)
from exulanica.movement.flight_checks import check_window
from exulanica.movement.registry import MovementModuleNotConnected
from exulanica.world import flight_input as composer
from exulanica.world.flight_input import cached_input, served_window
from scripts.measure_flight_bounds import _placed, compose

from flight_support import (
    DEVELOPMENT_SEEDS,
    check_windows,
    cluttered_flight,
    crowded_flight,
    seeded,
    square_flight,
    square_objects,
    trees_flight,
)

EPISODE = FLIGHT_MODULE.value("episode_steps")
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")


def _episode(flight):
    """Every window of one whole episode, from its first step."""
    return [flight_window(flight, start, WINDOW) for start in range(0, EPISODE, WINDOW)]


def _digest(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


# -- the checker finds what is there ----------------------------------------------------------


def _solid_centre(flight):
    """The centre of some solid cell that is no perch's own, and the cell."""
    own = {cell for perch in flight.perches for c in perch.columns.values() for cell in c.own_cells}
    nx, ny, nz = flight.volume.shape
    for ix in range(nx):
        for iy in range(ny):
            for iz in range(nz):
                cell = (ix, iy, iz)
                if flight.occupancy.is_solid(cell) and cell not in own:
                    low, high = flight.volume.cell_bounds(cell)
                    return [(a + b) // 2 for a, b in zip(low, high, strict=True)], cell
    raise AssertionError("the world has no solid cell")


def _flying_sample(window):
    """The first flyer and step at which it is flying, and not at a window edge."""
    flying = window["states"].index("flying")
    for row in window["flyers"]:
        for index in range(1, len(row["state"]) - 1):
            if row["state"][index] == flying and row["state"][index + 1] == flying:
                return row, index
    raise AssertionError("nobody flies in this window")


def test_the_checker_finds_a_flyer_placed_in_a_solid_cell():
    """Positive control: a served position moved into a crown is found, with the rule named."""
    flight = square_flight()
    window = flight_window(flight, 0, WINDOW)
    assert check_window(flight, window).violations == []
    planted = copy.deepcopy(window)
    row, index = _flying_sample(planted)
    centre, _cell = _solid_centre(flight)
    row["position_mm"][3 * index : 3 * index + 3] = centre
    rules = {v["rule"] for v in check_window(flight, planted).violations}
    assert "entered_solid_cell" in rules


def test_the_checker_finds_a_jump_and_a_flyer_out_of_its_band():
    flight = square_flight()
    planted = copy.deepcopy(flight_window(flight, 0, WINDOW))
    row, index = _flying_sample(planted)
    x, _y, z = row["position_mm"][3 * index : 3 * index + 3]
    row["position_mm"][3 * index : 3 * index + 3] = [x, flight.volume.ground_mm + 1_000, z]
    rules = {v["rule"] for v in check_window(flight, planted).violations}
    assert {"out_of_bounds", "moved_too_far"} <= rules


def test_the_exact_segment_test_keeps_a_cell_half_open():
    flight = square_flight()
    volume = flight.volume
    cell = (10, 10, 10)
    low, high = volume.cell_bounds(cell)
    inside = [(a + b) // 2 for a, b in zip(low, high, strict=True)]
    beside = [high[0] + 10, inside[1], inside[2]]
    # A segment ending exactly on the cell's low face touches it; one ending on its high face
    # does not, because the face belongs to the next cell.
    assert segment_meets_cell(volume, [low[0] - 100, inside[1], inside[2]], low, cell)
    assert not segment_meets_cell(volume, beside, [high[0], inside[1], inside[2]], cell)
    assert segment_meets_cell(volume, beside, inside, cell)
    # Crossing the cell's high edge diagonally touches only the edge's points, which belong to
    # the neighbouring cells, so the segment never lies in this one.
    assert not segment_meets_cell(
        volume,
        [high[0] - 100, high[1] + 100, inside[2]],
        [high[0] + 100, high[1] - 100, inside[2]],
        cell,
    )


def test_the_move_that_joins_two_windows_is_checked_too():
    """A window's first step ends the move from the last window's last step; only a join sees it."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[0])
    windows = copy.deepcopy(_episode(flight)[:2])
    assert check_windows(flight, windows).violations == []
    first = windows[1]["from_step"]
    windows[1]["flyers"][0]["position_mm"][0] += 5_000

    def too_far(check):
        return {v["step"] for v in check.violations if v["rule"] == "moved_too_far"}

    assert first not in too_far(check_window(flight, windows[1]))
    assert first in too_far(check_window(flight, windows[1], before=windows[0]))
    assert first in too_far(check_windows(flight, windows))


def _last_window_of_episode(flight):
    """The window holding episode 0's last step, and the next episode's first window."""
    return flight_window(flight, EPISODE - WINDOW, WINDOW), flight_window(flight, EPISODE, WINDOW)


def test_the_checker_finds_a_flyer_not_home_when_its_episode_ends():
    """Positive control: a flyer moved off its perch at an episode's last step is named late, the
    window is named for not saying so, and its jump home into the next episode is a move."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[1])
    last, following = _last_window_of_episode(flight)
    assert check_windows(flight, [last, following]).violations == []
    planted = copy.deepcopy(last)
    row = planted["flyers"][0]
    end = 3 * (WINDOW - 1)
    home = list(row["position_mm"][end : end + 3])
    # Two metres to the side of home and a metre up, flying: its way home crosses the crown.
    row["position_mm"][end : end + 3] = [home[0] + 2_000, home[1] + 1_000, home[2]]
    row["state"][WINDOW - 1] = planted["states"].index("flying")
    alone = check_window(flight, planted)
    assert alone.late_home == 1
    rules = {v["rule"] for v in alone.violations}
    assert {"not_home_at_episode_end", "late_home_misreported"} <= rules
    into = {v["rule"] for v in check_window(flight, following, before=planted).violations}
    assert {"moved_too_far", "entered_solid_cell"} <= into


def test_the_checker_derives_a_perch_s_own_cells_from_its_object():
    """Positive control: a column whose own cells were forged to include another object's cells
    still lets no landing through them, because the checker reads the cells from the parts."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[2])
    windows = _episode(flight)[:1]
    lamp_solid = next(s for s in flight.solids if "lamp" in s.object_id)
    low, high = _solid_bounds(lamp_solid)
    lamp_cell = flight.volume.cell_of(
        ((low[0] + high[0]) // 2, high[1] - 1, (low[2] + high[2]) // 2)
    )
    above = (lamp_cell[0], lamp_cell[1] + 1, lamp_cell[2])
    assert flight.occupancy.is_solid(lamp_cell)
    # A flyer standing over the lamp's cell, as if on a perch of the square's tree whose column
    # the forged input says runs through it.
    home = flight.perch_index[flight.flyers[0].home_perch_id]
    column = home.columns[flight.flyers[0].kind]
    bottom = flight.volume.cell_bounds(lamp_cell)[0]
    forged_column = dataclasses.replace(
        column,
        approach_mm=(bottom[0] + 250, bottom[1] + 1_250, bottom[2] + 250),
        own_cells=(*column.own_cells, lamp_cell, above),
    )
    forged_home = dataclasses.replace(
        home,
        point_mm=(bottom[0] + 250, bottom[1] + 250, bottom[2] + 250),
        columns={flight.flyers[0].kind: forged_column},
    )
    forged = dataclasses.replace(
        flight,
        perches=tuple(forged_home if p.perch_id == home.perch_id else p for p in flight.perches),
    )
    planted = copy.deepcopy(windows[0])
    row = planted["flyers"][0]
    landing = planted["states"].index("landing")
    for index, height in enumerate((1_250, 750, 250)):
        row["position_mm"][3 * index : 3 * index + 3] = [
            bottom[0] + 250,
            bottom[1] + height,
            bottom[2] + 250,
        ]
        row["state"][index] = landing
    entered = {
        violation["step"]
        for violation in check_window(forged, planted).violations
        if violation["rule"] == "entered_solid_cell"
    }
    # The move into the lamp's own cell, not the teleport back to the tree after it.
    assert planted["from_step"] + 2 in entered


def test_the_checker_finds_a_body_touching_a_part():
    """Positive control: a flying flyer a hand's width from a crown's side, its point clear of
    every part but its body not, is found."""
    flight = square_flight()
    window = copy.deepcopy(flight_window(flight, 0, WINDOW))
    crown = max(
        (s for s in flight.solids if "tree" in s.object_id), key=lambda s: _solid_bounds(s)[1][1]
    )
    low, high = _solid_bounds(crown)
    half = ceil_div(flight.kinds[flight.flyers[0].kind].body_span_mm, 2)
    point = [high[0] + half // 2, (low[1] + high[1]) // 2, (low[2] + high[2]) // 2]
    row, index = _flying_sample(window)
    row["position_mm"][3 * index : 3 * index + 3] = point
    row["position_mm"][3 * index + 3 : 3 * index + 6] = point
    rules = {v["rule"] for v in check_window(flight, window).violations}
    assert "body_meets_solid" in rules


# -- bounds and solids over every seed run ------------------------------------------------------


@pytest.mark.parametrize("index", range(3), ids=[f"development_seed_{i}" for i in range(3)])
def test_no_flyer_leaves_its_bounds_or_enters_a_solid_cell_in_the_small_square(index):
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[index])
    assert len(flight.flyers) == 3
    check = check_windows(flight, _episode(flight))
    assert (check.violations, check.late_home) == ([], 0)
    assert set(check.states) == set(flight_module.STATES), "every state is reached, or it is thin"


def test_no_flyer_leaves_its_bounds_or_enters_a_solid_cell_among_eight_trees():
    flight = seeded(trees_flight(), DEVELOPMENT_SEEDS[3])
    assert len(flight.flyers) == FLIGHT_MODULE.value("max_flyers")
    check = check_windows(flight, _episode(flight))
    assert (check.violations, check.late_home) == ([], 0)


def test_every_flyer_is_home_when_every_episode_ends_among_crowded_crowns():
    """Going home finds a way over free cells: no flyer is late where the crowns crowd the band."""
    for seed in DEVELOPMENT_SEEDS[:2]:
        flight = seeded(crowded_flight(), seed)
        windows = [
            flight_window(flight, start, WINDOW) for start in range(0, 2 * EPISODE + 1, WINDOW)
        ]
        check = check_windows(flight, windows)
        assert check.episode_ends == 2 * len(flight.flyers)
        assert (check.late_home, check.violations) == (0, [])


def test_the_cluttered_world_starts_24_birds_and_keeps_them_clear():
    flight = seeded(cluttered_flight(), DEVELOPMENT_SEEDS[8])
    assert len(flight.flyers) == FLIGHT_MODULE.value("max_flyers") and not flight.unplaced
    check = check_windows(flight, [*_episode(flight), flight_window(flight, EPISODE, WINDOW)])
    assert (check.late_home, check.violations) == (0, [])


def test_a_flyer_whose_home_is_just_under_the_band_s_top_gets_home():
    """Development seed 5 among the crowded crowns once left a flyer circling a hand's width under
    its home's approach point, near the band's top and the volume's side, until its episode ended:
    containment turned it back from the top, and avoidance probed past its target into the band's
    top. Heading to a perch, neither holds it back now, and it is home when the episode ends."""
    flight = seeded(crowded_flight(), DEVELOPMENT_SEEDS[5])
    state = state_at(flight, 2 * EPISODE - 1)
    homes = {f.ordinal: flight.perch_index[f.home_perch_id].point_mm for f in flight.flyers}
    away = [
        row["flyer_id"]
        for row in state["flyers"]
        if row["state"] != "perching" or tuple(row["position_mm"]) != homes[row["ordinal"]]
    ]
    assert away == []


def test_a_window_names_every_flyer_not_home_at_an_episode_s_last_step(monkeypatch):
    """Break homing: nobody goes home. Every window holding the last step names each of them."""
    monkeypatch.setattr(flight_module, "_go_home", lambda flight, flyer_state: None)
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[3])
    last, following = _last_window_of_episode(flight)
    late = {row["flyer_id"] for row in last["late_home"]}
    assert late and {row["step"] for row in last["late_home"]} == {EPISODE - 1}
    ending = flight_window(flight, EPISODE - 1, 2)
    assert {row["flyer_id"] for row in ending["late_home"]} == late
    assert following["late_home"] == []


def test_a_route_home_runs_over_free_cells_of_the_band():
    flight = seeded(crowded_flight(), DEVELOPMENT_SEEDS[4])
    flyer = flight.flyers[0]
    kind = flight.kinds[flyer.kind]
    goal = flight.column(flyer.home_perch_id, flyer.kind).approach_mm
    volume = flight.volume
    start = (volume.min_x_mm + 1_250, volume.ground_mm + 6_250, volume.max_z_mm - 1_250)
    route = flight_module._route(flight, kind, start, goal)
    assert route and route == flight_module._route(flight, kind, start, goal)
    first, last = flight_module._band_rows(flight, kind)
    cells = [volume.cell_of(start), *(volume.cell_of(point) for point in route)]
    assert cells[-1] == volume.cell_of(goal)
    for before, after in itertools.pairwise(cells):
        assert sum(abs(a - b) for a, b in zip(before, after, strict=True)) == 1
        assert not flight.occupancy.is_solid(after)
    assert all(first <= cell[1] <= last for cell in cells[1:-1])

    flight = seeded(crowded_flight(), DEVELOPMENT_SEEDS[7])
    check = check_windows(flight, _episode(flight))
    assert (check.violations, check.late_home) == ([], 0)
    assert check.guard_holds > 0, "the crowns never came in a flyer's way, so this tests nothing"


def test_the_guard_keeps_a_flyer_out_whatever_steering_proposes(monkeypatch):
    """Break steering: every flyer flies straight at a crown. The guard alone keeps it out."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[4])
    centre, _cell = _solid_centre(flight)

    def into_the_crown(flight_input, kind, flyer_state, step):
        position = tuple(flyer_state["position_mm"])
        offset = tuple(c - p for c, p in zip(centre, position, strict=True))
        return flight_module.scale_to(offset, kind.max_speed_mm_s), False

    monkeypatch.setattr(flight_module, "_desired", into_the_crown)
    check = check_windows(flight, _episode(flight)[:3])
    assert check.violations == []
    assert check.guard_holds > 0, "steering pointed into a solid and the guard never had to act"


# -- episodes ------------------------------------------------------------------------------------


def test_every_episode_starts_with_every_flyer_perching_at_home():
    flight = square_flight()
    for episode in (0, 1, 7):
        state = genesis(flight, episode)
        assert state["step"] == episode * EPISODE
        for row, flyer in zip(state["flyers"], flight.flyers, strict=True):
            home = flight.perch_index[flyer.home_perch_id]
            assert (row["state"], row["position_mm"]) == ("perching", list(home.point_mm))


def test_every_flyer_is_home_when_its_episode_ends():
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[5])
    last = state_at(flight, EPISODE - 1)
    homes = {flyer.flyer_id: flyer.home_perch_id for flyer in flight.flyers}
    assert all(
        (row["state"], row["perch_id"]) == ("perching", homes[row["flyer_id"]])
        for row in last["flyers"]
    )
    # So the step into the next episode, its genesis, moves nobody.
    following = advance_flight(flight, last)
    assert following == genesis(flight, 1)
    assert [r["position_mm"] for r in following["flyers"]] == [
        r["position_mm"] for r in last["flyers"]
    ]


# -- exact replay and bounded requests ---------------------------------------------------------

#: The small square's first flight episode, served in five windows, as its canonical digest. Pinned
#: from the module as it is: a change to the step, its figures or the square moves it.
SQUARE_EPISODE_SHA256 = "9c605c6246d573269a79c96eadae0a25c5b42f9591502e2331777740021361bc"


def test_a_flight_replays_exactly():
    flight = square_flight()
    first = [_digest(window) for window in _episode(flight)]
    assert first == [_digest(window) for window in _episode(flight)]
    assert _digest(first) == SQUARE_EPISODE_SHA256


def test_a_window_resumed_from_the_last_one_is_the_window_computed_cold():
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[6])
    resumed = [served_window(flight, start, WINDOW) for start in range(0, 2 * WINDOW, WINDOW)]
    cold = [flight_window(flight, start, WINDOW) for start in range(0, 2 * WINDOW, WINDOW)]
    assert resumed == cold


@pytest.mark.parametrize(
    ("from_step", "steps", "code"),
    [
        (0, WINDOW + 1, "flight_window_too_long"),
        (0, 0, "flight_window_too_long"),
        (-1, 10, "flight_step_out_of_range"),
        (FLIGHT_MODULE.value("max_from_step") + 1, 10, "flight_step_out_of_range"),
    ],
    ids=["too_many_steps", "no_steps", "before_the_start", "past_the_last_step"],
)
def test_a_window_beyond_the_module_bounds_is_refused_by_name(from_step, steps, code):
    with pytest.raises(FlightRefused) as refused:
        flight_window(square_flight(), from_step, steps)
    assert refused.value.code == code


def test_served_windows_are_shared_safely_between_request_threads():
    """Many threads asking for windows at once never break the shared resume states, and every
    window they are served is the one computed cold."""
    flight = seeded(square_flight(), DEVELOPMENT_SEEDS[5])
    cold = {start: flight_window(flight, start, WINDOW) for start in range(0, 4 * WINDOW, WINDOW)}
    failures: list[BaseException] = []
    served: list[tuple[int, dict]] = []

    def ask(offset: int) -> None:
        try:
            for round_ in range(6):
                start = ((offset + round_) % 4) * WINDOW
                served.append((start, served_window(flight, start, WINDOW)))
        except BaseException as error:
            failures.append(error)

    threads = [threading.Thread(target=ask, args=(offset,)) for offset in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert failures == []
    assert all(window == cold[start] for start, window in served)


def test_a_world_s_input_is_composed_once_for_each_state():
    made = []

    def make(name):
        def compose_it():
            made.append(name)
            return square_flight()

        return compose_it

    key = ("test", "a version", "a state")
    assert cached_input(key, make("first")) is cached_input(key, make("second"))
    assert made == ["first"]
    cached_input((*key[:2], "another state"), make("third"))
    assert made == ["first", "third"]


@pytest.mark.parametrize(
    ("bound", "limit"),
    [("_MAX_PARTS", 10), ("_MAX_CELLS", 1_000)],
    ids=["too_many_parts", "too_many_cells"],
)
def test_a_world_too_large_to_fly_over_is_refused_by_name(monkeypatch, bound, limit):
    monkeypatch.setattr(composer, bound, limit)
    with pytest.raises(FlightRefused) as refused:
        compose("small_square")
    assert refused.value.code == "flight_world_too_large"


def test_the_air_is_grown_by_half_the_widest_span_and_an_input_that_is_not_is_refused():
    square = square_flight()
    span = max(kind.body_span_mm for kind in square.kinds.values())
    assert square.clearance_mm == square.occupancy.clearance_mm == ceil_div(span, 2)
    bare = build_occupancy(square.volume, square.solids)
    with pytest.raises(FlightRefused) as refused:
        flight_input(
            world_id=square.world_id,
            version_id=square.version_id,
            seed=square.seed,
            occupancy=bare,
            perches=square.perches,
            kinds=square.kinds,
            flyers=square.flyers,
            solids=square.solids,
        )
    assert refused.value.code == "invalid_flight_input"


def test_a_perch_whose_column_another_object_crosses_is_refused():
    """A lamp post turned so its head hangs over a tree's crown takes that perch from its birds."""
    import uuid

    from exulanica.world.authored_delta import AlternateVersion, delta_sha256
    from exulanica.world.flight_input import compose_flight_input
    from scripts.measure_flight_bounds import (
        VERSION_ID,
        WORLD_ID,
        _assets,
        ground,
    )

    tree = _placed("tree", "cc0.planter-tree", 0, 0, 0, 1000)
    # The lamp's head is 1,275 mm out along its arm; turned half a turn from 1,275 mm east, the
    # head stands over the tree's top.
    lamp = _placed("lamp", "cc0.lamp-post", 1_275, 0, 3_141_593, 1000)
    objects = (lamp, tree)
    version = AlternateVersion(
        version_id=VERSION_ID,
        world_id=WORLD_ID,
        source_snapshot_id=uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/lamp"),
        parent_version_id=None,
        title="lamp over a tree",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=objects, element_overrides=(), environment_instances=(), point_map_instances=()
        ),
        edit_seq=2,
        source_invalidated=False,
        created_by=uuid.UUID(int=1),
        created_at="2026-09-25T00:00:00+00:00",
        objects=objects,
    )
    keys = {digest: key for key, digest in _assets().items()}
    flight = compose_flight_input(
        world_id=WORLD_ID, version=version, ground=ground(), asset_keys=keys
    )
    top = next(p for p in flight.perches if p.perch_id == "tree:perch:0")
    assert top.refused == {"small_bird": "perch_approach_blocked"}
    # The lamp's head stands in cells the tree's crown touches too, so its perch is lost as well:
    # a column is its own object's alone.
    head = next(p for p in flight.perches if p.object_id == "lamp")
    assert head.refused == {"small_bird": "perch_approach_blocked"}
    # Apart, each keeps its perches.
    apart = compose("small_square")
    assert any(p.columns for p in apart.perches if "lamp" in p.object_id)


def test_the_flight_row_is_a_switch_asked_where_a_flight_is_made_or_served(monkeypatch):
    flight = square_flight()

    def switched_off(name):
        raise MovementModuleNotConnected(name, "flight_not_connected")

    monkeypatch.setattr(flight_module, "built_module", switched_off)
    with pytest.raises(MovementModuleNotConnected) as refused:
        flight_window(flight, 0, 1)
    assert refused.value.code == "flight_not_connected"
    with pytest.raises(MovementModuleNotConnected):
        seeded(flight, DEVELOPMENT_SEEDS[0])


@pytest.mark.parametrize("before_the_last", [0, 1], ids=["last_step", "step_before_the_last"])
def test_the_latest_steps_cost_no_more_than_one_episode(monkeypatch, before_the_last):
    """A request at the largest steps a page may ask for computes from its own episode's
    genesis: the steps it advances are the step's place in its episode, never more."""
    calls = []
    original = flight_module.advance_flight

    def counted(flight_input, state):
        calls.append(state["step"])
        return original(flight_input, state)

    monkeypatch.setattr(flight_module, "advance_flight", counted)
    step = FLIGHT_MODULE.value("max_from_step") - before_the_last
    flight_window(square_flight(), step, 1)
    assert len(calls) == step % EPISODE < EPISODE


# -- choices are refused by name, as a person's are ---------------------------------------------


def _deciding(flight):
    """A state in which flyer 0 has just finished its perch and chooses."""
    state = genesis(flight, 0)
    state["flyers"][0]["timer_steps"] = 0
    return state


def test_a_perch_on_an_undeclared_surface_is_refused():
    """A bench declares no perch, and a tree declares five: neither a bench nor a sixth is one."""
    flight = square_flight()
    state = _deciding(flight)
    flyer = flight.flyers[0].flyer_id
    bench = next(obj.object_id for obj in square_objects() if obj.object_id.endswith("bench"))
    tree = next(obj.object_id for obj in square_objects() if obj.object_id.endswith("tree"))
    assert not any(perch.object_id == bench for perch in flight.perches)
    for undeclared in (f"{bench}:perch:0", f"{tree}:perch:5", "the lamp's arm"):
        proposal = {"kind": "perch", "perch_id": undeclared}
        assert validate_choice(flight, state, flyer, proposal) == "perch_not_declared"


def test_a_choice_is_refused_by_name_unless_it_is_one_the_flyer_may_make():
    flight = square_flight()
    state = _deciding(flight)
    flyer = flight.flyers[0]
    others = {row["perch_id"] for row in state["flyers"][1:]}
    taken = next(iter(others))
    free = [c for c in allowed_choices(flight, state, state["flyers"][0]) if c["kind"] == "perch"]
    assert free and all(c["perch_id"] not in others for c in free)
    assert validate_choice(flight, state, flyer.flyer_id, free[0]) is None
    assert validate_choice(flight, state, flyer.flyer_id, {"kind": "roam"}) is None
    refusals = {
        "perch_taken": {"kind": "perch", "perch_id": taken},
        "already_here": {"kind": "perch", "perch_id": flyer.home_perch_id},
        "unsupported_proposal": {"kind": "land_on_a_person"},
        "invalid_proposal_fields": {"kind": "perch", "perch_id": free[0]["perch_id"], "x": 1},
    }
    for reason, proposal in refusals.items():
        assert validate_choice(flight, state, flyer.flyer_id, proposal) == reason
    busy = genesis(flight, 0)
    assert validate_choice(flight, busy, flyer.flyer_id, free[0]) == "action_in_progress"
    assert validate_choice(flight, state, "nobody", free[0]) == "unknown_flyer"


def test_a_perch_a_kind_cannot_use_is_refused_with_its_reason():
    square = square_flight()
    lamp = next(p for p in square.perches if p.span_mm < 600)
    kind = square.flyers[0].kind
    narrow = dataclasses.replace(lamp, columns={}, refused={kind: "perch_too_narrow"})
    flight = flight_input(
        world_id=square.world_id,
        version_id=square.version_id,
        seed=square.seed,
        occupancy=square.occupancy,
        perches=[narrow if p.perch_id == lamp.perch_id else p for p in square.perches],
        kinds=square.kinds,
        flyers=square.flyers,
        solids=square.solids,
    )
    state = _deciding(flight)
    proposal = {"kind": "perch", "perch_id": lamp.perch_id}
    assert validate_choice(flight, state, square.flyers[0].flyer_id, proposal) == (
        "perch_too_narrow"
    )
    assert proposal not in allowed_choices(flight, state, state["flyers"][0])


# -- integer turns ------------------------------------------------------------------------------


def test_an_integer_turn_is_the_true_turn_within_its_stated_bound():
    import math

    for microradians in (0, 1, 785_398, 1_570_796, 3_141_593, 4_712_389, 6_283_185, 12_345):
        cosine, sine = turn(microradians)
        assert abs(cosine / ONE - math.cos(microradians / 1e6)) < 2**-30
        assert abs(sine / ONE - math.sin(microradians / 1e6)) < 2**-30
