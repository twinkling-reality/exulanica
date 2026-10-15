"""A landscape's placed volumes realized: each under a seed of its own, chunks at every stated
level, tops, a section naming every body by digest, and the same bytes every time."""

from __future__ import annotations

import hashlib

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.landscape import (
    compose_volumes,
    placement_seed,
    read_landscape_document,
    volume_bodies,
    volumes_section,
)
from exulanica.grammar.volumes import read_volume_chunk, read_volume_sheet

from test_landscape_document import BAY

SEED = hashlib.sha256(b"exulanica landscape compose test").hexdigest()
#: The bay's volumes section under landscape rules version 1. A change that moves it is a new
#: rules version.
GOLDEN_SECTION = "392fc55e0d4d43bab695011827726589f955c4a8866df6fa69ff31dba616bf8e"


def test_each_placement_draws_a_seed_of_its_own_under_its_own_prefix():
    west, east = placement_seed(SEED, "west_stack"), placement_seed(SEED, "east_stack")
    assert west != east
    assert west == placement_seed(SEED, "west_stack")
    assert west != hashlib.sha256(SEED.encode()).digest()
    assert placement_seed(SEED + "0", "west_stack") != west


def test_the_bay_realizes_each_placement_at_every_level_with_its_tops():
    landscape = read_landscape_document(BAY)
    west, east = compose_volumes(landscape, SEED)
    assert (west.id, east.id) == ("west_stack", "east_stack")
    assert west.volume_sha256 == east.volume_sha256
    assert west.input_sha256 != east.input_sha256
    for placed in (west, east):
        assert {chunk.cell_mm for chunk in placed.chunks} == {4000, 2000}
        assert [top.surface for top in placed.tops] == ["top:0"]
        assert placed.tops[0].cells > 50
    # The same rock weathers differently in each place.
    assert {chunk.positions_mm for chunk in west.chunks} != {
        chunk.positions_mm for chunk in east.chunks
    }
    assert (east.at_mm, east.yaw_mdeg) == ((90000, 50000, -3000), 45000)


def test_the_section_names_exactly_the_bodies_and_each_reads_back_by_its_digest():
    placed = compose_volumes(read_landscape_document(BAY), SEED)
    section = volumes_section(placed)
    bodies = volume_bodies(placed)
    named = {
        entry["sha256"]
        for volume in section["volumes"]
        for entry in [*volume["chunks"], *volume["tops"]]
    }
    assert named == set(bodies)
    for digest, body in bodies.items():
        if body["profile"] == "exulanica.volume-chunk/v1":
            assert read_volume_chunk(body, digest).sha256 == digest
        else:
            assert read_volume_sheet(body, digest).sha256 == digest
    assert sha256_of_canonical(section).hex() == GOLDEN_SECTION


def test_a_coarser_finest_cell_realizes_only_the_coarser_levels():
    coarse = read_landscape_document({**BAY, "finest_cell_mm": 4000})
    for placed in compose_volumes(coarse, SEED):
        assert {chunk.cell_mm for chunk in placed.chunks} == {4000}


def test_land_alone_composes_no_volumes():
    bare = {key: value for key, value in BAY.items() if key != "volumes"}
    assert compose_volumes(read_landscape_document(bare), SEED) == ()
    assert volumes_section(()) == {"volumes": []}
