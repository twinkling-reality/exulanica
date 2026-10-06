"""Stage B of a kind's checks: sample worlds, each held to what people need to live, walk and work.

A kind that passed stage A (:mod:`exulanica.world.kinds.document`) is generated at every preset
with two seeds, and at each adjustable value's least and greatest (the others at the first preset)
with one, at most :data:`SAMPLES_MAXIMUM` samples. Each sample is made the way a world of the kind
is made (:func:`compose_site`): the kind's seed candidates are tried in order, and a candidate is
kept only when

* the site grammar lays it out (its parts fit their zones) within its layout budget: one world's
  layout tries at most the bounds catalog's ``layout_trials`` placements, and every sample of one
  kind's check together at most ``check_layout_trials``, so the work a kind asks for is bounded
  whatever its document says;
* its place passes the society's own place check (:func:`~exulanica.world.society_place.
  validate_place`) under the kind's routine;
* its walking graph is no larger than the largest a living society's tick was measured on;
* it houses at least one person and no more than the ceiling;
* from the entry, every destination is reached, so every resident reaches their workplace and
  everything the routine sends them to;
* when it has workplaces, its employment share of its residents gives at least one worker.

A sample none of whose candidates is kept refuses the kind by name, with the code of what failed
and every candidate's sentence. The outcome of every sample is the validation report
(``exulanica.world-kind-validation/v1``), which a stored kind keeps by digest.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import InvalidParameterError, InvalidRecordError
from exulanica.grammar.grammars.site import generate_site, site_records
from exulanica.grammar.grammars.site.layout import LayoutBudget, LayoutOverBudget
from exulanica.grammar.grammars.site.plan import SitePlan, plan_sha256
from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindDocument, KindRefused
from exulanica.world.kinds.routine import kind_routine
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_place import validate_place
from exulanica.world.society_site_place import (
    GraphOverBudget,
    SiteSociety,
    place_from_site_records,
    place_residents,
)

__all__ = [
    "REPORT_PROFILE",
    "SAMPLES_MAXIMUM",
    "SEED_PROFILE",
    "SiteRefused",
    "SiteWorld",
    "check_samples",
    "compose_site",
    "layout_budget",
    "sample_values",
    "site_seed",
]

REPORT_PROFILE: Final = "exulanica.world-kind-validation/v1"
SEED_PROFILE: Final = "exulanica.site-world-seed/v1"
#: The most sample worlds one kind's check builds: eight presets with two seeds each and sixteen
#: values at both ends; a kind states at most that many of each (the bounds catalog).
SAMPLES_MAXIMUM: Final = 48
_SAMPLE_NAMESPACE: Final = uuid.uuid5(
    uuid.NAMESPACE_URL, "https://exulanica.invalid/world-kind/sample"
)
#: The order a candidate's checks report a failure in, so a refusal names the first need unmet.
_CODES: Final = (
    "kind_generation_refused",
    "kind_layout_over_budget",
    "kind_graph_over_budget",
    "kind_population_out_of_bounds",
    "kind_unreachable",
    "kind_capacity_short",
)


class SiteRefused(Exception):
    """No candidate of one world made a site people can live in: every candidate's refusal."""

    def __init__(self, code: str, refusals: Sequence[Mapping[str, object]]) -> None:
        self.code = code
        self.refusals = tuple(dict(refusal) for refusal in refusals)
        stated = "; ".join(f"candidate {r['candidate']}: {r['refusal']}" for r in self.refusals)
        super().__init__(f"{code}: no seed candidate made a world ({stated})")


@dataclass(frozen=True, slots=True)
class SiteWorld:
    """One world of a kind: the plan, the candidate kept, its seed, its records and its place."""

    plan: SitePlan
    plan_sha256: str
    candidate: int
    seed: str
    subject_identity: str
    output_digest: str
    records: tuple[object, ...]
    place: dict[str, Any]
    routine: RoutineModel
    society: SiteSociety
    refused: tuple[dict[str, object], ...]

    def counts(self) -> dict[str, int]:
        destinations = self.place["destinations"]
        return {
            "records": len(self.records),
            "nodes": len(self.place["nodes"]),
            "edges": len(self.place["edges"]),
            "spots": len(self.place["spots"]),
            "residents": place_residents(self.place),
            "staff_positions": sum(int(d["staff_capacity"]) for d in destinations),
            "visitor_places": sum(int(d["visitor_capacity"]) for d in destinations),
            "destinations": len(destinations),
        }


