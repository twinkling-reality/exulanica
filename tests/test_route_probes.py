"""The authorisation sweep covers exactly the declared surface, checked without a database.

``tests/test_api.py`` sends every probe in :data:`route_probes.ROUTE_PROBES` three ways, and that
needs PostgreSQL. Whether every mounted route HAS a probe, and whether every realistic request in
:data:`route_probes.PROBE_OVERRIDES` still names a route, does not, so it is checked here against
the real application's router, and a route that drifts out of the sweep fails a run with no
database configured.
"""

from __future__ import annotations

import pytest
from exulanica.api.permissions import ROUTE_RULES, Requires, route_key
from exulanica.api.routes import routable_paths
from exulanica.api.surface import routing_only_application

from route_probes import (
    ACCOUNT_ROUTES,
    PROBE_OVERRIDES,
    PUBLIC_ROUTES,
    ROUTE_PROBES,
    authenticated_routes,
    default_probe,
    derive_probes,
    fill,
)

APP = routing_only_application()
SWEPT = routable_paths(APP)
OPERATIONS = APP.openapi()["paths"]


def test_the_sweep_can_see_the_application_by_name():
    """The guard on the guard. A coverage check over no routes, or over the documentation pages
    alone, passes; so the walk must have found the authenticated surface, by name."""
    for key in (
        ("GET", "/graph"),
        ("POST", "/identity/name"),
        ("GET", "/evidence/{span_id}"),
        ("POST", "/world/versions/{version_id}/objects"),
    ):
        assert key in SWEPT and key in ROUTE_PROBES, key
    assert len(ROUTE_PROBES) > len(SWEPT) - len(ROUTE_PROBES)


def test_every_mounted_route_is_public_sign_in_or_probed():
    uncovered = [
        (method, path)
        for method, path in SWEPT
        if path not in PUBLIC_ROUTES
        and (method, path) not in ACCOUNT_ROUTES
        and (method, path) not in ROUTE_PROBES
    ]
    assert not uncovered, (
        f"these routes are neither public, sign-in nor probed: {uncovered}. Declare them in "
        "ROUTE_RULES; the sweep derives a probe from the declaration."
    )


def test_every_probe_is_a_mounted_route():
    """A probe for a route that no longer exists is a test asserting things about nothing."""
    assert sorted(set(ROUTE_PROBES) - set(SWEPT)) == []
    assert set(ROUTE_PROBES) == set(authenticated_routes())


@pytest.mark.parametrize("route", sorted(PROBE_OVERRIDES))
def test_every_override_names_a_declared_authenticated_route(route):
    """The stale-probe check: an override outliving its route would pass silently otherwise."""
    key = route_key(route)
    assert key in SWEPT, f"{route} is overridden and not mounted"
    assert isinstance(ROUTE_RULES[key], Requires), f"{route} is overridden and needs no credential"
    assert ROUTE_PROBES[key] is PROBE_OVERRIDES[route]


@pytest.mark.parametrize("route", sorted(PROBE_OVERRIDES))
def test_every_override_differs_from_the_request_the_route_would_get_anyway(route):
    """Keeps the list to the requests that need saying: an override equal to the derived default
    adds a line two changes can collide on and changes nothing the sweep sends."""
    method, path = route_key(route)
    assert PROBE_OVERRIDES[route] != default_probe(OPERATIONS[path][method.lower()])


def test_the_overrides_are_sorted_by_path_then_method():
    routes = list(PROBE_OVERRIDES)
    assert routes == sorted(routes, key=lambda route: route_key(route)[::-1])


def test_a_body_the_sweep_cannot_default_is_refused_by_name():
    """Positive control for the derivation: without its override, multipart intake has no
    default, and the refusal names the route rather than probing it with a request it rejects."""
    without_intake = {
        route: probe for route, probe in PROBE_OVERRIDES.items() if route != "POST /intake"
    }
    with pytest.raises(LookupError, match="POST /intake"):
        derive_probes(OPERATIONS, without_intake)


def test_a_route_is_probed_by_being_declared():
    """Positive control for coverage: a declared route with no override gets its default probe."""
    key = ("POST", "/world/versions/{version_id}/objects/undo")
    reduced = {route: probe for route, probe in PROBE_OVERRIDES.items() if route_key(route) != key}
    probes = derive_probes(OPERATIONS, reduced)
    assert probes[key] == {"json": {}}
    assert set(probes) == set(authenticated_routes())


@pytest.mark.parametrize(("method", "path"), sorted(ROUTE_PROBES))
def test_no_route_is_probed_with_a_placeholder_left_in_its_url(method, path):
    filled = fill(path)
    assert "{" not in filled and "}" not in filled, (method, path, filled)


def test_fill_keeps_known_ids_and_the_closed_set_parameters():
    assert fill("/evidence/{span_id}/region", {"span_id": "s-1"}) == "/evidence/s-1/region"
    assert fill("/environment-resources/{kind}/{resource_id}").startswith(
        "/environment-resources/source/"
    )
    first, second = fill("/world/versions/{version_id}"), fill("/world/versions/{version_id}")
    assert first != second, "an invented id is fresh each time, never one another test allocated"
