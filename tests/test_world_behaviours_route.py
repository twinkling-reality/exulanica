"""The reviewed behaviour registry over HTTP: served as the table holds it, and enforced as served.

``GET /world/behaviours`` exists so a client can choose a behaviour and parameters by asking the
server. That is only worth anything if what the route advertises is exactly what an edit is held
to, so the second test derives every accepted and refused edit from the served registry itself and
restates no bound. Who may call the route is the generated permission sweep's business
(``tests/route_probes.py`` probes it from its declaration).
"""

from __future__ import annotations

import pytest
from exulanica.world.reviewed_catalog import ReviewedCatalog

from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _served(objects_api) -> list[dict]:
    response = objects_api.get("/world/behaviours")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_registry_is_served_as_the_table_holds_it(objects_api, repository):
    served = _served(objects_api)
    # The registry is the same for every world, so it is read with no world named.
    table = ReviewedCatalog(repository.connection).behaviours()
    assert {
        (row["behaviour_key"], row["behaviour_version"]): row["parameters"] for row in served
    } == {key: dict(parameters) for key, parameters in table.items()}
    # The guard on the guard: an empty registry would agree with an empty answer.
    assert ("motion.bounded-path", 1) in table
    assert [(row["behaviour_key"], row["behaviour_version"]) for row in served] == sorted(table)


def _edges(parameters: dict) -> tuple[list[dict], list[dict]]:
    """Parameter sets on each advertised edge, and sets one step past it, from the served bounds."""
    defaults = {name: bound["default"] for name, bound in parameters.items()}
    inside, outside = [defaults], []
    for name, bound in parameters.items():
        if bound["kind"] == "integer":
            inside += [{**defaults, name: bound["minimum"]}, {**defaults, name: bound["maximum"]}]
            outside += [
                {**defaults, name: bound["minimum"] - 1},
                {**defaults, name: bound["maximum"] + 1},
            ]
        elif bound["kind"] == "choice":
            inside += [{**defaults, name: choice} for choice in bound["choices"]]
            outside.append({**defaults, name: "-".join(bound["choices"])})
        else:
            inside += [{**defaults, name: True}, {**defaults, name: False}]
            outside.append({**defaults, name: "not a toggle"})
    return inside, outside


def test_what_the_registry_advertises_is_what_an_edit_is_held_to(objects_api):
    """Every advertised edge is accepted and one step past it refused, so a bound served wider or
    narrower than the one enforced fails here, as does a version the registry does not list."""
    version = objects_api.version("Advertised bounds")
    accepted = refused = 0
    for row in _served(objects_api):
        key, number = row["behaviour_key"], row["behaviour_version"]
        inside, outside = _edges(row["parameters"])
        for parameters in inside:
            answer = objects_api.add(
                version,
                object_id=f"object:accepted-{accepted}",
                behaviour={
                    "behaviour_key": key,
                    "behaviour_version": number,
                    "parameters": parameters,
                },
            )
            assert answer.status_code == 201, (parameters, answer.text)
            version = answer.json()
            accepted += 1
        unlisted = {"behaviour_key": key, "behaviour_version": number + 1, "parameters": inside[0]}
        for behaviour in [
            unlisted,
            *(
                {"behaviour_key": key, "behaviour_version": number, "parameters": p}
                for p in outside
            ),
        ]:
            answer = objects_api.add(
                version, object_id=f"object:refused-{refused}", behaviour=behaviour
            )
            assert (answer.status_code, answer.json()["code"]) == (422, "invalid_object_data"), (
                behaviour,
                answer.text,
            )
            refused += 1
    # motion.bounded-path@1 alone: 1 default + 2 + 2 integer edges + 3 + 2 choices accepted; its
    # unlisted version, 4 integer steps and 2 unlisted choices refused.
    assert (accepted, refused) >= (10, 7), (accepted, refused)
