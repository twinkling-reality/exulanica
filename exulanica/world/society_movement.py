"""How a planned society's people move in a minute, by the movement modules it recorded.

A society the purposeful planner moves (:mod:`exulanica.world.society_planner`) moves its people
for its whole life by the movement modules its first input recorded (``movement_modules``): the
first walking where it recorded none, its second version, which paces each body
(:mod:`exulanica.movement.walking_v2`), and, in a society of things recorded since it was built,
swimming (:mod:`exulanica.movement.swimming`). This module answers, for one state:

* how each walker is paced and what one tick lets it spend (:func:`walker_paces`,
  :func:`tick_budgets`, :func:`own_walk_budgets`);
* and, for one input, who swims and how each person moves over it (:class:`Movers`). A being swims
  where its society records a swimming, its input states water
  (:mod:`exulanica.world.society_water`) and its kind's moves name a swimming: it is read against
  the walking graph and the water together, takes the quickest route over both and crosses it a
  stretch at a time (:func:`exulanica.movement.swimming.crossing`), walking the land by the walking
  its society records. Everybody else is read, routed and moved over the walking graph alone, as
  before, and a society that records no swimming reads no water at all.

Pure: no connection and no store.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from typing import Any, Final

from exulanica.movement.registry import movement_kind, recorded_movement
from exulanica.movement.steps import step_of
from exulanica.movement.swimming import PACE_PARAMETER as SWIM_PACE
from exulanica.movement.swimming import crossing, quickest_routes
from exulanica.movement.walking import Leg
from exulanica.world.society_thing_inputs import MOVEMENT_MODULES_FIELD
from exulanica.world.society_water import WATER_FIELD

__all__ = ["Movers", "own_walk_budgets", "tick_budgets", "walker_paces"]

#: The pace a society's walking spends its whole budget at, where it paces nobody.
_OWN_PACE: Final = 1000

Graph = tuple[dict[str, Any], dict[str, Any], dict[frozenset[str], Any]]


def walker_paces(state: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], int] | None:
    """How a society's walkers are paced. None where its minutes run the first walking, which
    spends one budget for everybody: every society whose first input recorded no movement module.
    Where it recorded a walking that declares a pace, what answers each walker's own, in
    thousandths of the society's: the one its kind states with the walking it moves by, or the
    module's reference pace where its kind states none or it states no kind. A kind is read once
    a call, from the run forms the state keeps."""
    from exulanica.movement.walking_v2 import PACE_PARAMETER

    row = recorded_movement(state.get(MOVEMENT_MODULES_FIELD), "walking")
    if row is None or PACE_PARAMETER not in row.parameters:
        return None
    from exulanica.world.society_kinds import pace_permille_of

    reference = row.value("reference_pace_permille")
    held: dict[tuple[object, object], int] = {}

    def pace(person: Mapping[str, Any]) -> int:
        kind = person.get("kind")
        if kind is None:
            return reference
        key = (kind.get("source"), kind["sha256"])
        if key not in held:
            stated = pace_permille_of(state, kind)
            held[key] = reference if stated is None else stated
        return held[key]

    return pace


def tick_budgets(state: Mapping[str, Any]) -> Callable[[Mapping[str, Any]], int]:
    """What each walker of a society may spend along its route in one tick, in millimetres: the
    budget its state records, for everybody where its minutes run the first walking, and scaled
    by the walker's own pace where they run one that declares it (:func:`walker_paces`)."""
    budget = state["movement_budget_mm_per_tick"]
    pace = walker_paces(state)
    if pace is None:
        return lambda person: budget
    from exulanica.movement.walking_v2 import own_budget_mm

    return lambda person: own_budget_mm(budget, pace(person))


def own_walk_budgets(state: Mapping[str, Any]) -> dict[str, int]:
    """Each inhabitant whose kind states its own pace, by id: what one tick lets it walk, in
    millimetres (:func:`tick_budgets`). Empty where the society's walking paces nobody or records
    no budget. A served projection beside the state, never part of it: a page walks such a body
    at this budget, and everyone not named here walks the budget the state records."""
    if "movement_budget_mm_per_tick" not in state or walker_paces(state) is None:
        return {}
    from exulanica.world.society_kinds import pace_permille_of

    budget = tick_budgets(state)
    return {
        str(person["id"]): budget(person)
        for person in state.get("inhabitants", ())
        if person.get("kind") is not None and pace_permille_of(state, person["kind"]) is not None
    }


def _with_water(document: Mapping[str, Any], graph: Graph) -> tuple[Graph, frozenset[str]]:
    """The input's walking graph with its water joined to it, keyed as the planner walks a graph,
    and the edges of the water by id: what a swimmer is read against and moves over."""
    nodes, adjacent, edges = graph
    water = document[WATER_FIELD]
    wet_nodes = {node["node_id"]: node for node in water["nodes"]}
    joined = {node: list(values) for node, values in adjacent.items()}
    joined.update((node, []) for node in wet_nodes)
    every_edge = dict(edges)
    for edge in water["edges"]:
        a, b = edge["from_node_id"], edge["to_node_id"]
        joined[a].append((b, edge))
        joined[b].append((a, edge))
        every_edge[frozenset((a, b))] = edge
    for values in joined.values():
        values.sort(key=lambda pair: pair[0])
    wet = frozenset(edge["edge_id"] for edge in water["edges"])
    return ({**nodes, **wet_nodes}, joined, every_edge), wet


