"""The names, roles, weather and resources of a v1 to v3 society are a frozen catalog's.

``society-legacy-identity.v1.json`` serves the first three engine profiles, chosen by the profile
a society records, and its digest is pinned because every stored genesis of those profiles hashes
its values. The digests below were computed on main before the values left the code
(d7d3b2f1, 2026-09-26) and are unchanged by the move.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.world import society_legacy
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import (
    LEGACY_IDENTITY_CATALOG,
    ROUTINE_DIRECTORY,
    legacy_identity,
)
from exulanica.world.society_legacy import initial_society
from exulanica.world.society_planner import initial_purposeful_society
from exulanica.world.society_social import initial_social_society

from society_fixtures import SEED, SOCIETY, society_input

PROFILES = ("exulanica-society/v1", "exulanica-society/v2", "exulanica-society/v3")


def test_every_genesis_the_catalog_serves_hashes_as_it_did_when_the_values_were_code():
    document = society_input()
    assert (
        society_state_sha256(initial_society(SOCIETY, SEED))
        == "1072771ce079acb489e949660bbf12d31d723a8e965c119cb3b644c1d8db41c7"
    )
    assert (
        society_state_sha256(initial_purposeful_society(SOCIETY, SEED, document))
        == "2d1a76b73f8a7d63c560ac74aaac6431bb254510707a229b9a9b46a62c5e219a"
    )
    assert (
        society_state_sha256(initial_social_society(SOCIETY, SEED, document))
        == "a854042aa5fe819d8c3e2695992fb36ce7925c50f3bbe5decafecc4c73942cec"
    )


def test_each_profile_it_serves_reads_the_same_identity_and_no_other_profile_reads_one():
    first, *others = (legacy_identity(profile) for profile in PROFILES)
    assert all(other == first for other in others)
    with pytest.raises(CatalogError, match="serves the profile 'exulanica-society/v4'"):
        legacy_identity("exulanica-society/v4")


def test_a_published_version_edited_in_place_is_refused(tmp_path):
    directory = tmp_path / "society"
    shutil.copytree(ROUTINE_DIRECTORY, directory)
    published = directory / f"{LEGACY_IDENTITY_CATALOG}.v1.json"
    document = json.loads(published.read_text(encoding="utf-8"))
    next(e for e in document["entries"] if e["key"] == "first_ari")["text"] = "Aria"
    published.write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(CatalogError, match="is published and stored societies hash its values"):
        legacy_identity(PROFILES[1], directory)


def test_the_frozen_module_states_no_name_role_or_world_value_of_its_own():
    """The special case this catalog replaced: tables of names and roles written into code."""
    identity = legacy_identity(PROFILES[0])
    stated = {
        *identity.roles,
        *identity.first_names,
        *identity.last_names,
        str(identity.weather["kind"]),
    }
    source = Path(society_legacy.__file__).read_text(encoding="utf-8")
    constants = {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert constants & stated == set()
    # Positive control: the same reading finds a name planted as a constant.
    assert "Ari" in {
        node.value
        for node in ast.walk(ast.parse('NAMES = ("Ari",)'))
        if isinstance(node, ast.Constant)
    }