def site_seed(
    reference: Mapping[str, object], values: Mapping[str, int], world_id: str, candidate: int
) -> str:
    """One candidate's seed: SHA-256 over the kind's reference, the values, the world's identity
    and the candidate's number, as canonical JSON so every field is framed."""
    return sha256_of_canonical(
        {
            "profile": SEED_PROFILE,
            "kind": dict(reference),
            "values": dict(sorted(values.items())),
            "world_id": world_id,
            "candidate": candidate,
        }
    ).hex()


def _identity(seed: str) -> str:
    return str(uuid.uuid5(_SAMPLE_NAMESPACE, seed))


def _reached(place: Mapping[str, Any], start: str) -> set[str]:
    adjacent: dict[str, list[str]] = {}
    for edge in place["edges"]:
        adjacent.setdefault(edge["from_node_id"], []).append(edge["to_node_id"])
        adjacent.setdefault(edge["to_node_id"], []).append(edge["from_node_id"])
    seen = {start}
    frontier = [start]
    while frontier:
        node = frontier.pop()
        for other in adjacent.get(node, ()):
            if other not in seen:
                seen.add(other)
                frontier.append(other)
    return seen


def _needs(
    world_place: Mapping[str, Any],
    routine: RoutineModel,
    catalogs_bounds: Mapping[str, tuple[int, int]],
    employment: int,
) -> tuple[str, str] | None:
    """The first need a candidate's place does not meet, as (code, sentence), or None."""
    nodes_high = catalogs_bounds["walking_nodes"][1]
    count = len(world_place["nodes"])
    if count > nodes_high:
        return (
            "kind_graph_over_budget",
            f"its walking graph has {count} places, over the {nodes_high} a living society's tick "
            "was measured on",
        )
    residents = place_residents(world_place)
    low, high = catalogs_bounds["residents"]
    if not low <= residents <= high:
        return (
            "kind_population_out_of_bounds",
            f"it houses {residents} people; a world houses {low} to {high}",
        )
    reached = _reached(world_place, "entry")
    for destination in world_place["destinations"]:
        if destination["node_id"] not in reached:
            return (
                "kind_unreachable",
                f"{destination['label']} ({destination['destination_id']}) is not reached from "
                "the entry",
            )
    staffed = [d for d in world_place["destinations"] if d["staff_capacity"] > 0]
    if staffed and residents * employment // 1000 < 1:
        return (
            "kind_capacity_short",
            f"{len(staffed)} workplaces and {residents} residents of whom {employment} per mille "
            "work: nobody would work there",
        )
    return None


def layout_budget(*, in_all: bool = False) -> LayoutBudget:
    """The layout budget the bounds catalog states: ``layout_trials`` for each world, and with
    ``in_all`` also ``check_layout_trials`` for every sample world of one kind's check together."""
    bounds = load_kind_catalogs().bounds
    return LayoutBudget(
        bounds["layout_trials"][1], bounds["check_layout_trials"][1] if in_all else None
    )


