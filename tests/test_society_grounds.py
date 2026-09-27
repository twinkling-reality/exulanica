"""The grounds a society stands on are data, and the starter's reads exactly as it did.

``assets/catalogs/society-ground/society-ground.v1.json`` states the starter ground's population,
lattice spacing and declared area, with their reasons; the ground builder and the repository read
them there. The goldens below were computed from the tree before the figures moved out of code
(main at d7d3b2f1, the starter's constants 8, 2,000 mm and 12,000 mm), over the same objects and
seed: the ground descriptors, the composed inputs, and a square society's genesis and thirtieth
minute. A figure that moved would move one of them.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest
from exulanica.canonical import canonical_json
from exulanica.environment.district_geometry import segment_blocked
from exulanica.grammar.errors import CatalogError
from exulanica.world import society_authored_ground as ground_builder
from exulanica.world.society_authored_ground import build_authored_ground_society_input_v3
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison_verdict import protocol_value
from exulanica.world.society_engines import COMPARISON_ENGINES, CREATES
from exulanica.world.society_grounds import (
    CATALOG_DIRECTORY,
    UnknownSocietyGround,
    load_society_grounds,
    society_ground_for_composer,
    society_ground_for_navigation,
    society_grounds,
)
from exulanica.world.starter import AUTHORED_STARTER_COMPOSER

import living_square_support as square
import test_society_authored_ground as authored
from test_society_authored_world_postgres import create_society, place_object, saved_world

__all__ = ["saved_world"]

#: Computed on d7d3b2f1 (the starter's figures in code) and again on this tree, equal.
GOLDEN = {
    "endless_descriptor": "af0dc49f65bb56913da7b81095d537d68414c71d642b6966e6ba1da4d5e7bcbc",
    "bounded_descriptor": "0ffd9caae4575ac51b34b9ecb27e7dd9e85bee4f56fed390993c25bc0e9f61f0",
    "endless_input": "d4b8a554690d86e1d279565c7cadd2eecd1cafe1d3fd2e72cc79348d8a70c277",
    "bounded_input": "1325080eec051a6691d654d5792acd323db0e50b817d20f1f843856d477de06c",
    "genesis_state": "82a10ad4a4146cabb9454b3af0cfabcf03773d132e30451b431fae96a2e3257a",
    "minute_30_state": "3d23611c693ee0c08c2f7fc9a92065b205c3bd1a3286b4488b5c2eb909a17b8c",
}


def _digest(value: dict) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def test_the_starter_ground_reads_as_it_did_before_it_was_data():
    bounded = build_authored_ground_society_input_v3(
        ground=authored.ground(),
        version=square.version(square.square_objects(), None),
        input_seq=1,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=square.REGISTRY,
        segment_blocked=segment_blocked,
        standing=square.STANDING,
    )
    states = square.run(square.JUDGED_SEEDS[0], 30)
    assert {
        "endless_descriptor": authored.endless().document()["document_sha256"],
        "bounded_descriptor": authored.ground().document()["document_sha256"],
        "endless_input": square.compose(square.square_objects())["document_sha256"],
        "bounded_input": bounded["document_sha256"],
        "genesis_state": _digest(states[0]),
        "minute_30_state": _digest(states[-1]),
    } == GOLDEN
    assert len(states[0]["inhabitants"]) == 8


def test_the_builders_figures_are_the_catalogs():
    starter = society_ground_for_composer(AUTHORED_STARTER_COMPOSER)
    assert (starter.population, starter.lattice_mm, starter.declared_half_extent_mm) == (
        8,
        2_000,
        12_000,
    )
    assert starter == ground_builder.STARTER_GROUND
    assert (
        starter.population,
        starter.lattice_mm,
        starter.declared_half_extent_mm,
        starter.navigation_profile,
    ) == (
        ground_builder.AUTHORED_GROUND_POPULATION,
        ground_builder.LATTICE_MM,
        ground_builder.DECLARED_HALF_EXTENT_MM,
        ground_builder.NAVIGATION_PROFILE,
    )
    assert society_ground_for_navigation(starter.navigation_profile) == starter
    with pytest.raises(UnknownSocietyGround, match="a-composer-nobody-states"):
        society_ground_for_composer("a-composer-nobody-states")
    with pytest.raises(UnknownSocietyGround, match="bounded-sidewalk-graph/v1"):
        society_ground_for_navigation("bounded-sidewalk-graph/v1")


def test_every_ground_can_be_compared_under_the_comparison_protocol():
    """A comparison runs the society its world holds, with the population that society recorded
    from its ground; the protocol refuses a larger one by name. Every ground a comparable engine
    stands on therefore states a population the protocol runs, so no saved world is made that
    cannot be compared."""
    assert society_grounds(), "the parity needs a ground to hold"
    maximum = protocol_value(load_comparison_catalogs(), "population_maximum")
    assert CREATES["saved_world"] in COMPARISON_ENGINES
    assert all(ground.population <= maximum for ground in society_grounds())


def _malformed(tmp_path, change) -> None:
    document = json.loads((CATALOG_DIRECTORY / "society-ground.v1.json").read_text("utf-8"))
    change(document["entries"])
    (tmp_path / "society-ground.v1.json").write_text(json.dumps(document), encoding="utf-8")
    load_society_grounds(tmp_path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda entries: entries[0].update(population=0), "population is an int"),
        (lambda entries: entries[0].update(population=513), "population 513"),
        (lambda entries: entries[0].update(lattice_mm=2_200), "reviewed reach"),
        (lambda entries: entries[0].update(declared_half_extent_mm=2_000), "clearance"),
        (lambda entries: entries[0].pop("population_reason"), "missing"),
        (lambda entries: entries.append(dict(entries[0], key="again")), "two grounds name"),
        (lambda entries: entries[1].update(population=7), "state different figures"),
        (lambda entries: entries[1].update(arrival="somewhere"), "arrival is one of"),
    ],
    ids=[
        "empty",
        "beyond-the-engine",
        "beyond-reach",
        "no-room",
        "no-reason",
        "twice",
        "one-profile-two-populations",
        "unknown-arrival",
    ],
)
def test_a_malformed_ground_catalog_is_refused(tmp_path, change, message):
    with pytest.raises(CatalogError, match=message):
        _malformed(tmp_path, change)


def test_a_file_the_catalog_has_no_schema_for_is_refused(tmp_path):
    source = CATALOG_DIRECTORY / "society-ground.v1.json"
    (tmp_path / source.name).write_bytes(source.read_bytes())
    (tmp_path / "society-ground.v2.json").write_bytes(source.read_bytes())
    with pytest.raises(CatalogError, match="files with no schema"):
        load_society_grounds(tmp_path)


@pytest.mark.postgres
def test_the_repository_starts_a_saved_world_with_its_grounds_population(saved_world, monkeypatch):
    """Read from the ground's entry when a society is created: an entry stating three people
    starts three, over the same input."""
    from exulanica.world import society_repository

    stated = society_repository.society_ground_for_navigation
    monkeypatch.setattr(
        society_repository,
        "society_ground_for_navigation",
        lambda profile: dataclasses.replace(stated(profile), population=3),
    )
    place_object(saved_world, saved_world["plate"], "object:cushion", 3_000, 5_000)
    society, document = create_society(saved_world)
    assert document["navigation"]["profile"] == ground_builder.NAVIGATION_PROFILE
    assert society["population_size"] == 3
    assert len(society["state"]["inhabitants"]) == 3
