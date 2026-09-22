"""The built-in ground module's stored shapes, one per version, and how a snapshot is read back.

A starter snapshot is committed to a database and read for years afterwards. The projection that
reads one matches it against every supported module version rather than trusting the version the
stored bytes claim, so these tests pin what each version's bytes are and check that a snapshot
written at one version keeps projecting to that version's ground.
"""

from __future__ import annotations

import copy

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.starter import (
    AUTHORED_GROUND_ELEVATION_MM,
    AUTHORED_GROUND_MODULE_VERSION,
    AUTHORED_GROUND_STREAMING_KEY,
    AUTHORED_GROUND_V1_HALF_DEPTH_MM,
    AUTHORED_GROUND_V1_HALF_WIDTH_MM,
    AUTHORED_GROUND_V1_MODULE_VERSION,
    AUTHORED_GROUND_V1_STREAMING_KEY,
    AUTHORED_STARTER_COMPOSER,
    AUTHORED_STARTER_COMPOSER_VERSION,
    BoundedAuthoredGround,
    EndlessAuthoredGround,
    _authored_starter_candidate,
    authored_starter_candidate,
    authored_starter_scene,
)

WORLD_ID = "world:authored:00000000-0000-4000-8000-000000000000"

# The exact bytes each ground module version commits. Version 1's digest was taken from the
# unmodified main checkout, so a change here that would make a world created before version 2
# unreadable fails this test rather than that world.
CANDIDATE_DIGESTS = {
    1: "a21979736cc3631aaa7e22e559744f5ce84aeb1a9f6b927ffc8524877984759a",
    2: "91cb46b1c04fdce9a13de37cc2d470b30e05433bb96abd7e13a0e15133924bdc",
}


def _candidate(module_version: int):
    if module_version == AUTHORED_GROUND_V1_MODULE_VERSION:
        return _authored_starter_candidate(
            WORLD_ID,
            module_version=AUTHORED_GROUND_V1_MODULE_VERSION,
            streaming_key=AUTHORED_GROUND_V1_STREAMING_KEY,
        )
    return authored_starter_candidate(WORLD_ID)


def _scene(candidate):
    return authored_starter_scene(
        composer_key=AUTHORED_STARTER_COMPOSER,
        composer_version=AUTHORED_STARTER_COMPOSER_VERSION,
        topology=candidate.topology,
        placement=candidate.placement,
    )


@pytest.mark.parametrize("module_version", sorted(CANDIDATE_DIGESTS))
def test_each_ground_module_version_commits_exactly_the_bytes_it_committed_before(module_version):
    candidate = _candidate(module_version)
    digest = sha256_of_canonical(
        {"topology": candidate.topology, "placement": candidate.placement}
    ).hex()
    assert digest == CANDIDATE_DIGESTS[module_version]
    element = candidate.topology["elements"][0]
    assert element["module"]["version"] == module_version
    assert element["streaming_key"] == f"builtin:region.authored-ground@{module_version}"


def test_the_two_versions_are_different_snapshots():
    assert CANDIDATE_DIGESTS[1] != CANDIDATE_DIGESTS[2]
    assert AUTHORED_GROUND_MODULE_VERSION == 2
    assert AUTHORED_GROUND_STREAMING_KEY == "builtin:region.authored-ground@2"


def test_a_new_starter_states_an_endless_ground_and_carries_no_extent():
    scene = _scene(authored_starter_candidate(WORLD_ID))
    assert scene.region.module.version == AUTHORED_GROUND_MODULE_VERSION
    assert scene.region.ground == EndlessAuthoredGround("endless", AUTHORED_GROUND_ELEVATION_MM)
    assert not hasattr(scene.region.ground, "half_width_mm")
    assert not hasattr(scene.region.ground, "half_depth_mm")


def test_a_world_created_at_version_one_still_reads_back_as_its_own_bounded_ground():
    scene = _scene(_candidate(AUTHORED_GROUND_V1_MODULE_VERSION))
    assert scene.region.module.version == AUTHORED_GROUND_V1_MODULE_VERSION
    assert scene.region.ground == BoundedAuthoredGround(
        "flat",
        AUTHORED_GROUND_V1_HALF_WIDTH_MM,
        AUTHORED_GROUND_V1_HALF_DEPTH_MM,
        AUTHORED_GROUND_ELEVATION_MM,
    )
    assert scene.region.spawn.z_mm == 4_000


def test_a_snapshot_at_an_unsupported_module_version_is_refused():
    candidate = _authored_starter_candidate(
        WORLD_ID, module_version=3, streaming_key="builtin:region.authored-ground@3"
    )
    with pytest.raises(InvalidStructuralData, match="supported ground module version"):
        _scene(candidate)


@pytest.mark.parametrize("module_version", sorted(CANDIDATE_DIGESTS))
def test_a_snapshot_the_module_did_not_write_is_refused(module_version):
    """The positive control for the match above: it accepts because the bytes agree, not always."""

    candidate = _candidate(module_version)
    topology = copy.deepcopy(dict(candidate.topology))
    topology["elements"][0]["collision"] = {"kind": "box", "half_width_mm": 1, "half_depth_mm": 1}
    with pytest.raises(InvalidStructuralData, match="supported ground module version"):
        authored_starter_scene(
            composer_key=AUTHORED_STARTER_COMPOSER,
            composer_version=AUTHORED_STARTER_COMPOSER_VERSION,
            topology=topology,
            placement=candidate.placement,
        )


def test_a_snapshot_from_another_composer_is_refused_before_any_version_is_tried():
    candidate = authored_starter_candidate(WORLD_ID)
    with pytest.raises(InvalidStructuralData, match="starter composer"):
        authored_starter_scene(
            composer_key="some-other-composer",
            composer_version=AUTHORED_STARTER_COMPOSER_VERSION,
            topology=candidate.topology,
            placement=candidate.placement,
        )
