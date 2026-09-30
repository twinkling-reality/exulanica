"""A society whose engine takes no inputs is offered nothing to compare, never a server error.

The plan and start routes name the kind of ground a society stands on from its newest input, to
read the typical figures measured there. A society of an engine that takes no inputs (the first
engine, the creation route's default profile) has none: the plan route serves it with no roles, and
a start is refused by name (``engine_takes_no_comparison``) and records nothing. The application
connects as a provisioned runtime role, as the start tests' own fixture sets it up.
"""

from __future__ import annotations

import pytest
from exulanica.api.routes import society_comparisons as routes
from exulanica.world.society_engines import DEFAULT_ENGINE, society_engine
from exulanica.world.society_social import SOCIAL_PROFILE

import test_society_comparison_start_postgres as starts

pytestmark = pytest.mark.postgres
saved_world = starts.saved_world
started = starts.started


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_without_inputs_has_nothing_to_compare_and_a_start_is_refused_by_name(started):
    engine = society_engine(DEFAULT_ENGINE)
    assert not engine.takes_inputs and not engine.comparisons, "the case needs such an engine"
    world, client = started["world"], started["client"]
    created = client.post(
        f"/world/versions/{world['binding'].version_id}/society",
        headers=starts.OWNER,
        params=starts._scope(world),
        json={
            "place_id": str(world["binding"].place_id),
            "region_id": world["binding"].region_id,
            "profile": DEFAULT_ENGINE,
        },
    )
    assert created.status_code in (200, 201), created.text
    for headers in (starts.READER, starts.OWNER):
        planned = client.get(
            starts._comparisons(world) + "/plan", headers=headers, params=starts._scope(world)
        )
        assert planned.status_code == 200, planned.text
        assert planned.json()["roles"] == []
    refused = starts._start(started, starts._body())
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "engine_takes_no_comparison"
    assert starts._counts(world) == {
        "society_comparison": 0,
        "society_comparison_run": 0,
        "society_comparison_start": 0,
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_unsupported_saved_world_engine_is_refused_before_its_people_are_read(
    started, monkeypatch
):
    """A retired saved-world engine still refuses comparisons before reading unnamed people."""
    unsupported = society_engine(SOCIAL_PROFILE)
    assert unsupported.saved_world and not unsupported.comparisons
    world, client = started["world"], started["client"]
    starts.stays._inhabited(world, client)
    read = routes._society

    def as_unsupported(comparisons, version_id):
        row = read(comparisons, version_id)
        people = [
            {key: value for key, value in person.items() if key != "display_name"}
            for person in row["state"]["inhabitants"]
        ]
        assert people, "the positive control: the society holds people whose names are left out"
        return {
            **row,
            "engine_version": unsupported.engine,
            "state": {**row["state"], "inhabitants": people},
        }

    monkeypatch.setattr(routes, "_society", as_unsupported)
    planned = client.get(
        starts._comparisons(world) + "/plan", headers=starts.OWNER, params=starts._scope(world)
    )
    assert planned.status_code == 200, planned.text
    document = planned.json()
    assert document["refusal"]["code"] == "engine_takes_no_comparison"
    assert document["roles"] == [] and document["people"] == []