def compose_site(
    kind: KindDocument,
    values: Mapping[str, int],
    world_id: str,
    *,
    routine: RoutineModel | None = None,
    candidates: int | None = None,
    budget: LayoutBudget | None = None,
) -> SiteWorld:
    """The world ``kind`` makes with ``values`` for ``world_id``: the first seed candidate whose
    site is laid out within ``budget`` (by default each candidate within the bounds catalog's
    ``layout_trials``) and meets every need; :class:`SiteRefused` with every candidate's sentence
    when none does."""
    bounds = load_kind_catalogs().bounds
    tries = bounds["candidates"][0] if candidates is None else candidates
    budget = layout_budget() if budget is None else budget
    routine = kind_routine(kind) if routine is None else routine
    try:
        plan = kind.plan(values)
    except (InvalidParameterError, InvalidRecordError) as exc:
        refusal = {
            "candidate": 0,
            "code": "kind_generation_refused",
            "refusal": f"its values make no site plan: {str(exc)[:400]}",
        }
        raise SiteRefused("kind_generation_refused", [refusal]) from exc
    digest = plan_sha256(plan)
    society = kind.society(values)
    refused: list[dict[str, object]] = []
    code = _CODES[0]
    for candidate in range(tries):
        seed = site_seed(kind.reference(), values, world_id, candidate)
        identity = _identity(seed)
        try:
            generation = generate_site(plan, seed=seed, subject_identity=identity, budget=budget)
        except LayoutOverBudget as exc:
            refused.append(
                {
                    "candidate": candidate,
                    "code": "kind_layout_over_budget",
                    "refusal": str(exc)[:500],
                }
            )
            if _CODES.index("kind_layout_over_budget") > _CODES.index(code):
                code = "kind_layout_over_budget"
            continue
        except (InvalidParameterError, InvalidRecordError) as exc:
            refused.append(
                {
                    "candidate": candidate,
                    "code": "kind_generation_refused",
                    "refusal": str(exc)[:500],
                }
            )
            continue
        records = site_records(generation)
        try:
            # The graph's budget is held while it is built, so an oversized site stops early.
            place = place_from_site_records(
                place_id=f"generated:{world_id}",
                records=records,
                society=society,
                routine=routine,
                node_limit=bounds["walking_nodes"][1],
            )
        except GraphOverBudget as exc:
            refused.append(
                {
                    "candidate": candidate,
                    "code": "kind_graph_over_budget",
                    "refusal": f"{exc}, the most a living society's tick was measured on",
                }
            )
            if _CODES.index("kind_graph_over_budget") > _CODES.index(code):
                code = "kind_graph_over_budget"
            continue
        try:
            validate_place(place, routine)
        except ValueError as exc:
            refused.append(
                {
                    "candidate": candidate,
                    "code": "kind_generation_refused",
                    "refusal": f"its place is refused: {exc}",
                }
            )
            continue
        unmet = _needs(place, routine, bounds, kind.employment_permille)
        if unmet is not None:
            refused.append({"candidate": candidate, "code": unmet[0], "refusal": unmet[1]})
            if _CODES.index(unmet[0]) > _CODES.index(code):
                code = unmet[0]
            continue
        return SiteWorld(
            plan=plan,
            plan_sha256=digest,
            candidate=candidate,
            seed=seed,
            subject_identity=identity,
            output_digest=generation.receipt.output_digest,
            records=records,
            place=place,
            routine=routine,
            society=society,
            refused=tuple(refused),
        )
    raise SiteRefused(code, refused)


def sample_values(kind: KindDocument) -> list[tuple[str, dict[str, int], int]]:
    """Every sample a kind's check builds: (what it samples, its values, its seed number)."""
    samples: list[tuple[str, dict[str, int], int]] = []
    seen: set[tuple[str, int]] = set()

    def add(label: str, values: dict[str, int], seed: int) -> None:
        key = (repr(sorted(values.items())), seed)
        if key not in seen and len(samples) < SAMPLES_MAXIMUM:
            seen.add(key)
            samples.append((label, values, seed))

    for preset, _label, values in kind.presets:
        for seed in range(2):
            add(f"preset {preset}", dict(values), seed)
    first = dict(kind.presets[0][2])
    for parameter in kind.parameters:
        for end, value in (("least", parameter.minimum), ("greatest", parameter.maximum)):
            add(f"{parameter.key} at its {end}", {**first, parameter.key: value}, 0)
    return samples


def check_samples(kind: KindDocument) -> dict[str, Any]:
    """Build every sample world of a kind and refuse the kind by name at the first that fails;
    the validation report when all pass. Every sample's layouts share one budget in all
    (:func:`layout_budget`)."""
    routine = kind_routine(kind)
    budget = layout_budget(in_all=True)
    outcomes: list[dict[str, Any]] = []
    for label, values, seed in sample_values(kind):
        world_id = f"sample:{kind.sha256}:{seed}"
        try:
            world = compose_site(kind, values, world_id, routine=routine, budget=budget)
        except SiteRefused as exc:
            refusal = KindRefused(
                exc.code,
                "; ".join(f"candidate {r['candidate']}: {r['refusal']}" for r in exc.refusals),
                f"sample {label}",
            )
            refusal.report = {  # type: ignore[attr-defined]
                "profile": REPORT_PROFILE,
                "kind": kind.reference(),
                "verdict": "refused",
                "failed": {"sample": label, "values": values, "refusals": list(exc.refusals)},
                "samples": outcomes,
            }
            raise refusal from exc
        outcomes.append(
            {
                "sample": label,
                "values": values,
                "seed": seed,
                "candidate": world.candidate,
                "plan_sha256": world.plan_sha256,
                "output_digest": world.output_digest,
                "counts": world.counts(),
            }
        )
    return {
        "profile": REPORT_PROFILE,
        "kind": kind.reference(),
        "verdict": "passed",
        "routine_sha256": routine.sha256,
        "samples": outcomes,
    }
