"""A start whose model would decide for more people than one run's read allows is refused by name.

The application connects as a provisioned runtime role, as the start tests' own fixture sets it up,
under catalogs whose replay line lets a model decide for three of the saved world's eight people.
The plan route serves the bounds for the version's society; a selection over them is refused in the
plan and at the start by ``decided_over_comparison_bound``, recording nothing; a group within them
is planned and started.
"""

from __future__ import annotations

import dataclasses

import pytest
from exulanica.world.society_comparison_reading import decided_maximum, population_maximum

import test_society_comparison_start_postgres as starts
import test_society_stay_requests_api as stays
from comparison_support import seeded_catalogs

pytestmark = pytest.mark.postgres
saved_world = starts.saved_world
started = starts.started
#: A replay line under which one run's read allows 5,000 people nobody decides for and, of the
#: saved world's eight, a model deciding for three: 5,000 us for the run, 1 us a person, 1,600 us a
#: decided person.
TIGHT = {
    "pair_replay_budget_ms": 10,
    "replay_fixed_ms": 0,
    "replay_per_person_us": 1,
    "replay_per_decided_person_us": 1_600,
    "replay_per_decided_pair_us": 0,
}


def _tight(started) -> None:
    services = started["client"].app.state.services
    catalogs = services.comparison_catalogs or seeded_catalogs()
    protocol = {key: dict(entry) for key, entry in catalogs.protocol.items()}
    for key, value in TIGHT.items():
        protocol[key]["value"] = value
    tight = dataclasses.replace(catalogs, protocol=protocol)
    assert (population_maximum(tight), decided_maximum(tight, 8)) == (5_000, 3)
    started["client"].app.state.services = dataclasses.replace(services, comparison_catalogs=tight)


def _plan(started, **query):
    world = started["world"]
    planned = started["client"].get(
        starts._comparisons(world) + "/plan",
        headers=starts.OWNER,
        params={**starts._scope(world), **query},
    )
    assert planned.status_code == 200, planned.text
    return planned.json()


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_group_beyond_the_decided_bound_is_refused_and_one_within_it_starts(started):
    world = started["world"]
    snapshot = stays._inhabited(world, started["client"])
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    assert len(people) == 8
    _tight(started)
    offered = _plan(started)
    assert (offered["population"], offered["population_most"], offered["decided_most"]) == (
        8,
        5_000,
        3,
    )
    model = f"{starts.MODEL.provider}/{starts.MODEL.model_id}"
    role = starts.person_role().key
    everybody = _plan(started, role=role, group="everyone", model=model)
    assert everybody["plan"] is None
    assert everybody["plan_refusal"]["code"] == "decided_over_comparison_bound"
    refused = starts._start(started, starts._body())
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "decided_over_comparison_bound"
    assert starts._counts(world) == {
        "society_comparison": 0,
        "society_comparison_run": 0,
        "society_comparison_start": 0,
    }
    # Positive control: three of them, the most a model may decide for, are planned and started.
    three = _plan(started, role=role, group="named", person=people[:3], model=model)
    assert three["plan_refusal"] is None, three["plan_refusal"]
    assert [minute["decided"] for minute in three["plan"]["minutes"]] == [3]
    begun = starts._start(started, starts._body(group={"kind": "named", "people": people[:3]}))
    assert begun.status_code == 201, begun.text
    assert starts._counts(world)["society_comparison_start"] == 1
