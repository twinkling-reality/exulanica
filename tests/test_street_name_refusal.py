"""The refusal a city too large for its street vocabulary meets, and the predicate behind it.

The street-name catalog draws names without repeating and refuses when the options run out. That
refusal used to arrive PART WAY THROUGH GENERATION, as an `InvalidRecordError` reading "the
street-name catalog has no more local_street names", naming no parameter and leaving a caller
nothing to act on. Measured on 2026-09-19: a district twice the corridor's length, changing
`city_extent_x_mm` and nothing else, refused all forty seeds tried that way.

It now arrives before any street record exists, as an `InvalidParameterError` naming the
parameters that decided the street count, the count, and the catalog that would have to grow.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars.city.catalogs import CATALOG_DIRECTORY, load_city_catalogs
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE
from exulanica.grammar.grammars.city.generation import stage as generation_stage
from exulanica.grammar.grammars.city.generation import streets as generation_streets
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_SEED,
)
from exulanica.grammar.grammars.city.generation.tiles import city_records, generate_city


def _catalog() -> dict:
    return json.loads((CATALOG_DIRECTORY / "street-name.v1.json").read_text(encoding="utf-8"))


def _widest_declared_district() -> tuple[int, int, int, int]:
    """The district and blocks that lay the MOST streets: the largest city, the smallest blocks."""
    parameters = {spec.name: spec for spec in CITY_SURFACE.parameters.parameters}
    return (
        parameters["city_extent_x_mm"].maximum,
        parameters["city_extent_y_mm"].maximum,
        parameters["block_length_mm"].minimum,
        parameters["block_depth_mm"].minimum,
    )


def _corridor_values() -> dict:
    return dict(CORRIDOR_BINDINGS[0].values)


def _catalogs_with_fewer_street_names(tmp_path: Path, keep: int) -> Path:
    """A copy of the shipped catalogs whose street-name file holds ``keep`` entries."""
    directory = tmp_path / "catalogs"
    shutil.copytree(CATALOG_DIRECTORY, directory)
    document = json.loads((directory / "street-name.v1.json").read_text(encoding="utf-8"))
    document["entries"] = document["entries"][:keep]
    (directory / "street-name.v1.json").write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8"
    )
    return directory


def test_the_narrowest_reach_lays_at_least_as_many_streets_as_the_widest():
    """The two reaches are the ends of a range, and which end is which is load-bearing.

    The coverage check above asks the vocabulary to name the MOST streets a shape can lay, so it
    uses the narrowest reach; `street_name_shortfall` may refuse only what no shape could name,
    so it uses the widest. If those were the other way round the check would under-ask and the
    predicate would refuse cities that build.
    """
    narrow = generation_streets.narrowest_reach("local_street")
    wide = generation_streets.widest_reach("local_street")
    assert narrow < wide, (narrow, wide)
    span_x, span_y, length, depth = _widest_declared_district()
    most = generation_streets.street_name_demand(span_x, span_y, length, depth, narrow)
    fewest = generation_streets.street_name_demand(span_x, span_y, length, depth, wide)
    assert sum(most.values()) >= sum(fewest.values()) > 1


def test_more_room_between_streets_never_lays_more_of_them():
    """What a caller is told to pass for a derived block length or depth rests on this.

    `street_name_shortfall` tells a caller with a derived value to pass the declared MAXIMUM,
    because that is the best case. That is only true if the count falls as the spacing grows, so
    it is measured over the declared range rather than argued.
    """
    parameters = {spec.name: spec for spec in CITY_SURFACE.parameters.parameters}
    span = parameters["city_extent_x_mm"].maximum
    reach = generation_streets.widest_reach("local_street")
    lengths = range(
        parameters["block_length_mm"].minimum, parameters["block_length_mm"].maximum + 1, 10_000
    )
    counts = [
        sum(generation_streets.street_name_demand(span, span, length, length, reach).values())
        for length in lengths
    ]
    assert counts == sorted(counts, reverse=True), counts
    assert counts[0] > counts[-1], "the range does not move the count, so this proves nothing"


def test_the_predicate_answers_none_for_a_city_that_generates():
    """The corridor builds, so the predicate must not refuse it; and it is pure, so no seed."""
    values = dict(CORRIDOR_BINDINGS[0].values)
    assert (
        generation_streets.street_name_shortfall(
            span_x_mm=values["city_extent_x_mm"],
            span_y_mm=values["city_extent_y_mm"],
            block_length_mm=values["block_length_mm"],
            block_depth_mm=values["block_depth_mm"],
        )
        is None
    )


def test_the_predicate_names_the_parameters_when_no_naming_could_exist(tmp_path, monkeypatch):
    """Its sentence is the refusal a caller shows, so what it names is checked, not assumed."""
    directory = _catalogs_with_fewer_street_names(tmp_path, 1)
    loaded = {item.catalog_id: item for item in load_city_catalogs(directory)}
    monkeypatch.setattr(generation_stage, "_catalogs", lambda: loaded)
    values = dict(CORRIDOR_BINDINGS[0].values)
    message = generation_streets.street_name_shortfall(
        span_x_mm=values["city_extent_x_mm"],
        span_y_mm=values["city_extent_y_mm"],
        block_length_mm=values["block_length_mm"],
        block_depth_mm=values["block_depth_mm"],
    )
    assert message is not None
    for named in ("city_extent_x_mm", "city_extent_y_mm", "block_length_mm", "block_depth_mm"):
        assert named in message, message
    assert "street-name v1" in message, message


@pytest.mark.parametrize(
    "parameter",
    ["city_extent_x_mm", "city_extent_y_mm", "block_length_mm", "block_depth_mm"],
)
def test_a_value_outside_its_declared_range_is_refused_by_name(parameter):
    """Each of the predicate's four arguments, refused by the name of its own parameter.

    NOT TIDINESS. `_lay_out` walks outward from the district's middle in steps of the spacing,
    and on a spacing of ZERO its two candidate positions stop moving while one of them stays
    inside the district, so the loop never ends. Measured 2026-09-19 in a child process with a
    deadline: at the declared minimum of 60000 it returned ten positions, and at zero it had not
    returned after twenty seconds. A caller that resolved the cascade first can never pass one;
    this is for the caller who does not, and a refusal has to arrive instead of a request that
    never comes back.

    SO THIS GOES OVER EACH RANGE RATHER THAN UNDER IT, because a test that hangs is not a test
    and a falsification that removes the guard would hang with it. The value the guard exists for
    is the one value this test cannot use.
    """
    values = _corridor_values()
    spans = {"city_extent_x_mm": "span_x_mm", "city_extent_y_mm": "span_y_mm"}
    arguments = {
        "span_x_mm": values["city_extent_x_mm"],
        "span_y_mm": values["city_extent_y_mm"],
        "block_length_mm": values["block_length_mm"],
        "block_depth_mm": values["block_depth_mm"],
    }
    assert generation_streets.street_name_shortfall(**arguments) is None
    declared = {spec.name: spec for spec in CITY_SURFACE.parameters.parameters}
    arguments[spans.get(parameter, parameter)] = declared[parameter].maximum + 1
    with pytest.raises(InvalidParameterError, match=parameter):
        generation_streets.street_name_shortfall(**arguments)


def test_one_name_serving_two_hierarchies_is_spent_on_whichever_draws_it():
    """The subset check, put to the function directly, because no layout can reach it.

    This streets stage version lays ONE high street and makes every other street local, so a
    demand of five high streets cannot arise from any district it lays. The check is here because
    the demand is public and a caller passes its own, and because a version laying an avenue would
    reach it with nothing to say so.

    THE PROPERTY: a name suiting two hierarchies is spent on whichever draws it first, so holding
    each hierarchy to its own supply is not enough. With the shipped vocabulary five high streets
    and six local ones each fit their own supply and cannot all be named, because two names serve
    both. A per-hierarchy check would admit it.
    """
    supply = generation_streets.street_names_by_hierarchy()
    high, local = supply["high_street"], supply["local_street"]
    shared = high & local
    assert shared, "no name serves both hierarchies, so this property cannot be exercised"
    wanted = {"high_street": len(high), "local_street": len(local)}
    assert all(count <= len(supply[name]) for name, count in wanted.items()), (
        "each hierarchy alone fits, which is what makes this a test of the subsets"
    )
    assert sum(wanted.values()) > len(high | local), "the union fits, so nothing is being asked"
    message = generation_streets._shortfall(wanted, 640_000, 128_000, 140_000, 56_000)
    assert message is not None, "a demand no assignment can serve was admitted"
    assert "high_street or local_street" in message, message


def test_a_city_its_vocabulary_cannot_name_is_refused_before_a_record_exists(tmp_path, monkeypatch):
    """THE CALL IS WHAT IS BROKEN HERE, not the callee.

    The refusal is reached by generating a real city against a shrunken catalog, so this fails if
    the check is correct and nothing calls it. The refusal must name the parameters that decided
    the street count: the old one was an `InvalidRecordError` reading `the street-name catalog has
    no more local_street names`, which told a caller nothing they could change.
    """
    directory = _catalogs_with_fewer_street_names(tmp_path, 1)
    loaded = {item.catalog_id: item for item in load_city_catalogs(directory)}
    monkeypatch.setattr(generation_stage, "_catalogs", lambda: loaded)
    with pytest.raises(InvalidParameterError) as refusal:
        generate_city(
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            bindings=CORRIDOR_BINDINGS,
        )
    message = str(refusal.value)
    for named in ("city_extent_x_mm", "city_extent_y_mm", "block_depth_mm", "block_length_mm"):
        assert named in message, message
    assert "street-name v1" in message, message


def test_the_same_city_generates_when_the_catalog_is_whole(tmp_path, monkeypatch):
    """The positive control for the refusal above, on the same path with the same patching.

    Without it, the refusal could be the patching rather than the catalog, and an arm that cannot
    succeed is not a control.
    """
    directory = _catalogs_with_fewer_street_names(tmp_path, len(_catalog()["entries"]))
    loaded = {item.catalog_id: item for item in load_city_catalogs(directory)}
    monkeypatch.setattr(generation_stage, "_catalogs", lambda: loaded)
    generation = generate_city(
        seed=CORRIDOR_SEED, subject_identity=CORRIDOR_CITY_IDENTITY, bindings=CORRIDOR_BINDINGS
    )
    assert city_records(generation)
