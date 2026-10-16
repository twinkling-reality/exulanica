"""A site on a volume's top, stated in a landscape: read against landscape catalog version 2 under
landscape rules 4 and refused by path, and written into the canonical form only where it is stated
so every landscape without one keeps its identity. A world made on the top is
``tests/test_site_on_island.py``'s."""

from __future__ import annotations

import pytest
from exulanica.grammar.landscape import (
    LandscapeRefused,
    LandscapeSite,
    landscape_catalog,
    read_landscape_document,
)

from test_landscape_document import BAY, BAY_SHA256
from test_volume_top_land import GENTLE, mesa

#: The bay with a 60 m block whose top is a gentle hill, standing 20 m above the sea's level.
TOPPED = {
    **BAY,
    "volumes": [
        *BAY["volumes"],
        {"id": "mesa", "volume": mesa(GENTLE), "at_mm": [60000, 20000, 20000]},
    ],
}
SITE = {"on": "mesa", "at_mm": [-8000, -10000]}


def refusal(raw: object, version: int = 2) -> LandscapeRefused:
    with pytest.raises(LandscapeRefused) as caught:
        read_landscape_document(raw, landscape_catalog(version))
    return caught.value


def test_a_site_is_read_with_its_bound_written_in_and_reads_back_the_same():
    read = read_landscape_document({**TOPPED, "site": SITE})
    assert read.site == LandscapeSite(on="mesa", at_mm=(-8000, -10000), cut_fill_mm=2000)
    assert read.canonical()["site"] == {"on": "mesa", "at_mm": [-8000, -10000], "cut_fill_mm": 2000}
    again = read_landscape_document(read.canonical())
    assert (again.sha256, again.site) == (read.sha256, read.site)
    stated = read_landscape_document({**TOPPED, "site": {**SITE, "cut_fill_mm": 500}})
    assert stated.site is not None and stated.site.cut_fill_mm == 500


def test_a_landscape_without_a_site_keeps_its_identity_under_either_catalog():
    for raw in (BAY, TOPPED):
        first = read_landscape_document(raw, landscape_catalog(1))
        second = read_landscape_document(raw, landscape_catalog(2))
        assert first.canonical_bytes == second.canonical_bytes
        assert second.site is None and "site" not in second.canonical()
    assert read_landscape_document(BAY).sha256 == BAY_SHA256[3]


@pytest.mark.parametrize(
    ("site", "where", "code", "words"),
    [
        ([], "site", "landscape_invalid", "a site has"),
        ({"on": "mesa"}, "site", "landscape_invalid", "a site has"),
        ({**SITE, "turn": 1}, "site", "landscape_invalid", "a site has"),
        ({**SITE, "on": "nowhere"}, "site.on", "landscape_site_unknown_placement", "nowhere"),
        ({**SITE, "on": "west_stack"}, "site.on", "landscape_site_no_top_land", "no top land"),
        ({**SITE, "at_mm": [-8500, 0]}, "site.at_mm", "landscape_site_outside_top", "-30000 to"),
        ({**SITE, "at_mm": [30000, 0]}, "site.at_mm", "landscape_site_outside_top", "whole metres"),
        ({**SITE, "at_mm": [0, -31000]}, "site.at_mm", "landscape_site_outside_top", "inside mesa"),
        ({**SITE, "at_mm": [65000, 0]}, "site.at_mm[0]", "landscape_invalid", "-64000 to 64000"),
        ({**SITE, "at_mm": [0]}, "site.at_mm", "landscape_invalid", "2 whole numbers"),
        ({**SITE, "at_mm": [0, "0"]}, "site.at_mm[1]", "landscape_invalid", "whole number"),
        ({**SITE, "cut_fill_mm": 400}, "site.cut_fill_mm", "landscape_invalid", "500 to 4000"),
        ({**SITE, "cut_fill_mm": 4001}, "site.cut_fill_mm", "landscape_invalid", "500 to 4000"),
    ],
)  # fmt: skip
def test_every_site_refusal_names_its_path_and_code(site, where, code, words):
    refused = refusal({**TOPPED, "site": site})
    assert (refused.path, refused.code) == (where, code), refused
    assert words in refused.detail


def test_the_first_catalog_states_no_site():
    refused = refusal({**TOPPED, "site": SITE}, version=1)
    assert (refused.path, refused.code) == ("site", "landscape_invalid")
    assert "catalog version 2 or later" in refused.detail
