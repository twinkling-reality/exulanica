"""The layout of ROUTE_RULES, which is what keeps two changes to it from colliding.

:data:`exulanica.api.permissions.ROUTE_RULE_SECTIONS` is the source :data:`ROUTE_RULES` is
assembled from. Three rules make a new route's line land in exactly one place, and in a different
place from anybody else's new route, so parallel changes touch different lines rather than the
same end of the same block (two changes to one section collided there on 2026-09-22):

1.  a section declares one requirement;
2.  its routes are listed one per line, sorted by path and then method;
3.  no two sections declare the same requirement.

The sign-in and public sections are the two exceptions to the first rule by nature, because each
of their routes carries its own reason; they are still sorted and still unique. Everything here
reads the module's data, not its source text, and runs without a database.
"""

from __future__ import annotations

import pytest
from exulanica.api import permissions
from exulanica.api.permissions import (
    ROUTE_RULE_SECTIONS,
    ROUTE_RULES,
    Authentication,
    Public,
    Requires,
    RouteDeclarationError,
    route_key,
)


def _order(route: str) -> tuple[str, str]:
    method, path = route_key(route)
    return path, method


@pytest.mark.parametrize("index", range(len(ROUTE_RULE_SECTIONS)))
def test_each_section_is_sorted_by_path_then_method(index):
    routes = list(ROUTE_RULE_SECTIONS[index])
    assert routes == sorted(routes, key=_order), (
        f"section {index} is out of order; sorted it reads:\n  "
        + "\n  ".join(sorted(routes, key=_order))
    )


def test_each_requirement_has_one_section_and_each_section_one_requirement():
    requirements: list[frozenset[str]] = []
    reason_sections = {Public: 0, Authentication: 0}
    for section in ROUTE_RULE_SECTIONS:
        kinds = {type(rule) for rule in section.values()}
        assert len(kinds) == 1, f"a section mixes {sorted(kind.__name__ for kind in kinds)}"
        [kind] = kinds
        if kind is Requires:
            declared = {frozenset(map(str, rule.permissions)) for rule in section.values()}
            assert len(declared) == 1, f"one section declares {sorted(map(sorted, declared))}"
            requirements.extend(declared)
        else:
            reason_sections[kind] += 1
    assert len(requirements) == len(set(requirements)), "two sections declare one requirement"
    assert reason_sections == {Public: 1, Authentication: 1}


def test_the_map_is_exactly_the_sections():
    """Nothing is declared outside a section, and nothing a section lists is lost or doubled."""
    listed = [route_key(route) for section in ROUTE_RULE_SECTIONS for route in section]
    assert len(listed) == len(set(listed)) == len(ROUTE_RULES)
    assert set(listed) == set(ROUTE_RULES)
    for section in ROUTE_RULE_SECTIONS:
        for route, rule in section.items():
            assert ROUTE_RULES[route_key(route)] is rule


def test_a_route_is_written_as_method_and_path():
    assert route_key("POST /world/versions") == ("POST", "/world/versions")
    for written in ("post /world/versions", "GET world/versions", "GET /a b", "HEAD /healthz", ""):
        with pytest.raises(RouteDeclarationError):
            route_key(written)


def test_a_route_in_two_sections_or_twice_in_one_is_refused():
    rule = Requires(frozenset({permissions.Permission.WORLD_READ}))
    with pytest.raises(RouteDeclarationError, match="declared in two sections"):
        permissions._declare(({"GET /world/versions": rule}, {"GET /world/versions": rule}))
    with pytest.raises(RouteDeclarationError, match="listed twice in one section"):
        permissions._every(rule, "GET /world/versions", "GET /world/versions")


def test_an_out_of_order_section_is_what_the_sort_test_reports():
    """Positive control for the first test: the ordering it asserts is the one a swap breaks."""
    section = list(ROUTE_RULE_SECTIONS[2])
    swapped = [section[1], section[0], *section[2:]]
    assert swapped != sorted(swapped, key=_order)
    assert section == sorted(section, key=_order)
