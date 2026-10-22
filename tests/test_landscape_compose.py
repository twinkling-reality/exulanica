"""A landscape's placed volumes realized: each under a seed of its own, chunks at every stated
level, tops, a section naming every body by digest, and the same bytes every time."""

from __future__ import annotations

import hashlib

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.landscape import (
    SERVED_LANDSCAPE_RULES,
    compose_volumes,
    placement_seed,
    read_landscape_document,
    volume_bodies,
    volumes_section,
)
from exulanica.grammar.volumes import read_volume_chunk, read_volume_sheet

from test_landscape_document import BAY

SEED = hashlib.sha256(b"exulanica landscape compose test").hexdigest()
#: The bay's volumes section under each landscape rules version, its volumes read and realized by
#: the volume rules that version names. A change that moves one is a new rules version.
GOLDEN_SECTION = {
    1: "392fc55e0d4d43bab695011827726589f955c4a8866df6fa69ff31dba616bf8e",
    2: "91296abf6d4b4e6188599b89e350f9649ffeb19ee36afe73d01548c8b6a7b8c5",
    3: "87d987d818a018a1fc1099a61607e733d699680e580b1d9f620213d907b5f167",
    # Version 4 reads a site on a volume's top beside version 3's volumes: the bay states none.
    4: "87d987d818a018a1fc1099a61607e733d699680e580b1d9f620213d907b5f167",
    # Version 5 realizes version 4's volumes by volume rules 4: version 3's rock, naming 4.
    5: "a93e4275d086e7caad9958b44833e3ea8a71d064a35a5c18f00c2055c0f39c3f",
}


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


@pytest.mark.parametrize("version", sorted(SERVED_LANDSCAPE_RULES))
def test_the_section_names_exactly_the_bodies_and_each_reads_back_by_its_digest(version):
    assert set(GOLDEN_SECTION) == set(SERVED_LANDSCAPE_RULES)
    volume_rules = SERVED_LANDSCAPE_RULES[version][1]
    placed = compose_volumes(read_landscape_document(BAY, volume_rules=volume_rules), SEED)
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
        assert body["rules_version"] == volume_rules
    assert sha256_of_canonical(section).hex() == GOLDEN_SECTION[version]


def test_a_coarser_finest_cell_realizes_only_the_coarser_levels():
    coarse = read_landscape_document({**BAY, "finest_cell_mm": 4000})
    for placed in compose_volumes(coarse, SEED):
        assert {chunk.cell_mm for chunk in placed.chunks} == {4000}


def test_land_alone_composes_no_volumes():
    bare = {key: value for key, value in BAY.items() if key != "volumes"}
    assert compose_volumes(read_landscape_document(bare), SEED) == ()
    assert volumes_section(()) == {"volumes": []}


def test_a_landscape_composed_again_realizes_only_volumes_whose_inputs_changed(monkeypatch):
    from exulanica.grammar.landscape import compose

    landscape = read_landscape_document(BAY)
    first = compose_volumes(landscape, SEED)
    realized: list[tuple[str, int]] = []
    real = compose.realize_volume

    def counted(field, cell_mm):
        realized.append((field.seed.hex(), cell_mm))
        return real(field, cell_mm)

    monkeypatch.setattr(compose, "realize_volume", counted)
    # The same landscape under the same seed is the realization it was, none realized again.
    assert compose_volumes(landscape, SEED) == first
    assert realized == []
    # Another seed is other inputs: every volume at every level, and the same bytes it would be.
    other = compose_volumes(landscape, SEED + "0")
    assert len(realized) == len(first) * 2
    assert volume_bodies(other) != volume_bodies(first)
    # Only the last composition is held: the first seed is realized again, as it was.
    assert compose_volumes(landscape, SEED) == first
    assert len(realized) == len(first) * 4