class Movers:
    """How each person moves over one input in a minute: the graph each is read against, the
    routes each takes and the legs of each one's minute.

    ``graph`` is the input's walking graph as the planner reads it (its nodes, neighbours and
    edges). A swimmer (:meth:`swim_pace`) is read against the walking graph and the input's water
    together, routed over both by the quickest way and moved by
    :func:`~exulanica.movement.swimming.crossing`; anybody else is read, routed and moved over the
    walking graph alone, by exactly what the planner always called. The joined graph and a
    swimmer's routes are built once each, for the minute this is made in.
    """

    def __init__(self, state: Mapping[str, Any], document: Mapping[str, Any], graph: Graph) -> None:
        self._state = state
        self.nodes, self.adjacent, self.edges = graph
        self._row = recorded_movement(state.get(MOVEMENT_MODULES_FIELD), "swimming")
        self._swims: dict[tuple[object, ...], int | None] = {}
        self._routes: dict[tuple[str, int, int], dict[str, tuple[int, tuple[str, ...]]]] = {}
        self._paces = walker_paces(state)
        self._joined: Graph | None = None
        self._wet: frozenset[str] = frozenset()
        if self._row is not None and WATER_FIELD in document:
            self._joined, self._wet = _with_water(document, graph)
        #: The nodes and edges anybody is read against where who stands and is headed where is
        #: asked: the walking graph's and the water's, which no walker ever stands in.
        self.whole = (
            (self.nodes, self.edges) if self._joined is None else (self._joined[0], self._joined[2])
        )

    def swim_pace(self, person: Mapping[str, Any]) -> int | None:
        """A swimmer's pace in water, in thousandths of the society's: the one its kind states
        with the swimming it moves by, else the reference pace of the swimming its society
        records; None for anybody who does not swim here. A kind is read once a minute."""
        reference = person.get("kind")
        if self._joined is None or reference is None:
            return None
        key = tuple(reference.get(name) for name in ("source", "kind", "version", "sha256"))
        if key not in self._swims:
            self._swims[key] = self._pace_of(reference)
        return self._swims[key]

    def _pace_of(self, reference: Mapping[str, Any]) -> int | None:
        from exulanica.world.society_kinds import kind_here

        assert self._row is not None
        for move in kind_here(self._state, reference).document["moves"]:
            module = move if isinstance(move, str) else move["module"]
            if movement_kind(module) == "swimming":
                stated = {} if isinstance(move, str) else move.get("parameters", {})
                return int(stated.get(SWIM_PACE, self._row.value("reference_pace_permille")))
        return None

    def __call__(self, person: Mapping[str, Any]) -> tuple[dict[str, Any], dict[Any, Any]]:
        """The nodes and edges ``person`` is read against: the walking graph's, and the water's
        too for a swimmer."""
        return self.whole if self.swim_pace(person) is not None else (self.nodes, self.edges)

    def routes(
        self, person: Mapping[str, Any], start: str, walked: Callable[[str], dict]
    ) -> dict[str, tuple[int, tuple[str, ...]]]:
        """The routes ``person`` may take from ``start``: ``walked``'s, the walking graph's, for
        anybody who does not swim; for a swimmer the quickest over land and water, its costs in
        units of time rather than millimetres, and none from a node neither graph has."""
        swim = self.swim_pace(person)
        if swim is None or self._joined is None:
            return walked(start)
        walk = _OWN_PACE if self._paces is None else self._paces(person)
        key = (start, walk, swim)
        if key not in self._routes:
            adjacent = self._joined[1]
            self._routes[key] = (
                quickest_routes(start, adjacent, self._wet, walk, swim) if start in adjacent else {}
            )
        return self._routes[key]

    def legs(
        self,
        person: Mapping[str, Any],
        route: dict[str, Any],
        walk: Callable[..., Iterator[Leg]],
        figures: tuple[int, ...],
    ) -> Iterator[Leg]:
        """One minute of ``person`` along ``route``: ``walk``, the walking step the society
        records, handed ``figures`` (the society's budget, and the walker's pace where the step
        takes one) over the walking graph; a swimmer's route crossed a stretch of land or water at
        a time, the water swum by the swimming its society records."""
        swim = self.swim_pace(person)
        if swim is None or self._joined is None or self._row is None:
            return walk(route, self.nodes, self.edges, *figures)
        nodes, _adjacent, edges = self._joined
        pace = figures[1] if len(figures) > 1 else None
        swum = step_of(self._row.module)
        return crossing(route, nodes, edges, self._wet, figures[0], walk, pace, swum, swim)
