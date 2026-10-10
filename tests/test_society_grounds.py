"""The grounds a society stands on are data, and the starter's reads exactly as it did.

``assets/catalogs/society-ground/society-ground.v<N>.json`` states the starter ground's population,
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
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world import society_authored_ground as ground_builder
from exulanica.world.society_authored_ground import build_authored_ground_society_input_v3
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison_reading import population_maximum
from exulanica.world.society_engines import COMPARISON_ENGINES, CREATES
from exulanica.world.society_grounds import (
    CATALOG_DIRECTORY,
    CATALOG_VERSION,
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


def test_every_stated_ground_can_be_compared_under_the_comparison_protocol():
    """A comparison runs the society its world holds, with the population that society recorded
    from its ground; the protocol refuses a larger one by name. Every ground that states its
    population therefore states one the protocol runs. A ground whose population is its world's
    residents (a generated town) is held by the protocol's derived bounds on the population it
    recorded (``tests/test_comparison_reading_bound.py``)."""
    assert society_grounds(), "the parity needs a ground to hold"
    maximum = population_maximum(load_comparison_catalogs())
    assert CREATES["saved_world"] in COMPARISON_ENGINES
    stated = [ground for ground in society_grounds() if ground.population_rule == "stated"]
    assert stated, "the parity needs a stated ground to hold"
    assert all(ground.population <= maximum for ground in stated)


def _malformed(tmp_path, change) -> None:
    for path in CATALOG_DIRECTORY.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    current = f"society-ground.v{CATALOG_VERSION}.json"
    document = json.loads((CATALOG_DIRECTORY / current).read_text("utf-8"))
    change(document["entries"])
    (tmp_path / current).write_text(json.dumps(document), encoding="utf-8")
    load_society_grounds(tmp_path)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda entries: entries[0].update(population=0), "people are the world's own"),
        (lambda entries: entries[0].update(lattice_mm=2_200), "reviewed reach"),
        (lambda entries: entries[0].update(declared_half_extent_mm=2_000), "clearance"),
        (lambda entries: entries[0].pop("population_reason"), "missing"),
        (lambda entries: entries.append(dict(entries[0], key="again")), "two grounds name"),
        (lambda entries: entries[1].update(population=7), "state different figures"),
        (lambda entries: entries[1].update(arrival="somewhere"), "arrival is one of"),
    ],
    ids=[
        "empty",
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
    for path in CATALOG_DIRECTORY.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    source = CATALOG_DIRECTORY / f"society-ground.v{CATALOG_VERSION}.json"
    (tmp_path / f"society-ground.v{CATALOG_VERSION + 1}.json").write_bytes(source.read_bytes())
    with pytest.raises(CatalogError, match="files with no schema"):
        load_society_grounds(tmp_path)


@pytest.mark.postgres
def test_the_repository_starts_a_saved_world_with_its_grounds_population(saved_world, monkeypatch):
    """Read from the ground's entry when a society is created: an entry stating three people
    starts three, over the same input."""
    from exulanica.world import society_grounds

    stated = society_grounds.society_ground_for_navigation
    monkeypatch.setattr(
        society_grounds,
        "society_ground_for_navigation",
        lambda profile: dataclasses.replace(stated(profile), population=3),
    )
    place_object(saved_world, saved_world["plate"], "object:cushion", 3_000, 5_000)
    society, document = create_society(saved_world)
    assert document["navigation"]["profile"] == ground_builder.NAVIGATION_PROFILE
    assert society["population_size"] == 3
    assert len(society["state"]["inhabitants"]) == 3


def test_each_ground_states_the_place_its_input_names_and_the_records_its_people_use():
    from exulanica.world.society_grounds import place_dependency_for, record_subjects_for

    stated = json.loads(
        (CATALOG_DIRECTORY / f"society-ground.v{CATALOG_VERSION}.json").read_text("utf-8")
    )
    assert {entry["key"] for entry in stated["entries"]} == {g.key for g in society_grounds()}
    for entry in stated["entries"]:
        ground = society_ground_for_composer(entry["composer_key"])
        assert ground.place_dependency == entry["place_dependency"]
        assert ground.record_subjects == tuple(entry["record_subjects"])
        assert place_dependency_for(ground.navigation_profile) == entry["place_dependency"]
        assert record_subjects_for(ground.navigation_profile) == tuple(entry["record_subjects"])
    # A profile no ground states names no place and no records.
    assert place_dependency_for("bounded-sidewalk-graph/v1") == "none"
    assert record_subjects_for("bounded-sidewalk-graph/v1") == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda entries: entries[2].update(place_dependency="none"), "names the place"),
        (lambda entries: entries[0].update(place_dependency="city_place"), "names the place"),
        (lambda entries: entries[2].update(record_subjects=[]), "names records"),
        (lambda entries: entries[0].update(record_subjects=["city.premises"]), "names records"),
        (
            lambda entries: entries[2].update(record_subjects=["city.street_furniture", "city.a"]),
            "sorted",
        ),
        (lambda entries: entries[2].update(record_subjects=["premises"]), "record kinds"),
        (lambda entries: entries[3].update(place_dependency="town_place"), "is one of"),
    ],
    ids=[
        "surfaces-no-place",
        "lattice-place",
        "surfaces-no-records",
        "lattice-records",
        "unsorted",
        "not-a-kind",
        "unknown-place",
    ],
)
def test_a_ground_naming_the_wrong_place_or_records_is_refused(tmp_path, change, message):
    with pytest.raises(CatalogError, match=message):
        _malformed(tmp_path, change)


def test_an_activity_may_name_only_the_records_its_own_ground_states():
    from exulanica.world.society_input_policy import (
        UNREACHABLE,
        WALKING_SURFACES_INPUT_V2,
        validate_local_affordances,
    )

    def document(navigation_profile: str, subject: str) -> dict:
        return {
            "profile": WALKING_SURFACES_INPUT_V2,
            "version_id": "v",
            "navigation": {"profile": navigation_profile},
            "availability": "available",
            "targets": [],
            "unavailable_affordances": [
                {
                    "target_id": f"{subject}:o:sit",
                    "subject_id": f"{subject}:o",
                    "object_id": "o",
                    "version_id": "v",
                    "affordance": "sit",
                    "reason": UNREACHABLE,
                }
            ],
        }

    site = society_ground_for_composer("site-plan")
    town = society_ground_for_composer("city-grammar-town")
    validate_local_affordances(document(site.navigation_profile, "site.fixture"), {"sit"})
    validate_local_affordances(document(town.navigation_profile, "city.street_furniture"), {"sit"})
    # A site's input naming a town's record kind, or a town's a site's, is refused.
    for profile, subject in (
        (site.navigation_profile, "city.street_furniture"),
        (town.navigation_profile, "site.fixture"),
    ):
        with pytest.raises(ValueError, match="identity or reason mismatch"):
            validate_local_affordances(document(profile, subject), {"sit"})


def test_each_ground_names_the_shipped_being_its_population_is_made_of():
    villager = dict(shipped_thing_kinds()[("villager", 1)].reference())
    grounds = load_society_grounds()
    assert [ground.population_kind for ground in grounds] == [villager] * len(grounds)
    # Every reader shares the loaded grounds, so none may change the kind for the others: it is
    # read-only, and a reader's copy is its own.
    with pytest.raises(TypeError):
        grounds[0].population_kind["version"] = 2  # type: ignore[index]
    copied = dict(grounds[0].population_kind)
    copied["version"] = 2
    assert grounds[0].population_kind == villager


def _reference(key: str, version: int) -> dict:
    return dict(shipped_thing_kinds()[(key, version)].reference())


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda entries: entries[0].pop("population_kind"), "missing"),
        (
            lambda entries: entries[0].update(
                population_kind=_reference("villager", 1) | {"sha256": "e" * 64}
            ),
            "population_kind",
        ),
        (lambda entries: entries[0].update(population_kind=_reference("well", 1)), "routine"),
        (lambda entries: entries[0].update(population_kind=_reference("visitor", 1)), "routine"),
        (lambda entries: entries[0].update(population_kind={"kind": "villager"}), "digest"),
        (
            lambda entries: entries[1].update(population_kind=_reference("knight", 1)),
            "state different figures",
        ),
    ],
    ids=[
        "no-kind",
        "another-digest",
        "an-object",
        "decided-only-from-outside",
        "not-a-reference",
        "one-profile-two-kinds",
    ],
)
def test_a_ground_naming_a_kind_no_population_may_be_is_refused(tmp_path, change, message):
    with pytest.raises(CatalogError, match=message):
        _malformed(tmp_path, change)
